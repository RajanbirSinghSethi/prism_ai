"""Unit tests for sdlc_copilot.agents.validators."""
from __future__ import annotations

from sdlc_copilot.agents.validators import (
    format_findings,
    validate_cross_agent_ids,
)
from sdlc_copilot.models import AgentOutput, ArtifactType


def _output(agent_id: str, artifact_type, content: dict) -> AgentOutput:
    return AgentOutput(
        agent_id=agent_id,
        title=agent_id,
        artifact_type=artifact_type,
        content=content,
        confidence=0.9,
    )


def test_validate_clean_run_returns_empty() -> None:
    outputs = {
        "requirement_extraction": _output(
            "requirement_extraction",
            ArtifactType.REQUIREMENTS,
            {"functional": [{"id": "REQ-1", "description": "x"}]},
        ),
        "user_story_generation": _output(
            "user_story_generation",
            ArtifactType.STORIES,
            {"stories": [{"id": "STORY-1", "as_a": "user"}]},
        ),
        "task_decomposition": _output(
            "task_decomposition",
            ArtifactType.TASKS,
            {"tasks": [{"id": "TASK-1", "depends_on": ["STORY-1"]}]},
        ),
        "team_allocation": _output(
            "team_allocation",
            ArtifactType.TEAM_ALLOCATION,
            {"assignments": [{"task_id": "TASK-1", "role": "Developer"}]},
        ),
        "api_specification": _output(
            "api_specification",
            ArtifactType.API_SPEC,
            {"endpoints": [{"method": "GET", "path": "/v1/users"}]},
        ),
        "traceability": _output(
            "traceability",
            ArtifactType.TRACEABILITY,
            {"links": [{"requirement_id": "REQ-1", "api_ids": ["GET /v1/users"]}]},
        ),
    }
    assert validate_cross_agent_ids(outputs) == {}


def test_validate_detects_each_kind_of_mismatch() -> None:
    outputs = {
        "requirement_extraction": _output(
            "requirement_extraction",
            ArtifactType.REQUIREMENTS,
            {"functional": [{"id": "REQ-1"}]},
        ),
        "user_story_generation": _output(
            "user_story_generation",
            ArtifactType.STORIES,
            {"stories": [{"id": "STORY-1"}]},
        ),
        # Task references a story that doesn't exist
        "task_decomposition": _output(
            "task_decomposition",
            ArtifactType.TASKS,
            {"tasks": [{"id": "TASK-1", "depends_on": ["STORY-999"]}]},
        ),
        # Assignment references a non-existent task
        "team_allocation": _output(
            "team_allocation",
            ArtifactType.TEAM_ALLOCATION,
            {"assignments": [{"task_id": "TASK-999"}]},
        ),
        "api_specification": _output(
            "api_specification",
            ArtifactType.API_SPEC,
            {"endpoints": [{"method": "GET", "path": "/v1/orphan"}]},
        ),
        # Traceability invents a requirement ID, has no api_ids
        "traceability": _output(
            "traceability",
            ArtifactType.TRACEABILITY,
            {"links": [{"requirement_id": "REQ-NOPE"}]},
        ),
    }
    findings = validate_cross_agent_ids(outputs)
    assert "story_ids_in_tasks" in findings
    assert any("STORY-999" in issue for issue in findings["story_ids_in_tasks"])
    assert "task_ids_in_team_allocation" in findings
    assert any("TASK-999" in issue for issue in findings["task_ids_in_team_allocation"])
    assert "requirement_ids_in_traceability" in findings
    assert any("REQ-NOPE" in issue for issue in findings["requirement_ids_in_traceability"])
    assert "endpoints_in_traceability" in findings


def test_validate_handles_empty_outputs() -> None:
    """Empty/missing agent outputs must not crash any check."""
    assert validate_cross_agent_ids({}) == {}


def test_format_findings_round_trips() -> None:
    formatted = format_findings({"story_ids_in_tasks": ["issue A"]})
    assert "story_ids_in_tasks" in formatted
    assert "issue A" in formatted
    assert format_findings({}) == ""
