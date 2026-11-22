import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from opentelemetry import context, propagate

from . import db
from .models import Scenario
from .runner import Manager


@asynccontextmanager
async def lifespan(app):
    await db.init()
    app.state.manager = Manager()
    # Single-process deployment: interrupted runs are recorded, not silently replayed.
    async with await db.connect() as c:
        cur = await c.execute(
            "SELECT id FROM sandbox_control.runs WHERE status IN ('queued','running')"
        )
        for (run_id,) in await cur.fetchall():
            await db.cleanup(run_id)
            await db.save_report(
                run_id, "interrupted", {"status": "interrupted", "harness_completed": False}
            )
    yield
    await app.state.manager.close()
    from .telemetry import provider

    await asyncio.to_thread(provider.force_flush)


app = FastAPI(title="Hermetic Enterprise Sandbox", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def trace_context(request, call_next):
    token = context.attach(propagate.extract(dict(request.headers)))
    try:
        return await call_next(request)
    finally:
        context.detach(token)


@app.get("/", response_class=HTMLResponse)
async def home():
    return Path("web/index.html").read_text()


@app.get("/health")
async def health():
    async with await db.connect() as c:
        await c.execute("SELECT 1")
    return {"status": "ok"}


@app.post("/runs", status_code=202)
async def submit(spec: Scenario):
    try:
        run_id, _ = await app.state.manager.submit(spec)
    except ValueError as exc:
        raise HTTPException(429, str(exc)) from exc
    return {"run_id": run_id}


@app.get("/runs")
async def runs():
    return await db.list_runs()


@app.get("/runs/{run_id}")
async def run(run_id: str):
    result = await db.get_run(run_id)
    if not result:
        raise HTTPException(404, "run not found")
    return result


@app.post("/runs/{run_id}/cancel")
async def cancel(run_id: str):
    task = app.state.manager.tasks.get(run_id)
    if not task:
        raise HTTPException(409, "run is not active in this process")
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    return {"status": "cancelled"}


@app.get("/contracts")
async def contracts():
    from .tools import CONTRACTS

    return {k: v.model_json_schema() for k, v in CONTRACTS.items()}
