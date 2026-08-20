"""OpenTelemetry SDK bootstrap — gated behind Settings.otel_enabled.

MVP scope: auto-instrumentation only (FastAPI routes, outbound httpx calls
made by ChatOpenAI, trace_id/span_id injected into log records). No manual
spans or metrics yet — see CLAUDE.md for the instrumentation follow-up plan.
"""

from __future__ import annotations

import logging
import sys

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from sdlc_copilot import __version__

log = logging.getLogger(__name__)

_configured = False


def configure_telemetry() -> None:
    """Install a console-exporting TracerProvider plus httpx/logging auto-instrumentation.

    Idempotent — safe to call more than once (e.g. CLI callback re-invoked in tests).
    """
    global _configured
    if _configured:
        return
    resource = Resource.create({SERVICE_NAME: "sdlc-copilot", SERVICE_VERSION: __version__})
    provider = TracerProvider(resource=resource)
    # stderr matches logging_config.configure_logging()'s StreamHandler so spans and
    # log lines interleave on the same stream when both go to the terminal.
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))
    trace.set_tracer_provider(provider)

    HTTPXClientInstrumentor().instrument()
    # inject_trace_context=True adds otelTraceID/otelSpanID to LogRecords without touching
    # the existing formatter/handlers (set_logging_format=True would overwrite both).
    LoggingInstrumentor().instrument(set_logging_format=False, inject_trace_context=True)
    _configured = True
    log.info("OpenTelemetry configured (console exporter)")


def instrument_fastapi_app(app: FastAPI) -> None:
    """Attach ASGI middleware that emits one span per HTTP request. Call once per app instance."""
    FastAPIInstrumentor.instrument_app(app)
