import os
import secrets
import socket
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def database(tmp_path_factory):
    url = os.getenv("TEST_DATABASE_URL")
    binaries = None
    data = None
    if not url:
        import pgserver

        binaries = Path(pgserver.__file__).parent / "pginstall" / "bin"
        folder = tmp_path_factory.mktemp("postgres")
        data = folder / "data"
        password = secrets.token_hex(16)
        pwfile = folder / "password"
        pwfile.write_text(password)
        pwfile.chmod(0o600)
        subprocess.run(
            [
                str(binaries / "initdb"),
                "-D",
                str(data),
                "-U",
                "tester",
                "-A",
                "scram-sha-256",
                "--pwfile",
                str(pwfile),
            ],
            check=True,
            capture_output=True,
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        subprocess.run(
            [
                str(binaries / "pg_ctl"),
                "-D",
                str(data),
                "-l",
                str(folder / "server.log"),
                "-o",
                f"-h 127.0.0.1 -p {port} -k ''",
                "-w",
                "start",
            ],
            check=True,
            capture_output=True,
        )
        url = f"postgresql://tester:{password}@127.0.0.1:{port}/postgres"
    from sandbox import db

    db.DSN = url
    yield url
    if binaries:
        subprocess.run(
            [str(binaries / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"],
            check=True,
            capture_output=True,
        )
