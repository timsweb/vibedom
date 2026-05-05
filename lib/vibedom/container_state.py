"""Persistent container state management."""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class ContainerState:
    """Persisted state for a long-lived project container (container.json).

    Example:
        state = ContainerState.create(workspace, 'docker')
        state.save(container_dir)
        # later:
        state = ContainerState.load(container_dir)
    """

    workspace: str
    container_name: str
    runtime: str
    created_at: str
    repo_dir: str
    status: str           # 'running' | 'stopped'
    proxy_port: Optional[int] = None
    proxy_pid: Optional[int] = None

    @classmethod
    def create(cls, workspace: Path, runtime: str) -> 'ContainerState':
        """Create a new ContainerState for a fresh container."""
        workspace = workspace.resolve()
        name = workspace.name
        container_name = f'vibedom-{name}'
        repo_dir = Path.home() / '.vibedom' / 'containers' / name / 'repo'
        return cls(
            workspace=str(workspace),
            container_name=container_name,
            runtime=runtime,
            created_at=datetime.now().isoformat(timespec='seconds'),
            repo_dir=str(repo_dir),
            status='stopped',
        )

    @classmethod
    def load(cls, container_dir: Path) -> 'ContainerState':
        """Load state from container directory."""
        state_file = container_dir / 'container.json'
        if not state_file.exists():
            raise FileNotFoundError(f"No container.json in {container_dir}")
        try:
            data = json.loads(state_file.read_text())
            return cls(**data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Malformed container.json in {container_dir}: {e}") from e
        except TypeError as e:
            raise ValueError(f"Invalid container.json schema in {container_dir}: {e}") from e

    def save(self, container_dir: Path) -> None:
        """Persist state to container directory."""
        container_dir.mkdir(parents=True, exist_ok=True)
        state_file = container_dir / 'container.json'
        state_file.write_text(json.dumps(asdict(self), indent=2))

    def mark_running(self, proxy_port: int, proxy_pid: int, container_dir: Path) -> None:
        """Transition to running status and persist."""
        self.status = 'running'
        self.proxy_port = proxy_port
        self.proxy_pid = proxy_pid
        self.save(container_dir)

    def mark_stopped(self, container_dir: Path) -> None:
        """Transition to stopped status and persist."""
        self.status = 'stopped'
        self.save(container_dir)


class ContainerRegistry:
    """Finds and lists persistent containers from ~/.vibedom/containers/."""

    def __init__(self, containers_dir: Optional[Path] = None):
        if containers_dir is None:
            containers_dir = Path.home() / '.vibedom' / 'containers'
        self.containers_dir = containers_dir

    def all(self) -> list[ContainerState]:
        """Return all known containers."""
        if not self.containers_dir.exists():
            return []
        results = []
        for state_file in self.containers_dir.glob('*/container.json'):
            try:
                results.append(ContainerState.load(state_file.parent))
            except (ValueError, FileNotFoundError):
                pass
        return results

    def find(self, identifier: str) -> Optional[ContainerState]:
        """Find container by workspace name or workspace path.

        Args:
            identifier: Workspace directory name (e.g. 'myapp') or full path

        Returns:
            ContainerState if found, None otherwise
        """
        for state in self.all():
            if Path(state.workspace).name == identifier:
                return state
            if state.workspace == identifier:
                return state
            # Also match by container name
            if state.container_name == identifier:
                return state
        return None
