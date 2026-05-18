"""Unit tests for SDLCSpecAgent (agents/executor.py)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from sdlc_copilot.agents.executor import SDLCSpecAgent, _compact_prior_outputs, _trim_text, _try_parse_json
from sdlc_copilot.config import get_settings
from sdlc_copilot.agents.specs import AGENTS_BY_ID
from sdlc_copilot.models import AgentOutput, ArtifactType, PipelineState


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_run_returns_agent_output(mock_llm: MagicMock, sample_state: PipelineState) -> None:
    """Valid JSON response → AgentOutput with correct fields."""
    spec = AGENTS_BY_ID["requirement_extraction"]
    agent = SDLCSpecAgent(spec, mock_llm)
    output = agent.run(sample_state)

    assert isinstance(output, AgentOutput)
    assert output.agent_id == "requirement_extraction"
    assert output.confidence == pytest.approx(0.85)
    assert output.artifact_type == ArtifactType.REQUIREMENTS
    mock_llm.invoke.assert_called_once()


def test_run_handles_markdown_json_fence(sample_state: PipelineState) -> None:
    """LLM wraps JSON in ```json ... ``` — should still parse correctly."""
    llm = MagicMock(spec=BaseChatModel)
    llm.invoke.return_value = MagicMock(
        content='```json\n{"content":{},"risks":[],"assumptions":[],"confidence":0.7}\n```'
    )
    spec = AGENTS_BY_ID["requirement_extraction"]
    output = SDLCSpecAgent(spec, llm).run(sample_state)
    assert output.confidence == pytest.approx(0.7)


def test_run_defaults_missing_confidence(sample_state: PipelineState) -> None:
    """JSON without 'confidence' key → defaults to 0.75."""
    llm = MagicMock(spec=BaseChatModel)
    llm.invoke.return_value = MagicMock(content='{"content":{"items":[]},"risks":[],"assumptions":[]}')
    spec = AGENTS_BY_ID["requirement_extraction"]
    output = SDLCSpecAgent(spec, llm).run(sample_state)
    assert output.confidence == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# Failure / fallback paths
# ---------------------------------------------------------------------------

def test_run_handles_non_json_response(sample_state: PipelineState) -> None:
    """Non-JSON LLM output → retry then graceful fallback with reduced confidence."""
    llm = MagicMock(spec=BaseChatModel)
    llm.invoke.return_value = MagicMock(content="Sorry, I cannot help with that.")
    spec = AGENTS_BY_ID["requirement_extraction"]
    output = SDLCSpecAgent(spec, llm).run(sample_state)

    assert output.confidence == pytest.approx(0.55)
    assert "raw" in output.content
    assert llm.invoke.call_count == 2


def test_try_parse_json_extracts_from_prose() -> None:
    text = (
        'Analysis complete.\n\n{"content":{"items":["login"]},"risks":[],"assumptions":[],"confidence":0.88}\n'
    )
    parsed = _try_parse_json(text)
    assert parsed is not None
    assert parsed["confidence"] == pytest.approx(0.88)


def test_run_handles_list_response(sample_state: PipelineState) -> None:
    """JSON array → wrapped in a dict so AgentOutput.content is always a dict."""
    llm = MagicMock(spec=BaseChatModel)
    llm.invoke.return_value = MagicMock(content='["item1", "item2"]')
    spec = AGENTS_BY_ID["task_decomposition"]
    output = SDLCSpecAgent(spec, llm).run(sample_state)
    assert isinstance(output.content, dict)
    assert "items" in output.content


# ---------------------------------------------------------------------------
# Prompt content
# ---------------------------------------------------------------------------

def test_system_prompt_contains_spec_fields() -> None:
    """System prompt references title, purpose, and every responsibility."""
    spec = AGENTS_BY_ID["security_review"]
    agent = SDLCSpecAgent(spec, MagicMock(spec=BaseChatModel))
    prompt = agent._system_prompt()

    assert spec.title in prompt
    assert spec.purpose in prompt
    for responsibility in spec.responsibilities:
        assert responsibility in prompt


def test_system_prompt_contains_edge_cases() -> None:
    spec = AGENTS_BY_ID["conflict_detection"]
    agent = SDLCSpecAgent(spec, MagicMock(spec=BaseChatModel))
    prompt = agent._system_prompt()
    for edge_case in spec.edge_cases:
        assert edge_case in prompt


def test_user_prompt_includes_prior_outputs(mock_llm: MagicMock, sample_state: PipelineState) -> None:
    """Prior agent outputs are injected into the user prompt JSON."""
    prior = AgentOutput(
        agent_id="requirement_extraction",
        title="Req Extraction",
        artifact_type=ArtifactType.REQUIREMENTS,
        content={"items": ["auth flow"]},
        confidence=0.8,
    )
    sample_state.outputs["requirement_extraction"] = prior

    spec = AGENTS_BY_ID["conflict_detection"]
    agent = SDLCSpecAgent(spec, mock_llm)
    data = json.loads(agent._user_prompt(sample_state))

    assert "requirement_extraction" in data["previous_agent_outputs"]


def test_user_prompt_excludes_self_from_prior(mock_llm: MagicMock, sample_state: PipelineState) -> None:
    """Current agent's own id is NOT included in previous_agent_outputs."""
    prior = AgentOutput(
        agent_id="requirement_extraction",
        title="x", artifact_type="test", content={}, confidence=0.8,
    )
    sample_state.outputs["requirement_extraction"] = prior

    spec = AGENTS_BY_ID["requirement_extraction"]
    agent = SDLCSpecAgent(spec, mock_llm)
    data = json.loads(agent._user_prompt(sample_state))

    assert "requirement_extraction" not in data["previous_agent_outputs"]


