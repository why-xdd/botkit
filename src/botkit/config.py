"""Configuration from the environment."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Every setting, validated at startup.

    Validation happens once, at boot, on purpose: a bot that starts with a
    malformed owner list and only fails when someone runs /promote has moved a
    configuration error into production.
    """

    model_config = SettingsConfigDict(
        env_prefix="BOT_", env_file=".env", extra="ignore"
    )

    # SecretStr so the token cannot land in a log line through an accidental
    # repr of the settings object.
    token: SecretStr = Field(..., description="Telegram bot token from @BotFather")

    owner_ids: frozenset[int] = Field(default_factory=frozenset)
    database_url: str = "sqlite+aiosqlite:///botkit.db"

    # Redis keeps FSM state across restarts. Without it, a deploy drops every
    # user mid-form — fine in development, rude in production.
    redis_url: str | None = None

    default_locale: str = "en"
    locales_dir: Path = ROOT / "locales"

    throttle_limit: int = Field(default=5, ge=1)
    throttle_window: float = Field(default=2.0, gt=0)

    drop_pending_updates: bool = True
    log_level: str = "INFO"

    @field_validator("owner_ids", mode="before")
    @classmethod
    def _parse_owners(cls, value: object) -> object:
        """Accept "111,222" from the environment."""
        if isinstance(value, str):
            return frozenset(
                int(part.strip()) for part in value.split(",") if part.strip()
            )
        return value

    @field_validator("token")
    @classmethod
    def _token_looks_real(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if ":" not in raw or not raw.split(":")[0].isdigit():
            raise ValueError(
                "BOT_TOKEN does not look like a Telegram token "
                "(expected '<digits>:<secret>')"
            )
        return value

    @property
    def bot_token(self) -> str:
        return self.token.get_secret_value()
