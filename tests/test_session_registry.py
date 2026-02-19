import json
import pytest
import click
from pathlib import Path
from unittest.mock import patch
from vibedom.session import Session, SessionRegistry


def make_session_dir(logs_dir, name, workspace='/Users/test/myapp',
                     status='running', session_id=None):
    """Create a valid session directory with state.json for testing."""
    ws_name = Path(workspace).name
    sid = session_id or f'{ws_name}-happy-turing'
    d = logs_dir / name
    d.mkdir(parents=True)
    state = {
        'session_id': sid,
        'workspace': workspace,
        'runtime': 'docker',
        'container_name': f'vibedom-{ws_name}',
        'status': status,
        'started_at': '2026-02-19T10:00:00',
        'ended_at': None,
        'bundle_path': None,
    }
    (d / 'state.json').write_text(json.dumps(state))
    return d


def test_all_returns_all_sessions(tmp_path):
    make_session_dir(tmp_path, 'session-20260219-100000-000000')
    make_session_dir(tmp_path, 'session-20260219-110000-000000',
                     session_id='myapp-second-session')
    registry = SessionRegistry(tmp_path)
    assert len(registry.all()) == 2


def test_all_returns_newest_first(tmp_path):
    make_session_dir(tmp_path, 'session-20260219-100000-000000',
                     session_id='myapp-old-session')
    make_session_dir(tmp_path, 'session-20260219-110000-000000',
                     session_id='myapp-new-session')
    registry = SessionRegistry(tmp_path)
    sessions = registry.all()
    assert sessions[0].state.session_id == 'myapp-new-session'


def test_all_skips_dirs_without_state_json(tmp_path):
    (tmp_path / 'session-20260219-100000-000000').mkdir()  # no state.json
    make_session_dir(tmp_path, 'session-20260219-110000-000000')
    registry = SessionRegistry(tmp_path)
    assert len(registry.all()) == 1


def test_all_empty_logs_dir(tmp_path):
    registry = SessionRegistry(tmp_path)
    assert registry.all() == []


def test_running_filters_by_status(tmp_path):
    make_session_dir(tmp_path, 'session-20260219-100000-000000', status='running')
    make_session_dir(tmp_path, 'session-20260219-110000-000000',
                     status='complete', session_id='myapp-complete-one')
    registry = SessionRegistry(tmp_path)
    running = registry.running()
    assert len(running) == 1
    assert running[0].state.status == 'running'


def test_find_by_session_id(tmp_path):
    make_session_dir(tmp_path, 'session-20260219-100000-000000',
                     session_id='myapp-happy-turing')
    registry = SessionRegistry(tmp_path)
    session = registry.find('myapp-happy-turing')
    assert session is not None
    assert session.state.session_id == 'myapp-happy-turing'


def test_find_by_workspace_name(tmp_path):
    make_session_dir(tmp_path, 'session-20260219-100000-000000',
                     workspace='/Users/test/rabbitmq-talk',
                     session_id='rabbitmq-talk-happy-turing')
    registry = SessionRegistry(tmp_path)
    session = registry.find('rabbitmq-talk')
    assert session is not None
    assert 'rabbitmq-talk' in session.state.workspace


def test_find_returns_none_for_unknown(tmp_path):
    registry = SessionRegistry(tmp_path)
    assert registry.find('nonexistent') is None


def test_find_returns_most_recent_for_workspace(tmp_path):
    make_session_dir(tmp_path, 'session-20260219-100000-000000',
                     workspace='/Users/test/myapp', session_id='myapp-old-one')
    make_session_dir(tmp_path, 'session-20260219-110000-000000',
                     workspace='/Users/test/myapp', session_id='myapp-new-one')
    registry = SessionRegistry(tmp_path)
    session = registry.find('myapp')
    assert session.state.session_id == 'myapp-new-one'


def test_resolve_with_id_returns_match(tmp_path):
    make_session_dir(tmp_path, 'session-20260219-100000-000000',
                     session_id='myapp-happy-turing')
    registry = SessionRegistry(tmp_path)
    session = registry.resolve('myapp-happy-turing')
    assert session.state.session_id == 'myapp-happy-turing'


def test_resolve_raises_for_unknown_id(tmp_path):
    registry = SessionRegistry(tmp_path)
    with pytest.raises(click.ClickException):
        registry.resolve('nonexistent')


def test_resolve_single_session_auto_selects(tmp_path):
    make_session_dir(tmp_path, 'session-20260219-100000-000000',
                     session_id='myapp-happy-turing')
    registry = SessionRegistry(tmp_path)
    # Single session, no id_or_name — auto-select
    session = registry.resolve(None)
    assert session.state.session_id == 'myapp-happy-turing'


def test_resolve_no_sessions_raises(tmp_path):
    registry = SessionRegistry(tmp_path)
    with pytest.raises(click.ClickException):
        registry.resolve(None)
