from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import orjson

from sdlc_copilot.config import Settings
from sdlc_copilot.models import AgentOutput, SourceDocument

log = logging.getLogger(__name__)

# Raw-text-only requests use this synthetic filename and are NOT cached.
_RAW_INPUT_FILENAME = "raw-input.txt"


def cache_key_for(documents: Iterable[SourceDocument] | None) -> str | None:
    """Derive a stable cache key from uploaded document filenames.

    Returns ``None`` for raw-text-only requests (no real files). When multiple
    files are uploaded, names are lowercased, sorted, and joined with ``|``.
    """
    if not documents:
        return None
    names = sorted(
        doc.filename.strip().lower()
        for doc in documents
        if doc.filename and doc.filename.strip().lower() != _RAW_INPUT_FILENAME
    )
    if not names:
        return None
    return "|".join(names)


def _safe_path(settings: Settings, key: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._|-]+", "_", key)
    return settings.cache_dir / f"{safe}.json"


def load(settings: Settings, key: str) -> dict[str, AgentOutput]:
    """Return cached ``AgentOutput`` objects keyed by agent_id, or an empty dict."""
    path = _safe_path(settings, key)
    if not path.exists():
        return {}
    try:
        raw = orjson.loads(path.read_bytes())
    except Exception as exc:  # noqa: BLE001 - corrupt cache must not crash the pipeline
        log.warning("Cache read failed for %s: %s", key, exc)
        return {}
    outputs_raw = raw.get("outputs", {}) if isinstance(raw, dict) else {}
    outputs: dict[str, AgentOutput] = {}
    for agent_id, payload in outputs_raw.items():
        try:
            outputs[agent_id] = AgentOutput.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("Cache entry skipped (%s/%s): %s", key, agent_id, exc)
    return outputs


def save_output(
    settings: Settings,
    key: str,
    agent_id: str,
    output: AgentOutput,
    source_filenames: list[str] | None = None,
) -> None:
    """Persist a single agent output into the cache file for ``key``."""
    path = _safe_path(settings, key)
    path.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any]
    if path.exists():
        try:
            data = orjson.loads(path.read_bytes())
            if not isinstance(data, dict):
                data = {}
        except Exception:  # noqa: BLE001
            data = {}
    else:
        data = {}

    data.setdefault("cache_key", key)
    if source_filenames is not None:
        data["source_filenames"] = list(source_filenames)
    data["cached_at"] = datetime.now(UTC).isoformat()
    outputs = data.setdefault("outputs", {})
    if not isinstance(outputs, dict):
        outputs = {}
        data["outputs"] = outputs
    outputs[agent_id] = output.model_dump(mode="json")

    path.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))


def clear(settings: Settings, key: str) -> bool:
    """Delete the cache file for ``key``. Returns True if a file was removed."""
    path = _safe_path(settings, key)
    if path.exists():
        try:
            path.unlink()
            return True
        except OSError as exc:
            log.warning("Cache clear failed for %s: %s", key, exc)
    return False


def cache_path(settings: Settings, key: str) -> Path:
    """Public helper for tests/debugging — returns the on-disk path for ``key``."""
    return _safe_path(settings, key)
