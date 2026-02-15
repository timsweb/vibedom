"""VM lifecycle management."""

import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

class VMManager:
    """Manages VM instances for sandbox sessions."""

    def __init__(self, workspace: Path, config_dir: Path, session_dir: Optional[Path] = None):
        """Initialize VM manager.

        Args:
            workspace: Path to workspace directory
            config_dir: Path to config directory
            session_dir: Path to session directory (for repo mount)
        """
        self.workspace = workspace.resolve()
        self.config_dir = config_dir.resolve()
        self.session_dir = session_dir.resolve() if session_dir else None
        self.container_name = f'vibedom-{workspace.name}'

    def start(self) -> None:
        """Start the VM with workspace mounted."""
        # Stop existing container if any
        self.stop()

        # Copy mitmproxy addon to config dir
        addon_src = Path(__file__).parent.parent.parent / 'vm' / 'mitmproxy_addon.py'
        addon_dst = self.config_dir / 'mitmproxy_addon.py'
        shutil.copy(addon_src, addon_dst)

        # Copy DLP scrubber module to config dir
        scrubber_src = Path(__file__).parent.parent.parent / 'vm' / 'dlp_scrubber.py'
        scrubber_dst = self.config_dir / 'dlp_scrubber.py'
        shutil.copy(scrubber_src, scrubber_dst)

        # Copy gitleaks config for runtime DLP patterns
        gitleaks_src = Path(__file__).parent / 'config' / 'gitleaks.toml'
        gitleaks_dst = self.config_dir / 'gitleaks.toml'
        shutil.copy(gitleaks_src, gitleaks_dst)

        # Prepare session repo directory if provided
        repo_mount = []
        session_mount = []
        if self.session_dir:
            repo_dir = self.session_dir / 'repo'
            repo_dir.mkdir(parents=True, exist_ok=True)
            repo_mount = ['-v', f'{repo_dir}:/work/repo']
            session_mount = ['-v', f'{self.session_dir}:/mnt/session']

        # Start new container
        # Note: Using Docker for PoC, would use apple/container in production
        try:
            subprocess.run([
                'docker', 'run',
                '-d',  # Detached
                '--name', self.container_name,
                '--privileged',  # Required for git operations
                                 # WARNING: Reduces container isolation - acceptable for local dev sandbox
                                 # TODO: Replace with specific capabilities (CAP_SYS_ADMIN) in production
                # Set proxy environment variables for docker exec sessions
                '-e', 'HTTP_PROXY=http://127.0.0.1:8080',
                '-e', 'HTTPS_PROXY=http://127.0.0.1:8080',
                '-e', 'NO_PROXY=localhost,127.0.0.1,::1',
                '-e', 'http_proxy=http://127.0.0.1:8080',
                '-e', 'https_proxy=http://127.0.0.1:8080',
                '-e', 'no_proxy=localhost,127.0.0.1,::1',
                '-v', f'{self.workspace}:/mnt/workspace:ro',  # Read-only workspace
                '-v', f'{self.config_dir}:/mnt/config:ro',  # Config
                *repo_mount,  # Session repo directory
                *session_mount,  # Session directory for bundle output
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

    
