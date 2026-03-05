"""
AxiomBrain — Configuration
All settings are loaded from environment variables (or a .env file via python-dotenv).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always resolve .env relative to this file's location (project root)
# This ensures .env is found regardless of the working directory the
# process was launched from (e.g. Cursor MCP not passing cwd).
_PROJECT_ROOT = Path(__file__).parent.parent
_ENV_FILE = str(_PROJECT_ROOT / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = "postgresql://postgres:postgres@localhost:5432/axiombrain"

    # ── OpenRouter ────────────────────────────────────────────────────────────
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # ── Models ───────────────────────────────────────────────────────────────
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dimensions: int = 1536
    classifier_model: str = "openai/gpt-4o-mini"

    # ── Routing ───────────────────────────────────────────────────────────────
    confidence_threshold: float = 0.6

    # ── API ───────────────────────────────────────────────────────────────────
    axiom_api_key: str = "change-me-in-env"
    axiom_rest_port: int = 8000
    axiom_mcp_port: int = 8001
    axiom_agent_source: str = "mcp_agent"
    axiom_default_project: str = ""

    # ── Search defaults ───────────────────────────────────────────────────────
    default_search_limit: int = 10
    max_search_limit: int = 50

    # ── Embedding cache ───────────────────────────────────────────────────────
    embedding_cache_size: int = 512   # LRU cache entries

    # ── Neo4j ─────────────────────────────────────────────────────────────────
    neo4j_uri:      str = "bolt://localhost:7687"
    neo4j_user:     str = "neo4j"
    neo4j_password: str = "password"

    # ── Notifications ─────────────────────────────────────────────────────────
    # Set TEAMS_WEBHOOK_URL to an Incoming Webhook URL from a Teams channel
    # connector to enable nightly summary notifications.
    teams_webhook_url: Optional[str] = None

    # ── App metadata ──────────────────────────────────────────────────────────
    app_name: str = "AxiomBrain"
    app_version: str = "1.0.0"
    debug: bool = False

    @field_validator("debug", mode="before")
    @classmethod
    def coerce_debug(cls, v: object) -> bool:
        """Coerce debug from env: 'release' and other non-bool strings -> False."""
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes")
        return False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()


# Convenient module-level alias — import as `from axiom_brain.config import settings`
settings: Settings = get_settings()
