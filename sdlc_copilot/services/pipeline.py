import logging
from collections.abc import Iterable
from typing import Any

import orjson

from sdlc_copilot.agents.agent_logger import AgentLogger
from sdlc_copilot.agents.executor import SDLCSpecAgent
from sdlc_copilot.agents.registry import DEFAULT_WORKFLOW, get_specs
from sdlc_copilot.agents.validators import format_findings, validate_cross_agent_ids
from sdlc_copilot.config import Settings, get_settings
from sdlc_copilot.ingestion.preprocess import chunk_documents, clean_text
from sdlc_copilot.llm.providers import build_chat_model
from sdlc_copilot.models import PipelineRequest, PipelineResponse, PipelineState, SourceDocument
from sdlc_copilot.orchestrator.workflow import SDLCOrchestrator
from sdlc_copilot.services import agent_cache, run_sessions
from sdlc_copilot.storage.vectorstore import index_chunks

log = logging.getLogger(__name__)

# Phase split for the human-in-the-loop flow. Head agents end with traceability;
# sprint_planning + team_allocation are gated by user input; the tail wraps up.
HEAD_AGENTS: list[str] = DEFAULT_WORKFLOW[: DEFAULT_WORKFLOW.index("sprint_planning")]
MID_AGENTS: list[str] = ["sprint_planning", "team_allocation"]
TAIL_AGENTS: list[str] = DEFAULT_WORKFLOW[DEFAULT_WORKFLOW.index("team_allocation") + 1 :]


