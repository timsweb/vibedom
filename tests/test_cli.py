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
