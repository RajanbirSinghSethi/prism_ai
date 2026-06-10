# CLAUDE.md

Multi-agent AI SDLC Copilot — requirement documents in, Jira-ready tasks/tests/sprint plans/API specs/architecture/compliance out, via 27 specialised LLM agents with LangGraph conditional routing and a static `prism_ui` web frontend.

## Code Style

- Python ≥ 3.11; type-annotate all public functions
- Pydantic v2 models; `model_dump(mode="json")` for serialisation
- `from __future__ import annotations` at top of every module
- Prefer `Path` over `str` for filesystem paths
- Agent IDs are `snake_case` strings matching keys in `AGENTS_BY_ID`
- Tests mock at `SDLCSpecAgent.run` (not `llm.invoke`) to bypass tenacity retries
- Settings fields use `validation_alias` — construct via `get_settings().model_copy(update={...})` in tests, never `Settings(field=value)` for aliased fields

## Commands

```bash
pip install -e ".[dev,ui]"                          # install all deps
ruff check .
mypy sdlc_copilot
uvicorn sdlc_copilot.main:app --reload              # API + UI at http://localhost:8000/ and http://localhost:8000/docs
USE_LANGGRAPH=true uvicorn sdlc_copilot.main:app --reload  # LangGraph routing
sdlc-copilot agents
sdlc-copilot run requirements.pdf --project-name "My Project"
sdlc-copilot interactive                            # end text with .END
```

**Required `.env`:** `LLM_PROVIDER`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `GOOGLE_API_KEY`
**Optional:** `USE_LANGGRAPH=true`, `CONFIDENCE_THRESHOLD=0.6`, `GROQ_*`, `JIRA_*`, `GITHUB_TOKEN`

## Architecture

```
sdlc_copilot/
  main.py          # FastAPI: GET /health /agents /runs/{id} /runs/{id}/export, POST /runs /runs/upload
  config.py        # Settings (pydantic-settings, lru_cache); use_langgraph + confidence_threshold flags
  models.py        # PipelineRequest/State/Response, AgentOutput, ArtifactType, LangGraphState
  agents/
    specs.py       # 27 AgentSpec definitions
    registry.py    # DEFAULT_WORKFLOW (22 agents), build_agents(), list_agents()
    executor.py    # SDLCSpecAgent — prompt → LLM → JSON parse → AgentOutput; tenacity retry
  orchestrator/
    workflow.py    # SDLCOrchestrator (sequential) + LangGraphOrchestrator (conditional routing)
  services/
    pipeline.py    # SDLCPipelineService.run() / .stream() + stream_head / stream_mid / stream_tail (phased HITL)
    agent_cache.py # Filename-keyed cache for head-agent outputs (.data/cache/{key}.json)
    run_sessions.py# In-memory PipelineState store keyed by run_id (across phase HTTP calls)
  ingestion/
    loaders.py     # PDF/DOCX/HTML/CSV/JSON/TXT/MD → SourceDocument
    preprocess.py  # clean_text(), chunk_documents()
  integrations/
    exporters.py   # export_json / export_csv / export_pdf (fpdf2)
  api/
    ayra_routes.py # /api/ayra/{config,message,runs/stream,runs/{id}/plan,runs/{id}/finalize}
prism_ui/          # static HTML+JS frontend (index.html, app.js, styles.css)
tests/             # 111 tests; conftest.py has mock_llm, low_confidence_llm, sample_state fixtures
```

## Key Decisions

- **LangGraph routing**: enabled by `USE_LANGGRAPH=true`. After `hallucination_validation`, if any output's `confidence < threshold`, graph detours to `feedback_refinement` before continuing. `LangGraphState` uses `Annotated[dict, operator.or_]` reducers so partial node updates merge safely.
- **feedback_refinement agent**: automated mode only — `_build_feedback_context()` injects low-confidence summaries + instruction into the user prompt; no human-in-the-loop blocking.
- **Failure isolation**: every agent error is caught and written to `state.errors[agent_id]`; the run always completes and persists.
- **Artifacts**: `{run_id}.json` under `settings.artifact_dir` (default `.data/artifacts/`). `_persist()` calls `mkdir(parents=True)` so no pre-creation needed.
- **PDF export**: fpdf2 with Helvetica 8pt and `multi_cell(pdf.epw, ...)` — never `multi_cell(0, ...)` which causes an fpdf2 width error.
- **prism_ui (static frontend)**: vanilla HTML/JS served by FastAPI; consumes SSE from `/api/ayra/runs/stream` → `/runs/{id}/plan` → `/runs/{id}/finalize` and shares a `consumeSse(response, handlers)` helper across phases.
- **Phased HITL flow**: head (17 agents, ends at `traceability`) → `requires_input` (sprint + project duration form) → mid (`sprint_planning`, `team_allocation`) → `requires_team_review` (editable assignments table) → tail (`devops_recommendation`, `compliance`, `export_integration`) → `done`. Artifact is written exactly once at the end.
- **Filename-keyed cache**: head-agent outputs are persisted to `.data/cache/{filename}.json` (lowercased; multi-file = sorted-joined with `|`). Repeat uploads of the same filename(s) replay cached outputs without LLM calls. Raw-text-only requests are not cached. UI "Force refresh" checkbox deletes the cache file before phase 1; cache is always written through on success.
