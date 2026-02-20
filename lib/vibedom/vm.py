"""VM lifecycle management."""

import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

class VMManager:
    """Manages VM instances for sandbox sessions."""

    def __init__(self, workspace: Path, config_dir: Path, session_dir: Optional[Path] = None, runtime: Optional[str] = None):
        """Initialize VM manager.

        Args:
            workspace: Path to workspace directory
            config_dir: Path to config directory
            session_dir: Path to session directory (for repo mount)
            runtime: Container runtime ('auto', 'docker', or 'apple'). If None, auto-detects.
        """
        self.workspace = workspace.resolve()
        self.config_dir = config_dir.resolve()
        self.session_dir = session_dir.resolve() if session_dir else None
        self.container_name = f'vibedom-{workspace.name}'
        self.runtime, self.runtime_cmd = self._detect_runtime(runtime)

    @staticmethod
    def _detect_runtime(runtime: Optional[str] = None) -> tuple[str, str]:
        """Detect available container runtime or use specified one.

        Args:
            runtime: Explicit runtime ('docker' or 'apple'), or None for auto-detect

        Returns:
            Tuple of (runtime_name, command) — e.g. ('apple', 'container')
        """
        if runtime == 'docker':
            if not shutil.which('docker'):
                raise RuntimeError("Docker runtime requested but not found on system.")
            return 'docker', 'docker'
        if runtime == 'apple':
            if not shutil.which('container'):
                raise RuntimeError("apple/container runtime requested but not found on system.")
            return 'apple', 'container'

        # Auto-detect
        if shutil.which('container'):
            return 'apple', 'container'
        if shutil.which('docker'):
            return 'docker', 'docker'
        raise RuntimeError(
            "No container runtime found. Install apple/container (macOS 26+) or Docker."
        )

    @staticmethod
    def image_exists(runtime_cmd: str) -> bool:
        """Check whether the vibedom-alpine image has been built."""
        result = subprocess.run(
            [runtime_cmd, 'image', 'inspect', 'vibedom-alpine:latest'],
            capture_output=True
        )
        return result.returncode == 0

    @staticmethod
    def build_image(runtime: Optional[str] = None) -> None:
        """Build the vibedom-alpine container image.

        Args:
            runtime: Container runtime ('docker' or 'apple'), or None for auto-detect
        """
        _, runtime_cmd = VMManager._detect_runtime(runtime)
        vm_dir = Path(__file__).parent.parent.parent / 'vm'
        dockerfile = vm_dir / 'Dockerfile.alpine'

        if not dockerfile.exists():
            raise RuntimeError(f"Dockerfile not found at {dockerfile}")

        subprocess.run(
            [runtime_cmd, 'build', '-t', 'vibedom-alpine:latest',
             '-f', str(dockerfile), str(vm_dir)],
            check=True
        )

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

        # Build container run command
        detach_flag = '--detach' if self.runtime == 'apple' else '-d'

        cmd = [
            self.runtime_cmd, 'run',
            detach_flag,
            '--name', self.container_name,
            # Proxy environment variables
            '-e', 'HTTP_PROXY=http://127.0.0.1:8080',
            '-e', 'HTTPS_PROXY=http://127.0.0.1:8080',
            '-e', 'NO_PROXY=localhost,127.0.0.1,::1',
            '-e', 'http_proxy=http://127.0.0.1:8080',
            '-e', 'https_proxy=http://127.0.0.1:8080',
            '-e', 'no_proxy=localhost,127.0.0.1,::1',
            # Mounts
            '-v', f'{self.workspace}:/mnt/workspace:ro',
            '-v', f'{self.config_dir}:/mnt/config:ro',
        ]

        # Session mounts
        if self.session_dir:
            repo_dir = self.session_dir / 'repo'
            repo_dir.mkdir(parents=True, exist_ok=True)
            cmd += ['-v', f'{repo_dir}:/work/repo']
            cmd += ['-v', f'{self.session_dir}:/mnt/session']

        # Claude/OpenCode config - shared persistent volume across all workspaces
        cmd += ['-v', 'vibedom-claude-config:/root/.claude']

        cmd.append('vibedom-alpine:latest')

        # Start container
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to start VM container '{self.container_name}': {e}"
            ) from e
        except FileNotFoundError:
            raise RuntimeError(
                f"Container command '{self.runtime_cmd}' not found."
            ) from None

        # Wait for VM to be ready (increased timeout for git cloning)
        for _ in range(60):
            result = subprocess.run(
                [self.runtime_cmd, 'exec', self.container_name,
                 'test', '-f', '/tmp/.vm-ready'],
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                return
            time.sleep(1)
        raise RuntimeError(
            f"VM '{self.container_name}' failed to become ready within 60 seconds"
        )

    def stop(self) -> None:
        """Stop and remove the VM."""
        try:
            if self.runtime == 'apple':
                subprocess.run(
                    ['container', 'stop', self.container_name],
                    capture_output=True,
                )
                subprocess.run(
                    ['container', 'delete', '--force', self.container_name],
                    capture_output=True,
                )
            else:
                subprocess.run(
                    ['docker', 'rm', '-f', self.container_name],
                    capture_output=True,
                )
        except FileNotFoundError:
            pass  # Runtime not installed

    def exec(self, command: list[str]) -> subprocess.CompletedProcess:
        """Execute a command inside the VM.

        Args:
            command: Command and arguments to execute

        Returns:
            CompletedProcess with stdout/stderr
        """
        return subprocess.run(
            [self.runtime_cmd, 'exec', self.container_name] + command,
            capture_output=True,
            text=True,
        )

    
