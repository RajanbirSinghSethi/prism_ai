"""Tests for exporters and the export/get-run API endpoints."""
from __future__ import annotations

import json
import orjson
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from sdlc_copilot.integrations.exporters import export_csv, export_json, export_pdf
from sdlc_copilot.models import PipelineResponse


# ---------------------------------------------------------------------------
# Unit: export_json
# ---------------------------------------------------------------------------

def test_export_json_creates_file(sample_response: PipelineResponse, tmp_path: Path) -> None:
    path = export_json(sample_response, tmp_path / "out.json")
    assert path.exists()


def test_export_json_roundtrip(sample_response: PipelineResponse, tmp_path: Path) -> None:
    path = export_json(sample_response, tmp_path / "out.json")
    loaded = PipelineResponse.model_validate_json(path.read_text(encoding="utf-8"))
    assert loaded.run_id == sample_response.run_id
    assert loaded.project_name == sample_response.project_name


# ---------------------------------------------------------------------------
# Unit: export_csv
# ---------------------------------------------------------------------------

def test_export_csv_creates_file(sample_response: PipelineResponse, tmp_path: Path) -> None:
    path = export_csv(sample_response, tmp_path / "out.csv")
    assert path.exists()


def test_export_csv_has_header_and_rows(sample_response: PipelineResponse, tmp_path: Path) -> None:
    path = export_csv(sample_response, tmp_path / "out.csv")
    text = path.read_text(encoding="utf-8")
    assert "agent_id,title,artifact_type,content" in text
    assert "requirement_extraction" in text


# ---------------------------------------------------------------------------
# Unit: export_pdf
# ---------------------------------------------------------------------------

def test_export_pdf_creates_file(sample_response: PipelineResponse, tmp_path: Path) -> None:
    path = export_pdf(sample_response, tmp_path / "out.pdf")
    assert path.exists()
    assert path.stat().st_size > 0


def test_export_pdf_is_valid_pdf(sample_response: PipelineResponse, tmp_path: Path) -> None:
    """PDF files must start with the %PDF magic bytes."""
    path = export_pdf(sample_response, tmp_path / "out.pdf")
    assert path.read_bytes()[:4] == b"%PDF"


def test_export_pdf_handles_dict_risks_and_long_text(tmp_path: Path) -> None:
    """PDF export must tolerate dict risks and long strings (fpdf width fix)."""
    from sdlc_copilot.models import AgentOutput, ArtifactType

    long_risk = "Risk: " + ("x" * 280)
    output = AgentOutput(
        agent_id="security_review",
        title="Security Review Agent",
        artifact_type=ArtifactType.SECURITY_REVIEW,
        content={"findings": [{"id": "SEC-1"}]},
        risks=[long_risk],
        assumptions=["Assume TLS 1.2+ in production"],
        confidence=0.85,
    )
    response = PipelineResponse(run_id="test", project_name="P", outputs={"security_review": output})
    path = export_pdf(response, tmp_path / "dict_risks.pdf")
    assert path.read_bytes()[:4] == b"%PDF"


def test_export_pdf_handles_empty_risks_and_assumptions(tmp_path: Path) -> None:
    """PDF export must not crash when risks/assumptions lists are empty."""
    from sdlc_copilot.models import AgentOutput, ArtifactType
    output = AgentOutput(
        agent_id="test_agent", title="Test Agent",
        artifact_type=ArtifactType.TASKS, content={"tasks": []},
        risks=[], assumptions=[], confidence=0.9,
    )
    response = PipelineResponse(run_id="test", project_name="P", outputs={"test_agent": output})
    path = export_pdf(response, tmp_path / "no_risks.pdf")
    assert path.read_bytes()[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# API: GET /runs/{run_id}
# ---------------------------------------------------------------------------

@pytest.fixture
def client_with_artifact(monkeypatch: pytest.MonkeyPatch, sample_response: PipelineResponse, tmp_path: Path):
    """TestClient with a pre-written artifact file and settings pointing to tmp_path."""
    # Write the artifact
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir(parents=True)
    artifact_file = artifact_dir / f"{sample_response.run_id}.json"
    artifact_file.write_bytes(orjson.dumps(sample_response.model_dump(mode="json")))

    # Patch settings — use model_copy to avoid validation_alias keyword-arg issues
    from sdlc_copilot.config import get_settings
    fake_settings = get_settings().model_copy(
        update={"artifact_dir": artifact_dir, "chroma_persist_dir": tmp_path / "chroma"}
    )
    monkeypatch.setattr("sdlc_copilot.main.settings", fake_settings)

    # Also patch SDLCPipelineService so /runs POST still works
    monkeypatch.setattr(
        "sdlc_copilot.main.SDLCPipelineService",
        lambda *a, **kw: SimpleNamespace(run=lambda *a, **kw: sample_response),
    )

    from fastapi.testclient import TestClient
    from sdlc_copilot.main import app
    return TestClient(app), sample_response.run_id


def test_get_run_returns_200(client_with_artifact) -> None:
    client, run_id = client_with_artifact
    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["run_id"] == run_id


def test_get_run_not_found_returns_404(client_with_artifact) -> None:
    client, _ = client_with_artifact
    response = client.get("/runs/nonexistent-run-id-xyz")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# API: GET /runs/{run_id}/export
# ---------------------------------------------------------------------------

def test_export_endpoint_json(client_with_artifact) -> None:
    client, run_id = client_with_artifact
    response = client.get(f"/runs/{run_id}/export?format=json")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert run_id in response.headers.get("content-disposition", "")


def test_export_endpoint_csv(client_with_artifact) -> None:
    client, run_id = client_with_artifact
    response = client.get(f"/runs/{run_id}/export?format=csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]


def test_export_endpoint_pdf(client_with_artifact) -> None:
    client, run_id = client_with_artifact
    response = client.get(f"/runs/{run_id}/export?format=pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:4] == b"%PDF"


def test_export_endpoint_not_found_returns_404(client_with_artifact) -> None:
    client, _ = client_with_artifact
    response = client.get("/runs/no-such-run/export?format=json")
    assert response.status_code == 404
