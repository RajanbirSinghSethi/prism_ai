from langchain_core.language_models.chat_models import BaseChatModel

from sdlc_copilot.agents.agent_logger import AgentLogger
from sdlc_copilot.agents.executor import SDLCSpecAgent
from sdlc_copilot.agents.specs import AGENTS_BY_ID, AGENT_SPECS, AgentSpec


# Token-heavy agents (acceptance_criteria, test_case_generation) are now
# interleaved with cheaper agents so the model's TPM budget isn't burned in a
# single burst right after task_decomposition.
DEFAULT_WORKFLOW = [
    "requirement_extraction",
    "requirement_classification",
    "ambiguity_detection",
    "missing_requirement",
    "conflict_detection",
    "user_story_generation",
    "task_decomposition",
    "api_specification",
    "database_schema",
    "security_review",
    "scalability_architecture",
    "acceptance_criteria",
    "effort_estimation",
    "test_case_generation",
    "dependency_mapping",
    "hallucination_validation",
    "traceability",
    "sprint_planning",
    "team_allocation",
    "devops_recommendation",
    "compliance",
    "export_integration",
]


def get_specs(agent_ids: list[str] | None = None) -> list[AgentSpec]:
    if not agent_ids:
        return [AGENTS_BY_ID[agent_id] for agent_id in DEFAULT_WORKFLOW]
    unknown = sorted(set(agent_ids) - set(AGENTS_BY_ID))
    if unknown:
        raise ValueError(f"Unknown agent ids: {unknown}")
    return [AGENTS_BY_ID[agent_id] for agent_id in agent_ids]


def build_agents(
    llm: BaseChatModel,
    agent_ids: list[str] | None = None,
    *,
    logger: AgentLogger | None = None,
) -> list[SDLCSpecAgent]:
    return [
        SDLCSpecAgent(spec, llm, logger=logger, order=order)
        for order, spec in enumerate(get_specs(agent_ids))
    ]


def list_agents() -> list[dict[str, object]]:
    return [
        {
            "id": spec.id,
            "title": spec.title,
            "purpose": spec.purpose,
            "responsibilities": list(spec.responsibilities),
            "edge_cases": list(spec.edge_cases),
            "artifact_type": str(spec.artifact_type),
        }
        for spec in AGENT_SPECS
    ]
