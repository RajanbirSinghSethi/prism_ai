import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# On Vercel (and similar serverless platforms) only /tmp is writable.
_TMP = Path("/tmp")
_IS_SERVERLESS = os.getenv("VERCEL") == "1" or not os.access(".", os.W_OK)


def _writable_path(preferred: Path) -> Path:
    """Return preferred path when writable, otherwise redirect to /tmp."""
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        fallback = _TMP / preferred.name
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "PRISM - AI SDLC Copilot"
    llm_provider: str = Field(default="openrouter", validation_alias="LLM_PROVIDER")
    openrouter_api_key: str | None = Field(default=None, validation_alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(
        default="meta-llama/llama-3.1-8b-instruct:free",
        validation_alias="OPENROUTER_MODEL",
    )
    groq_api_key: str | None = Field(default=None, validation_alias="GROQ_API_KEY")
    groq_model: str = Field(default="llama-3.1-8b-instant", validation_alias="GROQ_MODEL")
    google_api_key: str | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    embedding_model: str = Field(
        default="gemini-embedding-001",
        validation_alias="EMBEDDING_MODEL",
    )
    chroma_persist_dir: Path = Field(default=Path(".data/chroma"), validation_alias="CHROMA_PERSIST_DIR")
    artifact_dir: Path = Field(default=Path(".data/artifacts"), validation_alias="ARTIFACT_DIR")
    cache_dir: Path = Field(default=Path(".data/cache"), validation_alias="CACHE_DIR")
    log_dir: Path = Field(default=Path(".data/logs"), validation_alias="LOG_DIR")
    agent_logs_enabled: bool = Field(default=True, validation_alias="AGENT_LOGS_ENABLED")
    max_agent_retries: int = Field(default=2, validation_alias="MAX_AGENT_RETRIES")
    agent_timeout_seconds: int = Field(default=120, validation_alias="AGENT_TIMEOUT_SECONDS")
    use_langgraph: bool = Field(default=False, validation_alias="USE_LANGGRAPH")
    confidence_threshold: float = Field(default=0.6, validation_alias="CONFIDENCE_THRESHOLD")
    # Prompt budget — keep requests under free-tier limits (e.g. Groq ~6k TPM per request).
    max_context_chars: int = Field(default=6000, validation_alias="MAX_CONTEXT_CHARS")
    max_context_chunks: int = Field(default=8, validation_alias="MAX_CONTEXT_CHUNKS")
    max_prior_agents: int = Field(default=5, validation_alias="MAX_PRIOR_AGENTS")
    max_prior_output_chars: int = Field(default=800, validation_alias="MAX_PRIOR_OUTPUT_CHARS")
    jira_base_url: str | None = Field(default=None, validation_alias="JIRA_BASE_URL")
    jira_email: str | None = Field(default=None, validation_alias="JIRA_EMAIL")
    jira_api_token: str | None = Field(default=None, validation_alias="JIRA_API_TOKEN")
    github_token: str | None = Field(default=None, validation_alias="GITHUB_TOKEN")
    sdlc_log_level: str = Field(default="INFO", validation_alias="SDLC_LOG_LEVEL")
    whisper_model: str = Field(default="base", validation_alias="WHISPER_MODEL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    # Use writable paths — on serverless envs (Vercel) this redirects to /tmp.
    settings.chroma_persist_dir = _writable_path(settings.chroma_persist_dir)
    settings.artifact_dir = _writable_path(settings.artifact_dir)
    settings.cache_dir = _writable_path(settings.cache_dir)
    if settings.agent_logs_enabled:
        settings.log_dir = _writable_path(settings.log_dir)
    return settings
