# Hermetic Enterprise Sandbox and Multi-Turn Agent Simulation Runtime

A runnable portfolio project for evaluating agents that change enterprise state. Create a ticket, read it in a later turn, resolve it, and validate the final database state. Each run uses its own PostgreSQL schema and leaves an inspectable report after cleanup.

**Status:** functional local-development implementation. Measured results and limitations are in [docs/benchmark.json](docs/benchmark.json) and [docs/architecture.md](docs/architecture.md).

## Quick start

Prerequisites: Docker with Compose. From this repository:

```bash
docker compose up --build
```

Open **http://localhost:8000** for the scenario launcher and report explorer, or **http://localhost:8000/docs** for the REST API. Paste a JSON scenario or use the included create/read/resolve fixture:

```bash
curl -X POST http://localhost:8000/runs -H 'Content-Type: application/json' --data-binary @examples/ticket.json
curl http://localhost:8000/runs
# Replace RUN_ID with the returned run_id
curl http://localhost:8000/runs/RUN_ID
```

Stop with `docker compose down`. Database records remain in the named volume. All fixtures are synthetic; no enterprise account or model key is needed for scripted mode.

## What is implemented

- Stateful ticket creation/read/update, user-directory lookup, and knowledge-document search.
- PostgreSQL schema per run; deterministic baseline data and ticket identifiers; finally-block teardown on success, failure, timeout, and cancellation.
- Mutation receipts with request validation and idempotency keys. A lost-response fault exercises replay after commit.
- Python asyncio orchestration, bounded concurrency and admission, per-run deadlines, cancellation, and bounded exponential retries for injected transient faults.
- Scripted state-machine flows plus opt-in persona-driven LLM user and agent adapters.
- Versioned YAML/JSON scenarios, specification hashes, persistent transcripts, step assertions, and final-state validation. Harness completion and agent pass/fail are separate.
- REST API, CLI, and a separately runnable gRPC control plane with generated protobuf bindings.
- OpenTelemetry SDK spans, W3C parent-context propagation into scheduled tasks, full redacted JSON attributes, and optional OTLP export.
- Go worker-pool benchmark client, database integration tests, pinned local tool contracts, and GitHub Actions CI.

## Local Python development

Python 3.12 and PostgreSQL 16 are recommended. Start only the database, create a venv, and install:

```bash
docker compose up -d db
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e '.[test]'
```

Set `DATABASE_URL=postgresql://sandbox:local-demo-only@localhost:5432/sandbox` in your shell. In PowerShell use `$env:DATABASE_URL="..."`; in bash use `export DATABASE_URL="..."`.

```bash
python -m sandbox examples/ticket.yaml --repeat 32 --concurrency 4
python -m uvicorn sandbox.api:app --port 8000
```

The CLI writes `artifacts/report.json`. Run the API with **one process**: the queue is in memory, while results are durable. API startup marks interrupted runs and cleans their schemas; it does not silently replay live LLM calls.

## gRPC

The generated code is committed. To regenerate, install test dependencies and run `python scripts/generate_proto.py`. Start `python -m sandbox.grpc_server` instead of the REST scheduler. It listens on loopback port 50051 and exposes Submit, Get, and Cancel from `proto/evaluation.proto`. The gRPC server is a separate development entry point, not a second scheduler for the same database.

## Live LLM scenarios (optional)

Set `LLM_BASE_URL` to your provider's OpenAI-compatible `/v1` URL, `LLM_MODEL`, and `LLM_API_KEY` in your environment (never commit credentials). Then:

```bash
python -m sandbox examples/live.yaml --repeat 1
```

This uses real paid model calls if your provider charges. Each turn calls a user simulator and an agent. The adapter requires JSON-mode support, validates tool output, limits turns and request duration, and never grants tools shell or external enterprise access. No live-model quality or latency claim is made; the adapter contract is tested with stubs. A fixed temperature/seed is not a guarantee of reproducible live model behavior.

## Connect the independent tracer project

Run the separate **OpenTelemetry Agent Trajectory Tracer and Fault Attribution Engine** on port 8001. For a local Python sandbox, set:

```bash
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:8001/v1/traces
```

For the sandbox Docker container, set the endpoint to `http://host.docker.internal:8001/v1/traces` before starting Compose. Every sandbox span carries `eval.traffic=true` and `eval.run_id`. Inspect the report's trace_id in the tracer UI.

## Tests and benchmark

```bash
python -m pytest -q
python -m ruff check .
go test ./...
go run ./cmd/bench -n 32 -workers 4
```

Tests use a disposable real PostgreSQL server from the `pgserver` test dependency on supported Linux/macOS hosts. On other platforms set `TEST_DATABASE_URL` to a **dedicated disposable test database**. CI supplies PostgreSQL 16. Contract tests compare our own synthetic enterprise tool schemas, not a vendor's undocumented API. Review schema changes before updating `examples/tool-contracts.v1.json`.

## Boundaries

Schema isolation protects fixture independence, **not hostile code**. The same database role owns all schemas. This is a local trusted-user tool without authentication, tenant authorization, durable distributed scheduling, or production SLO enforcement. Do not expose its ports publicly. See [architecture](docs/architecture.md), [demo walkthrough](docs/demo.md), and [AI assistance](AI_USAGE.md).

## Optional Kubernetes development deployment

`deploy/kubernetes.yaml` runs a single API replica behind a ClusterIP service. Build/load `sandbox-platform:local` into your development cluster and create the `sandbox-database` Secret containing `DATABASE_URL` for a reachable PostgreSQL instance before applying it. Access with port-forwarding. These manifests are supplied for local experimentation and were not applied during this build.
