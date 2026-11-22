import argparse
import asyncio
import json
from pathlib import Path

import yaml

from . import db
from .models import Scenario
from .runner import Manager
from .telemetry import provider


async def main():
    p = argparse.ArgumentParser(description="Run a versioned evaluation spec locally")
    p.add_argument("spec", type=Path)
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--output", type=Path, default=Path("artifacts/report.json"))
    args = p.parse_args()
    if not 1 <= args.repeat <= 10000 or not 1 <= args.concurrency <= 64:
        p.error("repeat 1..10000; concurrency 1..64")
    spec = Scenario.model_validate(yaml.safe_load(args.spec.read_text()))
    await db.init()
    manager = Manager(args.concurrency, args.repeat)
    import time

    start = time.perf_counter()
    try:
        tasks = [(await manager.submit(spec))[1] for _ in range(args.repeat)]
        results = await asyncio.gather(*tasks)
    finally:
        await manager.close()
    elapsed = time.perf_counter() - start
    report = {
        "mode": spec.mode,
        "concurrency": args.concurrency,
        "episodes": len(results),
        "elapsed_seconds": elapsed,
        "episodes_per_second": len(results) / elapsed,
        "harness_completed": sum(r["harness_completed"] for r in results),
        "passed": sum(r["status"] == "passed" for r in results),
        "runs": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "runs"}, indent=2))
    provider.force_flush()
    if report["passed"] != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
