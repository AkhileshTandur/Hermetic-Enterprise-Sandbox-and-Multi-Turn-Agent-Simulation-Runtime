from pathlib import Path

from grpc_tools import protoc

out = Path("sandbox/generated")
out.mkdir(exist_ok=True)
(out / "__init__.py").touch()
assert (
    protoc.main(
        [
            "protoc",
            "-Iproto",
            "--python_out=" + str(out),
            "--grpc_python_out=" + str(out),
            "proto/evaluation.proto",
        ]
    )
    == 0
)
p = out / "evaluation_pb2_grpc.py"
p.write_text(p.read_text().replace("import evaluation_pb2 as", "from . import evaluation_pb2 as"))
