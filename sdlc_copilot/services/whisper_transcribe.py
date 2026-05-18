from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile

log = logging.getLogger(__name__)


def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


@lru_cache(maxsize=4)
def _load_model(model_size: str, device: str = "cpu"):
    from faster_whisper import WhisperModel

    compute_type = "int8" if device == "cpu" else "float16"
    log.info("Loading Whisper model %s on %s", model_size, device)
    return WhisperModel(model_size, device=device, compute_type=compute_type)


def transcribe_bytes(audio: bytes, filename: str, *, model_size: str = "base") -> str:
    """Transcribe audio using open-source faster-whisper (local, no API key)."""
    if not whisper_available():
        raise RuntimeError(
            "Whisper is not installed. Run: pip install -e \".[whisper]\" "
            "(downloads the model on first use)."
        )
    if not audio:
        raise ValueError("Empty audio recording.")

    suffix = Path(filename or "speech.webm").suffix or ".webm"
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(audio)
        tmp_path = Path(tmp.name)

    try:
        model = _load_model(model_size)
        segments, _info = model.transcribe(str(tmp_path), vad_filter=True)
        text = " ".join(segment.text.strip() for segment in segments).strip()
    finally:
        tmp_path.unlink(missing_ok=True)

    if not text:
        raise ValueError("No speech detected in the recording.")
    return text
