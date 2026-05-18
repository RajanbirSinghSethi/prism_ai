"""FastAPI endpoint tests using synchronous TestClient (no real LLM calls)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sdlc_copilot.agents.specs import AGENT_SPECS


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_returns_ayra_html(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "PRISM" in response.text


def test_api_info_returns_service_metadata(client: TestClient) -> None:
    response = client.get("/api/info")
    assert response.status_code == 200
    data = response.json()
    assert "service" in data
    assert "docs" in data


def test_agents_returns_full_list(client: TestClient) -> None:
    response = client.get("/agents")
    assert response.status_code == 200
    ids = {a["id"] for a in response.json()}
    assert "requirement_extraction" in ids
    assert "compliance" in ids
    assert len(ids) == len(AGENT_SPECS)


def test_post_runs_success(client: TestClient) -> None:
    payload = {"project_name": "API Test", "raw_text": "Build a login form."}
    response = client.post("/runs", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert "outputs" in data


def test_post_runs_empty_text_returns_400(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Service raising ValueError on empty input must surface as HTTP 400."""
    from types import SimpleNamespace

    def _raise(*args, **kwargs):
        raise ValueError("Provide raw_text or at least one document.")

    monkeypatch.setattr(
        "sdlc_copilot.main.SDLCPipelineService",
        lambda *a, **kw: SimpleNamespace(run=_raise),
    )
    response = client.post("/runs", json={"project_name": "Bad"})
    assert response.status_code == 400


def test_post_upload_with_txt_file(client: TestClient) -> None:
    data = {"project_name": "Upload Test"}
    files = [("files", ("requirements.txt", b"User can log in.", "text/plain"))]
    response = client.post("/runs/upload", data=data, files=files)
    assert response.status_code == 200
    assert "run_id" in response.json()


def test_post_upload_no_files_returns_422(client: TestClient) -> None:
    """Missing required 'files' field → 422 Unprocessable Entity from FastAPI."""
    response = client.post("/runs/upload", data={"project_name": "No Files"})
    assert response.status_code == 422
