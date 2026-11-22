import asyncio
import uuid
from pathlib import Path

import pytest
import yaml

from sandbox import db
from sandbox.models import Action, Scenario
from sandbox.runner import Manager
from sandbox.tools import invoke, snapshot


@pytest.fixture
def spec():
    return Scenario.model_validate(yaml.safe_load(Path("examples/ticket.yaml").read_text()))


async def test_state_persists_within_run_and_isolated_between_runs(spec):
    a, b = uuid.uuid4().hex, uuid.uuid4().hex
    async with db.world(a, spec) as ca, db.world(b, spec) as cb:
        action = spec.steps[0].action
        first = await invoke(ca, action, spec.seed)
        assert (
            await invoke(ca, Action(tool="ticket.read", arguments={"id": first["id"]}), 42)
        ) == first
        with pytest.raises(ValueError, match="not found"):
            await invoke(cb, Action(tool="ticket.read", arguments={"id": first["id"]}), 42)
        assert len((await snapshot(ca))["tickets"]) == 1
        assert (await snapshot(cb))["tickets"] == []
    async with await db.connect() as c:
        cur = await c.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name IN (%s,%s)",
            (db.schema_name(a), db.schema_name(b)),
        )
        assert await cur.fetchall() == []


async def test_idempotency_replay_and_key_conflict(spec):
    async with db.world(uuid.uuid4().hex, spec) as c:
        first = await invoke(c, spec.steps[0].action, 42)
        assert await invoke(c, spec.steps[0].action, 42) == first
        changed = spec.steps[0].action.model_copy(update={"arguments": {"title": "Other"}})
        with pytest.raises(ValueError, match="reused"):
            await invoke(c, changed, 42)
        assert len((await snapshot(c))["tickets"]) == 1


async def test_lost_response_retry_does_not_duplicate(spec):
    await db.init()
    spec.inject_transient_after_create = True
    manager = Manager(2)
    rid, task = await manager.submit(spec)
    report = await task
    assert report["status"] == "passed"
    assert report["transcript"][0]["attempts"] == 2
    assert len(report["final_state"]["tickets"]) == 1
    assert (await db.get_run(rid))["status"] == "passed"


async def test_replay_and_concurrent_runs(spec):
    await db.init()
    manager = Manager(3)
    tasks = [(await manager.submit(spec))[1] for _ in range(8)]
    reports = await asyncio.gather(*tasks)
    assert all(r["status"] == "passed" for r in reports)
    assert all(r["final_state"] == reports[0]["final_state"] for r in reports)
    assert len({r["run_id"] for r in reports}) == 8


async def test_cancel_cleans_schema(spec, monkeypatch):
    from sandbox import runner

    await db.init()
    entered = asyncio.Event()

    async def slow(*args):
        entered.set()
        await asyncio.sleep(100)

    monkeypatch.setattr(runner, "invoke", slow)
    manager = Manager()
    rid, task = await manager.submit(spec)
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await db.get_run(rid))["status"] == "cancelled"
    async with await db.connect() as c:
        cur = await c.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name=%s", (db.schema_name(rid),)
        )
        assert await cur.fetchone() is None


async def test_timeout_is_harness_error(spec, monkeypatch):
    from sandbox import runner

    await db.init()

    async def slow(*args):
        await asyncio.sleep(1)

    monkeypatch.setattr(runner, "invoke", slow)
    spec.timeout_seconds = 0.1
    _, task = await Manager().submit(spec)
    report = await task
    assert report["status"] == "error"
    assert report["error"]["type"] == "TimeoutError"
    assert not report["harness_completed"]


async def test_agent_failure_not_harness_failure(spec):
    await db.init()
    spec.expected_tickets = 2
    _, task = await Manager().submit(spec)
    report = await task
    assert report["status"] == "failed"
    assert report["harness_completed"]


def test_rejects_schema_injection():
    with pytest.raises(ValueError):
        db.schema_name("x; DROP SCHEMA public")


def test_contract_strictness():
    from sandbox.tools import CONTRACTS

    with pytest.raises(ValueError):
        CONTRACTS["ticket.create"].model_validate({"title": "hello", "admin": True})
    with pytest.raises(ValueError):
        CONTRACTS["ticket.update"].model_validate({"id": "x", "status": "invented"})


async def test_live_simulator_contract_with_stub(spec, monkeypatch):
    from sandbox import llm

    await db.init()
    spec.mode = "live"
    spec.max_turns = 1
    spec.expected_status = "open"

    async def user(*args):
        return "Open a VPN ticket"

    async def agent(*args):
        return {"tool": "ticket.create", "arguments": {"title": "VPN"}, "idempotency_key": "live-1"}

    monkeypatch.setattr(llm, "user_turn", user)
    monkeypatch.setattr(llm, "agent_turn", agent)
    _, task = await Manager().submit(spec)
    assert (await task)["status"] == "passed"
