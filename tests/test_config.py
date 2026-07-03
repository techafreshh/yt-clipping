"""Tests for the configuration module."""

import pytest
from click.exceptions import BadParameter
from typer.testing import CliRunner

from shorts.cli import app
from shorts.config import Settings, mask, require

runner = CliRunner()


def test_settings_loads_defaults():
    s = Settings(_env_file=None)
    assert s.default_model == "anthropic/claude-sonnet-4"
    assert s.default_split == 50
    assert s.default_clip_duration_min == 30
    assert s.default_clip_duration_max == 300
    assert s.supadata_api_key is None
    assert s.openrouter_api_key is None


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("SUPADATA_API_KEY", "sk-test123")
    monkeypatch.setenv("DEFAULT_SPLIT", "75")
    s = Settings(_env_file=None)
    assert s.supadata_api_key == "sk-test123"
    assert s.default_split == 75


def test_require_raises_on_missing():
    s = Settings(_env_file=None)
    with pytest.raises(BadParameter):
        require(s, "supadata_api_key")


def test_require_returns_value(monkeypatch):
    monkeypatch.setenv("SUPADATA_API_KEY", "sk-real-key")
    s = Settings(_env_file=None)
    assert require(s, "supadata_api_key") == "sk-real-key"


def test_mask_hides_secrets():
    assert mask("sk-abc123") == "sk-***"
    assert mask("ab") == "***"
    assert mask("abcd") == "abc***"


def test_config_command_masks_keys(monkeypatch):
    monkeypatch.setenv("SUPADATA_API_KEY", "sk-secret999")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key12345")
    import shorts.config

    monkeypatch.setattr(shorts.config, "settings", Settings(_env_file=None))
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "sk-***" in result.output
    assert "or-***" in result.output
    assert "sk-secret999" not in result.output


def test_config_command_shows_defaults():
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "DEFAULT_SPLIT: 50" in result.output
    assert "DEFAULT_SPLIT: 50" in result.output
