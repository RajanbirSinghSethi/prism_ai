import json
import re
import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from sdlc_copilot.agents.agent_logger import AgentLogger
from sdlc_copilot.agents.specs import AgentSpec
from sdlc_copilot.config import get_settings
from sdlc_copilot.models import AgentOutput, ArtifactType, PipelineState

_FEEDBACK_AGENT_ID = "feedback_refinement"
_DEFAULT_CONFIDENCE_THRESHOLD = 0.6
_JSON_REPAIR_USER = (
    "Your previous reply was not valid JSON. Reply again with ONLY one JSON object, "
    "no markdown fences, no commentary. Required keys: content (object), risks (array of strings), "
    "assumptions (array of strings), confidence (number 0-1)."
)

# Per-agent context budget overrides. Override `max_context_chars` and
# `max_prior_agents` for token-heavy or context-hungry agents so we don't
# blow the model's TPM budget on the first few prompts.
#
# Tuning rationale (positions reference DEFAULT_WORKFLOW in registry.py):
# - ambiguity_detection (pos 2) / missing_requirement (pos 3): cap to 2 prior
#   agents (extraction + classification only) so responses stay under output limits.
# - dependency_mapping (pos 7): only needs stories (pos 5) + tasks (pos 6).
#   2 prior agents is sufficient and keeps the payload small.
# - acceptance_criteria (pos 8): needs stories (pos 5) + tasks (pos 6) + dep map
#   (pos 7). 3 prior agents covers exactly those three.
# - effort_estimation (pos 9): needs tasks (pos 6) + dep map (pos 7) + AC (pos 8).
#   3 prior agents is the minimal correct window.
# - test_case_generation (pos 14): must reach acceptance_criteria at pos 8 —
#   6 agents back. Window of 7 gives one extra for context.
# - traceability (pos 16): must reach user_story_generation (pos 5) and
#   task_decomposition (pos 6). 12 prior agents covers the full design+spec phase.
# - hallucination_validation (pos 15): needs api_spec, task IDs, and stories —
#   all within 12 agents back.
# - compliance (pos 20): only needs req extraction + classification + security
#   review. 4 prior agents is sufficient.
_AGENT_CONTEXT_OVERRIDES: dict[str, dict[str, int]] = {
    "ambiguity_detection":      {"max_context_chars": 2500, "max_prior_agents": 2},
    "missing_requirement":      {"max_context_chars": 2500, "max_prior_agents": 2},
    "dependency_mapping":       {"max_context_chars": 2000, "max_prior_agents": 2},
    "acceptance_criteria":      {"max_context_chars": 2000, "max_prior_agents": 3},
    "effort_estimation":        {"max_context_chars": 3000, "max_prior_agents": 3},
    "test_case_generation":     {"max_context_chars": 2000, "max_prior_agents": 7},
    "hallucination_validation": {"max_context_chars": 3000, "max_prior_agents": 12},
    "traceability":             {"max_context_chars": 2000, "max_prior_agents": 12},
    "compliance":               {"max_context_chars": 4500, "max_prior_agents": 4},
}

# Default output-shape hint keyed by ArtifactType.
_ARTIFACT_HINTS: dict[str, str] = {
    str(ArtifactType.REQUIREMENTS): (
        'content should include lists such as "functional", "non_functional", "actors", "modules".'
    ),
    str(ArtifactType.RISKS): 'content should include "findings" (list of objects with id, severity, detail).',
    str(ArtifactType.STORIES): 'content should include "stories" (list with id, as_a, i_want, so_that).',
    str(ArtifactType.TASKS): 'content should include "tasks" (list with id, title, type, component, depends_on).',
    str(ArtifactType.ACCEPTANCE_CRITERIA): 'content should include "criteria" (list with id, scenario, expected).',
    str(ArtifactType.TEST_CASES): 'content should include "test_cases" (list with id, type, steps, expected).',
    str(ArtifactType.API_SPEC): 'content should include "endpoints" (list with method, path, request, response).',
    str(ArtifactType.DATABASE_SCHEMA): 'content should include "tables" (list with name, columns, keys).',
    str(ArtifactType.SECURITY_REVIEW): 'content should include "findings" (severity, threat, mitigation).',
    str(ArtifactType.ARCHITECTURE): 'content should include "components", "data_flow", "scaling_notes".',
    str(ArtifactType.ESTIMATION): 'content should include "estimates" (item, points_or_days, rationale).',
    str(ArtifactType.TRACEABILITY): 'content should include "links" (requirement_id, artifact_ids).',
    str(ArtifactType.SPRINT_PLAN): 'content should include "sprints" (name, goal, items).',
    str(ArtifactType.TEAM_ALLOCATION): 'content should include "assignments" (task_id, role, owner).',
    str(ArtifactType.DEVOPS): 'content should include "recommendations" (area, action, priority).',
    str(ArtifactType.COMPLIANCE): 'content should include "controls" (regulation, requirement, status).',
    str(ArtifactType.EXPORT): 'content should include "deliverables" (format, destination, payload_summary).',
}

