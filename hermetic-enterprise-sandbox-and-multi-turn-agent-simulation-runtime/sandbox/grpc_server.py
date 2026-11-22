"""Standalone gRPC runtime. Run instead of HTTP API (one scheduler per database)."""

import asyncio
import json

import grpc

from . import db
from .generated import evaluation_pb2 as pb
from .generated import evaluation_pb2_grpc as rpc
from .models import Scenario
from .runner import Manager


class Service(rpc.EvaluationServicer):
    def __init__(self):
        self.manager = Manager()

    async def Submit(self, request, context):
        try:
            spec = Scenario.model_validate_json(request.scenario_json)
            rid, _ = await self.manager.submit(spec)
            return pb.RunReply(run_id=rid, status="queued")
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))

    async def Get(self, request, context):
        run = await db.get_run(request.run_id)
        if not run:
            await context.abort(grpc.StatusCode.NOT_FOUND, "run not found")
        return pb.RunReply(
            run_id=run["id"], status=run["status"], report_json=json.dumps(run["report"])
        )

    async def Cancel(self, request, context):
        task = self.manager.tasks.get(request.run_id)
        if not task:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, "run is not active")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return pb.RunReply(run_id=request.run_id, status="cancelled")


async def main():
    await db.init()
    server = grpc.aio.server()
    service = Service()
    rpc.add_EvaluationServicer_to_server(service, server)
    server.add_insecure_port("127.0.0.1:50051")
    await server.start()
    try:
        await server.wait_for_termination()
    finally:
        await service.manager.close()
        await server.stop(5)


if __name__ == "__main__":
    asyncio.run(main())
