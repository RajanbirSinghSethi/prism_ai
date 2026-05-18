"""Tests for LangGraphOrchestrator (orchestrator/workflow.py)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from sdlc_copilot.models import LangGraphState, PipelineState
from sdlc_copilot.orchestrator.workflow import (
    LangGraphOrchestrator,
    _LANGGRAPH_WORKFLOW,
    _TAIL_START,
)


def _make_state() -> PipelineState:
    return PipelineState(project_name="LG Test", context="Build a payment service.")


# ---------------------------------------------------------------------------
# Routing logic (unit tests — no graph execution)
# ---------------------------------------------------------------------------

def test_route_returns_tail_start_when_no_low_confidence(mock_llm: MagicMock) -> None:
    """Router must return _TAIL_START when low_confidence_agents is empty."""
    orch = LangGraphOrchestrator(mock_llm, selected_agents=["requirement_extraction"])
    state: LangGraphState = {  # type: ignore[typeddict-item]
        "run_id": "test",
        "project_name": "P",
        "context": "",
        "team": [],
        "constraints": {},
        "outputs": {},
        "errors": {},
        "low_confidence_agents": [],
    }
    assert orch._route_after_validation(state) == _TAIL_START


def test_route_returns_feedback_when_low_confidence_agents_present(mock_llm: MagicMock) -> None:
    """Router must return 'feedback_refinement' when list is non-empty."""
    orch = LangGraphOrchestrator(mock_llm, selected_agents=["requirement_extraction"])
    state: LangGraphState = {  # type: ignore[typeddict-item]
        "run_id": "test",
        "project_name": "P",
        "context": "",
        "team": [],
        "constraints": {},
        "outputs": {},
        "errors": {},
        "low_confidence_agents": ["hallucination_validation"],
    }
    assert orch._route_after_validation(state) == "feedback_refinement"


# ---------------------------------------------------------------------------
# Full graph execution
# ---------------------------------------------------------------------------

def test_langgraph_run_all_confident_skips_feedback(mock_llm: MagicMock) -> None:
    """High-confidence mock LLM → feedback_refinement should NOT appear in outputs."""
    orch = LangGraphOrchestrator(mock_llm, confidence_threshold=0.6)
    result = orch.run(_make_state())
    assert "feedback_refinement" not in result.outputs
    # All workflow agents must have run
    assert len(result.outputs) >= len(_LANGGRAPH_WORKFLOW) - 1


def test_langgraph_run_triggers_feedback_on_low_confidence(low_confidence_llm: MagicMock) -> None:
    """Low-confidence mock LLM (0.4) → feedback_refinement must appear in outputs."""
    orch = LangGraphOrchestrator(low_confidence_llm, confidence_threshold=0.6)
    result = orch.run(_make_state())
    assert "feedback_refinement" in result.outputs


def test_langgraph_run_errors_are_isolated(mock_llm: MagicMock, sample_state: PipelineState, monkeypatch: pytest.MonkeyPatch) -> None:
    """One node throwing an exception must not abort the entire graph run.

    Mocked at SDLCSpecAgent.run level to bypass tenacity retry waits.
    """
    from sdlc_copilot.agents.executor import SDLCSpecAgent

    call_count = 0
    original_run = SDLCSpecAgent.run

    def patched_run(self, state):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("Simulated node failure")
        return original_run(self, state)

    monkeypatch.setattr(SDLCSpecAgent, "run", patched_run)

    orch = LangGraphOrchestrator(mock_llm, confidence_threshold=0.6)
    result = orch.run(sample_state)
    assert len(result.errors) >= 1
    assert len(result.outputs) > 0


def test_langgraph_stream_yields_tuples(mock_llm: MagicMock) -> None:
    """stream() must yield (node_name, PipelineState) tuples."""
    orch = LangGraphOrchestrator(
        mock_llm,
        selected_agents=["requirement_extraction", "ambiguity_detection"],
        confidence_threshold=0.6,
    )
    events = list(orch.stream(_make_state()))
    assert len(events) >= 1
    for node_name, state in events:
        assert isinstance(node_name, str)
        assert isinstance(state, PipelineState)


# ---------------------------------------------------------------------------
# Pipeline service integration — USE_LANGGRAPH flag
# ---------------------------------------------------------------------------

def test_pipeline_service_uses_langgraph_when_flag_set(
    mock_llm: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Setting use_langgraph=True must cause the service to instantiate LangGraphOrchestrator."""
    from sdlc_copilot.models import PipelineRequest
    from sdlc_copilot.services.pipeline import SDLCPipelineService

    from sdlc_copilot.config import get_settings
    settings = get_settings().model_copy(
        update={
            "use_langgraph": True,
            "artifact_dir": tmp_path / "artifacts",
            "chroma_persist_dir": tmp_path / "chroma",
        }
    )
    monkeypatch.setattr("sdlc_copilot.services.pipeline.build_chat_model", lambda _: mock_llm)
    monkeypatch.setattr("sdlc_copilot.services.pipeline.index_chunks", lambda *a, **kw: None)

    instantiated = []

    original_init = LangGraphOrchestrator.__init__

    def tracking_init(self, *args, **kwargs):
        instantiated.append(True)
        original_init(self, *args, **kwargs)

    # Patch the class object directly — string dotted path can't reach __init__ reliably
    monkeypatch.setattr(LangGraphOrchestrator, "__init__", tracking_init)

    service = SDLCPipelineService(settings)
    service.run(PipelineRequest(project_name="LG Flag Test", raw_text="login flow"))
    # The LangGraphOrchestrator must have been constructed
    assert len(instantiated) > 0
