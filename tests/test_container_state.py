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
    assert state.repo_dir == str(Path.home() / '.vibedom' / 'containers' / 'myapp' / 'repo')


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