# Agent-id-specific overrides take precedence over the artifact-type hints.
# This lets two agents that share an ArtifactType (e.g. requirement_extraction
# and requirement_classification, both REQUIREMENTS) produce different shapes.
_AGENT_HINTS: dict[str, str] = {
    "requirement_extraction": (
        'content MUST include "functional" (list), "non_functional" (list), '
        '"actors" (list), "modules" (list), "open_questions" (list). '
        'Every numbered section in the source MUST produce at least one entry. '
        'Use IDs aligned with the source section: REQ-3.1, REQ-4.1.1, etc.'
    ),
    "requirement_classification": (
        'content MUST include "classified" (list of {id, description, category, priority}). '
        'category ∈ {functional, security, performance, compliance, ux, integration, data}. '
        'priority ∈ {P0, P1, P2, P3}. Do NOT repeat requirement_extraction verbatim — '
        'enrich every item with category and priority.'
    ),
    "ambiguity_detection": (
        'content MUST include "findings" (list of {id, requirement_id, description, suggestion}). '
        'id format: AMB-1, AMB-2, etc. requirement_id MUST match an existing REQ-x.y ID. '
        'Limit to at most 8 findings. Keep each description under 20 words. '
        'CRITICAL: output ONLY a single compact JSON object — no preamble, no markdown, '
        'no trailing text. Stop after the closing brace.'
    ),
    "missing_requirement": (
        'content MUST include "gaps" (list of {id, area, description, suggested_requirement}). '
        'id format: GAP-1, GAP-2, etc. Limit to at most 8 gaps. '
        'Only reference areas not covered by the existing requirements. '
        'Do NOT invent requirement IDs that were not in requirement_extraction output. '
        'CRITICAL: output ONLY a single compact JSON object — no preamble, no markdown, '
        'no trailing text. Stop after the closing brace.'
    ),
    "conflict_detection": (
        'content MUST include "conflicts" (list of {id, severity, a, b, detail}) '
        'where a and b are the two contradicting requirement IDs. '
        'Return an empty list if no real contradictions exist. '
        'Do NOT list missing requirements — that is missing_requirement\'s job.'
    ),
    "acceptance_criteria": (
        'content MUST include "criteria" (list of {id, requirement_id, scenario, expected}). '
        'id format: AC-1, AC-2, etc. requirement_id MUST match an existing REQ-x.y. '
        'Limit to at most 6 criteria. Keep scenario under 30 words. '
        'CRITICAL: output ONLY a single compact JSON object — no preamble, no markdown, '
        'no trailing text. Stop after the closing brace.'
    ),
    "api_specification": (
        'content MUST include "endpoints" (list of {method, path, request_schema, '
        'response_schema, status_codes, auth_required, idempotency_key_required}). '
        'All paths MUST start with /v1/. '
        'status_codes MUST include at least 200, 400, 401, and 429.'
    ),
    "effort_estimation": (
        'content MUST include "estimates" (list of {task_id, item, points_or_days, rationale}). '
        'task_id MUST match an ID from task_decomposition output. '
        'Provide an estimate for EVERY task in task_decomposition. '
        'Keep rationale under 15 words per item.'
    ),
    "hallucination_validation": (
        'content MUST include three lists: "fabricated_apis" (endpoints not traceable '
        'to requirements), "id_mismatches" (story/task IDs referenced but not defined '
        'in their source agent), "false_claims" (statements contradicted by the '
        'requirements text). Do NOT flag legitimate system components or technologies '
        'mentioned in the requirements (e.g. PostgreSQL, FastAPI, React, Zendesk, Power BI) as hallucinations.'
    ),
    "traceability": (
        'content MUST include "links" (list of {requirement_id, story_ids, task_ids, '
        'api_ids, test_ids}). '
        'requirement_id MUST be an exact REQ-x.y ID from requirement_extraction output. '
        'story_ids MUST be exact STY-x.y IDs from user_story_generation output. '
        'task_ids MUST be exact TASK-x.y IDs from task_decomposition output. '
        'test_ids MUST be exact TC-N IDs from test_case_generation output. '
        'Do NOT invent new ID schemes (no STORY-N, no TASK-N).'
    ),
    "dependency_mapping": (
        'content MUST include "dependencies" (list of {from_id, to_id, dependency_type, reason}) '
        'and "critical_path" (ordered list of task IDs). '
        'from_id and to_id MUST be exact TASK-x.y IDs from task_decomposition output. '
        'Do NOT use REQ IDs or invented IDs as task references.'
    ),
    "sprint_planning": (
        'content MUST include "sprints" (list of {id, name, goal, duration_weeks, items}). '
        'items entries MUST reference task IDs from task_decomposition. '
        'Honour constraints.sprint_duration_weeks for each sprint and '
        'constraints.project_duration_weeks for the total horizon. '
        'Cap each sprint at 40 story points.'
    ),
    "team_allocation": (
        'content MUST include "assignments" (list of {task_id, role, owner, '
        'estimated_hours}). task_id MUST match an ID from task_decomposition. '
        'role ∈ {Developer, QA, DevOps, PM, Designer}. Use placeholder owner names '
        'only when team input is empty.'
    ),
    "compliance": (
        'content MUST include "controls" (list of {regulation, requirement, status, '
        'evidence_from_requirements}). status ∈ {compliant, gap, n_a}. '
        'Only include regulations explicitly mentioned in the requirements text. '
        'Mark unmentioned regulations as n_a or omit them entirely.'
    ),
}


