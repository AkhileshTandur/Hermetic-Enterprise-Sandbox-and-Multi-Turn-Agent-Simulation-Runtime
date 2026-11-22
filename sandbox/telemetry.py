from contextlib import contextmanager
from opentelemetry.trace import Status, StatusCode
import json
import os

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanLimits, TracerProvider
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .privacy import redact


def make_provider():
    provider = TracerProvider(
        sampler=ALWAYS_ON,
        resource=Resource({"service.name": "enterprise-sandbox"}),
        span_limits=SpanLimits(max_attribute_length=None),
    )
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    return provider


provider = make_provider()
tracer = provider.get_tracer("sandbox", "0.1.0")


def payload(value):
    return json.dumps(redact(value), sort_keys=True)


@contextmanager
def safe_span(name, **kwargs):
    """Record failure type without exporting exception strings or stack payloads."""
    kwargs.pop("record_exception", None)
    kwargs.pop("set_status_on_exception", None)
    with tracer.start_as_current_span(
        name, record_exception=False, set_status_on_exception=False, **kwargs
    ) as span:
        try:
            yield span
        except BaseException as exc:
            span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
            span.set_attribute("agent.outcome", "error")
            span.set_attribute("error.type", type(exc).__name__)
            raise
