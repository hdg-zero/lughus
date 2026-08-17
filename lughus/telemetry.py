"""OpenTelemetry setup — traces + metrics for lughus agents."""

from __future__ import annotations

import logging
import os
import threading

# Only the OpenTelemetry *API* is imported at module level. It is a base
# dependency: without an SDK installed it returns no-op tracers and meters at
# near-zero cost, which is exactly the contract a library needs.
# The SDK (otel extra) is imported inside setup_telemetry() -- see W1-01 / N-01.
from opentelemetry import metrics, trace

_INITIALIZED = False
_INIT_LOCK = threading.Lock()


def setup_telemetry(service_name: str, *, configure_logging: bool = True) -> None:
    """Configure OpenTelemetry atomically and at most once.

    Provider construction happens under the initialization lock.  A failure leaves the
    module retryable instead of poisoning the process-wide initialized flag.
    """
    global _INITIALIZED
    try:
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
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised in dist-core CI job
        raise ImportError(
            "setup_telemetry() requires the OpenTelemetry SDK, which is an optional "
            "dependency. Install it with: pip install 'lughus[otel]'"
        ) from exc

    with _INIT_LOCK:
        if _INITIALIZED:
            return

        resource = Resource.create({"service.name": service_name})
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        console_enabled = os.getenv("LUGHUS_TELEMETRY_CONSOLE", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if otlp_endpoint or console_enabled:
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
            meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[PeriodicExportingMetricReader(metric_exporter)],
            )
            trace.set_tracer_provider(tracer_provider)
            metrics.set_meter_provider(meter_provider)

        root_logger = logging.getLogger()
        if configure_logging and not root_logger.handlers:
            log_level = os.getenv("LOG_LEVEL", "INFO").upper()
            logging.basicConfig(
                level=getattr(logging, log_level, logging.INFO),
                format="%(asctime)s %(name)s %(levelname)s %(message)s",
            )
        _INITIALIZED = True


tracer = trace.get_tracer("lughus")
meter = metrics.get_meter("lughus")
