from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from sdlc_copilot.agents.registry import DEFAULT_WORKFLOW
from sdlc_copilot.agents.specs import AGENTS_BY_ID
from sdlc_copilot.ingestion.loaders import SUPPORTED_SUFFIXES, load_upload
from sdlc_copilot.models import AgentOutput, PipelineRequest, PipelineState
from sdlc_copilot.config import get_settings
from sdlc_copilot.services import run_sessions
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


def _sse_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


def _progress_event(agent_id: str, state: PipelineState, *, cached: bool, total: int) -> str:
    title = (
        AGENTS_BY_ID[agent_id].title
        if agent_id in AGENTS_BY_ID
        else agent_id.replace("_", " ").title()
    )
    return _sse(
        "progress",
        {
            "agent_id": agent_id,
            "title": title,
            "cached": cached,
            "completed": list(state.outputs.keys()),
            "errors": dict(state.errors),
            "index": len(state.outputs)
            + len([e for e in state.errors if e not in state.outputs]),
            "total": total,
        },
    )


def _extract_tasks(state: PipelineState) -> list[dict[str, Any]]:
    output = state.outputs.get("task_decomposition")
    if output is None or not isinstance(output.content, dict):
        return []
    tasks = output.content.get("tasks", [])
    return tasks if isinstance(tasks, list) else []


def _coerce_hours(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 8.0


def _extract_assignments(state: PipelineState) -> list[dict[str, Any]]:
    """Return team-allocation assignments, falling back to task_decomposition tasks.

    The LLM sometimes returns ``team_allocation`` without an ``assignments``
    list (or returns it in a non-list shape). To keep the UI useful we always
    produce at least one row per task so the user can edit/finalize.
    """
    normalised: list[dict[str, Any]] = []
    output = state.outputs.get("team_allocation")
    if output is not None and isinstance(output.content, dict):
        raw = output.content.get("assignments")
        # Some models nest assignments under e.g. "items" — accept any list value.
        if not isinstance(raw, list):
            for value in output.content.values():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    raw = value
                    break
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    normalised.append(
                        {
                            "task_id": str(item.get("task_id") or item.get("id") or ""),
                            "role": str(item.get("role") or "Developer"),
                            "owner": str(item.get("owner") or item.get("assignee") or "TBD"),
                            "estimated_hours": _coerce_hours(item.get("estimated_hours")),
                        }
                    )

    if normalised:
        return normalised

    # Fallback: one default row per task from task_decomposition.
    for task in _extract_tasks(state):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or task.get("task_id") or "")
        if not task_id:
            continue
        normalised.append(
            {
                "task_id": task_id,
                "role": "Developer",
                "owner": "TBD",
                "estimated_hours": 8.0,
            }
        )
    return normalised


def _done_payload(state: PipelineState) -> dict[str, Any]:
    outputs = {k: _serialize_output(v) for k, v in state.outputs.items()}
    summary = build_run_summary(outputs, state.errors)
    return {
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
    }


@router.post("/runs/stream")
async def ayra_stream_run(
    message: str = Form(""),
    project_name: str = Form("PRISM Project"),
    use_langgraph: bool = Form(False),
    force_refresh: bool = Form(False),
    files: list[UploadFile] = File(default=[]),
) -> StreamingResponse:
    """SSE stream for the head phase. Ends with a ``requires_input`` event."""
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
    total = len(DEFAULT_WORKFLOW)

    def event_stream() -> Iterator[str]:
        service = SDLCPipelineService(cfg)
        state: PipelineState | None = None
        any_cached = False
        yield _sse("workflow", {"agents": _workflow_meta(), "total": total})
        try:
            for agent_id, updated, cached in service.stream_head(
                request,
                documents=documents or None,
                force_refresh=force_refresh,
            ):
                state = updated
                any_cached = any_cached or cached
                yield _progress_event(agent_id, updated, cached=cached, total=total)
        except Exception as exc:  # noqa: BLE001
            log.exception("Ayra head stream failed")
            yield _sse("error", {"detail": str(exc)})
            return

        if state is None:
            yield _sse("error", {"detail": "Pipeline did not start."})
            return

        yield _sse(
            "requires_input",
            {
                "run_id": state.run_id,
                "phase": "plan",
                "suggested_sprint_duration_weeks": 2,
                "suggested_project_duration_weeks": 12,
                "cached": any_cached,
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_sse_headers())


@router.post("/runs/{run_id}/plan")
async def ayra_plan(
    run_id: str,
    sprint_duration_weeks: int = Form(...),
    project_duration_weeks: int = Form(...),
) -> StreamingResponse:
    """Phase 2 SSE: run sprint_planning + team_allocation, then require team review."""
    cfg = get_settings()
    if run_sessions.get(run_id, settings=cfg) is None:
        raise HTTPException(status_code=404, detail=f"Unknown run_id '{run_id}'.")
    if sprint_duration_weeks <= 0 or project_duration_weeks <= 0:
        raise HTTPException(status_code=400, detail="Durations must be positive integers.")
    total = len(DEFAULT_WORKFLOW)

    def event_stream() -> Iterator[str]:
        service = SDLCPipelineService(cfg)
        state: PipelineState | None = None
        try:
            for agent_id, updated, cached in service.stream_mid(
                run_id,
                sprint_duration_weeks=sprint_duration_weeks,
                project_duration_weeks=project_duration_weeks,
            ):
                state = updated
                yield _progress_event(agent_id, updated, cached=cached, total=total)
        except Exception as exc:  # noqa: BLE001
            log.exception("Ayra mid stream failed")
            yield _sse("error", {"detail": str(exc)})
            return

        if state is None:
            yield _sse("error", {"detail": "Plan phase did not start."})
            return

        yield _sse(
            "requires_team_review",
            {
                "run_id": state.run_id,
                "assignments": _extract_assignments(state),
                "tasks": _extract_tasks(state),
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_sse_headers())


@router.post("/runs/{run_id}/finalize")
async def ayra_finalize(
    run_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> StreamingResponse:
    """Phase 3 SSE: apply edited assignments, run tail agents, emit ``done``."""
    cfg = get_settings()
    if run_sessions.get(run_id, settings=cfg) is None:
        raise HTTPException(status_code=404, detail=f"Unknown run_id '{run_id}'.")

    assignments_in = payload.get("assignments") if isinstance(payload, dict) else None
    assignments: list[dict[str, Any]] | None = None
    if isinstance(assignments_in, list):
        assignments = [item for item in assignments_in if isinstance(item, dict)]
    total = len(DEFAULT_WORKFLOW)

    def event_stream() -> Iterator[str]:
        service = SDLCPipelineService(cfg)
        state: PipelineState | None = None
        try:
            for agent_id, updated, cached in service.stream_tail(run_id, assignments=assignments):
                state = updated
                yield _progress_event(agent_id, updated, cached=cached, total=total)
        except Exception as exc:  # noqa: BLE001
            log.exception("Ayra tail stream failed")
            yield _sse("error", {"detail": str(exc)})
            return

        if state is None:
            yield _sse("error", {"detail": "Finalize phase did not start."})
            return

        yield _sse("done", _done_payload(state))

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_sse_headers())
