"""Configuration module using Pydantic BaseSettings."""

from __future__ import annotations

from typing import Optional

import typer
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    supadata_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    default_model: str = "anthropic/claude-sonnet-4"
    default_split: int = 50
    default_clip_duration_min: int = 30
    default_clip_duration_max: int = 300
    youtube_proxy: Optional[str] = None
    caption_alignment: int = 2
    caption_margin_v: int = 480
    default_resolution: int = 1080
    n8n_webhook_url: Optional[str] = None


def require(settings: Settings, field_name: str) -> str:
    """Return field value or raise if missing."""
    value = getattr(settings, field_name)
    if value is None:
        raise typer.BadParameter(f"Missing required config: {field_name.upper()}. Set it in .env")
    return value


def mask(value: str) -> str:
    """Mask a secret value, showing only first 3 chars."""
    if len(value) > 3:
        return value[:3] + "***"
    return "***"


settings = Settings()
