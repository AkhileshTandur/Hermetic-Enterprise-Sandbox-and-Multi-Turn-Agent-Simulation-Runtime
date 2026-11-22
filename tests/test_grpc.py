import asyncio
import json
from pathlib import Path

import grpc
import yaml

from sandbox import db
from sandbox.generated import evaluation_pb2 as pb
from sandbox.generated import evaluation_pb2_grpc as rpc
from sandbox.grpc_server import Service


async def test_grpc_submit_and_get():
    await db.init()
    server = grpc.aio.server()
    service = Service()
    rpc.add_EvaluationServicer_to_server(service, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            client = rpc.EvaluationStub(channel)
            spec = yaml.safe_load(Path("examples/ticket.yaml").read_text())
            result = await client.Submit(pb.SubmitRequest(scenario_json=json.dumps(spec)))
            for _ in range(100):
                result = await client.Get(pb.RunRequest(run_id=result.run_id))
                if result.status not in {"queued", "running"}:
                    break
                await asyncio.sleep(0.01)
            assert result.status == "passed"
            assert json.loads(result.report_json)["harness_completed"]
    finally:
        await service.manager.close()
        await server.stop(0)
