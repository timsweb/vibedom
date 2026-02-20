"""Tests for SessionCleanup filter and delete helpers."""
import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from vibedom.session import Session, SessionCleanup


def make_session(logs_dir, name, status='complete', days_old=0,
                 workspace='/Users/test/myapp'):
    """Create a session directory with state.json for testing."""
    d = logs_dir / name
    d.mkdir(parents=True)
    ws_name = Path(workspace).name
    started = (datetime.now() - timedelta(days=days_old)).isoformat(timespec='seconds')
    state = {
        'session_id': f'{ws_name}-happy-turing',
        'workspace': workspace,
        'runtime': 'docker',
        'container_name': f'vibedom-{ws_name}',
        'status': status,
        'started_at': started,
        'ended_at': None,
        'bundle_path': None,
    }
    (d / 'state.json').write_text(json.dumps(state))
    return Session.load(d)


def test_filter_by_age_returns_old_sessions(tmp_path):
    sessions = [
        make_session(tmp_path, 'session-a', days_old=10),
        make_session(tmp_path, 'session-b', days_old=5),
        make_session(tmp_path, 'session-c', days_old=8),
    ]
    old = SessionCleanup._filter_by_age(sessions, days=7)
    assert len(old) == 2


def test_filter_by_age_excludes_recent(tmp_path):
    sessions = [make_session(tmp_path, 'session-a', days_old=2)]
    assert SessionCleanup._filter_by_age(sessions, days=7) == []


def test_filter_not_running_excludes_running_status(tmp_path):
    sessions = [
        make_session(tmp_path, 'session-a', status='running'),
        make_session(tmp_path, 'session-b', status='complete'),
        make_session(tmp_path, 'session-c', status='abandoned'),
    ]
    not_running = SessionCleanup._filter_not_running(sessions)
    assert len(not_running) == 2
    assert all(s.state.status != 'running' for s in not_running)


def test_filter_not_running_does_not_call_subprocess(tmp_path):
    """_filter_not_running uses state.status only, no subprocess call."""
    from unittest.mock import patch
    sessions = [
        make_session(tmp_path, 'session-a', status='complete'),
    ]
    with patch('subprocess.run') as mock_run:
        SessionCleanup._filter_not_running(sessions)
        mock_run.assert_not_called()


def test_delete_session(tmp_path):
    d = tmp_path / 'session-to-delete'
    d.mkdir()
    (d / 'file.txt').write_text('test')
    SessionCleanup._delete_session(d)
    assert not d.exists()


def test_delete_session_handles_missing_dir(tmp_path):
    # Should not raise
    SessionCleanup._delete_session(tmp_path / 'nonexistent')


def test_removed_methods_do_not_exist():
    """Verify the old methods have been removed."""
    assert not hasattr(SessionCleanup, '_parse_timestamp')
    assert not hasattr(SessionCleanup, '_extract_workspace')
    assert not hasattr(SessionCleanup, '_is_container_running')
    assert not hasattr(SessionCleanup, 'find_all_sessions')
