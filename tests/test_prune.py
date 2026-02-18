"""Tests for prune CLI command."""

import click
from pathlib import Path
from click.testing import CliRunner
from vibedom.cli import main


def test_prune_help():
    """Test prune command has help text."""
    runner = CliRunner()
    result = runner.invoke(main, ['prune', '--help'])
    assert result.exit_code == 0
    assert 'prune' in result.output.lower()


def test_housekeeping_help():
    """Test housekeeping command has help text."""
    runner = CliRunner()
    result = runner.invoke(main, ['housekeeping', '--help'])
    assert result.exit_code == 0
    assert 'housekeeping' in result.output.lower()
    assert '--days' in result.output


def test_prune_dry_run(tmp_path, monkeypatch):
    """Test prune with dry-run doesn't delete anything."""
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
    logs_dir = tmp_path / '.vibedom' / 'logs'
    logs_dir.mkdir(parents=True)

    session = logs_dir / 'session-20260216-171057-123456'
    session.mkdir()
    (session / 'session.log').write_text('Session started for workspace: /Users/test')

    runner = CliRunner()
    result = runner.invoke(main, ['prune', '--dry-run'])
    assert result.exit_code == 0
    assert 'Would delete' in result.output
    assert session.exists()


def test_housekeeping_dry_run(tmp_path, monkeypatch):
    """Test housekeeping with dry-run doesn't delete anything."""
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
    logs_dir = tmp_path / '.vibedom' / 'logs'
    logs_dir.mkdir(parents=True)

    old_session = logs_dir / 'session-20260210-171057-123456'
    old_session.mkdir()
    (old_session / 'session.log').write_text('Session started for workspace: /Users/test')

    runner = CliRunner()
    result = runner.invoke(main, ['housekeeping', '--days', '3', '--dry-run'])
    assert result.exit_code == 0
    assert 'Would delete' in result.output
    assert old_session.exists()
