"""Unit tests for sdlc_copilot.agents.agent_logger."""
from __future__ import annotations

import json
from pathlib import Path

from sdlc_copilot.agents.agent_logger import AgentLogger
from sdlc_copilot.models import AgentOutput, ArtifactType


def _sample_output() -> AgentOutput:
    return AgentOutput(
        agent_id="requirement_extraction",
        title="Requirement Extraction Agent",
        artifact_type=ArtifactType.REQUIREMENTS,
        content={"functional": [{"id": "REQ-1"}]},
        risks=["one risk"],
        assumptions=[],
        confidence=0.9,
    )


def test_enabled_logger_writes_json(tmp_path: Path) -> None:
    logger = AgentLogger(run_id="r1", log_dir=tmp_path, enabled=True,
                         model="m", provider="p")
    logger.record(
        agent_id="requirement_extraction",
        order=0,
        system_prompt="sys",
        user_payload={"project_name": "x"},
        raw_response='{"content": {}}',
        parsed_ok=True,
        attempts=1,
        retry_reasons=[],
        duration_ms=42,
        output=_sample_output(),
        error=None,
    )

    log_path = tmp_path / "r1" / "00_requirement_extraction.json"
    assert log_path.exists()
    data = json.loads(log_path.read_text())
    assert data["agent_id"] == "requirement_extraction"
    assert data["model"] == "m"
    assert data["provider"] == "p"
    assert data["parsed_ok"] is True
    assert data["output"]["confidence"] == 0.9
    assert data["output"]["risks_count"] == 1
    assert data["output"]["content_keys"] == ["functional"]
    assert data["prompt"]["user_payload_keys"] == ["project_name"]


def test_disabled_logger_writes_nothing(tmp_path: Path) -> None:
    logger = AgentLogger(run_id="r2", log_dir=tmp_path, enabled=False)
    logger.record(
        agent_id="security_review",
        order=0,
        system_prompt="sys",
        user_payload={},
        raw_response="",
        parsed_ok=False,
        attempts=0,
        retry_reasons=[],
        duration_ms=0,
        output=None,
        error=None,
    )
    # No directory and no files created.
    assert not (tmp_path / "r2").exists()


def test_error_path_still_writes_valid_json(tmp_path: Path) -> None:
    logger = AgentLogger(run_id="r3", log_dir=tmp_path, enabled=True)
    logger.record(
        agent_id="acceptance_criteria",
        order=11,
        system_prompt="sys",
        user_payload={"a": 1},
        raw_response="",
        parsed_ok=False,
        attempts=3,
        retry_reasons=["RateLimitError: 429"],
        duration_ms=12345,
        output=None,
        error="Error code: 429",
    )
    log_path = tmp_path / "r3" / "11_acceptance_criteria.json"
    assert log_path.exists()
    data = json.loads(log_path.read_text())
    assert data["output"] is None
    assert data["error"] == "Error code: 429"
    assert data["attempts"] == 3
    assert data["retry_reasons"] == ["RateLimitError: 429"]
