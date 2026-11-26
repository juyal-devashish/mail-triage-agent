"""Settings, read from MTA_* environment variables or backend/.env. Model choice lives here and nowhere else."""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MTA_", env_file=BACKEND / ".env", extra="ignore")

    provider: Literal["synthetic", "gmail"] = "synthetic"
    db_path: Path | None = None  # default: data/<provider>.db, so real and synthetic mail never mix

    @property
    def database(self) -> Path:
        return self.db_path or BACKEND / "data" / f"{self.provider}.db"

    # Claude
    model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high"] = "low"
    max_tokens: int = 4000
    max_calls: int = 10  # live calls per run; anything bigger is an explicit --max-calls
    # Response cache for real mail. The synthetic inbox uses the committed file in app/synth/.
    cache_path: Path = BACKEND / "data" / "responses.jsonl"
    # List prices per million tokens, for cost estimates only (Claude Opus 5.5).
    input_price: float = 4.0
    output_price: float = 20.0

    # Gmail
    gmail_dir: Path = Path.home() / ".config" / "mail-triage-agent"
    gmail_days: int = 7
    gmail_max_messages: int = 300


def settings() -> Settings:
    return Settings()
