"""OpenTelemetry setup — traces + metrics for lughus agents."""
from __future__ import annotations

import logging
import os
import threading

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)

_INITIALIZED = False
_INIT_LOCK = threading.Lock()


def setup_telemetry(service_name: str, *, configure_logging: bool = True) -> None:
    """Configure OTel providers. OTLP if endpoint set, console otherwise.

    Thread-safe: safe to call from multiple threads simultaneously.
    Idempotent: subsequent calls after the first are no-ops.
    Set ``configure_logging=False`` when the host application owns logging.
    """
    global _INITIALIZED
    with _INIT_LOCK:
        if _INITIALIZED:
            return
        _INITIALIZED = True

    resource = Resource.create({"service.name": service_name})
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")

    if otlp_endpoint or os.getenv("LUGHUS_TELEMETRY_CONSOLE", "").lower() in ("1", "true", "yes", "on"):
        if otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            span_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            metric_exporter = OTLPMetricExporter(endpoint=otlp_endpoint)
        else:
            span_exporter = ConsoleSpanExporter()  # type: ignore[assignment]
            metric_exporter = ConsoleMetricExporter()  # type: ignore[assignment]

        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        trace.set_tracer_provider(tracer_provider)

        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[PeriodicExportingMetricReader(metric_exporter)],
        )
        metrics.set_meter_provider(meter_provider)

    root_logger = logging.getLogger()
    if configure_logging and not root_logger.handlers:
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )


tracer = trace.get_tracer("lughus")
meter = metrics.get_meter("lughus")
