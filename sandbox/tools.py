"""Stateful enterprise fakes. No external enterprise API is called."""

import uuid

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field


class CreateTicket(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    user_id: str = "employee-1"


class ReadTicket(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str


class UpdateTicket(ReadTicket):
    status: str = Field(pattern="^(open|in_progress|resolved)$")


class Search(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=200)


CONTRACTS = {
    "ticket.create": CreateTicket,
    "ticket.read": ReadTicket,
    "ticket.update": UpdateTicket,
    "user.read": ReadTicket,
    "document.search": Search,
}


async def invoke(c, action, seed):
    args = CONTRACTS[action.tool].model_validate(action.arguments).model_dump()
    key = action.idempotency_key
    if action.tool in {"ticket.create", "ticket.update"} and not key:
        raise ValueError("mutations require an idempotency_key")
    request = {"tool": action.tool, "arguments": args}
    async with c.transaction():
        if key:
            await c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (key,))
            cur = await c.execute("SELECT request,response FROM receipts WHERE key=%s", (key,))
            receipt = await cur.fetchone()
            if receipt:
                if receipt[0] != request:
                    raise ValueError("idempotency key reused with different arguments")
                return receipt[1]
        if action.tool == "ticket.create":
            cur = await c.execute("SELECT payload FROM users WHERE id=%s", (args["user_id"],))
            if not await cur.fetchone():
                raise ValueError("unknown user")
            ticket_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:{key}"))
            result = {"id": ticket_id, **args, "status": "open"}
            await c.execute("INSERT INTO tickets VALUES(%s,%s)", (ticket_id, Jsonb(result)))
        elif action.tool in {"ticket.read", "user.read"}:
            table = "tickets" if action.tool == "ticket.read" else "users"
            cur = await c.execute(f"SELECT payload FROM {table} WHERE id=%s", (args["id"],))
            row = await cur.fetchone()
            if not row:
                raise ValueError("entity not found")
            result = row[0]
        elif action.tool == "ticket.update":
            cur = await c.execute(
                "SELECT payload FROM tickets WHERE id=%s FOR UPDATE", (args["id"],)
            )
            row = await cur.fetchone()
            if not row:
                raise ValueError("ticket not found")
            result = {**row[0], "status": args["status"]}
            await c.execute(
                "UPDATE tickets SET payload=%s WHERE id=%s", (Jsonb(result), args["id"])
            )
        else:
            cur = await c.execute("SELECT payload FROM documents ORDER BY id")
            result = {
                "documents": [
                    r[0]
                    for r in await cur.fetchall()
                    if args["query"].casefold() in r[0]["text"].casefold()
                ]
            }
        if key:
            await c.execute(
                "INSERT INTO receipts VALUES(%s,%s,%s)", (key, Jsonb(request), Jsonb(result))
            )
        return result


async def snapshot(c):
    result = {}
    for table in ["tickets", "users", "documents"]:
        cur = await c.execute(f"SELECT payload FROM {table} ORDER BY id")
        result[table] = [r[0] for r in await cur.fetchall()]
    return result