def _is_retryable_error(exc: BaseException) -> bool:
    """Skip retry for errors that will never succeed in the next 10s.

    Auth / quota-exhausted / bad-request all fail deterministically. Retrying
    them just wastes the UI's time budget. JSON-parse failures are *not* an
    exception path (the agent falls back to a structured payload internally),
    so they aren't seen here.
    """
    msg = str(exc).lower()
    non_retryable = (
        "api key",
        "unauthorized",
        "invalid_api_key",
        "model_not_found",
        "400 bad request",
        "401 ",
        "403 ",
    )
    return not any(token in msg for token in non_retryable)


class SDLCSpecAgent:
    def __init__(
        self,
        spec: AgentSpec,
        llm: BaseChatModel,
        attempts: int = 2,
        *,
        logger: AgentLogger | None = None,
        order: int = 0,
    ) -> None:
        self.spec = spec
        self.llm = llm
        self.attempts = attempts
        self.logger = logger
        self.order = order

    def run(self, state: PipelineState) -> AgentOutput:
        # Track retry/timing info even when the @retry decorator handles
        # multiple LLM round-trips. We pass a mutable bookkeeping dict to
        # _invoke so retries can append to it.
        bookkeeping: dict[str, Any] = {
            "attempts": 0,
            "retry_reasons": [],
            "started_at": time.time(),
            "last_system_prompt": "",
            "last_user_payload": {},
            "last_raw": "",
            "parsed_ok": False,
        }
        error: str | None = None
        output: AgentOutput | None = None
        try:
            output = self._invoke(state, bookkeeping)
            return output
        except Exception as exc:  # noqa: BLE001 - we want to log every failure path
            error = str(exc)
            raise
        finally:
            if self.logger is not None:
                duration_ms = int((time.time() - bookkeeping["started_at"]) * 1000)
                self.logger.record(
                    agent_id=self.spec.id,
                    order=self.order,
                    system_prompt=bookkeeping["last_system_prompt"],
                    user_payload=bookkeeping["last_user_payload"],
                    raw_response=bookkeeping["last_raw"],
                    parsed_ok=bookkeeping["parsed_ok"],
                    attempts=bookkeeping["attempts"],
                    retry_reasons=bookkeeping["retry_reasons"],
                    duration_ms=duration_ms,
                    output=output,
                    error=error,
                )

    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
        reraise=True,
        retry=retry_if_exception(_is_retryable_error),
    )
    def _invoke(
        self,
        state: PipelineState,
        bookkeeping: dict[str, Any] | None = None,
    ) -> AgentOutput:
        if bookkeeping is None:
            bookkeeping = {"attempts": 0, "retry_reasons": [], "last_system_prompt": "",
                           "last_user_payload": {}, "last_raw": "", "parsed_ok": False}
        bookkeeping["attempts"] += 1

        system_prompt = self._system_prompt()
        user_payload = self._user_payload(state)
        user_prompt = json.dumps(user_payload, ensure_ascii=False, indent=2)
        bookkeeping["last_system_prompt"] = system_prompt
        bookkeeping["last_user_payload"] = user_payload

        messages: list[SystemMessage | HumanMessage | AIMessage] = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        raw = ""
        parsed: dict[str, Any] | None = None
        try:
            for attempt in range(2):
                response = self.llm.invoke(messages)
                raw = response.content if isinstance(response.content, str) else str(response.content)
                parsed = _try_parse_json(raw)
                if parsed is not None:
                    break
                if attempt == 0:
                    messages.append(AIMessage(content=raw))
                    messages.append(HumanMessage(content=_JSON_REPAIR_USER))
        except Exception as exc:
            bookkeeping["retry_reasons"].append(type(exc).__name__ + ": " + str(exc)[:200])
            bookkeeping["last_raw"] = raw
            raise

        bookkeeping["last_raw"] = raw
        bookkeeping["parsed_ok"] = parsed is not None

        if parsed is None:
            parsed = _fallback_payload(raw)
            return _build_agent_output(self.spec, parsed, parse_ok=False)

        return _build_agent_output(self.spec, parsed, parse_ok=True)

    def _system_prompt(self) -> str:
        artifact = str(self.spec.artifact_type)
        # Agent-id-specific hint takes precedence over artifact-type hint.
        content_hint = _AGENT_HINTS.get(
            self.spec.id,
            _ARTIFACT_HINTS.get(artifact, 'content must be a JSON object with structured lists.'),
        )
        # For agents that are known to produce truncated responses (ambiguity_detection,
        # missing_requirement, acceptance_criteria), add an explicit size constraint so
        # the model stops generating before hitting the output token limit mid-JSON.
        _COMPACT_AGENTS = {"ambiguity_detection", "missing_requirement", "acceptance_criteria"}
        size_note = (
            "\n- Keep the entire JSON response under 1500 characters. "
            "Prefer fewer, shorter entries over a long exhaustive list."
            if self.spec.id in _COMPACT_AGENTS
            else ""
        )
        return f"""
You are the {self.spec.title} in an AI SDLC Copilot pipeline.
Purpose: {self.spec.purpose}
Responsibilities: {", ".join(self.spec.responsibilities)}
Edge cases to check: {", ".join(self.spec.edge_cases)}
Expected artifact type: {artifact}
Output shape: {content_hint}

Rules:
- Use only the supplied requirements context and prior agent outputs.
- If information is missing, add short entries under assumptions or risks — do not invent features.
- Be specific and implementation-ready (IDs, bullet lists, trace links).
- confidence: use 0.85–0.95 when the context clearly supports your output; use 0.55–0.75 only when important details are missing.

CRITICAL — response format:
- Return ONLY one JSON object. No markdown code fences. No text before or after the JSON.
- Required keys exactly: content, risks, assumptions, confidence
- content MUST be a JSON object (not a top-level array).
- risks and assumptions MUST be arrays of strings (can be empty []).{size_note}
- Example:
{{"content": {{"items": ["example"]}}, "risks": [], "assumptions": [], "confidence": 0.9}}
""".strip()

    def _context_limits(self) -> tuple[int, int]:
        """Return (max_context_chars, max_prior_agents) honouring per-agent overrides."""
        settings = get_settings()
        overrides = _AGENT_CONTEXT_OVERRIDES.get(self.spec.id, {})
        max_ctx = overrides.get("max_context_chars", settings.max_context_chars)
        max_prior = overrides.get("max_prior_agents", settings.max_prior_agents)
        return max_ctx, max_prior

    def _user_payload(self, state: PipelineState) -> dict[str, Any]:
        settings = get_settings()
        max_ctx, max_prior = self._context_limits()
        previous_outputs = _compact_prior_outputs(
            state.outputs,
            exclude_id=self.spec.id,
            max_agents=max_prior,
            max_content_chars=settings.max_prior_output_chars,
        )
        payload: dict[str, Any] = {
            "project_name": state.project_name,
            "requirements_context": _trim_text(state.context, max_ctx),
            "team": state.team,
            "constraints": state.constraints,
            "previous_agent_outputs": previous_outputs,
            "expected_artifact_type": str(self.spec.artifact_type),
        }
        if len(state.context) > max_ctx or len(state.outputs) > max_prior:
            payload["prompt_budget_note"] = (
                "Some requirements context and/or older agent outputs were truncated to fit model limits."
            )
        if self.spec.id == _FEEDBACK_AGENT_ID:
            payload["feedback_context"] = _build_feedback_context(state)
        return payload

    def _user_prompt(self, state: PipelineState) -> str:
        """Backward-compat wrapper used by tests and the previous public API."""
        return json.dumps(self._user_payload(state), ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Prompt budget helpers (free-tier TPM limits)
# ---------------------------------------------------------------------------

_TRUNCATION_SUFFIX = "\n\n[... truncated for model token limits ...]"


def _trim_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + _TRUNCATION_SUFFIX


def _compact_prior_outputs(
    outputs: dict[str, AgentOutput],
    *,
    exclude_id: str,
    max_agents: int,
    max_content_chars: int,
) -> dict[str, Any]:
    """Keep only the most recent prior agents and truncate large JSON content."""
    prior = [(key, output) for key, output in outputs.items() if key != exclude_id]
    if max_agents > 0 and len(prior) > max_agents:
        prior = prior[-max_agents:]

    compact: dict[str, Any] = {}
    for key, output in prior:
        dump = output.model_dump(mode="json")
        content_str = json.dumps(dump.get("content", {}), ensure_ascii=False)
        if max_content_chars > 0 and len(content_str) > max_content_chars:
            dump["content"] = {"_truncated_summary": content_str[:max_content_chars] + "..."}
            dump["_truncated"] = True
        compact[key] = dump
    return compact


# ---------------------------------------------------------------------------
# Feedback & Refinement helpers
# ---------------------------------------------------------------------------

def _build_feedback_context(
    state: PipelineState,
    threshold: float = _DEFAULT_CONFIDENCE_THRESHOLD,
) -> dict[str, Any]:
    low_confidence: dict[str, Any] = {
        agent_id: {
            "confidence": output.confidence,
            "risks": output.risks,
            "assumptions": output.assumptions,
            "content_summary": str(output.content)[:500],
        }
        for agent_id, output in state.outputs.items()
        if output.confidence < threshold
    }
    return {
        "mode": "automated",
        "instruction": (
            "Summarise each low-confidence output listed below. "
            "For each item add at least 2 clarifying assumptions that would raise confidence. "
            "Return JSON with keys: content (dict of agent_id → summary string), "
            "risks (list), assumptions (list), confidence (float 0-1)."
        ),
        "low_confidence_outputs": low_confidence,
    }


# ---------------------------------------------------------------------------
# JSON parsing helpers
# ---------------------------------------------------------------------------

def _build_agent_output(spec: AgentSpec, parsed: dict[str, Any], *, parse_ok: bool) -> AgentOutput:
    content = parsed.get("content", parsed)
    if not isinstance(content, dict):
        content = {"items": content} if isinstance(content, list) else {"value": str(content)}

    return AgentOutput(
        agent_id=spec.id,
        title=spec.title,
        artifact_type=spec.artifact_type,
        content=content,
        risks=_coerce_str_list(parsed.get("risks")),
        assumptions=_coerce_str_list(parsed.get("assumptions")),
        confidence=_coerce_confidence(parsed.get("confidence"), parse_ok=parse_ok),
    )


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else str(item) for item in value]
    return [str(value)]


