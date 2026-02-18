"""Session management and logging."""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

class Session:
    """Manages a sandbox session with logging."""

    def __init__(self, workspace: Path, logs_base_dir: Path):
        """Create a new session.

        Args:
            workspace: Path to workspace being sandboxed
            logs_base_dir: Base directory for logs (e.g., ~/.vibedom/logs)
        """
        self.workspace = workspace

        # Create session directory with timestamp (including microseconds for uniqueness)
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.session_dir = logs_base_dir / f'session-{timestamp}'
        self.session_dir.mkdir(parents=True, exist_ok=True)

        # Create log files
        self.network_log = self.session_dir / 'network.jsonl'
        self.session_log = self.session_dir / 'session.log'

        # Initialize session log
        self.log_event(f'Session started for workspace: {workspace}', level='INFO')

    def log_network_request(
        self,
        method: str,
        url: str,
        allowed: bool,
        reason: Optional[str] = None
    ) -> None:
        """Log a network request.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            allowed: Whether request was allowed
            reason: Optional reason for block/scrub
        """
        entry = {
            'timestamp': datetime.now().isoformat(),
            'method': method,
            'url': url,
            'allowed': allowed,
            'reason': reason
        }

        try:
            with open(self.network_log, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except (IOError, OSError) as e:
            # Don't crash the session - log to stderr
            import sys
            print(f"Warning: Failed to log network request: {e}", file=sys.stderr)

    def log_event(self, message: str, level: str = 'INFO') -> None:
        """Log an event to session log.

        Args:
            message: Log message
            level: Log level (INFO, WARN, ERROR)
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        entry = f'[{timestamp}] {level}: {message}\n'

        try:
            with open(self.session_log, 'a') as f:
                f.write(entry)
        except (IOError, OSError) as e:
            # Don't crash the session - log to stderr
            import sys
            print(f"Warning: Failed to log event: {e}", file=sys.stderr)

    def create_bundle(self) -> Optional[Path]:
        """Create git bundle from session repository.

        Creates a git bundle containing all refs from the container's
        git repository. The bundle can be used as a git remote for
        review and merge.

        Returns:
            Path to bundle file if successful, None if creation failed

        Example:
            >>> session = Session(workspace, logs_dir)
            >>> bundle_path = session.create_bundle()
            >>> if bundle_path:
            ...     # User can now: git remote add vibedom bundle_path
        """
        bundle_path = self.session_dir / 'repo.bundle'
        repo_dir = self.session_dir / 'repo'

        try:
            self.log_event('Creating git bundle...', level='INFO')

            # Check if repo directory exists
            if not repo_dir.exists():
                self.log_event('Repository directory not found', level='ERROR')
                return None

            # Create bundle with all refs
            result = subprocess.run([
                'git', '-C', str(repo_dir),
                'bundle', 'create', str(bundle_path), '--all'
            ], capture_output=True, check=True, text=True)

            # Verify bundle is valid
            verify_result = subprocess.run([
                'git', 'bundle', 'verify', str(bundle_path)
            ], capture_output=True, check=False, text=True)

            if verify_result.returncode == 0:
                self.log_event(f'Bundle created: {bundle_path}', level='INFO')
                return bundle_path
            else:
                self.log_event(f'Bundle verification failed: {verify_result.stderr}', level='ERROR')
                return None

        except subprocess.CalledProcessError as e:
            self.log_event(f'Bundle creation failed: {e.stderr}', level='ERROR')
            self.log_event(f'Live repo still available at {repo_dir}', level='WARN')
            return None
        except Exception as e:
            self.log_event(f'Unexpected error creating bundle: {e}', level='ERROR')
            return None

    def finalize(self) -> None:
        """Finalize the session (called at end)."""
        self.log_event('Session ended', level='INFO')


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
