"""Per-agent JSON debug logger.

Writes one JSON file per agent per run to ``{log_dir}/{run_id}/{NN}_{agent_id}.json``
so post-run debugging is just opening a file. Order prefix (NN) preserves
execution sequence when the directory is listed alphabetically.

The logger is intentionally dependency-free (stdlib + Pydantic AgentOutput)
so it can be invoked from any agent context including failure paths.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sdlc_copilot.models import AgentOutput

log = logging.getLogger(__name__)

_RAW_RESPONSE_LIMIT = 4000


class AgentLogger:
    """Write one JSON debug log per agent execution.

    Args:
        run_id: Pipeline run identifier; logs are grouped under this directory.
        log_dir: Root directory; final path is ``log_dir / run_id``.
        enabled: When False every method is a no-op (useful for tests).
        model: Model identifier (e.g. ``llama-3.1-8b-instant``); recorded for context.
        provider: LLM provider name (e.g. ``groq``, ``openrouter``).
    """

    def __init__(
        self,
        run_id: str,
        log_dir: Path,
        *,
        enabled: bool = True,
        model: str | None = None,
        provider: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.enabled = enabled
        self.model = model
        self.provider = provider
        self.run_dir = Path(log_dir) / run_id
        if self.enabled:
            try:
                self.run_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                log.warning("AgentLogger: could not create log dir %s: %s", self.run_dir, exc)
                self.enabled = False

    def record(
        self,
        *,
        agent_id: str,
        order: int,
        system_prompt: str,
        user_payload: dict[str, Any],
        raw_response: str,
        parsed_ok: bool,
        attempts: int,
        retry_reasons: list[str],
        duration_ms: int,
        output: AgentOutput | None,
        error: str | None,
    ) -> None:
        if not self.enabled:
            return

        now = datetime.now(UTC).isoformat()
        started_ms = duration_ms
        record: dict[str, Any] = {
            "agent_id": agent_id,
            "run_id": self.run_id,
            "order": order,
            "ended_at": now,
            "duration_ms": started_ms,
            "attempts": attempts,
            "retry_reasons": retry_reasons,
            "model": self.model,
            "provider": self.provider,
            "prompt": {
                "system": system_prompt,
                "user_payload_keys": sorted(user_payload.keys()),
                "user_payload_size_chars": len(json.dumps(user_payload, ensure_ascii=False)),
            },
            "raw_response": (raw_response or "")[:_RAW_RESPONSE_LIMIT],
            "raw_response_truncated": len(raw_response or "") > _RAW_RESPONSE_LIMIT,
            "parsed_ok": parsed_ok,
            "output": _summarise_output(output),
            "error": error,
        }

        filename = f"{order:02d}_{agent_id}.json"
        target = self.run_dir / filename
        try:
            target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning("AgentLogger: failed to write %s: %s", target, exc)


def _summarise_output(output: AgentOutput | None) -> dict[str, Any] | None:
    if output is None:
        return None
    content = output.content if isinstance(output.content, dict) else {}
    return {
        "confidence": output.confidence,
        "risks_count": len(output.risks),
        "assumptions_count": len(output.assumptions),
        "content_keys": sorted(content.keys()),
    }
