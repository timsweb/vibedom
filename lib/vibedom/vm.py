"""VM lifecycle management."""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from vibedom.proxy import ProxyManager


class VMManager:
    """Manages VM instances for sandbox sessions."""

    def __init__(self, workspace: Path, config_dir: Path, session_dir: Optional[Path] = None,
                 runtime: Optional[str] = None, network: Optional[str] = None,
                 base_image: Optional[str] = None):
        """Initialize VM manager.

        Args:
            workspace: Path to workspace directory
            config_dir: Path to config directory
            session_dir: Path to session directory (for repo mount)
            runtime: Container runtime ('auto', 'docker', or 'apple'). If None, auto-detects.
            network: Docker network name to join (for project DB/service access).
            base_image: Project base image to layer vibedom on top of. If None, uses vibedom-alpine.
        """
        self.workspace = workspace.resolve()
        self.config_dir = config_dir.resolve()
        self.session_dir = session_dir.resolve() if session_dir else None
        self.container_name = f'vibedom-{workspace.name}'
        self.runtime, self.runtime_cmd = self._detect_runtime(runtime)
        self.network = network
        self.base_image = base_image
        self._proxy: Optional[ProxyManager] = None

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

        # Auto-detect: Docker is preferred; apple/container is experimental
        if shutil.which('docker'):
            return 'docker', 'docker'
        if shutil.which('container'):
            return 'apple', 'container'
        raise RuntimeError(
            "No container runtime found. Install Docker or apple/container (experimental, macOS 26+)."
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
        container_dir = Path(__file__).parent / 'container'
        dockerfile = container_dir / 'Dockerfile.alpine'

        if not dockerfile.exists():
            raise RuntimeError(f"Dockerfile not found at {dockerfile}")

        subprocess.run(
            [runtime_cmd, 'build', '-t', 'vibedom-alpine:latest',
             '-f', str(dockerfile), str(container_dir)],
            check=True
        )

    def _image_name(self) -> str:
        """Return the image to run. Builds project layer if base_image set."""
        if not self.base_image:
            return 'vibedom-alpine:latest'
        tag = f'vibedom-project-{self.container_name}:latest'
        self.build_project_image(self.base_image, tag)
        return tag

    def build_project_image(self, base_image: str, tag: str) -> None:
        """Build vibedom layer on top of a project base image."""
        container_dir = Path(__file__).parent / 'container'
        dockerfile = container_dir / 'Dockerfile.layer'
        subprocess.run(
            [
                self.runtime_cmd, 'build',
                '--build-arg', f'BASE_IMAGE={base_image}',
                '-t', tag,
                '-f', str(dockerfile),
                str(container_dir),
            ],
            check=True
        )

    def _apple_host_ip(self) -> str:
        """Return the host IP as seen from inside an apple/container container.

        apple/container doesn't support --add-host and doesn't inject host.docker.internal,
        so we resolve the host via the default network gateway.
        """
        result = subprocess.run(
            ['container', 'network', 'inspect', 'default'],
            capture_output=True, text=True, check=True
        )
        networks = json.loads(result.stdout)
        return networks[0]['status']['ipv4Gateway']

    def start(self) -> None:
        """Start the VM with workspace mounted."""
        # Stop existing container if any
        self.stop()

        # Copy gitleaks config for runtime DLP patterns
        gitleaks_src = Path(__file__).parent / 'config' / 'gitleaks.toml'
        gitleaks_dst = self.config_dir / 'gitleaks.toml'
        shutil.copy(gitleaks_src, gitleaks_dst)

        # Start host proxy
        self._proxy = ProxyManager(
            session_dir=self.session_dir,
            config_dir=self.config_dir,
        )
        proxy_port = self._proxy.start()

        # Determine image (builds project layer if base_image set)
        image = self._image_name()

        # Ensure mitmproxy conf dir exists so the CA cert will be readable via /mnt/config mount
        conf_dir = self.config_dir / 'mitmproxy'
        conf_dir.mkdir(parents=True, exist_ok=True)

        detach_flag = '--detach' if self.runtime == 'apple' else '-d'
        # apple/container doesn't support --add-host and doesn't inject host.docker.internal,
        # so we use the default network gateway IP to reach the host proxy.
        proxy_host = self._apple_host_ip() if self.runtime == 'apple' else 'host.docker.internal'
        proxy_url = f'http://{proxy_host}:{proxy_port}'
        # CA bundle path inside the container (set by update-ca-certificates)
        ca_bundle = '/etc/ssl/certs/ca-certificates.crt'

        cmd = [
            self.runtime_cmd, 'run',
            detach_flag,
            '--name', self.container_name,
        ]
        # Docker on Linux needs --add-host to resolve host.docker.internal;
        # apple/container doesn't support the flag (we use the gateway IP directly instead).
        if self.runtime != 'apple':
            cmd += ['--add-host', 'host.docker.internal:host-gateway']
        cmd += [
            # Proxy environment variables
            '-e', f'HTTP_PROXY={proxy_url}',
            '-e', f'HTTPS_PROXY={proxy_url}',
            '-e', 'NO_PROXY=localhost,127.0.0.1,::1',
            '-e', f'http_proxy={proxy_url}',
            '-e', f'https_proxy={proxy_url}',
            '-e', 'no_proxy=localhost,127.0.0.1,::1',
            # CA bundle env vars — set here so docker exec sessions inherit them
            '-e', f'REQUESTS_CA_BUNDLE={ca_bundle}',
            '-e', f'SSL_CERT_FILE={ca_bundle}',
            '-e', f'CURL_CA_BUNDLE={ca_bundle}',
            '-e', f'NODE_EXTRA_CA_CERTS={ca_bundle}',
            # Mounts
            '-v', f'{self.workspace}:/mnt/workspace:ro',
            '-v', f'{self.config_dir}:/mnt/config:ro',
        ]

        if self.session_dir:
            repo_dir = self.session_dir / 'repo'
            repo_dir.mkdir(parents=True, exist_ok=True)
            cmd += ['-v', f'{repo_dir}:/work/repo']
            cmd += ['-v', f'{self.session_dir}:/mnt/session']

        if self.network:
            if self.runtime == 'apple':
                print(
                    "Warning: vibedom.yml 'network:' is not supported with apple/container — "
                    "ignored. Connect to host services via host.docker.internal instead.",
                    file=sys.stderr,
                )
            else:
                cmd += ['--network', self.network]

        # Claude/OpenCode config - shared persistent volume across all workspaces
        cmd += ['-v', 'vibedom-claude-config:/root/.claude']

        cmd.append(image)

        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            self._proxy.stop()
            raise RuntimeError(
                f"Failed to start VM container '{self.container_name}': {e}"
            ) from e
        except FileNotFoundError:
            self._proxy.stop()
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
                    [self.runtime_cmd, 'stop', self.container_name],
                    capture_output=True,
                )
                subprocess.run(
                    [self.runtime_cmd, 'delete', '--force', self.container_name],
                    capture_output=True,
                )
            else:
                subprocess.run(
                    [self.runtime_cmd, 'rm', '-f', self.container_name],
                    capture_output=True,
                )
        except FileNotFoundError:
            pass  # Runtime not installed

        if self._proxy:
            self._proxy.stop()
            self._proxy = None

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
