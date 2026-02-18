"""Tests for session cleanup functionality."""

import pytest
from pathlib import Path
from datetime import datetime
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
