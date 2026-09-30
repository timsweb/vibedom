"""Tests for ContainerState and ContainerRegistry."""

import json
import pytest
from pathlib import Path
from vibedom.container_state import ContainerState, ContainerRegistry


def test_container_state_create(tmp_path):
    """ContainerState.create() should populate fields correctly."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    state = ContainerState.create(workspace, 'docker')
    assert state.workspace == str(workspace)
    assert state.container_name == 'vibedom-myapp'
    assert state.runtime == 'docker'
    assert state.status == 'stopped'
    assert state.created_at is not None


def test_container_state_save_and_load(tmp_path):
    """ContainerState should round-trip through save/load."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    container_dir = tmp_path / 'containers' / 'myapp'
    container_dir.mkdir(parents=True)

    state = ContainerState.create(workspace, 'docker')
    state.proxy_port = 54321
    state.proxy_pid = 99
    state.save(container_dir)

    loaded = ContainerState.load(container_dir)
    assert loaded.workspace == state.workspace
    assert loaded.container_name == state.container_name
    assert loaded.proxy_port == 54321
    assert loaded.proxy_pid == 99
    assert loaded.status == 'stopped'


def test_container_state_load_missing_file(tmp_path):
    """ContainerState.load() should raise ValueError for missing file."""
    with pytest.raises(FileNotFoundError):
        ContainerState.load(tmp_path)


def test_container_state_load_malformed_json(tmp_path):
    """ContainerState.load() should raise ValueError for bad JSON."""
    (tmp_path / 'container.json').write_text('not json')
    with pytest.raises(ValueError, match='Malformed'):
        ContainerState.load(tmp_path)


def test_container_state_mark_running(tmp_path):
    """mark_running() should update status and proxy info."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    container_dir = tmp_path / 'containers' / 'myapp'
    container_dir.mkdir(parents=True)

    state = ContainerState.create(workspace, 'docker')
    state.save(container_dir)
    state.mark_running(proxy_port=54321, proxy_pid=42, container_dir=container_dir)

    loaded = ContainerState.load(container_dir)
    assert loaded.status == 'running'
    assert loaded.proxy_port == 54321
    assert loaded.proxy_pid == 42


def test_container_state_mark_stopped(tmp_path):
    """mark_stopped() should update status and persist."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    container_dir = tmp_path / 'containers' / 'myapp'
    container_dir.mkdir(parents=True)

    state = ContainerState.create(workspace, 'docker')
    state.mark_running(proxy_port=1234, proxy_pid=10, container_dir=container_dir)
    state.mark_stopped(container_dir)

    loaded = ContainerState.load(container_dir)
    assert loaded.status == 'stopped'


def test_container_registry_find_by_workspace_name(tmp_path):
    """ContainerRegistry.find() should locate container by workspace name."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    containers_dir = tmp_path / 'containers'
    container_dir = containers_dir / 'myapp'
    container_dir.mkdir(parents=True)

    state = ContainerState.create(workspace, 'docker')
    state.save(container_dir)

    registry = ContainerRegistry(containers_dir)
    found = registry.find('myapp')
    assert found is not None
    assert found.container_name == 'vibedom-myapp'


def test_container_registry_find_returns_none_for_unknown(tmp_path):
    """ContainerRegistry.find() should return None when not found."""
    registry = ContainerRegistry(tmp_path / 'containers')
    assert registry.find('nonexistent') is None


def test_container_registry_all(tmp_path):
    """ContainerRegistry.all() should return all containers."""
    containers_dir = tmp_path / 'containers'

    for name in ('app1', 'app2'):
        ws = tmp_path / name
        ws.mkdir()
        cdir = containers_dir / name
        cdir.mkdir(parents=True)
        ContainerState.create(ws, 'docker').save(cdir)

    registry = ContainerRegistry(containers_dir)
    all_containers = registry.all()
    assert len(all_containers) == 2
    names = {c.container_name for c in all_containers}
    assert names == {'vibedom-app1', 'vibedom-app2'}


def test_container_registry_find_by_workspace_path(tmp_path):
    """ContainerRegistry.find() should match by full workspace path."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    containers_dir = tmp_path / 'containers'
    container_dir = containers_dir / 'myapp'
    container_dir.mkdir(parents=True)

    state = ContainerState.create(workspace, 'docker')
    state.save(container_dir)

    registry = ContainerRegistry(containers_dir)
    found = registry.find(str(workspace))
    assert found is not None
    assert found.workspace == str(workspace)


def _write_state(tmp_path, **extra):
    data = {
        'workspace': str(tmp_path / 'myapp'),
        'container_name': 'vibedom-myapp',
        'runtime': 'docker',
        'created_at': '2026-01-01T00:00:00',
        'status': 'stopped',
    }
    data.update(extra)
    (tmp_path / 'container.json').write_text(json.dumps(data))


def test_create_is_not_legacy(tmp_path):
    state = ContainerState.create(tmp_path / 'myapp', 'docker')
    assert state.legacy is False


def test_save_writes_live_marker_and_no_dropped_fields(tmp_path):
    """save() writes `live: true` as the new-model marker (so load() can tell
    new files from copy+sync ones) and nothing else from the old schema."""
    state = ContainerState.create(tmp_path / 'myapp', 'docker')
    state.save(tmp_path)
    data = json.loads((tmp_path / 'container.json').read_text())
    assert data['live'] is True
    assert 'legacy' not in data
    assert 'repo_dir' not in data


def test_load_json_without_live_key_is_legacy(tmp_path):
    """State written before live mounts existed = copy+sync container."""
    _write_state(tmp_path, repo_dir=str(tmp_path / 'repo'))
    assert ContainerState.load(tmp_path).legacy is True


def test_load_live_false_json_is_legacy(tmp_path):
    _write_state(tmp_path, repo_dir=str(tmp_path / 'repo'), live=False)
    assert ContainerState.load(tmp_path).legacy is True


def test_load_live_true_json_is_not_legacy(tmp_path):
    """Containers created with mounts: before this change keep working."""
    _write_state(tmp_path, repo_dir=str(tmp_path / 'repo'), live=True)
    state = ContainerState.load(tmp_path)
    assert state.legacy is False
    assert state.container_name == 'vibedom-myapp'


def test_load_ignores_dropped_fields(tmp_path):
    _write_state(tmp_path, repo_dir='/x', live=True)
    state = ContainerState.load(tmp_path)
    assert not hasattr(state, 'repo_dir')
    assert not hasattr(state, 'live')
