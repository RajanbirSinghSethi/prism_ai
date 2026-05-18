"""Ayra UI API tests."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_ayra_config(client: TestClient) -> None:
    response = client.get("/api/ayra/config")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "PRISM - AI SDLC Copilot"
    assert "pdf" in data["supported_formats"]
    assert data["agent_count"] == 22


def test_ayra_message_greeting(client: TestClient) -> None:
    response = client.post("/api/ayra/message", data={"message": "hello"})
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "reply"
    assert "PRISM" in body["text"]


def test_ayra_transcribe_without_whisper(client: TestClient) -> None:
    files = [("audio", ("speech.webm", b"\x00\x01", "audio/webm"))]
    response = client.post("/api/ayra/transcribe", files=files)
    assert response.status_code in (503, 500, 400)


def test_ayra_message_unsupported_file(client: TestClient) -> None:
    files = [("files", ("bad.exe", b"binary", "application/octet-stream"))]
    response = client.post("/api/ayra/message", data={"message": "analyze"}, files=files)
    assert response.status_code == 400
    assert "Unsupported" in response.json()["detail"]
