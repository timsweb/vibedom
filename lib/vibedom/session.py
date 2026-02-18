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
    def find_all_sessions(logs_dir: Path, runtime: str = 'auto') -> list:
        """Discover all sessions with metadata."""
        return []
