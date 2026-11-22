import json
from pathlib import Path

from sandbox.tools import CONTRACTS


def test_versioned_tool_schemas_do_not_drift():
    expected = json.loads(Path("examples/tool-contracts.v1.json").read_text())
    actual = {k: v.model_json_schema() for k, v in CONTRACTS.items()}
    assert actual == expected, "Review contract compatibility before updating the baseline"
