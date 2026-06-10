from langchain_core.language_models.chat_models import BaseChatModel

from sdlc_copilot.agents.agent_logger import AgentLogger
from sdlc_copilot.agents.executor import SDLCSpecAgent
from sdlc_copilot.agents.specs import AGENTS_BY_ID, AGENT_SPECS, AgentSpec


# Workflow ordering rationale:
#
# ANALYSIS PHASE (pos 0-4): Requirements fully validated before any design work.
#
# DESIGN PHASE (pos 5-9): Stories → tasks → dependency graph → acceptance criteria
#   → effort estimation. This order ensures:
#   - dependency_mapping runs before effort_estimation so sprint plans can honour
#     blockers and the estimation has full dependency context.
#   - acceptance_criteria runs before technical spec agents so API/DB design
#     accounts for pass/fail conditions, not just story intent.
#   - effort_estimation sees both the dependency graph and the acceptance criteria
#     before committing to story-point estimates.
#
# TECHNICAL SPEC PHASE (pos 10-14): API, DB, security, architecture, test cases.
#   test_case_generation is last here so it can reference acceptance_criteria
#   (pos 8) within its context window.
#
# VALIDATION GATE (pos 15-16): hallucination check then RTM traceability.
#   Both need a wide prior-agents window (see _AGENT_CONTEXT_OVERRIDES).
#
# HITL GATE 1 (pos 17-18): sprint_planning + team_allocation — gated by user
#   input on duration and assignments.
#
# GOVERNANCE + DELIVERY (pos 19-21): DevOps, compliance, export/Jira.
DEFAULT_WORKFLOW = [
    # --- ANALYSIS ---
    "requirement_extraction",       # 0
    "requirement_classification",   # 1
    "ambiguity_detection",          # 2
    "missing_requirement",          # 3
    "conflict_detection",           # 4
    # --- DESIGN ---
    "user_story_generation",        # 5
    "task_decomposition",           # 6
    "dependency_mapping",           # 7  moved up: sprint_planning needs blockers/critical-path
    "acceptance_criteria",          # 8  moved up: API/DB design should know AC conditions
    "effort_estimation",            # 9  now has dep map + AC context
    # --- TECHNICAL SPEC ---
    "api_specification",            # 10
    "database_schema",              # 11
    "security_review",              # 12
    "scalability_architecture",     # 13
    "test_case_generation",         # 14 references AC at pos 8, within 7-agent window
    # --- VALIDATION GATE ---
    "hallucination_validation",     # 15
    "traceability",                 # 16 RTM — wide context window to reach stories/tasks
    # --- HITL GATE 1: sprint duration + project horizon ---
    "sprint_planning",              # 17
    "team_allocation",              # 18
    # --- HITL GATE 2: team assignments review ---
    # --- GOVERNANCE + DELIVERY ---
    "devops_recommendation",        # 19
    "compliance",                   # 20
    "export_integration",           # 21
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
