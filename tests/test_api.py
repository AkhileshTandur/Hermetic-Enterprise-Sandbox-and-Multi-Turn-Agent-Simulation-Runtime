from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from sandbox.api import app


def test_submit_poll_and_contracts():
    import time

    spec = yaml.safe_load(Path("examples/ticket.yaml").read_text())
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        response = client.post("/runs", json=spec)
        assert response.status_code == 202
        rid = response.json()["run_id"]
        for _ in range(100):
            result = client.get("/runs/" + rid).json()
            if result["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert result["status"] == "passed"
        assert "ticket.create" in client.get("/contracts").json()
        assert client.get("/runs/missing").status_code == 404
        assert client.post("/runs", json={"name": "bad"}).status_code == 422
