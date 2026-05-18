# AI SDLC Copilot

Multi-agent AI pipeline that converts requirement documents into a full SDLC artifact suite: Jira-ready tasks, user stories, acceptance criteria, test cases, API specs, database schemas, architecture diagrams, security reviews, sprint plans, compliance checks, and more — driven by 27 specialised LLM agents.

## Features

- **27 agents** covering the full SDLC artifact pipeline defined in the blueprint PDF
- **LangGraph conditional routing** — low-confidence outputs automatically route to `feedback_refinement` before continuing; toggle with `USE_LANGGRAPH=true`
- **Automated feedback refinement** — no human-in-the-loop blocking; the agent summarises weak outputs and adds clarifying assumptions
- **Export** — JSON, CSV, and PDF (`GET /runs/{run_id}/export?format=pdf`)
- **Streamlit UI** — `streamlit run streamlit_app/app.py` for a guided demo
- **REST API + CLI** — FastAPI at `/docs`, Typer CLI via `sdlc-copilot`
- **70 unit/integration tests** — all run without real API keys

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,ui]"
cp .env.example .env   # fill in at least OPENROUTER_API_KEY and GOOGLE_API_KEY
```

**Minimum `.env`:**
```env
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct:free
GOOGLE_API_KEY=...          # Gemini embeddings
```

**Optional flags:**
```env
USE_LANGGRAPH=true          # enable conditional feedback routing
CONFIDENCE_THRESHOLD=0.6    # route to feedback_refinement below this score
```

## Usage

### API
```bash
uvicorn sdlc_copilot.main:app --reload
# http://localhost:8000/docs
```

```bash
# Run a pipeline
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"project_name":"Payments","raw_text":"Users can log in with email and password."}'

# Retrieve a run
curl http://localhost:8000/runs/{run_id}

# Export as PDF / CSV / JSON
curl "http://localhost:8000/runs/{run_id}/export?format=pdf" -o out.pdf
curl "http://localhost:8000/runs/{run_id}/export?format=csv" -o out.csv
```

### CLI
```bash
sdlc-copilot agents                                      # list all 27 agents
sdlc-copilot run requirements.pdf --project-name "MVP"
sdlc-copilot interactive                                 # guided; end text with .END
sdlc-copilot -v interactive                              # DEBUG logs
```

### Streamlit UI
```bash
streamlit run streamlit_app/app.py
# Input → Progress (live streaming) → Results (tabbed by artifact) → Export
```

### Tests
```bash
pytest          # 70 tests, no real API calls needed
ruff check .
mypy sdlc_copilot
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | `{"status": "ok"}` |
| `GET` | `/agents` | List all 27 agent specs |
| `POST` | `/runs` | Run pipeline from raw text |
| `POST` | `/runs/upload` | Run pipeline from uploaded files |
| `GET` | `/runs/{run_id}` | Retrieve a persisted run |
| `GET` | `/runs/{run_id}/export` | Download as `json`, `csv`, or `pdf` |

## Architecture

```
sdlc_copilot/
  main.py            FastAPI app + all endpoints
  config.py          Settings (pydantic-settings); USE_LANGGRAPH + CONFIDENCE_THRESHOLD
  models.py          PipelineRequest/State/Response, AgentOutput, LangGraphState
  agents/
    specs.py         27 AgentSpec definitions
    registry.py      DEFAULT_WORKFLOW (22 agents)
    executor.py      SDLCSpecAgent — LLM call, JSON parse, tenacity retry
  orchestrator/
    workflow.py      SDLCOrchestrator (sequential) + LangGraphOrchestrator (conditional)
  services/
    pipeline.py      SDLCPipelineService.run() and .stream()
  ingestion/
    loaders.py       PDF / DOCX / HTML / CSV / JSON / TXT / MD → SourceDocument
    preprocess.py    clean_text(), chunk_documents()
  integrations/
    exporters.py     export_json / export_csv / export_pdf
  llm/providers.py   build_chat_model() — OpenRouter or Groq
  storage/           ChromaDB index per run_id
streamlit_app/       pages: 1_Input, 2_Progress, 3_Results, 4_Export
tests/               70 tests across executor, orchestrator, pipeline, ingestion, API, exporters
```

## LangGraph Routing

When `USE_LANGGRAPH=true`, the pipeline uses a `StateGraph` instead of a sequential loop:

```
START → [22 agents in order] → hallucination_validation
  → router: confidence < threshold?
      yes → feedback_refinement → traceability → [tail agents] → END
      no  → traceability → [tail agents] → END
```

`LangGraphState` uses `Annotated[dict, operator.or_]` reducers so each node only needs to return its own outputs — partial updates merge automatically.

## Agent IDs

Use with `selected_agents` in `POST /runs` or `sdlc-copilot run --agents`:

`requirement_extraction` · `requirement_classification` · `ambiguity_detection` · `missing_requirement` · `conflict_detection` · `user_story_generation` · `task_decomposition` · `acceptance_criteria` · `test_case_generation` · `api_specification` · `database_schema` · `security_review` · `scalability_architecture` · `effort_estimation` · `dependency_mapping` · `hallucination_validation` · `traceability` · `sprint_planning` · `team_allocation` · `devops_recommendation` · `compliance` · `export_integration`

## Potential Next Steps

- OCR fallback for scanned PDFs (Tesseract / cloud OCR)
- Per-agent Chroma retrieval instead of first-pass bulk context
- Auth, multi-tenancy, project persistence
- Live Jira bulk task creation from `task_decomposition` output
- Human-in-the-loop feedback mode (currently automated only)
