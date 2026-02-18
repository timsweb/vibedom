"""Tests for session cleanup functionality."""

import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from vibedom.session import SessionCleanup


def test_class_exists():
    """Test that SessionCleanup class exists."""
    assert hasattr(SessionCleanup, 'find_all_sessions')


def test_parse_timestamp_valid():
    """Test timestamp parsing from valid directory name."""
    timestamp = SessionCleanup._parse_timestamp('session-20260216-171057-123456')
    assert timestamp == datetime(2026, 2, 16, 17, 10, 57, 123456)


def test_parse_timestamp_invalid():
    """Test timestamp parsing from invalid directory name."""
    timestamp = SessionCleanup._parse_timestamp('invalid-name')
    assert timestamp is None


def test_extract_workspace_valid(tmp_path):
    """Test workspace extraction from valid session.log."""
    session_log = tmp_path / 'session.log'
    session_log.write_text('Session started for workspace: /Users/test/workspace')
    workspace = SessionCleanup._extract_workspace(tmp_path)
    assert workspace == Path('/Users/test/workspace')


def test_extract_workspace_no_log(tmp_path):
    """Test workspace extraction when session.log is missing."""
    workspace = SessionCleanup._extract_workspace(tmp_path)
    assert workspace is None


def test_extract_workspace_no_workspace_line(tmp_path):
    """Test workspace extraction when log has no workspace line."""
    session_log = tmp_path / 'session.log'
    session_log.write_text('Some other log line')
    workspace = SessionCleanup._extract_workspace(tmp_path)
    assert workspace is None


def test_is_container_running_true():
    """Test container detection when container is running."""
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout='vibedom-test\n')
        result = SessionCleanup._is_container_running(Path('/Users/test'), 'docker')
        assert result is True


def test_is_container_running_false():
    """Test container detection when container is not running."""
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout='')
        result = SessionCleanup._is_container_running(Path('/Users/test'), 'docker')
        assert result is False


def test_is_container_running_error():
    """Test container detection on error (assume not running)."""
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = Exception('Runtime error')
        result = SessionCleanup._is_container_running(Path('/Users/test'), 'docker')
        assert result is False


def test_find_all_sessions(tmp_path):
    """Test session discovery returns all sessions."""
    session1 = tmp_path / 'session-20260216-171057-123456'
    session2 = tmp_path / 'session-20260217-171057-123456'
    session1.mkdir()
    session2.mkdir()

    log1 = session1 / 'session.log'
    log1.write_text('Session started for workspace: /Users/test/workspace1')
    log2 = session2 / 'session.log'
    log2.write_text('Session started for workspace: /Users/test/workspace2')

    with patch.object(SessionCleanup, '_is_container_running', return_value=False):
        sessions = SessionCleanup.find_all_sessions(tmp_path)

    assert len(sessions) == 2
    assert all('dir' in s for s in sessions)
    assert all('timestamp' in s for s in sessions)
    assert all('workspace' in s for s in sessions)
    assert all('is_running' in s for s in sessions)
    assert sessions[0]['dir'].name == 'session-20260217-171057-123456'


def test_filter_by_age():
    """Test age-based filtering."""
    sessions = [
        {'timestamp': datetime.now() - timedelta(days=10)},
        {'timestamp': datetime.now() - timedelta(days=5)},
        {'timestamp': datetime.now() - timedelta(days=7, seconds=1)},
    ]
    old = SessionCleanup._filter_by_age(sessions, days=7)
    assert len(old) == 2


def test_filter_by_age_future():
    """Test filtering skips future-dated sessions."""
    sessions = [
        {'timestamp': datetime.now() + timedelta(days=1)},
        {'timestamp': datetime.now() - timedelta(days=10)},
    ]
    old = SessionCleanup._filter_by_age(sessions, days=7)
    assert len(old) == 1
    assert old[0]['timestamp'] < datetime.now()


def test_filter_not_running():
    """Test filter for non-running containers."""
    sessions = [
        {'is_running': True, 'dir': Path('/a')},
        {'is_running': False, 'dir': Path('/b')},
        {'is_running': True, 'dir': Path('/c')},
    ]
    not_running = SessionCleanup._filter_not_running(sessions)
    assert len(not_running) == 1
    assert not_running[0]['dir'] == Path('/b')


def test_delete_session(tmp_path):
    """Test session directory deletion."""
    (tmp_path / 'file.txt').write_text('test')
    SessionCleanup._delete_session(tmp_path)
    assert not tmp_path.exists()


def test_delete_session_error(tmp_path):
    """Test deletion error is handled gracefully."""
    SessionCleanup._delete_session(tmp_path)
