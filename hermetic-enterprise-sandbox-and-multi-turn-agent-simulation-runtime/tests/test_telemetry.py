import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sandbox.telemetry import provider, safe_span


def test_error_span_is_sampled_without_exception_payload():
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with pytest.raises(ValueError):
        with safe_span("failed.tool", attributes={"eval.traffic": True}) as span:
            assert span.is_recording()
            raise ValueError("private-value-must-not-export")
    result = exporter.get_finished_spans()[-1]
    assert result.attributes["agent.outcome"] == "error"
    assert result.status.description == "ValueError"
    assert not result.events
