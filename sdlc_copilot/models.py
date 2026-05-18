import operator
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, TypedDict
from uuid import uuid4

from pydantic import BaseModel, Field


class ArtifactType(StrEnum):
    REQUIREMENTS = "requirements"
    RISKS = "risks"
    STORIES = "stories"
    TASKS = "tasks"
    ACCEPTANCE_CRITERIA = "acceptance_criteria"
    TEST_CASES = "test_cases"
    API_SPEC = "api_spec"
    DATABASE_SCHEMA = "database_schema"
    SECURITY_REVIEW = "security_review"
    ARCHITECTURE = "architecture"
    ESTIMATION = "estimation"
    TRACEABILITY = "traceability"
    SPRINT_PLAN = "sprint_plan"
    TEAM_ALLOCATION = "team_allocation"
    DEVOPS = "devops"
    COMPLIANCE = "compliance"
    EXPORT = "export"


class SourceDocument(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    filename: str
    content_type: str | None = None
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    document_id: str
    text: str
    index: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentOutput(BaseModel):
    agent_id: str
    title: str
    artifact_type: ArtifactType | str
    content: dict[str, Any]
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.75, ge=0, le=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PipelineRequest(BaseModel):
    project_name: str = "Untitled SDLC Project"
    raw_text: str | None = None
    selected_agents: list[str] | None = None
    team: list[dict[str, Any]] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)


class PipelineState(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    project_name: str
    documents: list[SourceDocument] = Field(default_factory=list)
    chunks: list[Chunk] = Field(default_factory=list)
    context: str = ""
    outputs: dict[str, AgentOutput] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)
    team: list[dict[str, Any]] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)


class PipelineResponse(BaseModel):
    run_id: str
    project_name: str
    outputs: dict[str, AgentOutput]
    errors: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# LangGraph-compatible state (TypedDict with reducer annotations)
# ---------------------------------------------------------------------------

class LangGraphState(TypedDict):
    """State type for the LangGraph StateGraph.

    Dict fields use ``operator.or_`` so each node can return partial updates
    without overwriting sibling outputs from other nodes.
    ``low_confidence_agents`` uses ``operator.add`` (list append semantics).
    """

    run_id: str
    project_name: str
    context: str
    team: list[dict[str, Any]]
    constraints: dict[str, Any]
    outputs: Annotated[dict[str, AgentOutput], operator.or_]
    errors: Annotated[dict[str, str], operator.or_]
    low_confidence_agents: Annotated[list[str], operator.add]


def pipeline_state_to_lg(state: PipelineState) -> LangGraphState:
    """Convert a ``PipelineState`` Pydantic model into a ``LangGraphState`` dict."""
    return LangGraphState(
        run_id=state.run_id,
        project_name=state.project_name,
        context=state.context,
        team=list(state.team),
        constraints=dict(state.constraints),
        outputs=dict(state.outputs),
        errors=dict(state.errors),
        low_confidence_agents=[],
    )


def lg_state_to_pipeline(lg: LangGraphState, original: PipelineState) -> PipelineState:
    """Merge LangGraph results back into the original ``PipelineState`` in-place.

    ``lg`` may be a *partial* event dict (stream mode) that only carries the
    keys written by the current node, so we use ``.get()`` for safety.
    """
    original.outputs.update(lg.get("outputs", {}))  # type: ignore[arg-type]
    original.errors.update(lg.get("errors", {}))  # type: ignore[arg-type]
    return original
