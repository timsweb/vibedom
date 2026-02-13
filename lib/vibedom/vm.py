"""VM lifecycle management."""

import subprocess
import time
from pathlib import Path
from typing import Optional

class VMManager:
    """Manages VM instances for sandbox sessions."""

    def __init__(self, workspace: Path, config_dir: Path):
        self.workspace = workspace
        self.config_dir = config_dir
        self.container_name = f"vibedom-{workspace.name}"

    def start(self) -> None:
        """Start the VM with workspace mounted."""
        # Stop existing container if any
        self.stop()

        # Start new container
        # Note: Using Docker for PoC, would use apple/container in production
        subprocess.run([
            'docker', 'run',
            '-d',  # Detached
            '--name', self.container_name,
            '--privileged',  # Needed for overlay FS and iptables
            '-v', f'{self.workspace}:/mnt/workspace:ro',  # Read-only workspace
            '-v', f'{self.config_dir}:/mnt/config:ro',  # Config
            'vibedom-alpine:latest'
        ], check=True)

        # Wait for VM to be ready
        time.sleep(2)

    def stop(self) -> None:
        """Stop and remove the VM."""
        try:
            subprocess.run([
                'docker', 'rm', '-f', self.container_name
            ], capture_output=True)
        except subprocess.CalledProcessError:
            pass  # Container doesn't exist

    def exec(self, command: list[str]) -> subprocess.CompletedProcess:
        """Execute a command inside the VM.

        Args:
            command: Command and arguments to execute

        Returns:
            CompletedProcess with stdout/stderr
        """
        return subprocess.run([
            'docker', 'exec', self.container_name
        ] + command, capture_output=True, text=True)

    def get_diff(self) -> str:
        """Get diff between workspace and overlay.

        Returns:
            Unified diff as string
        """
        result = self.exec([
            'diff', '-ur', '/mnt/workspace', '/work'
        ])
        # diff returns exit code 1 when there are differences
        return result.stdout
