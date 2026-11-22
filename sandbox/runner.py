import asyncio
import hashlib
import time
import uuid

from opentelemetry import propagate

from . import db, llm
from .models import Action, Scenario
from .privacy import redact
from .telemetry import payload, safe_span
from .tools import CONTRACTS, invoke, snapshot


class TransientFault(Exception):
    pass


def resolve(value, transcript):
    if isinstance(value, str) and value.startswith("$last."):
        return transcript[-1]["result"][value.removeprefix("$last.")]
    if isinstance(value, dict):
        return {k: resolve(v, transcript) for k, v in value.items()}
    return value


async def execute(run_id, spec, carrier=None):
    started = time.perf_counter()
    report = {
        "run_id": run_id,
        "scenario": spec.name,
        "version": spec.version,
        "mode": spec.mode,
        "spec_sha256": hashlib.sha256(spec.model_dump_json().encode()).hexdigest(),
        "transcript": [],
        "checks": [],
        "final_state": {},
        "harness_completed": False,
    }
    status = "error"
    fault_injected = False
    await db.save_report(run_id, "running", report)
    try:
        async with asyncio.timeout(spec.timeout_seconds):
            with safe_span(
                "evaluation.run",
                record_exception=False,
                set_status_on_exception=False,
                context=propagate.extract(carrier or {}),
                attributes={
                    "eval.run_id": run_id,
                    "eval.traffic": True,
                    "eval.scenario": spec.name,
                },
            ) as root:
                report["trace_id"] = format(root.get_span_context().trace_id, "032x")
                async with db.world(run_id, spec) as c:
                    count = len(spec.steps) if spec.mode == "scripted" else spec.max_turns
                    for index in range(count):
                        if spec.mode == "scripted":
                            step = spec.steps[index]
                            message = step.user
                            action = step.action.model_copy(
                                update={
                                    "arguments": resolve(
                                        step.action.arguments, report["transcript"]
                                    )
                                }
                            )
                        else:
                            message = await llm.user_turn(spec, report["transcript"])
                            action = Action.model_validate(
                                await llm.agent_turn(
                                    message,
                                    report["transcript"],
                                    {k: v.model_json_schema() for k, v in CONTRACTS.items()},
                                )
                            )
                        entry = {
                            "sequence": index,
                            "user": message,
                            "tool": action.tool,
                            "arguments": action.arguments,
                        }
                        with safe_span(
                            "agent.tool",
                            record_exception=False,
                            set_status_on_exception=False,
                            attributes={
                                "eval.run_id": run_id,
                                "eval.traffic": True,
                                "agent.sequence": index,
                                "agent.tool.name": action.tool,
                                "agent.prompt": payload(message),
                                "agent.tool.arguments": payload(action.arguments),
                            },
                        ) as span:
                            for attempt in range(spec.retries + 1):
                                try:
                                    result = await invoke(c, action, spec.seed)
                                    if (
                                        spec.inject_transient_after_create
                                        and action.tool == "ticket.create"
                                        and not fault_injected
                                    ):
                                        fault_injected = True
                                        raise TransientFault("injected lost response after commit")
                                    break
                                except TransientFault:
                                    if attempt == spec.retries:
                                        raise
                                    await asyncio.sleep(0.01 * 2**attempt)
                            entry.update(result=result, attempts=attempt + 1)
                            span.set_attribute("agent.tool.result", payload(result))
                            span.set_attribute("agent.outcome", "ok")
                        report["transcript"].append(entry)
                        if spec.mode == "scripted":
                            report["checks"].append(
                                {
                                    "step": index,
                                    "passed": all(
                                        result.get(k) == v for k, v in step.expect.items()
                                    ),
                                }
                            )
                    report["final_state"] = await snapshot(c)
                    tickets = report["final_state"]["tickets"]
                    report["checks"].append(
                        {"check": "ticket_count", "passed": len(tickets) == spec.expected_tickets}
                    )
                    if spec.expected_status:
                        report["checks"].append(
                            {
                                "check": "ticket_status",
                                "passed": all(x["status"] == spec.expected_status for x in tickets),
                            }
                        )
                    root.set_attribute("agent.final_state", payload(report["final_state"]))
                    report["harness_completed"] = True
                    status = "passed" if all(x["passed"] for x in report["checks"]) else "failed"
                    root.set_attribute("agent.outcome", status)
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    except Exception as exc:
        report["error"] = {
            "type": type(exc).__name__,
            "message": "Run failed; inspect redacted tool transcript and server logs.",
        }
    finally:
        report["elapsed_seconds"] = round(time.perf_counter() - started, 6)
        report["status"] = status
        await asyncio.shield(db.save_report(run_id, status, redact(report)))
    return redact(report)


class Manager:
    def __init__(self, concurrency=8, max_pending=256):
        self.semaphore = asyncio.Semaphore(concurrency)
        self.tasks = {}
        self.max_pending = max_pending
        self.admission = asyncio.Lock()

    async def submit(self, spec: Scenario):
        async with self.admission:
            return await self._submit(spec)

    async def _submit(self, spec: Scenario):
        if len(self.tasks) >= self.max_pending:
            raise ValueError("evaluation queue is full")
        run_id = uuid.uuid4().hex
        # Persist only synthetic/redacted specifications. Execution uses the in-memory validated spec.
        await db.save_new(run_id, redact(spec.model_dump()))
        carrier = {}
        propagate.inject(carrier)

        async def work():
            try:
                async with self.semaphore:
                    return await execute(run_id, spec, carrier)
            except asyncio.CancelledError:
                current = await db.get_run(run_id)
                if current["status"] == "queued":
                    await db.save_report(
                        run_id, "cancelled", {"status": "cancelled", "harness_completed": False}
                    )
                raise

        task = asyncio.create_task(work())
        self.tasks[run_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(run_id, None))
        return run_id, task

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
