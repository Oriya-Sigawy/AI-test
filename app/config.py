"""Application settings, read from the environment via pydantic-settings.

``SECRET_KEY`` and ``DATABASE_URL`` are required with no defaults, so a
misconfigured process fails at startup instead of falling back to an insecure
value (Principle V).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings read case-insensitively from the environment (or a local ``.env``).

    Each field maps to its upper-case env var (``secret_key`` -> ``SECRET_KEY``).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str
    """HS256 signing key for JWT tokens."""

    database_url: str
    """SQLAlchemy URL for PostgreSQL (``postgresql+psycopg`` driver)."""

    access_token_expire_minutes: int = 60
    """JWT lifetime in minutes; tokens are invalidated only by expiry."""

    default_page_size: int = 50
    """``limit`` applied when a list request omits it."""

    max_page_size: int = 100
    """Upper bound on ``limit`` for any list endpoint."""


settings = Settings()
"""Shared settings instance, imported wherever configuration is needed."""


DEFAULT_CATEGORIES: tuple[dict[str, str], ...] = (
    {"name": "Food", "icon": "food", "color": "#FF8800"},
    {"name": "Transport", "icon": "transport", "color": "#3498DB"},
    {"name": "Entertainment", "icon": "entertainment", "color": "#9B59B6"},
    {"name": "Shopping", "icon": "shopping", "color": "#E91E63"},
    {"name": "Bills", "icon": "bills", "color": "#E74C3C"},
    {"name": "Health", "icon": "health", "color": "#2ECC71"},
    {"name": "Other", "icon": "other", "color": "#95A5A6"},
)
