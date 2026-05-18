import json
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, ORJSONResponse, Response
from fastapi.staticfiles import StaticFiles

import orjson

from sdlc_copilot import __version__
from sdlc_copilot.agents.registry import list_agents
from sdlc_copilot.api.ayra_routes import router as ayra_router
from sdlc_copilot.config import get_settings
from sdlc_copilot.ingestion.loaders import load_upload
from sdlc_copilot.integrations.exporters import export_csv, export_pdf
from sdlc_copilot.logging_config import configure_logging
from sdlc_copilot.models import PipelineRequest, PipelineResponse
from sdlc_copilot.services.pipeline import SDLCPipelineService

log = logging.getLogger(__name__)

PRISM_UI_DIR = Path(__file__).resolve().parent.parent / "prism_ui"

# Defer settings init so import errors surface as a proper HTTP 500 with a log message
# rather than crashing the entire Vercel function at cold-start.
try:
    settings = get_settings()
except Exception as _settings_exc:  # noqa: BLE001
    logging.basicConfig(level="ERROR")
    logging.error("Failed to load settings: %s", _settings_exc)
    settings = None  # type: ignore[assignment]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings is not None:
        configure_logging(settings.sdlc_log_level)
        log.info("%s v%s starting (LLM_PROVIDER=%s)", settings.app_name, __version__, settings.llm_provider)
    yield
    if settings is not None:
        log.info("%s shutdown", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

app.include_router(ayra_router)


@app.get("/", include_in_schema=False)
def ayra_home() -> FileResponse:
    """PRISM web UI (Gemini-style dark chat)."""
    return FileResponse(PRISM_UI_DIR / "index.html")


if PRISM_UI_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=PRISM_UI_DIR), name="ayra_assets")


@app.get("/api/info")
def api_info() -> dict[str, object]:
    return {
        "service": settings.app_name,
        "version": __version__,
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": "/health",
        "agents": "/agents",
        "ayra": "/api/ayra/config",
        "runs": {"post_text": "/runs", "post_upload": "/runs/upload"},
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/agents")
def agents() -> list[dict[str, object]]:
    return list_agents()


@app.post("/runs", response_model=PipelineResponse)
def run_from_text(request: PipelineRequest) -> PipelineResponse:
    try:
        log.info(
            "POST /runs project=%r agents=%s raw_chars=%s",
            request.project_name,
            request.selected_agents or "default",
            len(request.raw_text or ""),
        )
        return SDLCPipelineService(settings).run(request)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/runs/upload", response_model=PipelineResponse)
async def run_from_uploads(
    project_name: str = Form("Untitled SDLC Project"),
    selected_agents: str | None = Form(None),
    team: str = Form("[]"),
    constraints: str = Form("{}"),
    files: list[UploadFile] = File(...),
) -> PipelineResponse:
    try:
        log.info("POST /runs/upload project=%r files=%s", project_name, len(files))
        request = PipelineRequest(
            project_name=project_name,
            selected_agents=json.loads(selected_agents) if selected_agents else None,
            team=json.loads(team),
            constraints=json.loads(constraints),
        )
        documents = [await load_upload(file) for file in files]
        return SDLCPipelineService(settings).run(request, documents)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/runs/{run_id}", response_model=PipelineResponse)
def get_run(run_id: str) -> PipelineResponse:
    artifact_path = settings.artifact_dir / f"{run_id}.json"
    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    data = orjson.loads(artifact_path.read_bytes())
    return PipelineResponse(**data)


@app.get("/runs/{run_id}/export")
def export_run(
    run_id: str,
    format: Literal["json", "csv", "pdf"] = "json",
) -> Response:
    artifact_path = settings.artifact_dir / f"{run_id}.json"
    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    data = orjson.loads(artifact_path.read_bytes())
    response_obj = PipelineResponse(**data)

    if format == "json":
        return Response(
            content=artifact_path.read_bytes(),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{run_id}.json"'},
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / f"{run_id}.{format}"
        if format == "csv":
            export_csv(response_obj, tmp_path)
            media_type = "text/csv"
        else:
            export_pdf(response_obj, tmp_path)
            media_type = "application/pdf"
        content = tmp_path.read_bytes()

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{run_id}.{format}"'},
    )
