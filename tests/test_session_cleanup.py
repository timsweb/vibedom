"""Tests for session cleanup functionality."""

import pytest
from pathlib import Path
from datetime import datetime
from vibedom.session import SessionCleanup


def test_class_exists():
    """Test that SessionCleanup class exists."""
    assert hasattr(SessionCleanup, 'find_all_sessions')
