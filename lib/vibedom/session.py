"""Session management and logging."""

import json
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

    def finalize(self) -> None:
        """Finalize the session (called at end)."""
        self.log_event('Session ended', level='INFO')
