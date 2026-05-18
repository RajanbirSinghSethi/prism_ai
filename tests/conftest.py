"""Shared pytest fixtures — no real LLM, embedding, or filesystem API calls."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel

from sdlc_copilot.config import Settings
from sdlc_copilot.models import (
    AgentOutput,
    ArtifactType,
    PipelineRequest,
    PipelineResponse,
    PipelineState,
    SourceDocument,
)
from sdlc_copilot.services.pipeline import SDLCPipelineService


# ---------------------------------------------------------------------------
# LLM mocks
# ---------------------------------------------------------------------------

_GOOD_JSON = '{"content":{"summary":"ok"},"risks":[],"assumptions":[],"confidence":0.85}'
_LOW_JSON = '{"content":{},"risks":["uncertain"],"assumptions":[],"confidence":0.4}'


@pytest.fixture
def mock_llm() -> MagicMock:
    """BaseChatModel whose invoke() returns a valid high-confidence JSON payload."""
    llm = MagicMock(spec=BaseChatModel)
    llm.invoke.return_value = MagicMock(content=_GOOD_JSON)
    return llm


@pytest.fixture
def low_confidence_llm() -> MagicMock:
    """BaseChatModel returning confidence=0.4 — triggers feedback_refinement routing."""
    llm = MagicMock(spec=BaseChatModel)
    llm.invoke.return_value = MagicMock(content=_LOW_JSON)
    return llm


# ---------------------------------------------------------------------------
# Pipeline state / response helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_state() -> PipelineState:
    return PipelineState(project_name="Test Project", context="Build a login page.")


@pytest.fixture
def sample_document() -> SourceDocument:
    return SourceDocument(filename="req.txt", content_type="text/plain", text="User registration flow.")


@pytest.fixture
def sample_output() -> AgentOutput:
    return AgentOutput(
        agent_id="requirement_extraction",
        title="Requirement Extraction Agent",
        artifact_type=ArtifactType.REQUIREMENTS,
        content={"items": ["login"]},
        confidence=0.9,
    )


@pytest.fixture
def sample_response(sample_output: AgentOutput) -> PipelineResponse:
    return PipelineResponse(
        run_id="test-run-id",
        project_name="Test Project",
        outputs={"requirement_extraction": sample_output},
    )


# ---------------------------------------------------------------------------
# Pipeline service with all external calls patched out
# ---------------------------------------------------------------------------

@pytest.fixture
def pipeline_service(mock_llm: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path) -> SDLCPipelineService:
    """SDLCPipelineService wired to mock LLM; Chroma indexing is a no-op."""
    settings = Settings(
        llm_provider="openrouter",
        openrouter_api_key="test-key",
        artifact_dir=tmp_path / "artifacts",
        chroma_persist_dir=tmp_path / "chroma",
    )
    monkeypatch.setattr("sdlc_copilot.services.pipeline.build_chat_model", lambda _: mock_llm)
    monkeypatch.setattr("sdlc_copilot.services.pipeline.index_chunks", lambda *a, **kw: None)
    return SDLCPipelineService(settings)


# ---------------------------------------------------------------------------
# FastAPI TestClient with pipeline service fully mocked
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_pipeline_response(sample_response: PipelineResponse) -> PipelineResponse:
    return sample_response


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, mock_pipeline_response: PipelineResponse):
    """FastAPI TestClient; SDLCPipelineService.run() always returns mock_pipeline_response."""
    def _fake_service(*args, **kwargs):
        return SimpleNamespace(run=lambda *a, **kw: mock_pipeline_response)

    monkeypatch.setattr("sdlc_copilot.main.SDLCPipelineService", _fake_service)

    from fastapi.testclient import TestClient
    from sdlc_copilot.main import app

    return TestClient(app)
