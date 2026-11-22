import os
import re
from contextlib import asynccontextmanager

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

DSN = os.getenv("DATABASE_URL", "postgresql://sandbox:sandbox@localhost:5432/sandbox")


def schema_name(run_id):
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("invalid run id")
    return "run_" + run_id


async def connect():
    return await psycopg.AsyncConnection.connect(DSN, autocommit=True)


async def init():
    async with await connect() as c:
        await c.execute("CREATE SCHEMA IF NOT EXISTS sandbox_control")
        await c.execute("""CREATE TABLE IF NOT EXISTS sandbox_control.runs (
            id text PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now(),
            status text NOT NULL, spec jsonb NOT NULL, report jsonb NOT NULL DEFAULT '{}')""")


async def save_new(run_id, spec):
    async with await connect() as c:
        await c.execute(
            "INSERT INTO sandbox_control.runs(id,status,spec) VALUES(%s,'queued',%s)",
            (run_id, Jsonb(spec)),
        )


async def save_report(run_id, status, report):
    async with await connect() as c:
        await c.execute(
            "UPDATE sandbox_control.runs SET status=%s,report=%s WHERE id=%s",
            (status, Jsonb(report), run_id),
        )


async def get_run(run_id):
    async with await connect() as c:
        cur = await c.execute(
            "SELECT id,status,spec,report FROM sandbox_control.runs WHERE id=%s", (run_id,)
        )
        row = await cur.fetchone()
        return dict(zip(["id", "status", "spec", "report"], row)) if row else None


async def list_runs():
    async with await connect() as c:
        cur = await c.execute(
            "SELECT id,status,created_at FROM sandbox_control.runs ORDER BY created_at DESC LIMIT 100"
        )
        return [
            {"id": r[0], "status": r[1], "created_at": r[2].isoformat()}
            for r in await cur.fetchall()
        ]


async def cleanup(run_id):
    async with await connect() as c:
        await c.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name(run_id)))
        )


@asynccontextmanager
async def world(run_id, spec):
    name = schema_name(run_id)
    c = await connect()
    try:
        await c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
        await c.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(name)))
        await c.execute("CREATE TABLE tickets(id text PRIMARY KEY, payload jsonb NOT NULL)")
        await c.execute("CREATE TABLE users(id text PRIMARY KEY, payload jsonb NOT NULL)")
        await c.execute("CREATE TABLE documents(id text PRIMARY KEY, payload jsonb NOT NULL)")
        await c.execute(
            "CREATE TABLE receipts(key text PRIMARY KEY, request jsonb NOT NULL, response jsonb NOT NULL)"
        )
        for table, rows in [("users", spec.initial_users), ("documents", spec.initial_documents)]:
            for row in rows:
                await c.execute(
                    sql.SQL("INSERT INTO {} VALUES(%s,%s)").format(sql.Identifier(table)),
                    (row["id"], Jsonb(row)),
                )
        yield c
    finally:
        await c.close()
        await cleanup(run_id)
