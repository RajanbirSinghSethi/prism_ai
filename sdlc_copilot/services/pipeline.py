import logging
from collections.abc import Iterable

import orjson

from sdlc_copilot.agents.agent_logger import AgentLogger
from sdlc_copilot.agents.validators import format_findings, validate_cross_agent_ids
from sdlc_copilot.config import Settings, get_settings
from sdlc_copilot.ingestion.preprocess import chunk_documents, clean_text
from sdlc_copilot.llm.providers import build_chat_model
from sdlc_copilot.models import PipelineRequest, PipelineResponse, PipelineState, SourceDocument
from sdlc_copilot.orchestrator.workflow import SDLCOrchestrator
from sdlc_copilot.storage.vectorstore import index_chunks

log = logging.getLogger(__name__)


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

    def _index_context(self, state: PipelineState) -> None:
        log.info("Embedding index: %s chunks -> Chroma collection %s", len(state.chunks), state.run_id)
        try:
            index_chunks(self.settings, state.chunks, collection_name=state.run_id)
            log.info("Embedding index OK")
        except Exception as exc:  # noqa: BLE001 - embeddings are valuable, but should not block MVP runs.
            state.errors["embedding_index"] = str(exc)
            log.warning("Embedding index failed: %s", exc)
