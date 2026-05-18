from collections.abc import Iterable
import logging

from langchain_core.language_models.chat_models import BaseChatModel

from sdlc_copilot.agents.agent_logger import AgentLogger
from sdlc_copilot.agents.executor import SDLCSpecAgent
from sdlc_copilot.agents.registry import build_agents, get_specs
from sdlc_copilot.models import (
    LangGraphState,
    PipelineState,
    lg_state_to_pipeline,
    pipeline_state_to_lg,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Deterministic orchestrator (original implementation)
# ---------------------------------------------------------------------------


class SDLCOrchestrator:
    """Deterministic coordinator for the SDLC agent workflow.

    LangGraph can be layered onto this class for conditional routing. The base workflow remains
    deterministic so human review, retries, and traceability are easier to reason about.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        selected_agents: list[str] | None = None,
        *,
        logger: AgentLogger | None = None,
    ) -> None:
        self.agents = build_agents(llm, selected_agents, logger=logger)

    def run(self, state: PipelineState) -> PipelineState:
        for agent in self.agents:
            self._run_agent(agent, state)
        return state

    def stream(self, state: PipelineState) -> Iterable[PipelineState]:
        for agent in self.agents:
            self._run_agent(agent, state)
            yield state

    @staticmethod
    def _run_agent(agent: SDLCSpecAgent, state: PipelineState) -> None:
        log.info("Agent start: %s", agent.spec.id)
        try:
            state.outputs[agent.spec.id] = agent.run(state)
            log.info("Agent OK: %s", agent.spec.id)
        except Exception as exc:  # noqa: BLE001 - preserve per-agent failures without killing the run.
            state.errors[agent.spec.id] = str(exc)
            log.error("Agent FAILED: %s — %s", agent.spec.id, exc, exc_info=log.isEnabledFor(logging.DEBUG))


# ---------------------------------------------------------------------------
# LangGraph workflow (conditional routing)
# ---------------------------------------------------------------------------

# The LangGraph workflow runs the same agents as DEFAULT_WORKFLOW but routes
# through feedback_refinement when any agent produces low-confidence output.
# feedback_refinement is NOT included in this list — it is injected as a
# conditional detour node between hallucination_validation and traceability.
_LANGGRAPH_WORKFLOW = [
    "requirement_extraction",
    "requirement_classification",
    "ambiguity_detection",
    "missing_requirement",
    "conflict_detection",
    "user_story_generation",
    "task_decomposition",
    "acceptance_criteria",
    "test_case_generation",
    "api_specification",
    "database_schema",
    "security_review",
    "scalability_architecture",
    "effort_estimation",
    "dependency_mapping",
    "hallucination_validation",
    # conditional split happens here → feedback_refinement OR traceability
    "traceability",
    "sprint_planning",
    "team_allocation",
    "devops_recommendation",
    "compliance",
    "export_integration",
]

_SPLIT_AFTER = "hallucination_validation"
_TAIL_START = "traceability"


class LangGraphOrchestrator:
    """LangGraph-backed orchestrator with conditional feedback routing.

    After ``hallucination_validation``, if any agent output has
    ``confidence < confidence_threshold``, the graph detours through
    ``feedback_refinement`` before continuing to ``traceability``.

    Activated by setting ``USE_LANGGRAPH=true`` in the environment.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        selected_agents: list[str] | None = None,
        confidence_threshold: float = 0.6,
        *,
        logger: AgentLogger | None = None,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        # Build agent map — includes feedback_refinement even if not in workflow list
        workflow = list(selected_agents or _LANGGRAPH_WORKFLOW)
        specs = {s.id: s for s in get_specs(workflow)}
        # Add feedback_refinement spec separately (it's never in the main list)
        from sdlc_copilot.agents.specs import AGENTS_BY_ID
        specs["feedback_refinement"] = AGENTS_BY_ID["feedback_refinement"]
        # Order map preserves execution order in the per-agent log filenames.
        order_of = {aid: idx for idx, aid in enumerate(workflow + ["feedback_refinement"])}
        self._agents: dict[str, SDLCSpecAgent] = {
            agent_id: SDLCSpecAgent(spec, llm, logger=logger, order=order_of.get(agent_id, 0))
            for agent_id, spec in specs.items()
        }
        self._workflow = workflow
        self._graph = self._build_graph()

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_graph(self):
        from langgraph.graph import END, START, StateGraph

        builder = StateGraph(LangGraphState)

        # Add one node per agent in the main workflow sequence
        for agent_id in self._workflow:
            builder.add_node(agent_id, self._make_node(agent_id))

        # Add feedback_refinement as an optional detour node
        builder.add_node("feedback_refinement", self._make_node("feedback_refinement"))

        # Determine the split point and tail
        if _SPLIT_AFTER in self._workflow and _TAIL_START in self._workflow:
            split_idx = self._workflow.index(_SPLIT_AFTER)
            tail_idx = self._workflow.index(_TAIL_START)
            head = self._workflow[: split_idx + 1]
            tail = self._workflow[tail_idx:]
        else:
            # Fallback: treat the whole workflow as linear (no conditional routing)
            head = self._workflow
            tail = []

        # Linear edges for the head segment
        builder.add_edge(START, head[0])
        for a, b in zip(head, head[1:]):
            builder.add_edge(a, b)

        if tail:
            # Conditional edge after hallucination_validation
            builder.add_conditional_edges(
                _SPLIT_AFTER,
                self._route_after_validation,
                {
                    "feedback_refinement": "feedback_refinement",
                    _TAIL_START: _TAIL_START,
                },
            )
            # feedback_refinement always flows back to the start of the tail
            builder.add_edge("feedback_refinement", _TAIL_START)

            # Linear edges for the tail segment
            for a, b in zip(tail, tail[1:]):
                builder.add_edge(a, b)
            builder.add_edge(tail[-1], END)
        else:
            # No split point found — simple linear graph
            builder.add_edge(head[-1], END)

        return builder.compile()

    # ------------------------------------------------------------------
    # Node factory
    # ------------------------------------------------------------------

    def _make_node(self, agent_id: str):
        """Return a LangGraph node function for the given agent_id."""
        agent = self._agents[agent_id]
        threshold = self.confidence_threshold

        def node_fn(state: LangGraphState) -> dict:
            # Reconstruct a minimal PipelineState view for the agent's prompt
            ps = PipelineState(
                run_id=state["run_id"],
                project_name=state["project_name"],
                context=state["context"],
                team=state["team"],
                constraints=state["constraints"],
                outputs=dict(state["outputs"]),
                errors=dict(state["errors"]),
            )
            log.info("LangGraph node start: %s", agent_id)
            try:
                output = agent.run(ps)
                updates: dict = {"outputs": {agent_id: output}}
                if output.confidence < threshold:
                    updates["low_confidence_agents"] = [agent_id]
                    log.info("Low confidence (%s) on %s — flagging for feedback.", output.confidence, agent_id)
                log.info("LangGraph node OK: %s", agent_id)
                return updates
            except Exception as exc:  # noqa: BLE001
                log.error("LangGraph node FAILED: %s — %s", agent_id, exc)
                return {"errors": {agent_id: str(exc)}}

        node_fn.__name__ = agent_id  # LangGraph uses __name__ for display/debugging
        return node_fn

    # ------------------------------------------------------------------
    # Conditional router
    # ------------------------------------------------------------------

    def _route_after_validation(self, state: LangGraphState) -> str:
        """Route to feedback_refinement if any low-confidence agents were detected."""
        low = state.get("low_confidence_agents", [])
        if low:
            log.info("Routing to feedback_refinement. Low-confidence agents: %s", low)
            return "feedback_refinement"
        return _TAIL_START

    # ------------------------------------------------------------------
    # Public interface (mirrors SDLCOrchestrator)
    # ------------------------------------------------------------------

    def run(self, state: PipelineState) -> PipelineState:
        lg_state = pipeline_state_to_lg(state)
        final_lg: LangGraphState = self._graph.invoke(lg_state)
        return lg_state_to_pipeline(final_lg, state)

    def stream(self, state: PipelineState) -> Iterable[tuple[str, PipelineState]]:
        """Yield ``(node_name, PipelineState)`` after each node completes."""
        lg_state = pipeline_state_to_lg(state)
        for event in self._graph.stream(lg_state):
            node_name = next(iter(event))
            lg_state_to_pipeline(event[node_name], state)
            yield node_name, state
