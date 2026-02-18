import subprocess
import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from vibedom.cli import main

def test_cli_shows_help():
    """CLI should show help message when invoked with --help"""
    result = subprocess.run(
        ['vibedom', '--help'],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert 'vibedom' in result.stdout.lower()
    assert 'init' in result.stdout
    assert 'run' in result.stdout


def test_reload_whitelist_sends_sighup(tmp_path):
    """reload-whitelist should send SIGHUP to mitmdump in container."""
    workspace = tmp_path / 'test-workspace'
    workspace.mkdir()

    with patch('vibedom.cli.VMManager._detect_runtime', return_value=('docker', 'docker')):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr='')

            runner = CliRunner()
            result = runner.invoke(main, ['reload-whitelist', str(workspace)])

            # Should call docker exec ... pkill -HUP mitmdump
            assert mock_run.called
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == 'docker'
            assert 'exec' in cmd
            assert 'pkill' in cmd
            assert '-HUP' in cmd
            assert 'mitmdump' in cmd
            assert result.exit_code == 0


def test_reload_whitelist_fails_if_container_not_running(tmp_path):
    """reload-whitelist should fail gracefully if container not running."""
    workspace = tmp_path / 'test-workspace'
    workspace.mkdir()

    with patch('vibedom.cli.VMManager._detect_runtime', return_value=('docker', 'docker')):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr='Error: No such container')

            runner = CliRunner()
            result = runner.invoke(main, ['reload-whitelist', str(workspace)])

            assert result.exit_code == 1
            assert 'Failed to reload' in result.output


def test_find_latest_session_success(tmp_path):
    """find_latest_session should return most recent session for workspace."""
    from vibedom.cli import find_latest_session

    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    logs_dir = tmp_path / 'logs'
    logs_dir.mkdir()

    # Create two sessions
    session1 = logs_dir / 'session-20260218-100000-000000'
    session1.mkdir()
    (session1 / 'session.log').write_text(f'Session started for workspace: {workspace}')

    session2 = logs_dir / 'session-20260218-110000-000000'
    session2.mkdir()
    (session2 / 'session.log').write_text(f'Session started for workspace: {workspace}')

    result = find_latest_session(workspace, logs_dir)
    assert result == session2  # Most recent


def test_find_latest_session_not_found(tmp_path):
    """find_latest_session should return None if no session found."""
    from vibedom.cli import find_latest_session

    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    logs_dir = tmp_path / 'logs'
    logs_dir.mkdir()

    result = find_latest_session(workspace, logs_dir)
    assert result is None
