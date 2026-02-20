"""Tests for prune CLI command."""

import json
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
    session_dir = logs_dir / 'session-20260216-171057-123456'
    session_dir.mkdir(parents=True)
    (session_dir / 'state.json').write_text(json.dumps({
        'session_id': 'myapp-happy-turing',
        'workspace': '/Users/test/myapp',
        'runtime': 'docker',
        'container_name': 'vibedom-myapp',
        'status': 'complete',   # not running -> eligible for prune
        'started_at': '2026-02-16T17:10:57',
        'ended_at': '2026-02-16T18:00:00',
        'bundle_path': None,
    }))

    runner = CliRunner()
    result = runner.invoke(main, ['prune', '--dry-run'])
    assert result.exit_code == 0
    assert 'Would delete' in result.output
    assert session_dir.exists()


def test_housekeeping_dry_run(tmp_path, monkeypatch):
    """Test housekeeping with dry-run doesn't delete anything."""
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260210-171057-123456'
    session_dir.mkdir(parents=True)
    (session_dir / 'state.json').write_text(json.dumps({
        'session_id': 'myapp-old-session',
        'workspace': '/Users/test/myapp',
        'runtime': 'docker',
        'container_name': 'vibedom-myapp',
        'status': 'complete',
        'started_at': '2026-02-10T17:10:57',
        'ended_at': '2026-02-10T18:00:00',
        'bundle_path': None,
    }))

    runner = CliRunner()
    result = runner.invoke(main, ['housekeeping', '--days', '3', '--dry-run'])
    assert result.exit_code == 0
    assert 'Would delete' in result.output
    assert session_dir.exists()
