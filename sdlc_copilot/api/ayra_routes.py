from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from sdlc_copilot.agents.registry import DEFAULT_WORKFLOW
from sdlc_copilot.agents.specs import AGENTS_BY_ID
from sdlc_copilot.ingestion.loaders import SUPPORTED_SUFFIXES, load_upload
from sdlc_copilot.models import AgentOutput, PipelineRequest, PipelineResponse, PipelineState
from sdlc_copilot.config import get_settings
from sdlc_copilot.services.ayra_chat import build_run_summary, handle_message
from sdlc_copilot.services.pipeline import SDLCPipelineService
from sdlc_copilot.services.whisper_transcribe import transcribe_bytes, whisper_available

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ayra", tags=["ayra"])

_SUPPORTED_LABEL = ", ".join(sorted(ext.lstrip(".") for ext in SUPPORTED_SUFFIXES))


def _workflow_meta() -> list[dict[str, str]]:
    return [
        {
            "id": agent_id,
            "title": AGENTS_BY_ID[agent_id].title,
        }
        for agent_id in DEFAULT_WORKFLOW
    ]


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _serialize_output(output: AgentOutput) -> dict[str, Any]:
    return output.model_dump(mode="json")


@router.get("/config")
def ayra_config() -> dict[str, Any]:
    return {
        "name": "PRISM - AI SDLC Copilot",
        "supported_formats": sorted(ext.lstrip(".") for ext in SUPPORTED_SUFFIXES),
        "workflow": _workflow_meta(),
        "agent_count": len(DEFAULT_WORKFLOW),
        "whisper_available": whisper_available(),
        "whisper_model": get_settings().whisper_model,
    }


@router.post("/transcribe")
async def ayra_transcribe(audio: UploadFile = File(...)) -> dict[str, str]:
    """Speech-to-text via local faster-whisper (open source)."""
    if not whisper_available():
        raise HTTPException(
            status_code=503,
            detail='Whisper not installed. Run: pip install -e ".[whisper]"',
        )
    raw = await audio.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio file.")
    try:
        text = transcribe_bytes(
            raw,
            audio.filename or "speech.webm",
            model_size=get_settings().whisper_model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("Whisper transcription failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"text": text, "engine": "faster-whisper"}


@router.post("/message")
async def ayra_message(
    message: str = Form(""),
    files: list[UploadFile] = File(default=[]),
) -> dict[str, Any]:
    """Conversational turn: reply only, or signal that the pipeline should run."""
    from sdlc_copilot.config import get_settings

    cfg = get_settings()
    valid_files: list[UploadFile] = []
    for upload in files:
        if not upload.filename:
            continue
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file '{upload.filename}'. Supported: {_SUPPORTED_LABEL}",
            )
        valid_files.append(upload)

    result = handle_message(message, settings=cfg, has_documents=bool(valid_files))
    result["supported_formats"] = sorted(ext.lstrip(".") for ext in SUPPORTED_SUFFIXES)
    return result


@router.post("/runs/stream")
async def ayra_stream_run(
    message: str = Form(""),
    project_name: str = Form("PRISM Project"),
    use_langgraph: bool = Form(False),
    files: list[UploadFile] = File(default=[]),
) -> StreamingResponse:
    """SSE stream: workflow steps, per-agent progress, final artifacts."""
    from sdlc_copilot.config import get_settings

    cfg = get_settings().model_copy(update={"use_langgraph": use_langgraph})
    documents = []
    for upload in files:
        if not upload.filename:
            continue
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file '{upload.filename}'. Supported: {_SUPPORTED_LABEL}",
            )
        documents.append(await load_upload(upload))

    requirements = message.strip()
    if not requirements and not documents:
        raise HTTPException(status_code=400, detail="Provide a message or at least one supported file.")

    request = PipelineRequest(
        project_name=project_name,
        raw_text=requirements or None,
    )

    def event_stream() -> Iterator[str]:
        service = SDLCPipelineService(cfg)
        state: PipelineState | None = None
        yield _sse("workflow", {"agents": _workflow_meta(), "total": len(DEFAULT_WORKFLOW)})
        try:
            for agent_id, updated in service.stream(request, documents=documents or None):
                state = updated
                yield _sse(
                    "progress",
                    {
                        "agent_id": agent_id,
                        "title": (
                            AGENTS_BY_ID[agent_id].title
                            if agent_id in AGENTS_BY_ID
                            else agent_id.replace("_", " ").title()
                        ),
                        "completed": list(updated.outputs.keys()),
                        "errors": dict(updated.errors),
                        "index": len(updated.outputs) + len(
                            [e for e in updated.errors if e not in updated.outputs]
                        ),
                        "total": len(DEFAULT_WORKFLOW),
                    },
                )
        except Exception as exc:  # noqa: BLE001
            log.exception("Ayra pipeline stream failed")
            yield _sse("error", {"detail": str(exc)})
            return

        if state is None:
            yield _sse("error", {"detail": "Pipeline did not start."})
            return

        outputs = {k: _serialize_output(v) for k, v in state.outputs.items()}
        response = PipelineResponse(
            run_id=state.run_id,
            project_name=state.project_name,
            outputs=state.outputs,
            errors=state.errors,
        )
        summary = build_run_summary(outputs, state.errors)
        yield _sse(
            "done",
            {
                "run_id": state.run_id,
                "project_name": state.project_name,
                "summary": summary,
                "outputs": outputs,
                "errors": state.errors,
                "workflow": _workflow_meta(),
                "export_urls": {
                    "json": f"/runs/{state.run_id}/export?format=json",
                    "csv": f"/runs/{state.run_id}/export?format=csv",
                    "pdf": f"/runs/{state.run_id}/export?format=pdf",
                },
            },
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
