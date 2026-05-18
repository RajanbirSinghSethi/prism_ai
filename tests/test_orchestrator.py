"""Unit tests for SDLCOrchestrator (orchestrator/workflow.py)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from sdlc_copilot.agents.registry import DEFAULT_WORKFLOW
from sdlc_copilot.models import PipelineState
from sdlc_copilot.orchestrator.workflow import SDLCOrchestrator


def test_run_populates_all_agent_outputs(mock_llm: MagicMock, sample_state: PipelineState) -> None:
    """All DEFAULT_WORKFLOW agents must produce an output; no errors."""
    orchestrator = SDLCOrchestrator(mock_llm)
    result = orchestrator.run(sample_state)

    assert len(result.outputs) == len(DEFAULT_WORKFLOW)
    assert len(result.errors) == 0


def test_run_records_error_and_continues(mock_llm: MagicMock, sample_state: PipelineState, monkeypatch: pytest.MonkeyPatch) -> None:
    """One failing agent records an error but does NOT abort remaining agents.

    Mocked at SDLCSpecAgent.run level (not llm.invoke) to bypass tenacity retry waits.
    """
    from sdlc_copilot.agents.executor import SDLCSpecAgent

    call_count = 0
    original_run = SDLCSpecAgent.run

    def patched_run(self, state):
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise RuntimeError("Simulated agent failure")
        return original_run(self, state)

    monkeypatch.setattr(SDLCSpecAgent, "run", patched_run)

    orchestrator = SDLCOrchestrator(mock_llm)
    result = orchestrator.run(sample_state)

    assert len(result.errors) == 1
    assert len(result.outputs) == len(DEFAULT_WORKFLOW) - 1


def test_stream_yields_one_state_per_agent(mock_llm: MagicMock) -> None:
    """stream() must yield exactly one PipelineState per agent in the subset."""
    state = PipelineState(project_name="Stream Test", context="ctx")
    orchestrator = SDLCOrchestrator(mock_llm, selected_agents=["requirement_extraction", "ambiguity_detection"])
    states = list(orchestrator.stream(state))

    assert len(states) == 2


def test_stream_accumulates_outputs(mock_llm: MagicMock) -> None:
    """Each yielded state must include all outputs produced so far."""
    state = PipelineState(project_name="Accumulate Test", context="ctx")
    orchestrator = SDLCOrchestrator(mock_llm, selected_agents=["requirement_extraction", "conflict_detection"])
    states = list(orchestrator.stream(state))

    # After first agent
    assert "requirement_extraction" in states[0].outputs
    # After second agent, both must be present
    assert "requirement_extraction" in states[1].outputs
    assert "conflict_detection" in states[1].outputs


def test_selected_agents_subset(mock_llm: MagicMock, sample_state: PipelineState) -> None:
    """Passing selected_agents limits execution to exactly that subset."""
    orchestrator = SDLCOrchestrator(mock_llm, selected_agents=["security_review"])
    result = orchestrator.run(sample_state)

    assert list(result.outputs.keys()) == ["security_review"]
    assert len(result.errors) == 0


def test_unknown_agent_id_raises() -> None:
    """Registry must reject unknown agent ids at construction time."""
    llm = MagicMock(spec=BaseChatModel)
    with pytest.raises(ValueError, match="Unknown agent ids"):
        SDLCOrchestrator(llm, selected_agents=["does_not_exist"])


def test_run_returns_same_state_object(mock_llm: MagicMock, sample_state: PipelineState) -> None:
    """run() mutates and returns the same PipelineState instance passed in."""
    orchestrator = SDLCOrchestrator(mock_llm, selected_agents=["effort_estimation"])
    result = orchestrator.run(sample_state)
    assert result is sample_state