def test_user_prompt_contains_project_name(mock_llm: MagicMock, sample_state: PipelineState) -> None:
    spec = AGENTS_BY_ID["effort_estimation"]
    agent = SDLCSpecAgent(spec, mock_llm)
    data = json.loads(agent._user_prompt(sample_state))
    assert data["project_name"] == "Test Project"


# ---------------------------------------------------------------------------
# Feedback & Refinement agent enrichment (Phase 3 — tested early)
# ---------------------------------------------------------------------------

def test_feedback_agent_prompt_includes_low_confidence_context(sample_state: PipelineState) -> None:
    """feedback_refinement user prompt must contain 'feedback_context' when prior outputs are low-confidence."""
    low_output = AgentOutput(
        agent_id="hallucination_validation",
        title="Hallucination Validation",
        artifact_type="validation",
        content={},
        confidence=0.3,
    )
    sample_state.outputs["hallucination_validation"] = low_output

    spec = AGENTS_BY_ID["feedback_refinement"]
    agent = SDLCSpecAgent(spec, MagicMock(spec=BaseChatModel))
    data = json.loads(agent._user_prompt(sample_state))

    assert "feedback_context" in data
    assert "hallucination_validation" in data["feedback_context"]["low_confidence_outputs"]


def test_feedback_agent_automated_mode_instruction(sample_state: PipelineState) -> None:
    """feedback_context must carry mode=automated and an instruction string."""
    sample_state.outputs["some_agent"] = AgentOutput(
        agent_id="some_agent", title="x", artifact_type="t", content={}, confidence=0.2
    )
    spec = AGENTS_BY_ID["feedback_refinement"]
    agent = SDLCSpecAgent(spec, MagicMock(spec=BaseChatModel))
    data = json.loads(agent._user_prompt(sample_state))

    assert data["feedback_context"]["mode"] == "automated"
    assert "instruction" in data["feedback_context"]


def test_trim_text_truncates_long_context() -> None:
    assert _trim_text("hello world", 100) == "hello world"
    assert "truncated" in _trim_text("x" * 200, 50)


def test_compact_prior_outputs_keeps_last_n_agents(sample_state: PipelineState) -> None:
    settings = get_settings()
    for agent_id in ("a", "b", "c", "d", "e"):
        sample_state.outputs[agent_id] = AgentOutput(
            agent_id=agent_id,
            title=agent_id,
            artifact_type="t",
            content={"data": "x" * 2000},
            confidence=0.8,
        )
    compact = _compact_prior_outputs(
        sample_state.outputs,
        exclude_id="z",
        max_agents=2,
        max_content_chars=100,
    )
    assert list(compact.keys()) == ["d", "e"]
    assert compact["e"]["content"]["_truncated_summary"].endswith("...")


def test_feedback_agent_omits_context_when_all_confident(sample_state: PipelineState) -> None:
    """No feedback_context key when all prior outputs are high-confidence."""
    high_output = AgentOutput(
        agent_id="security_review", title="x", artifact_type="t", content={}, confidence=0.9
    )
    sample_state.outputs["security_review"] = high_output

    spec = AGENTS_BY_ID["feedback_refinement"]
    agent = SDLCSpecAgent(spec, MagicMock(spec=BaseChatModel))
    data = json.loads(agent._user_prompt(sample_state))

    # feedback_context may be present but low_confidence_outputs should be empty
    fc = data.get("feedback_context", {})
    assert fc.get("low_confidence_outputs", {}) == {}