class SDLCPipelineService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------
    # Public: blocking run
    # ------------------------------------------------------------------

    def run(
        self,
        request: PipelineRequest,
        documents: list[SourceDocument] | None = None,
    ) -> PipelineResponse:
        state = self._prepare_state(request, documents)
        llm = build_chat_model(self.settings)
        logger = self._build_agent_logger(state.run_id)
        orchestrator = self._build_orchestrator(llm, request.selected_agents, logger)
        completed = orchestrator.run(state)
        self._run_cross_agent_validation(completed)
        self._persist(completed)
        log.info(
            "Pipeline done run_id=%s outputs=%s errors=%s",
            completed.run_id,
            list(completed.outputs.keys()),
            list(completed.errors.keys()),
        )
        return PipelineResponse(
            run_id=completed.run_id,
            project_name=completed.project_name,
            outputs=completed.outputs,
            errors=completed.errors,
        )

    # ------------------------------------------------------------------
    # Public: streaming run (yields agent_id, state after each agent)
    # ------------------------------------------------------------------

    def stream(
        self,
        request: PipelineRequest,
        documents: list[SourceDocument] | None = None,
    ) -> Iterable[tuple[str, PipelineState]]:
        """Same setup as ``run()`` but yields ``(agent_id, state)`` after each agent.

        The caller must consume the entire iterator; ``_persist()`` is called
        after the last item is yielded (via a finally block).
        """
        state = self._prepare_state(request, documents)
        llm = build_chat_model(self.settings)
        logger = self._build_agent_logger(state.run_id)
        orchestrator = self._build_orchestrator(llm, request.selected_agents, logger)

        try:
            if self.settings.use_langgraph:
                # LangGraphOrchestrator.stream() yields (node_name, state)
                yield from orchestrator.stream(state)
            else:
                # SDLCOrchestrator.stream() yields state — adapt to (agent_id, state)
                for updated_state in orchestrator.stream(state):
                    last_agent = list(updated_state.outputs.keys())[-1] if updated_state.outputs else ""
                    yield last_agent, updated_state
        finally:
            self._run_cross_agent_validation(state)
            self._persist(state)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prepare_state(
        self,
        request: PipelineRequest,
        documents: list[SourceDocument] | None,
    ) -> PipelineState:
        docs = list(documents or [])
        if request.raw_text:
            docs.append(SourceDocument(filename="raw-input.txt", content_type="text/plain", text=request.raw_text))
        if not docs:
            raise ValueError("Provide raw_text or at least one document.")

        log.info("Pipeline start run project=%r documents=%s", request.project_name, len(docs))
        chunks = chunk_documents(docs)
        log.info("Chunked into %s chunks (context preview max 20 chunks)", len(chunks))
        context = self._build_context(chunks)
        state = PipelineState(
            project_name=request.project_name,
            documents=docs,
            chunks=chunks,
            context=context,
            team=request.team,
            constraints=request.constraints,
        )
        self._index_context(state)
        log.info(
            "LLM provider=%s agents=%s",
            self.settings.llm_provider,
            request.selected_agents or "(default workflow)",
        )
        return state

    def _build_orchestrator(
        self,
        llm,
        selected_agents: list[str] | None,
        logger: AgentLogger | None = None,
    ):
        if self.settings.use_langgraph:
            from sdlc_copilot.orchestrator.workflow import LangGraphOrchestrator
            log.info("Using LangGraphOrchestrator (confidence_threshold=%.2f)", self.settings.confidence_threshold)
            return LangGraphOrchestrator(
                llm,
                selected_agents,
                self.settings.confidence_threshold,
                logger=logger,
            )
        return SDLCOrchestrator(llm, selected_agents, logger=logger)

    def _build_agent_logger(self, run_id: str) -> AgentLogger | None:
        if not self.settings.agent_logs_enabled:
            return None
        model = (
            self.settings.openrouter_model
            if self.settings.llm_provider == "openrouter"
            else self.settings.groq_model
        )
        logger = AgentLogger(
            run_id=run_id,
            log_dir=self.settings.log_dir,
            enabled=True,
            model=model,
            provider=self.settings.llm_provider,
        )
        log.info("Per-agent debug logs: %s", logger.run_dir)
        return logger

    def _run_cross_agent_validation(self, state: PipelineState) -> None:
        try:
            findings = validate_cross_agent_ids(state.outputs)
        except Exception as exc:  # noqa: BLE001 - validation must never block the run
            log.warning("Cross-agent validation crashed: %s", exc)
            return
        if findings:
            state.errors["cross_agent_validation"] = format_findings(findings)
            total = sum(len(v) for v in findings.values())
            log.info("Cross-agent validation: %s findings across %s checks", total, len(findings))

    def _build_context(self, chunks: list) -> str:
        # Keep initial runs cheap for free-tier models; vector retrieval can be added per-agent.
        joined = "\n\n".join(chunk.text for chunk in chunks[: self.settings.max_context_chunks])
        return clean_text(joined)[: self.settings.max_context_chars]

    def _persist(self, state: PipelineState) -> None:
        path = self.settings.artifact_dir / f"{state.run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(orjson.dumps(state.model_dump(mode="json"), option=orjson.OPT_INDENT_2))

    # ------------------------------------------------------------------
    # Phased streaming (human-in-the-loop): head -> mid -> tail
    # ------------------------------------------------------------------

    def stream_head(
        self,
        request: PipelineRequest,
        documents: list[SourceDocument] | None = None,
        *,
        force_refresh: bool = False,
    ) -> Iterable[tuple[str, PipelineState, bool]]:
        """Run (or replay from cache) the head agents.

        Yields ``(agent_id, state, cached)`` after each head agent. The session
        is registered with ``run_sessions`` so subsequent phases can resume it.
        """
        state = self._prepare_state(request, documents)
        logger = self._build_agent_logger(state.run_id)
        source_docs = list(documents or [])
        source_filenames = [d.filename for d in source_docs if d.filename]
        cache_key = agent_cache.cache_key_for(source_docs)

        if force_refresh and cache_key:
            agent_cache.clear(self.settings, cache_key)
            log.info("Cache cleared for key=%s (force_refresh)", cache_key)

        cached_outputs: dict[str, Any] = {}
        if cache_key and not force_refresh:
            cached_outputs = agent_cache.load(self.settings, cache_key)
            if cached_outputs:
                missing = [a for a in HEAD_AGENTS if a not in cached_outputs]
                log.info(
                    "Cache hit key=%s replay=%s re-run=%s",
                    cache_key,
                    len(cached_outputs),
                    missing or "[]",
                )

        run_sessions.put(
            state.run_id,
            state,
            cache_key=cache_key,
            source_filenames=source_filenames,
            settings=self.settings,
        )

        llm = build_chat_model(self.settings) if any(a not in cached_outputs for a in HEAD_AGENTS) else None
        specs = {s.id: s for s in get_specs(HEAD_AGENTS)}

        for order, agent_id in enumerate(HEAD_AGENTS):
            cached = False
            if agent_id in cached_outputs:
                state.outputs[agent_id] = cached_outputs[agent_id]
                cached = True
                log.info("Agent CACHE replay: %s", agent_id)
            else:
                if llm is None:
                    llm = build_chat_model(self.settings)
                agent = SDLCSpecAgent(specs[agent_id], llm, logger=logger, order=order)
                self._run_single_agent(agent, state)
                output = state.outputs.get(agent_id)
                if output is not None and cache_key and _is_cacheable(output):
                    try:
                        agent_cache.save_output(
                            self.settings,
                            cache_key,
                            agent_id,
                            output,
                            source_filenames=source_filenames,
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning("Cache write failed for %s/%s: %s", cache_key, agent_id, exc)
                elif output is not None:
                    log.info("Skipping cache write for %s (low-quality output)", agent_id)
            yield agent_id, state, cached

    def stream_mid(
        self,
        run_id: str,
        *,
        sprint_duration_weeks: int,
        project_duration_weeks: int,
    ) -> Iterable[tuple[str, PipelineState, bool]]:
        """Run sprint_planning + team_allocation with user-supplied durations."""
        session = run_sessions.get(run_id, settings=self.settings)
        if session is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        state = session.state
        state.constraints = dict(state.constraints)
        state.constraints["sprint_duration_weeks"] = int(sprint_duration_weeks)
        state.constraints["project_duration_weeks"] = int(project_duration_weeks)

        llm = build_chat_model(self.settings)
        logger = self._build_agent_logger(state.run_id)
        specs = {s.id: s for s in get_specs(MID_AGENTS)}

        base_order = len(HEAD_AGENTS)
        for offset, agent_id in enumerate(MID_AGENTS):
            agent = SDLCSpecAgent(specs[agent_id], llm, logger=logger, order=base_order + offset)
            self._run_single_agent(agent, state)
            yield agent_id, state, False

        # Persist updated session so tail phase survives a server restart too.
        run_sessions._persist_current(run_id, self.settings)

    def stream_tail(
        self,
        run_id: str,
        *,
        assignments: list[dict[str, Any]] | None = None,
    ) -> Iterable[tuple[str, PipelineState, bool]]:
        """Apply edited team assignments, then run the tail agents and persist."""
        session = run_sessions.get(run_id, settings=self.settings)
        if session is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        state = session.state

        if assignments is not None and "team_allocation" in state.outputs:
            output = state.outputs["team_allocation"]
            content = dict(output.content) if isinstance(output.content, dict) else {}
            content["assignments"] = list(assignments)
            output.content = content

        llm = build_chat_model(self.settings)
        logger = self._build_agent_logger(state.run_id)
        specs = {s.id: s for s in get_specs(TAIL_AGENTS)}

        base_order = len(HEAD_AGENTS) + len(MID_AGENTS)
        try:
            for offset, agent_id in enumerate(TAIL_AGENTS):
                agent = SDLCSpecAgent(specs[agent_id], llm, logger=logger, order=base_order + offset)
                self._run_single_agent(agent, state)
                yield agent_id, state, False
        finally:
            self._run_cross_agent_validation(state)
            self._persist(state)
            run_sessions.discard(run_id, settings=self.settings)

    @staticmethod
    def _run_single_agent(agent: SDLCSpecAgent, state: PipelineState) -> None:
        log.info("Agent start: %s", agent.spec.id)
        try:
            state.outputs[agent.spec.id] = agent.run(state)
            log.info("Agent OK: %s", agent.spec.id)
        except Exception as exc:  # noqa: BLE001 - preserve per-agent failures
            state.errors[agent.spec.id] = str(exc)
            log.error("Agent FAILED: %s — %s", agent.spec.id, exc, exc_info=True)

    def _index_context(self, state: PipelineState) -> None:
        log.info("Embedding index: %s chunks -> Chroma collection %s", len(state.chunks), state.run_id)
        try:
            index_chunks(self.settings, state.chunks, collection_name=state.run_id)
            log.info("Embedding index OK")
        except Exception as exc:  # noqa: BLE001 - embeddings are valuable, but should not block MVP runs.
            state.errors["embedding_index"] = str(exc)
            log.warning("Embedding index failed: %s", exc)


# ---------------------------------------------------------------------------
# Cache quality gate
# ---------------------------------------------------------------------------

# Risk strings written by SDLCSpecAgent._fallback_payload — outputs carrying
# these markers are LLM/parse failures rather than real artifacts and must NOT
# be cached, so the next run will re-attempt the agent.
_FALLBACK_RISK_MARKERS = {
    "Model returned non-JSON output after retry.",
}


def _is_cacheable(output: Any) -> bool:
    """Return True if the agent output is real (not a JSON-parse fallback)."""
    risks = getattr(output, "risks", None) or []
    if any(r in _FALLBACK_RISK_MARKERS for r in risks):
        return False
    content = getattr(output, "content", None)
    if isinstance(content, dict) and set(content.keys()) == {"raw"}:
        return False
    return True
