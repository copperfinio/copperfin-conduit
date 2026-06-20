"""Tests for the Conduit CLI shell."""

from __future__ import annotations

from click.testing import CliRunner

from conduit.cli import cli


def test_cli_help_mentions_tagline():
    """The top-level CLI is installable and discoverable."""
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "Use your AI subscriptions like an API." in result.output
    assert "auth" in result.output
    assert "smoke" in result.output


def test_init_creates_user_scoped_conduit_files(monkeypatch, tmp_path):
    """Conduit init writes to CONDUIT_HOME, which defaults to ~/.conduit."""
    monkeypatch.setenv("CONDUIT_HOME", str(tmp_path / ".conduit"))

    result = CliRunner().invoke(cli, ["init"])

    assert result.exit_code == 0
    assert tmp_path.joinpath(".conduit", ".env").exists()
    assert "Codex auth:" in result.output
    assert "Claude auth:" in result.output
    assert str(tmp_path.joinpath(".conduit", "auth.json")) in result.output
    assert str(tmp_path.joinpath(".conduit", "anthropic_auth.json")) in result.output


def test_service_install_dry_run_is_safe(monkeypatch, tmp_path):
    """Service install can be inspected without touching the OS."""
    monkeypatch.setenv("CONDUIT_HOME", str(tmp_path / ".conduit"))

    result = CliRunner().invoke(cli, ["service", "install", "--dry-run"])

    assert result.exit_code == 0
    assert "conduit" in result.output.lower()
