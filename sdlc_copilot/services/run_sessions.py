from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import orjson

from sdlc_copilot.config import Settings
from sdlc_copilot.models import PipelineState

log = logging.getLogger(__name__)


@dataclass
class _Session:
    state: PipelineState
    cache_key: str | None
    source_filenames: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    extra: dict[str, Any] = field(default_factory=dict)


_LOCK = threading.Lock()
_SESSIONS: dict[str, _Session] = {}


def _sessions_dir(settings: Settings | None) -> Path | None:
    if settings is None:
        return None
    base = getattr(settings, "artifact_dir", None)
    if base is None:
        return None
    return Path(base).parent / "sessions"


def _disk_path(settings: Settings | None, run_id: str) -> Path | None:
    base = _sessions_dir(settings)
    return None if base is None else base / f"{run_id}.json"


def _serialize(session: _Session) -> bytes:
    payload = {
        "state": session.state.model_dump(mode="json"),
        "cache_key": session.cache_key,
        "source_filenames": list(session.source_filenames),
        "created_at": session.created_at,
        "extra": dict(session.extra),
    }
    return orjson.dumps(payload, option=orjson.OPT_INDENT_2)


def _deserialize(raw: bytes) -> _Session | None:
    try:
        data = orjson.loads(raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("Session deserialize failed: %s", exc)
        return None
    try:
        state = PipelineState.model_validate(data["state"])
    except Exception as exc:  # noqa: BLE001
        log.warning("Session state validate failed: %s", exc)
        return None
    return _Session(
        state=state,
        cache_key=data.get("cache_key"),
        source_filenames=list(data.get("source_filenames") or []),
        created_at=float(data.get("created_at") or time.time()),
        extra=dict(data.get("extra") or {}),
    )


def put(
    run_id: str,
    state: PipelineState,
    *,
    cache_key: str | None = None,
    source_filenames: list[str] | None = None,
    settings: Settings | None = None,
) -> None:
    session = _Session(
        state=state,
        cache_key=cache_key,
        source_filenames=list(source_filenames or []),
    )
    with _LOCK:
        _SESSIONS[run_id] = session

    path = _disk_path(settings, run_id)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_serialize(session))
    except OSError as exc:
        log.warning("Session disk write failed for %s: %s", run_id, exc)


def _persist_current(run_id: str, settings: Settings | None) -> None:
    """Re-serialize the in-memory session for ``run_id`` (mid/tail phases mutate state)."""
    if settings is None:
        return
    with _LOCK:
        session = _SESSIONS.get(run_id)
    if session is None:
        return
    path = _disk_path(settings, run_id)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_serialize(session))
    except OSError as exc:
        log.warning("Session disk re-write failed for %s: %s", run_id, exc)


def get(run_id: str, *, settings: Settings | None = None) -> _Session | None:
    with _LOCK:
        session = _SESSIONS.get(run_id)
    if session is not None:
        return session

    path = _disk_path(settings, run_id)
    if path is None or not path.exists():
        return None
    try:
        session = _deserialize(path.read_bytes())
    except OSError as exc:
        log.warning("Session disk read failed for %s: %s", run_id, exc)
        return None
    if session is None:
        return None
    with _LOCK:
        _SESSIONS[run_id] = session
    return session


def get_state(run_id: str, *, settings: Settings | None = None) -> PipelineState | None:
    session = get(run_id, settings=settings)
    return session.state if session is not None else None


def discard(run_id: str, *, settings: Settings | None = None) -> None:
    with _LOCK:
        _SESSIONS.pop(run_id, None)
    path = _disk_path(settings, run_id)
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Session disk delete failed for %s: %s", run_id, exc)


def expire_older_than(max_age_seconds: float) -> int:
    """Drop in-memory sessions older than ``max_age_seconds``. Returns count removed."""
    cutoff = time.time() - max_age_seconds
    removed = 0
    with _LOCK:
        for run_id in [rid for rid, s in _SESSIONS.items() if s.created_at < cutoff]:
            _SESSIONS.pop(run_id, None)
            removed += 1
    return removed


def _reset_for_tests() -> None:
    with _LOCK:
        _SESSIONS.clear()


# asdict is intentionally imported but currently unused outside of debug helpers.
__all__ = [
    "get",
    "get_state",
    "put",
    "discard",
    "expire_older_than",
    "asdict",
]
