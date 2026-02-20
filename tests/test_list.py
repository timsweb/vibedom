# tests/test_list.py
import json
from pathlib import Path
from click.testing import CliRunner
from unittest.mock import patch
from vibedom.cli import main


def make_state(logs_dir, session_name, session_id, workspace, status):
    d = logs_dir / session_name
    d.mkdir(parents=True)
    ws_name = Path(workspace).name
    (d / 'state.json').write_text(json.dumps({
        'session_id': session_id,
        'workspace': workspace,
        'runtime': 'docker',
        'container_name': f'vibedom-{ws_name}',
        'status': status,
        'started_at': '2026-02-19T10:00:00',
        'ended_at': None,
        'bundle_path': None,
    }))


def test_list_shows_sessions(tmp_path):
    logs_dir = tmp_path / '.vibedom' / 'logs'
    make_state(logs_dir, 'session-20260219-100000-000000',
               'myapp-happy-turing', '/Users/test/myapp', 'running')
    make_state(logs_dir, 'session-20260219-090000-000000',
               'ifs-bridge-calm-lovelace', '/Users/test/ifs-bridge', 'complete')

    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        result = runner.invoke(main, ['list'])

    assert result.exit_code == 0
    assert 'myapp-happy-turing' in result.output
    assert 'ifs-bridge-calm-lovelace' in result.output
    assert 'running' in result.output
    assert 'complete' in result.output


def test_list_no_sessions(tmp_path):
    (tmp_path / '.vibedom' / 'logs').mkdir(parents=True)
    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        result = runner.invoke(main, ['list'])
    assert result.exit_code == 0
    assert 'No sessions' in result.output


def test_list_no_logs_dir(tmp_path):
    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        result = runner.invoke(main, ['list'])
    assert result.exit_code == 0
    assert 'No sessions' in result.output
