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
        try:
            subprocess.run([
                'docker', 'run',
                '-d',  # Detached
                '--name', self.container_name,
                '--privileged',  # Required for overlay mount syscalls and iptables rules
                                 # WARNING: Reduces container isolation - acceptable for local dev sandbox
                                 # TODO: Replace with specific capabilities (CAP_SYS_ADMIN, CAP_NET_ADMIN) in production
                '-v', f'{self.workspace}:/mnt/workspace:ro',  # Read-only workspace
                '-v', f'{self.config_dir}:/mnt/config:ro',  # Config
                'vibedom-alpine:latest'
            ], check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to start VM container '{self.container_name}': {e}") from e
        except FileNotFoundError:
            raise RuntimeError("Docker command not found. Is Docker installed?") from None

        # Wait for VM to be ready
        for _ in range(10):
            try:
                result = subprocess.run(
                    ['docker', 'exec', self.container_name, 'test', '-f', '/tmp/.vm-ready'],
                    capture_output=True,
                    check=False  # Don't raise on non-zero exit
                )
                if result.returncode == 0:
                    return
            except subprocess.CalledProcessError:
                pass  # Container not ready for exec yet
            time.sleep(1)
        raise RuntimeError(f"VM '{self.container_name}' failed to become ready within 10 seconds")

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
