import pytest
from pathlib import Path
from datetime import datetime
from vibedom.session import SessionState


def test_create_sets_all_fields():
    workspace = Path('/Users/test/myapp')
    state = SessionState.create(workspace, 'docker')
    assert state.workspace == '/Users/test/myapp'
    assert state.runtime == 'docker'
    assert state.container_name == 'vibedom-myapp'
    assert state.status == 'running'
    assert state.session_id.startswith('myapp-')
    assert state.ended_at is None
    assert state.bundle_path is None


def test_create_apple_runtime():
    state = SessionState.create(Path('/Users/test/myapp'), 'apple')
    assert state.runtime == 'apple'


def test_save_and_load_roundtrip(tmp_path):
    state = SessionState.create(Path('/Users/test/myapp'), 'docker')
    state.save(tmp_path)
    assert (tmp_path / 'state.json').exists()
    loaded = SessionState.load(tmp_path)
    assert loaded.session_id == state.session_id
    assert loaded.workspace == state.workspace
    assert loaded.runtime == state.runtime
    assert loaded.container_name == state.container_name
    assert loaded.status == state.status
    assert loaded.started_at == state.started_at
    assert loaded.ended_at is None
    assert loaded.bundle_path is None
    assert loaded.proxy_port is None
    assert loaded.proxy_pid is None


def test_load_missing_state_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        SessionState.load(tmp_path)


def test_mark_complete(tmp_path):
    state = SessionState.create(Path('/Users/test/myapp'), 'docker')
    state.save(tmp_path)
    bundle = tmp_path / 'repo.bundle'
    state.mark_complete(bundle, tmp_path)
    assert state.status == 'complete'
    assert state.bundle_path == str(bundle)
    assert state.ended_at is not None
    # Verify persisted to disk
    reloaded = SessionState.load(tmp_path)
    assert reloaded.status == 'complete'


def test_mark_abandoned(tmp_path):
    state = SessionState.create(Path('/Users/test/myapp'), 'docker')
    state.save(tmp_path)
    state.mark_abandoned(tmp_path)
    assert state.status == 'abandoned'
    assert state.ended_at is not None
    reloaded = SessionState.load(tmp_path)
    assert reloaded.status == 'abandoned'


def test_started_at_dt_is_datetime():
    state = SessionState.create(Path('/Users/test/myapp'), 'docker')
    assert isinstance(state.started_at_dt, datetime)


def test_session_state_stores_proxy_fields(tmp_path):
    """SessionState should persist proxy_port and proxy_pid."""
    state = SessionState.create(
        session_id='myapp-happy-turing',
        workspace=tmp_path / 'myapp',
        runtime='docker',
        container_name='vibedom-myapp',
    )
    state.proxy_port = 54321
    state.proxy_pid = 99999
    state.save(tmp_path)

    loaded = SessionState.load(tmp_path)
    assert loaded.proxy_port == 54321
    assert loaded.proxy_pid == 99999
