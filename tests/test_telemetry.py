"""Tests for the OpenTelemetry MVP bootstrap (sdlc_copilot.telemetry)."""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import ProxyTracerProvider

import sdlc_copilot.telemetry as telemetry_module
from sdlc_copilot.config import get_settings
from sdlc_copilot.telemetry import configure_telemetry, instrument_fastapi_app


@pytest.fixture(autouse=True)
def _reset_configured_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let every test re-enter configure_telemetry()'s body (idempotency is asserted
    explicitly where it matters). The underlying OTel SDK still only accepts the first
    real TracerProvider/instrumentation registered in this process — that's an
    OpenTelemetry API guarantee, not something our code needs to work around.
    """
    monkeypatch.setattr(telemetry_module, "_configured", False)


def test_otel_disabled_by_default() -> None:
    """Regression guard: nobody should flip the default without touching this test."""
    settings = get_settings().model_copy(update={})
    assert settings.otel_enabled is False


def test_otel_enabled_reads_from_settings() -> None:
    settings = get_settings().model_copy(update={"otel_enabled": True})
    assert settings.otel_enabled is True


def test_configure_telemetry_installs_real_tracer_provider() -> None:
    configure_telemetry()
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    assert not isinstance(provider, ProxyTracerProvider)
    assert telemetry_module._configured is True


def test_configure_telemetry_is_idempotent() -> None:
    configure_telemetry()
    provider_after_first_call = trace.get_tracer_provider()

    # Second call must be a no-op: no exception, no crash re-instrumenting httpx/logging.
    configure_telemetry()
    provider_after_second_call = trace.get_tracer_provider()

    assert provider_after_first_call is provider_after_second_call


def test_configure_telemetry_sets_service_resource_attributes() -> None:
    configure_telemetry()
    provider = trace.get_tracer_provider()
    resource_attrs = provider.resource.attributes
    assert resource_attrs["service.name"] == "sdlc-copilot"
    assert resource_attrs["service.version"] == "0.1.0"


def test_configure_telemetry_produces_recording_spans_with_real_context() -> None:
    """Spans created after configure_telemetry() must carry real (non-zero) trace context
    — the precondition for both the console exporter and log correlation to do anything."""
    configure_telemetry()
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("test-span") as span:
        assert span.is_recording()
        ctx = span.get_span_context()
        assert ctx.trace_id != 0
        assert ctx.span_id != 0


def test_configure_telemetry_injects_trace_context_into_log_records() -> None:
    """LoggingInstrumentor(inject_trace_context=True) must attach otelTraceID/otelSpanID
    to LogRecords emitted while a span is active — without requiring set_logging_format."""
    configure_telemetry()
    tracer = trace.get_tracer("test")

    captured_records: list[logging.LogRecord] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured_records.append(record)

    logger = logging.getLogger("sdlc_copilot.telemetry.test")
    logger.addHandler(_CaptureHandler())
    logger.setLevel(logging.INFO)

    with tracer.start_as_current_span("logging-span") as span:
        logger.info("inside a span")
        expected_trace_id = format(span.get_span_context().trace_id, "032x")
        expected_span_id = format(span.get_span_context().span_id, "016x")

    assert captured_records, "expected at least one captured log record"
    record = captured_records[-1]
    assert getattr(record, "otelTraceID", None) == expected_trace_id
    assert getattr(record, "otelSpanID", None) == expected_span_id


def test_logging_outside_a_span_does_not_crash() -> None:
    """Log correlation must be a no-op (not an error) when there is no active span."""
    configure_telemetry()
    logger = logging.getLogger("sdlc_copilot.telemetry.no_span_test")
    logger.info("no active span here")  # should not raise


def test_instrument_fastapi_app_does_not_raise() -> None:
    app = FastAPI()
    instrument_fastapi_app(app)  # should not raise


def test_instrument_fastapi_app_marks_app_as_instrumented() -> None:
    app = FastAPI()
    assert not hasattr(app, "_original_build_middleware_stack")
    instrument_fastapi_app(app)
    assert hasattr(app, "_original_build_middleware_stack")