def _coerce_confidence(value: Any, *, parse_ok: bool) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.75 if parse_ok else 0.55
    confidence = max(0.0, min(1.0, confidence))
    if parse_ok and confidence < 0.5 and value is None:
        return 0.75
    return confidence


def _fallback_payload(raw: str) -> dict[str, Any]:
    return {
        "content": {"raw": raw[:4000]},
        "risks": ["Model returned non-JSON output after retry."],
        "assumptions": ["Re-run this agent or use a model with stronger JSON adherence."],
        "confidence": 0.55,
    }


def _try_parse_json(text: str) -> dict[str, Any] | None:
    for candidate in _json_candidates(text):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            data = _try_parse_relaxed_json(candidate)
            if data is None:
                continue
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return {"content": {"items": data}, "risks": [], "assumptions": [], "confidence": 0.75}
    return None


def _json_candidates(text: str) -> list[str]:
    text = text.strip()
    candidates: list[str] = [text]
    fenced = _strip_markdown_fence(text)
    if fenced != text:
        candidates.insert(0, fenced)
    extracted = _extract_json_object(text)
    if extracted:
        candidates.insert(0, extracted)
    return candidates


def _strip_markdown_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for index, char in enumerate(text[start:], start=start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _try_parse_relaxed_json(text: str) -> dict[str, Any] | None:
    """Best-effort fix for trailing commas and single-quoted keys from small models."""
    relaxed = re.sub(r",\s*}", "}", text)
    relaxed = re.sub(r",\s*]", "]", relaxed)
    try:
        data = json.loads(relaxed)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
