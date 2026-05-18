"""Integration tests for SDLCPipelineService (services/pipeline.py)."""
from __future__ import annotations

import orjson
import pytest

from sdlc_copilot.agents.registry import DEFAULT_WORKFLOW
from sdlc_copilot.models import PipelineRequest, PipelineResponse, SourceDocument
from sdlc_copilot.services.pipeline import SDLCPipelineService


def test_run_with_raw_text_succeeds(pipeline_service: SDLCPipelineService) -> None:
    """Pipeline with raw_text returns a complete PipelineResponse."""
    request = PipelineRequest(project_name="Demo", raw_text="Build a login page with OAuth.")
    response = pipeline_service.run(request)

    assert isinstance(response, PipelineResponse)
    assert response.project_name == "Demo"
    assert len(response.outputs) == len(DEFAULT_WORKFLOW)
    assert len(response.errors) == 0


def test_run_with_source_document(pipeline_service: SDLCPipelineService) -> None:
    """Pipeline accepts a pre-loaded SourceDocument."""
    doc = SourceDocument(filename="spec.txt", text="User can register with email and password.")
    response = pipeline_service.run(PipelineRequest(project_name="DocTest"), documents=[doc])

    assert response.run_id  # a UUID is present
    assert response.project_name == "DocTest"


def test_run_raises_on_no_input(pipeline_service: SDLCPipelineService) -> None:
    """No raw_text and no documents → ValueError."""
    with pytest.raises(ValueError, match="Provide raw_text"):
        pipeline_service.run(PipelineRequest(project_name="Empty"))


def test_artifact_persisted_to_disk(pipeline_service: SDLCPipelineService) -> None:
    """After run(), a JSON artifact must exist at artifact_dir/{run_id}.json."""
    response = pipeline_service.run(PipelineRequest(project_name="Persist", raw_text="requirements text"))
    artifact_path = pipeline_service.settings.artifact_dir / f"{response.run_id}.json"

    assert artifact_path.exists()
    data = orjson.loads(artifact_path.read_bytes())
    assert data["run_id"] == response.run_id
    assert data["project_name"] == "Persist"


def test_embedding_failure_is_non_fatal(pipeline_service: SDLCPipelineService, monkeypatch: pytest.MonkeyPatch) -> None:
    """Chroma indexing failure must record an error but the run must still complete."""
    def _fail(*args, **kwargs):
        raise RuntimeError("Chroma is down")

    monkeypatch.setattr("sdlc_copilot.services.pipeline.index_chunks", _fail)

    response = pipeline_service.run(PipelineRequest(project_name="EmbedFail", raw_text="text"))
    assert "embedding_index" in response.errors
    assert len(response.outputs) == len(DEFAULT_WORKFLOW)


def test_run_raw_text_and_document_combined(pipeline_service: SDLCPipelineService) -> None:
    """Both raw_text and a document can be provided; both are processed."""
    doc = SourceDocument(filename="extra.txt", text="Extra context.")
    response = pipeline_service.run(
        PipelineRequest(project_name="Combined", raw_text="Main requirements."),
        documents=[doc],
    )
    assert isinstance(response, PipelineResponse)
