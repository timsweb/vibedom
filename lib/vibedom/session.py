"""Session management and logging."""

import json
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class SessionState:
    """Represents the persisted state of a session (state.json).

    Example:
        state = SessionState.create(workspace, 'docker')
        state.save(session_dir)
        # later:
        state = SessionState.load(session_dir)
    """

    session_id: str
    workspace: str
    runtime: str
    container_name: str
    status: str          # 'running' | 'complete' | 'abandoned'
    started_at: str      # ISO 8601 string
    ended_at: Optional[str] = None
    bundle_path: Optional[str] = None

    @classmethod
    def create(cls, workspace: Path, runtime: str) -> 'SessionState':
        """Create a new SessionState for a fresh session."""
        from vibedom.words import generate_session_id
        session_id = generate_session_id(workspace.name)
        return cls(
            session_id=session_id,
            workspace=str(workspace),
            runtime=runtime,
            container_name=f'vibedom-{workspace.name}',
            status='running',
            started_at=datetime.now().isoformat(timespec='seconds'),
        )

    @classmethod
    def load(cls, session_dir: Path) -> 'SessionState':
        """Load state from session directory."""
        state_file = session_dir / 'state.json'
        try:
            data = json.loads(state_file.read_text())
            return cls(**data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Malformed state.json in {session_dir}: {e}") from e
        except TypeError as e:
            raise ValueError(f"Invalid state.json schema in {session_dir}: {e}") from e

    def save(self, session_dir: Path) -> None:
        """Persist state to session directory."""
        state_file = session_dir / 'state.json'
        state_file.write_text(json.dumps(asdict(self), indent=2))

    def mark_complete(self, bundle_path: Path, session_dir: Path) -> None:
        """Transition to complete status and persist."""
        self.status = 'complete'
        self.ended_at = datetime.now().isoformat(timespec='seconds')
        self.bundle_path = str(bundle_path)
        self.save(session_dir)

    def mark_abandoned(self, session_dir: Path) -> None:
        """Transition to abandoned status and persist."""
        self.status = 'abandoned'
        self.ended_at = datetime.now().isoformat(timespec='seconds')
        self.save(session_dir)

    @property
    def started_at_dt(self) -> datetime:
        """started_at as a datetime object."""
        return datetime.fromisoformat(self.started_at)


class Session:
    """Manages a sandbox session: lifecycle, state, and logging."""

    def __init__(self, state: 'SessionState', session_dir: Path):
        self.state = state
        self.session_dir = session_dir
        self.network_log = session_dir / 'network.jsonl'
        self.session_log = session_dir / 'session.log'

    @classmethod
    def start(cls, workspace: Path, runtime: str, logs_dir: Path) -> 'Session':
        """Create and initialise a new session.

        Args:
            workspace: Resolved path to workspace directory
            runtime: Container runtime ('docker' or 'apple')
            logs_dir: Base directory for all session logs

        Returns:
            New Session with state.json written and initial log entry

        Example:
            >>> session = Session.start(Path('/projects/myapp'), 'docker', logs_dir)
        """
        state = SessionState.create(workspace, runtime)
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        session_dir = logs_dir / f'session-{timestamp}'
        session_dir.mkdir(parents=True, exist_ok=True)
        state.save(session_dir)
        session = cls(state, session_dir)
        session.log_event(f'Session started for workspace: {workspace}')
        return session

    @classmethod
    def load(cls, session_dir: Path) -> 'Session':
        """Load an existing session from its directory.

        Args:
            session_dir: Path to session directory containing state.json

        Returns:
            Session restored from state.json
        """
        state = SessionState.load(session_dir)
        return cls(state, session_dir)

    def is_container_running(self) -> bool:
        """Check if this session's container is currently running.

        Returns False immediately (without subprocess call) if status is not 'running'.
        """
        if self.state.status != 'running':
            return False
        runtime_cmd = 'container' if self.state.runtime == 'apple' else 'docker'
        try:
            result = subprocess.run(
                [runtime_cmd, 'ps', '--filter', f'name={self.state.container_name}',
                 '--format', '{{.Names}}'],
                capture_output=True, text=True, check=False
            )
            return any(
                line.strip() == self.state.container_name
                for line in result.stdout.splitlines()
            )
        except Exception:
            return False

    @property
    def age_str(self) -> str:
        """Human-readable age of this session (e.g. '2h ago', '3d ago')."""
        age = datetime.now() - self.state.started_at_dt
        if age.days > 0:
            n = age.days
            return f"{n} day{'s' if n > 1 else ''} ago"
        hours = age.seconds // 3600
        if hours > 0:
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        minutes = age.seconds // 60
        if minutes > 0:
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        n = age.seconds
        return f"{n} second{'s' if n != 1 else ''} ago"

    @property
    def display_name(self) -> str:
        """One-line display string for list/prompt output."""
        workspace_name = Path(self.state.workspace).name
        return f"{self.state.session_id} ({workspace_name}, {self.state.status}, {self.age_str})"

    def log_network_request(
        self,
        method: str,
        url: str,
        allowed: bool,
        reason: Optional[str] = None
    ) -> None:
        """Log a network request to network.jsonl."""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'method': method,
            'url': url,
            'allowed': allowed,
            'reason': reason,
        }
        try:
            with open(self.network_log, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except (IOError, OSError) as e:
            import sys
            print(f"Warning: Failed to log network request: {e}", file=sys.stderr)

    def log_event(self, message: str, level: str = 'INFO') -> None:
        """Log an event to session.log."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        entry = f'[{timestamp}] {level}: {message}\n'
        try:
            with open(self.session_log, 'a') as f:
                f.write(entry)
        except (IOError, OSError) as e:
            import sys
            print(f"Warning: Failed to log event: {e}", file=sys.stderr)

    def create_bundle(self) -> Optional[Path]:
        """Create git bundle from session repository.

        Returns:
            Path to bundle file if successful, None if creation failed

        Example:
            >>> bundle_path = session.create_bundle()
            >>> if bundle_path:
            ...     # git remote add vibedom bundle_path
        """
        bundle_path = self.session_dir / 'repo.bundle'
        repo_dir = self.session_dir / 'repo'
        try:
            self.log_event('Creating git bundle...')
            if not repo_dir.exists():
                self.log_event('Repository directory not found', level='ERROR')
                return None
            subprocess.run(
                ['git', '-C', str(repo_dir), 'bundle', 'create', str(bundle_path), '--all'],
                capture_output=True, check=True, text=True
            )
            verify = subprocess.run(
                ['git', 'bundle', 'verify', str(bundle_path)],
                capture_output=True, check=False, text=True
            )
            if verify.returncode == 0:
                self.log_event(f'Bundle created: {bundle_path}')
                return bundle_path
            else:
                self.log_event(f'Bundle verification failed: {verify.stderr}', level='ERROR')
                return None
        except subprocess.CalledProcessError as e:
            self.log_event(f'Bundle creation failed: {e.stderr}', level='ERROR')
            return None
        except Exception as e:
            self.log_event(f'Unexpected error creating bundle: {e}', level='ERROR')
            return None

    def finalize(self) -> None:
        """Finalize session: create bundle and update state.json.

        Sets status to 'complete' if bundle created, 'abandoned' otherwise.
        """
        self.log_event('Finalizing session...')
        bundle_path = self.create_bundle()
        if bundle_path:
            self.state.mark_complete(bundle_path, self.session_dir)
            self.log_event('Session complete')
        else:
            self.state.mark_abandoned(self.session_dir)
            self.log_event('Session abandoned (bundle creation failed)', level='WARN')


class SessionCleanup:
    """Handles session discovery and cleanup operations."""

    @staticmethod
    def _parse_timestamp(session_dir_name: str) -> datetime | None:
        """Parse timestamp from session directory name.

        Args:
            session_dir_name: Directory name like 'session-20260216-171057-123456'

        Returns:
            datetime object if valid, None otherwise
        """
        try:
            prefix = 'session-'
            if not session_dir_name.startswith(prefix):
                return None
            timestamp_str = session_dir_name[len(prefix):]
            return datetime.strptime(timestamp_str, '%Y%m%d-%H%M%S-%f')
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _extract_workspace(session_dir: Path) -> Path | None:
        """Extract workspace path from session.log.

        Args:
            session_dir: Path to session directory containing session.log

        Returns:
            Path to workspace if found, None otherwise
        """
        session_log = session_dir / 'session.log'
        if not session_log.exists():
            return None

        try:
            log_content = session_log.read_text()
            for line in log_content.split('\n'):
                if 'Session started for workspace:' in line:
                    workspace_str = line.split('Session started for workspace:')[-1].strip()
                    return Path(workspace_str)
        except (IOError, OSError):
            pass
        return None

    @staticmethod
    def _is_container_running(workspace: Path, runtime: str) -> bool:
        """Check if vibedom container for workspace is running.

        Args:
            workspace: Path to workspace
            runtime: Runtime type ('docker', 'apple', or 'auto')

        Returns:
            True if container is running, False otherwise
        """
        try:
            runtime_cmd = runtime if runtime in ('docker', 'apple') else 'docker'
            container_name = f'vibedom-{workspace.name}'

            result = subprocess.run(
                [runtime_cmd, 'ps', '--filter', f'name={container_name}',
                 '--format', '{{.Names}}'],
                capture_output=True, text=True, check=False
            )

            return container_name in result.stdout
        except Exception:
            return False

    @staticmethod
    def find_all_sessions(logs_dir: Path, runtime: str = 'auto') -> list:
        """Discover all sessions with metadata.

        Args:
            logs_dir: Base logs directory containing session-* subdirectories
            runtime: Runtime type for container detection

        Returns:
            List of session dictionaries with keys: dir, timestamp, workspace, is_running
        """
        sessions = []

        for session_dir in logs_dir.glob('session-*'):
            if not session_dir.is_dir():
                continue

            timestamp = SessionCleanup._parse_timestamp(session_dir.name)
            if timestamp is None:
                continue

            workspace = SessionCleanup._extract_workspace(session_dir)
            is_running = SessionCleanup._is_container_running(
                workspace, runtime
            ) if workspace else False

            sessions.append({
                'dir': session_dir,
                'timestamp': timestamp,
                'workspace': workspace,
                'is_running': is_running
            })

        return sorted(sessions, key=lambda x: x['timestamp'], reverse=True)

    @staticmethod
    def _filter_by_age(sessions: list, days: int) -> list:
        """Filter sessions older than N days.

        Args:
            sessions: List of session dictionaries
            days: Number of days threshold

        Returns:
            List of sessions older than N days (excluding future-dated)
        """
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(days=days)
        return [
            s for s in sessions
            if s['timestamp'] < cutoff and s['timestamp'] < datetime.now()
        ]

    @staticmethod
    def _filter_not_running(sessions: list) -> list:
        """Filter sessions without running containers.

        Args:
            sessions: List of session dictionaries

        Returns:
            List of sessions where is_running is False
        """
        return [s for s in sessions if not s['is_running']]

    @staticmethod
    def _delete_session(session_dir: Path) -> None:
        """Delete session directory.

        Args:
            session_dir: Path to session directory to delete
        """
        try:
            import shutil
            shutil.rmtree(session_dir, ignore_errors=True)
        except Exception:
            pass
