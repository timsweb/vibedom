# Host Proxy and Project Image Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move mitmproxy from inside the container to the host, then use that foundation to support project-specific base images (e.g. `wapi-php-fpm`) via a `vibedom.yml` config file, enabling Claude to run artisan commands and access the project's docker network.

**Architecture:** mitmproxy runs as a host process managed by a new `ProxyManager` class, one instance per session on an OS-assigned port (no hardcoded ports). The container receives `HTTP_PROXY=http://host.docker.internal:<port>` and a mounted CA cert. A `vibedom.yml` in the workspace root optionally specifies a `base_image` and docker `network`; when present, `vibedom run` builds a thin vibedom layer on top of the project image and joins the specified network.

**Tech Stack:** Python (subprocess, socket), mitmproxy (host-installed via pyproject.toml), Click CLI, Docker, PyYAML (already a dependency)

---

## Background reading

Before starting, read these files:
- `lib/vibedom/vm.py` — VMManager, especially `start()` and `stop()`
- `lib/vibedom/session.py` — SessionState dataclass
- `lib/vibedom/container/mitmproxy_addon.py` — proxy addon (paths currently hardcoded to container paths)
- `lib/vibedom/container/startup.sh` — container entrypoint (currently starts mitmproxy inside container)
- `lib/vibedom/container/Dockerfile.alpine` — base image (currently installs mitmproxy)
- `lib/vibedom/cli.py` — `run`, `stop`, `reload_whitelist` commands
- `pyproject.toml` — dependencies

---

## Task 1: Add mitmproxy as a host dependency

mitmproxy needs to move from the container to the host. Add it to pyproject.toml so pipx installs it alongside vibedom.

**Files:**
- Modify: `pyproject.toml`

**Step 1: Write a failing test**

```python
# tests/test_proxy_manager.py
def test_mitmdump_available():
    """mitmdump must be available on PATH when vibedom is installed."""
    import shutil
    assert shutil.which('mitmdump') is not None, \
        "mitmdump not found — add mitmproxy to pyproject.toml dependencies"
```

**Step 2: Run to verify it fails**

```bash
source .venv/bin/activate
pytest tests/test_proxy_manager.py::test_mitmdump_available -v
```

Expected: FAIL — `mitmdump not found`

**Step 3: Add mitmproxy to dependencies**

```toml
# pyproject.toml
dependencies = [
    "click>=8.1.0",
    "pyyaml>=6.0",
    "mitmproxy>=11.0",
]
```

**Step 4: Install and verify**

```bash
pip install -e .
pytest tests/test_proxy_manager.py::test_mitmdump_available -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add mitmproxy as host dependency"
```

---

## Task 2: ProxyManager — start/stop mitmproxy on the host

Create `lib/vibedom/proxy.py` with a `ProxyManager` class that starts mitmdump as a host process on an OS-assigned port (avoids all port conflicts) and stops it cleanly.

**Files:**
- Create: `lib/vibedom/proxy.py`
- Modify: `tests/test_proxy_manager.py`

**Step 1: Write failing tests**

```python
# tests/test_proxy_manager.py
import socket
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
from vibedom.proxy import ProxyManager


def test_find_free_port_returns_usable_port():
    """OS-assigned port should be bindable."""
    from vibedom.proxy import _find_free_port
    port = _find_free_port()
    assert isinstance(port, int)
    assert 1024 < port < 65535


def test_proxy_manager_start_returns_port(tmp_path):
    """start() should launch mitmdump and return the port."""
    session_dir = tmp_path / 'session'
    session_dir.mkdir()
    config_dir = tmp_path / 'config'
    config_dir.mkdir()

    manager = ProxyManager(session_dir=session_dir, config_dir=config_dir)

    with patch('subprocess.Popen') as mock_popen:
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        with patch('vibedom.proxy._wait_for_proxy', return_value=True):
            port = manager.start()

    assert isinstance(port, int)
    assert mock_popen.called
    cmd = mock_popen.call_args[0][0]
    assert 'mitmdump' in cmd[0]
    assert '--listen-port' in cmd
    assert str(port) in cmd


def test_proxy_manager_stop_terminates_process(tmp_path):
    """stop() should terminate the mitmdump process."""
    session_dir = tmp_path / 'session'
    session_dir.mkdir()
    config_dir = tmp_path / 'config'
    config_dir.mkdir()

    manager = ProxyManager(session_dir=session_dir, config_dir=config_dir)

    with patch('subprocess.Popen') as mock_popen:
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        with patch('vibedom.proxy._wait_for_proxy', return_value=True):
            manager.start()

        manager.stop()
        assert mock_proc.terminate.called


def test_proxy_manager_reload_sends_sighup(tmp_path):
    """reload() should send SIGHUP to the mitmdump process."""
    import signal as signal_module
    session_dir = tmp_path / 'session'
    session_dir.mkdir()
    config_dir = tmp_path / 'config'
    config_dir.mkdir()

    manager = ProxyManager(session_dir=session_dir, config_dir=config_dir)

    with patch('subprocess.Popen') as mock_popen:
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        with patch('vibedom.proxy._wait_for_proxy', return_value=True):
            manager.start()

        manager.reload()
        mock_proc.send_signal.assert_called_once_with(signal_module.SIGHUP)


def test_proxy_manager_passes_paths_as_env(tmp_path):
    """mitmdump should receive config paths via environment variables."""
    session_dir = tmp_path / 'session'
    session_dir.mkdir()
    config_dir = tmp_path / 'config'
    config_dir.mkdir()

    manager = ProxyManager(session_dir=session_dir, config_dir=config_dir)

    with patch('subprocess.Popen') as mock_popen:
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        with patch('vibedom.proxy._wait_for_proxy', return_value=True):
            manager.start()

    env = mock_popen.call_args[1]['env']
    assert 'VIBEDOM_WHITELIST_PATH' in env
    assert 'VIBEDOM_NETWORK_LOG_PATH' in env
    assert 'VIBEDOM_GITLEAKS_CONFIG' in env
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_proxy_manager.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'vibedom.proxy'`

**Step 3: Implement ProxyManager**

```python
# lib/vibedom/proxy.py
"""Host-based mitmproxy process management."""

import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional


def _find_free_port() -> int:
    """Ask the OS for an available port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def _wait_for_proxy(port: int, timeout: int = 10) -> bool:
    """Poll until mitmproxy is accepting connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


class ProxyManager:
    """Manages a host-side mitmproxy process for one session."""

    def __init__(self, session_dir: Path, config_dir: Path):
        self.session_dir = session_dir
        self.config_dir = config_dir
        self._process: Optional[subprocess.Popen] = None
        self.port: Optional[int] = None

    @property
    def pid(self) -> Optional[int]:
        return self._process.pid if self._process else None

    def start(self) -> int:
        """Start mitmdump on the host. Returns the port it's listening on."""
        mitmdump = shutil.which('mitmdump')
        if not mitmdump:
            raise RuntimeError(
                "mitmdump not found. Reinstall vibedom: "
                "pipx install --force git+https://github.com/timsweb/vibedom.git"
            )

        self.port = _find_free_port()

        addon_path = Path(__file__).parent / 'container' / 'mitmproxy_addon.py'
        conf_dir = self.config_dir / 'mitmproxy'
        conf_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.update({
            'VIBEDOM_WHITELIST_PATH': str(self.config_dir / 'trusted_domains.txt'),
            'VIBEDOM_NETWORK_LOG_PATH': str(self.session_dir / 'network.jsonl'),
            'VIBEDOM_GITLEAKS_CONFIG': str(self.config_dir / 'gitleaks.toml'),
        })

        log_path = self.session_dir / 'mitmproxy.log'
        self._process = subprocess.Popen(
            [
                mitmdump,
                '--listen-port', str(self.port),
                '--set', f'confdir={conf_dir}',
                '--mode', 'regular',
                '-q',
                '-s', str(addon_path),
            ],
            env=env,
            stdout=open(log_path, 'w'),
            stderr=subprocess.STDOUT,
        )

        if not _wait_for_proxy(self.port):
            self._process.terminate()
            raise RuntimeError(
                f"mitmproxy failed to start on port {self.port}. "
                f"Check {log_path}"
            )

        return self.port

    def stop(self) -> None:
        """Terminate the mitmdump process."""
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
            self.port = None

    def reload(self) -> None:
        """Send SIGHUP to reload the whitelist."""
        if self._process:
            self._process.send_signal(signal.SIGHUP)

    @property
    def ca_cert_path(self) -> Optional[Path]:
        """Path to the mitmproxy CA cert (exists after start())."""
        conf_dir = self.config_dir / 'mitmproxy'
        cert = conf_dir / 'mitmproxy-ca-cert.pem'
        return cert if cert.exists() else None
```

**Step 4: Run tests**

```bash
pytest tests/test_proxy_manager.py -v
```

Expected: All PASS

**Step 5: Commit**

```bash
git add lib/vibedom/proxy.py tests/test_proxy_manager.py
git commit -m "feat: add ProxyManager for host-based mitmproxy"
```

---

## Task 3: Update mitmproxy_addon.py to read paths from env vars

The addon currently reads hardcoded container paths (`/mnt/config/...`, `/mnt/session/...`). Update it to read from environment variables so it works both as a host process and (for backwards compat) falls back to container paths.

**Files:**
- Modify: `lib/vibedom/container/mitmproxy_addon.py`

**Step 1: Write failing test**

```python
# tests/test_mitmproxy_addon.py — add to existing file
def test_addon_reads_whitelist_from_env(tmp_path, monkeypatch):
    """VibedomProxy should read whitelist path from VIBEDOM_WHITELIST_PATH env var."""
    whitelist = tmp_path / 'domains.txt'
    whitelist.write_text('example.com\n')
    monkeypatch.setenv('VIBEDOM_WHITELIST_PATH', str(whitelist))

    from mitmproxy_addon import VibedomProxy
    proxy = VibedomProxy()
    assert 'example.com' in proxy.whitelist


def test_addon_reads_network_log_from_env(tmp_path, monkeypatch):
    """VibedomProxy should write network log to VIBEDOM_NETWORK_LOG_PATH."""
    log_path = tmp_path / 'network.jsonl'
    monkeypatch.setenv('VIBEDOM_NETWORK_LOG_PATH', str(log_path))
    monkeypatch.setenv('VIBEDOM_WHITELIST_PATH', str(tmp_path / 'domains.txt'))

    from mitmproxy_addon import VibedomProxy
    proxy = VibedomProxy()
    assert proxy.network_log_path == log_path
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_mitmproxy_addon.py::test_addon_reads_whitelist_from_env \
       tests/test_mitmproxy_addon.py::test_addon_reads_network_log_from_env -v
```

Expected: FAIL

**Step 3: Update addon to use env vars**

Replace the hardcoded paths at the top of `VibedomProxy.__init__` and `load_whitelist`:

```python
import os

class VibedomProxy:
    def __init__(self):
        self.whitelist = self.load_whitelist()
        network_log = os.environ.get(
            'VIBEDOM_NETWORK_LOG_PATH', '/mnt/session/network.jsonl'
        )
        self.network_log_path = Path(network_log)
        self.network_log_path.parent.mkdir(parents=True, exist_ok=True)

        gitleaks_config = os.environ.get(
            'VIBEDOM_GITLEAKS_CONFIG',
            str(Path(__file__).parent / 'gitleaks.toml')
        )
        config_path = gitleaks_config if Path(gitleaks_config).exists() else None
        self.scrubber = DLPScrubber(gitleaks_config=config_path)
        signal.signal(signal.SIGHUP, self._reload_whitelist)

    def load_whitelist(self) -> set:
        whitelist_path = Path(
            os.environ.get('VIBEDOM_WHITELIST_PATH', '/mnt/config/trusted_domains.txt')
        )
        if not whitelist_path.exists():
            return set()
        domains = set()
        with open(whitelist_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    domains.add(line.lower())
        return domains
```

**Step 4: Run tests**

```bash
pytest tests/test_mitmproxy_addon.py -v
```

Expected: All PASS

**Step 5: Commit**

```bash
git add lib/vibedom/container/mitmproxy_addon.py tests/test_mitmproxy_addon.py
git commit -m "feat: mitmproxy addon reads paths from env vars"
```

---

## Task 4: Update SessionState to store proxy port and pid

**Files:**
- Modify: `lib/vibedom/session.py`
- Modify: `tests/test_session_state.py`

**Step 1: Write failing test**

```python
# tests/test_session_state.py — add to existing tests
def test_session_state_stores_proxy_fields(tmp_path):
    """SessionState should persist proxy_port and proxy_pid."""
    state = SessionState.create(
        session_id='myapp-happy-turing',
        workspace=tmp_path / 'myapp',
        runtime='docker',
        container_name='vibedom-myapp',
    )
    state.proxy_port = 54321
    state.proxy_pid = 99999
    state.save(tmp_path)

    loaded = SessionState.load(tmp_path)
    assert loaded.proxy_port == 54321
    assert loaded.proxy_pid == 99999
```

**Step 2: Run to verify it fails**

```bash
pytest tests/test_session_state.py::test_session_state_stores_proxy_fields -v
```

Expected: FAIL — `AttributeError: proxy_port`

**Step 3: Add fields to SessionState**

In `lib/vibedom/session.py`, add to the `SessionState` dataclass:

```python
@dataclass
class SessionState:
    session_id: str
    workspace: str
    runtime: str
    container_name: str
    status: str = 'running'
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    bundle_path: Optional[str] = None
    proxy_port: Optional[int] = None   # add this
    proxy_pid: Optional[int] = None    # add this
```

**Step 4: Run tests**

```bash
pytest tests/test_session_state.py -v
```

Expected: All PASS

**Step 5: Commit**

```bash
git add lib/vibedom/session.py tests/test_session_state.py
git commit -m "feat: add proxy_port and proxy_pid to SessionState"
```

---

## Task 5: Update startup.sh — remove mitmproxy, install CA cert from mount

The container no longer starts mitmproxy. Instead it installs the CA cert generated by the host proxy (mounted at `/mnt/config/mitmproxy/mitmproxy-ca-cert.pem`).

**Files:**
- Modify: `lib/vibedom/container/startup.sh`

No unit test for shell scripts — verify manually after Task 9.

**Step 1: Replace mitmproxy section in startup.sh**

Remove this entire block from `startup.sh`:

```bash
# Start mitmproxy (using mitmdump for non-interactive mode)
echo "Starting mitmproxy..."
mkdir -p /var/log/vibedom
mitmdump \
    --mode regular \
    --listen-port 8080 \
    --set confdir=/tmp/mitmproxy \
    -s /mnt/config/mitmproxy_addon.py \
    > /var/log/vibedom/mitmproxy.log 2>&1 &

# Wait for mitmproxy to generate certificate
sleep 2

# Install mitmproxy CA certificate
echo "Installing mitmproxy CA certificate..."
if [ -f /tmp/mitmproxy/mitmproxy-ca-cert.pem ]; then
    cp /tmp/mitmproxy/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/mitmproxy.crt
    update-ca-certificates

    # Also set environment variables for tools that don't use system certs
    export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
    export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
    export CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
fi
```

Replace with:

```bash
# Install vibedom proxy CA certificate (generated by host-side mitmproxy)
echo "Installing vibedom CA certificate..."
CA_CERT=/mnt/config/mitmproxy/mitmproxy-ca-cert.pem
if [ -f "$CA_CERT" ]; then
    mkdir -p /usr/local/share/ca-certificates
    cp "$CA_CERT" /usr/local/share/ca-certificates/vibedom-ca.crt
    update-ca-certificates 2>/dev/null || true
    export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
    export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
    export CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
    export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
    echo "CA certificate installed"
else
    echo "Warning: CA cert not found at $CA_CERT"
fi
```

Also update the proxy log line (it no longer starts mitmproxy but the env vars are still set by the container runtime):

```bash
echo "Proxy: HTTP_PROXY=$HTTP_PROXY"
```

**Step 2: Commit**

```bash
git add lib/vibedom/container/startup.sh
git commit -m "feat: startup.sh installs host CA cert instead of starting mitmproxy"
```

---

## Task 6: Update Dockerfile.alpine — remove mitmproxy

mitmproxy is no longer needed in the image.

**Files:**
- Modify: `lib/vibedom/container/Dockerfile.alpine`

**Step 1: Remove mitmproxy (and python/pip which were only needed for it)**

Change:

```dockerfile
RUN apk add --no-cache \
    bash \
    openssh \
    git \
    python3 \
    py3-pip \
    curl \
    sudo \
    rsync \
    diffutils \
    ca-certificates \
    ca-certificates-bundle \
    mitmproxy
```

To:

```dockerfile
RUN apk add --no-cache \
    bash \
    openssh \
    git \
    curl \
    sudo \
    rsync \
    diffutils \
    ca-certificates \
    ca-certificates-bundle
```

**Step 2: Rebuild image to verify it still builds**

```bash
vibedom init --runtime docker
```

Expected: Image builds successfully, faster than before (no mitmproxy download)

**Step 3: Commit**

```bash
git add lib/vibedom/container/Dockerfile.alpine
git commit -m "feat: remove mitmproxy from container image"
```

---

## Task 7: Add Dockerfile.layer for project base images

A template Dockerfile that builds a thin vibedom layer on top of any project image. It adds git (if not present) and the startup.sh entrypoint without assuming the base OS.

**Files:**
- Create: `lib/vibedom/container/Dockerfile.layer`

**Step 1: Create Dockerfile.layer**

```dockerfile
# Vibedom layer — built on top of a project's base image at runtime
# ARG BASE_IMAGE is passed by VMManager.build_project_image()
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

# Install git if not already present.
# Tries apt-get (Debian/Ubuntu) then apk (Alpine) — ignores failure if git already installed.
RUN command -v git >/dev/null 2>&1 || \
    (apt-get update -qq && apt-get install -y --no-install-recommends git ca-certificates 2>/dev/null) || \
    (apk add --no-cache git ca-certificates 2>/dev/null) || true

# Ensure CA cert directory exists (for update-ca-certificates in startup.sh)
RUN mkdir -p /usr/local/share/ca-certificates

# Create required vibedom mount points
RUN mkdir -p /mnt/workspace /work /mnt/config /mnt/session

# Copy vibedom startup script
COPY startup.sh /usr/local/bin/vibedom-startup.sh
RUN chmod +x /usr/local/bin/vibedom-startup.sh

CMD ["/usr/local/bin/vibedom-startup.sh"]
```

**Step 2: Commit**

```bash
git add lib/vibedom/container/Dockerfile.layer
git commit -m "feat: add Dockerfile.layer for project base images"
```

---

## Task 8: ProjectConfig — parse vibedom.yml

**Files:**
- Create: `lib/vibedom/project_config.py`
- Create: `tests/test_project_config.py`

**Step 1: Write failing tests**

```python
# tests/test_project_config.py
import pytest
from pathlib import Path
from vibedom.project_config import ProjectConfig


def test_project_config_loads_base_image(tmp_path):
    """Should parse base_image from vibedom.yml."""
    (tmp_path / 'vibedom.yml').write_text('base_image: wapi-php-fpm:latest\n')
    config = ProjectConfig.load(tmp_path)
    assert config.base_image == 'wapi-php-fpm:latest'


def test_project_config_loads_network(tmp_path):
    """Should parse network from vibedom.yml."""
    (tmp_path / 'vibedom.yml').write_text(
        'base_image: wapi-php-fpm:latest\nnetwork: wapi_shared\n'
    )
    config = ProjectConfig.load(tmp_path)
    assert config.network == 'wapi_shared'


def test_project_config_returns_none_if_no_file(tmp_path):
    """Should return None when no vibedom.yml present."""
    config = ProjectConfig.load(tmp_path)
    assert config is None


def test_project_config_optional_fields(tmp_path):
    """network is optional."""
    (tmp_path / 'vibedom.yml').write_text('base_image: myimage:latest\n')
    config = ProjectConfig.load(tmp_path)
    assert config.network is None


def test_project_config_rejects_unknown_fields(tmp_path):
    """Should raise ValueError for unrecognised fields."""
    (tmp_path / 'vibedom.yml').write_text('typo_field: oops\n')
    with pytest.raises(ValueError, match='Unknown'):
        ProjectConfig.load(tmp_path)
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_project_config.py -v
```

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement ProjectConfig**

```python
# lib/vibedom/project_config.py
"""Parse vibedom.yml project configuration."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

KNOWN_FIELDS = {'base_image', 'network'}


@dataclass
class ProjectConfig:
    """Project-specific vibedom configuration from vibedom.yml."""
    base_image: Optional[str] = None
    network: Optional[str] = None

    @classmethod
    def load(cls, workspace: Path) -> Optional['ProjectConfig']:
        """Load vibedom.yml from workspace root. Returns None if not present."""
        config_file = workspace / 'vibedom.yml'
        if not config_file.exists():
            return None

        with open(config_file) as f:
            data = yaml.safe_load(f) or {}

        unknown = set(data.keys()) - KNOWN_FIELDS
        if unknown:
            raise ValueError(f"Unknown vibedom.yml field(s): {', '.join(sorted(unknown))}")

        return cls(
            base_image=data.get('base_image'),
            network=data.get('network'),
        )
```

**Step 4: Run tests**

```bash
pytest tests/test_project_config.py -v
```

Expected: All PASS

**Step 5: Commit**

```bash
git add lib/vibedom/project_config.py tests/test_project_config.py
git commit -m "feat: add ProjectConfig for vibedom.yml"
```

---

## Task 9: Update VMManager — host proxy, project image, network

This is the main integration task. VMManager needs to:
1. Start/stop ProxyManager alongside the container
2. Set `HTTP_PROXY=http://host.docker.internal:<port>` on the container
3. Mount the mitmproxy conf dir (for CA cert)
4. Optionally build a project image layer
5. Optionally join a docker network

**Files:**
- Modify: `lib/vibedom/vm.py`
- Modify: `tests/test_vm.py`

**Step 1: Write failing tests**

```python
# tests/test_vm.py — add these tests
from unittest.mock import patch, MagicMock, call
from pathlib import Path
from vibedom.vm import VMManager


def test_vm_start_uses_host_proxy(tmp_path):
    """VMManager.start() should start ProxyManager and pass port to container."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    config_dir = tmp_path / 'config'
    config_dir.mkdir()
    session_dir = tmp_path / 'session'
    session_dir.mkdir()

    vm = VMManager(workspace, config_dir, session_dir, runtime='docker')

    with patch('vibedom.vm.ProxyManager') as mock_proxy_cls:
        mock_proxy = MagicMock()
        mock_proxy.start.return_value = 54321
        mock_proxy.ca_cert_path = tmp_path / 'cert.pem'
        mock_proxy_cls.return_value = mock_proxy

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            vm.start()

        assert mock_proxy.start.called
        cmd = ' '.join(mock_run.call_args_list[0][0][0])
        assert 'host.docker.internal' in cmd
        assert '54321' in cmd


def test_vm_start_with_project_network(tmp_path):
    """VMManager.start() should add --network flag when network specified."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    vm = VMManager(workspace, tmp_path / 'config', tmp_path / 'session',
                   runtime='docker', network='wapi_shared')

    with patch('vibedom.vm.ProxyManager') as mock_proxy_cls:
        mock_proxy = MagicMock()
        mock_proxy.start.return_value = 54321
        mock_proxy.ca_cert_path = None
        mock_proxy_cls.return_value = mock_proxy

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            vm.start()

        cmd = ' '.join(mock_run.call_args_list[0][0][0])
        assert '--network' in cmd
        assert 'wapi_shared' in cmd


def test_vm_stop_stops_proxy(tmp_path):
    """VMManager.stop() should stop the ProxyManager."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    vm = VMManager(workspace, tmp_path / 'config', tmp_path / 'session',
                   runtime='docker')

    mock_proxy = MagicMock()
    vm._proxy = mock_proxy

    with patch('subprocess.run', return_value=MagicMock(returncode=0)):
        vm.stop()

    assert mock_proxy.stop.called
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_vm.py::test_vm_start_uses_host_proxy \
       tests/test_vm.py::test_vm_start_with_project_network \
       tests/test_vm.py::test_vm_stop_stops_proxy -v
```

Expected: FAIL

**Step 3: Update VMManager**

Add `network` and `base_image` to `__init__`, integrate `ProxyManager`, update `start()` and `stop()`:

```python
# lib/vibedom/vm.py — full updated __init__ and start/stop

from vibedom.proxy import ProxyManager  # add to imports

class VMManager:
    def __init__(self, workspace, config_dir, session_dir=None,
                 runtime=None, network=None, base_image=None):
        self.workspace = workspace.resolve()
        self.config_dir = config_dir.resolve()
        self.session_dir = session_dir.resolve() if session_dir else None
        self.container_name = f'vibedom-{workspace.name}'
        self.runtime, self.runtime_cmd = self._detect_runtime(runtime)
        self.network = network
        self.base_image = base_image  # None = use vibedom-alpine
        self._proxy: Optional[ProxyManager] = None

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

    def start(self) -> None:
        self.stop()

        # Start host proxy
        self._proxy = ProxyManager(
            session_dir=self.session_dir,
            config_dir=self.config_dir,
        )
        proxy_port = self._proxy.start()

        # Determine image (builds project layer if needed)
        image = self._image_name()

        # Mount the mitmproxy conf dir so container can install CA cert
        conf_dir = self.config_dir / 'mitmproxy'
        conf_dir.mkdir(parents=True, exist_ok=True)

        detach_flag = '--detach' if self.runtime == 'apple' else '-d'
        proxy_host = f'http://host.docker.internal:{proxy_port}'

        cmd = [
            self.runtime_cmd, 'run',
            detach_flag,
            '--name', self.container_name,
            '--add-host', 'host.docker.internal:host-gateway',
            # Proxy env vars
            '-e', f'HTTP_PROXY={proxy_host}',
            '-e', f'HTTPS_PROXY={proxy_host}',
            '-e', 'NO_PROXY=localhost,127.0.0.1,::1',
            '-e', f'http_proxy={proxy_host}',
            '-e', f'https_proxy={proxy_host}',
            '-e', 'no_proxy=localhost,127.0.0.1,::1',
            # Mounts
            '-v', f'{self.workspace}:/mnt/workspace:ro',
            '-v', f'{self.config_dir}:/mnt/config:ro',
            '-v', f'{conf_dir}:/mnt/config/mitmproxy:ro',
        ]

        if self.session_dir:
            repo_dir = self.session_dir / 'repo'
            repo_dir.mkdir(parents=True, exist_ok=True)
            cmd += ['-v', f'{repo_dir}:/work/repo']
            cmd += ['-v', f'{self.session_dir}:/mnt/session']

        if self.network:
            cmd += ['--network', self.network]

        cmd += ['-v', 'vibedom-claude-config:/root/.claude']
        cmd.append(image)

        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            self._proxy.stop()
            raise RuntimeError(
                f"Failed to start VM container '{self.container_name}': {e}"
            ) from e

        # Wait for VM ready
        for _ in range(60):
            result = subprocess.run(
                [self.runtime_cmd, 'exec', self.container_name,
                 'test', '-f', '/tmp/.vm-ready'],
                capture_output=True, check=False,
            )
            if result.returncode == 0:
                return
            time.sleep(1)
        raise RuntimeError("VM did not become ready in time")

    def stop(self) -> None:
        subprocess.run(
            [self.runtime_cmd, 'stop', self.container_name],
            capture_output=True, check=False,
        )
        subprocess.run(
            [self.runtime_cmd, 'rm', self.container_name],
            capture_output=True, check=False,
        )
        if self._proxy:
            self._proxy.stop()
            self._proxy = None
```

**Step 4: Run tests**

```bash
pytest tests/test_vm.py -v
```

Expected: New tests PASS, pre-existing Docker-dependent tests may still fail in sandbox (that's fine)

**Step 5: Commit**

```bash
git add lib/vibedom/vm.py tests/test_vm.py
git commit -m "feat: VMManager uses host ProxyManager, supports base_image and network"
```

---

## Task 10: Update cli.py — read vibedom.yml, store proxy info, fix reload-whitelist

Three changes to `cli.py`:

1. `vibedom run` reads `vibedom.yml` and passes `base_image`/`network` to VMManager
2. `vibedom run` stores `proxy_port` and `proxy_pid` in session state
3. `vibedom reload-whitelist` sends SIGHUP to the host process PID (not docker exec)

**Files:**
- Modify: `lib/vibedom/cli.py`
- Modify: `tests/test_cli.py`

**Step 1: Write failing tests**

```python
# tests/test_cli.py — add these

def test_run_reads_vibedom_yml(tmp_path):
    """vibedom run should pass base_image and network from vibedom.yml to VMManager."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    (workspace / 'vibedom.yml').write_text(
        'base_image: myapp-php:latest\nnetwork: myapp_net\n'
    )

    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        with patch('vibedom.cli.scan_workspace', return_value=[]):
            with patch('vibedom.cli.review_findings', return_value=True):
                with patch('vibedom.cli.VMManager') as mock_vm_cls:
                    mock_vm_cls._detect_runtime.return_value = ('docker', 'docker')
                    mock_vm = MagicMock()
                    mock_vm_cls.return_value = mock_vm

                    result = runner.invoke(main, ['run', str(workspace)])

    call_kwargs = mock_vm_cls.call_args[1]
    assert call_kwargs.get('base_image') == 'myapp-php:latest'
    assert call_kwargs.get('network') == 'myapp_net'


def test_reload_whitelist_sends_sighup_via_pid(tmp_path):
    """reload-whitelist should send SIGHUP to the host proxy PID from session state."""
    import json, signal as signal_module
    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260220-120000-000000'
    session_dir.mkdir(parents=True)

    state = {
        'session_id': 'myapp-happy-turing',
        'workspace': str(workspace),
        'runtime': 'docker',
        'container_name': 'vibedom-myapp',
        'status': 'running',
        'started_at': '2026-02-20T10:00:00',
        'ended_at': None,
        'bundle_path': None,
        'proxy_port': 54321,
        'proxy_pid': 99999,
    }
    (session_dir / 'state.json').write_text(json.dumps(state))

    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        with patch('os.kill') as mock_kill:
            result = runner.invoke(main, ['reload-whitelist'])

    assert result.exit_code == 0
    mock_kill.assert_called_once_with(99999, signal_module.SIGHUP)
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_cli.py::test_run_reads_vibedom_yml \
       tests/test_cli.py::test_reload_whitelist_sends_sighup_via_pid -v
```

Expected: FAIL

**Step 3: Update `vibedom run` in cli.py**

Add `from vibedom.project_config import ProjectConfig` to imports.

Update the `run` command to read `vibedom.yml` and pass it to VMManager:

```python
@main.command()
@click.argument('workspace', type=click.Path(exists=True))
@click.option('--runtime', '-r', ...)
def run(workspace: str, runtime: str) -> None:
    workspace_path = Path(workspace).resolve()
    # ... existing gitleaks scan ...

    # Read project config if present
    project_config = ProjectConfig.load(workspace_path)

    config_dir = Path.home() / '.vibedom'
    logs_dir = Path.home() / '.vibedom' / 'logs'
    session = Session.start(workspace_path, runtime=runtime or None)

    vm = VMManager(
        workspace=workspace_path,
        config_dir=config_dir,
        session_dir=session.session_dir,
        runtime=session.state.runtime,
        network=project_config.network if project_config else None,
        base_image=project_config.base_image if project_config else None,
    )
    vm.start()

    # Store proxy info in session state
    if vm._proxy:
        session.state.proxy_port = vm._proxy.port
        session.state.proxy_pid = vm._proxy.pid
        session.state.save(session.session_dir)

    # ... rest of run command (display session ID, hints) ...
```

**Step 4: Update `reload-whitelist` in cli.py**

Replace the current docker-exec SIGHUP approach with `os.kill` to the host PID:

```python
import os
import signal as signal_module

@main.command('reload-whitelist')
def reload_whitelist() -> None:
    """Reload domain whitelist in all running containers."""
    logs_dir = Path.home() / '.vibedom' / 'logs'
    registry = SessionRegistry(logs_dir)
    running = registry.running()

    if not running:
        click.echo("No running sessions found")
        return

    failed = 0
    for session in running:
        if not session.state.proxy_pid:
            click.secho(
                f"⚠️  No proxy PID for {session.display_name} "
                f"(started with older vibedom?)", fg='yellow'
            )
            failed += 1
            continue
        try:
            os.kill(session.state.proxy_pid, signal_module.SIGHUP)
            click.echo(f"✅ Reloaded whitelist for {session.display_name}")
        except ProcessLookupError:
            click.secho(
                f"❌ Proxy process not found for {session.display_name}", fg='red'
            )
            failed += 1

    if failed:
        sys.exit(1)
```

**Step 5: Run all CLI tests**

```bash
pytest tests/test_cli.py -v
```

Expected: All PASS

**Step 6: Commit**

```bash
git add lib/vibedom/cli.py tests/test_cli.py
git commit -m "feat: run reads vibedom.yml, reload-whitelist uses host PID"
```

---

## Task 11: Update docs

**Files:**
- Modify: `docs/USAGE.md`
- Modify: `CLAUDE.md`

**Step 1: Add vibedom.yml section to USAGE.md**

Add after the "Running a Session" section:

```markdown
## Project Integration (vibedom.yml)

For projects with existing Docker images and shared networks, add a `vibedom.yml`
to your workspace root:

    ```yaml
    base_image: wapi-php-fpm:latest   # use your project's image instead of Alpine
    network: wapi_shared_network      # join this docker network (for DB, Redis, etc.)
    ```

`vibedom run` will detect this file and:
1. Build a thin vibedom layer on top of your `base_image`
2. Connect the container to `network` (so artisan can reach the database)

The read-only workspace mount, git clone to `/work/repo`, and git bundle
workflow are unchanged — your original files remain protected.
```

**Step 2: Update CLAUDE.md component list**

Update the Network Control entry and add ProxyManager:

```markdown
2. **Network Control** (`lib/vibedom/proxy.py`, `lib/vibedom/container/mitmproxy_addon.py`)
   - ProxyManager starts mitmproxy as a HOST process (not inside the container)
   - One process per session on an OS-assigned port (stored in state.json)
   - Container receives HTTP_PROXY pointing to host.docker.internal:<port>
   - CA cert mounted into container from host mitmproxy conf dir
   - Whitelist reload via SIGHUP to host PID (no docker exec needed)
```

**Step 3: Commit**

```bash
git add docs/USAGE.md CLAUDE.md
git commit -m "docs: document host proxy architecture and vibedom.yml"
```

---

## Task 12: Run full test suite and push

**Step 1: Run all unit tests**

```bash
source .venv/bin/activate
pytest tests/ --ignore=tests/test_vm.py --ignore=tests/test_git_workflow.py \
       --ignore=tests/test_https_proxy.py --ignore=tests/test_proxy.py \
       --ignore=tests/test_integration.py -v
```

Expected: All PASS

**Step 2: Bump version**

```toml
# pyproject.toml
version = "0.2.0"
```

**Step 3: Commit and push**

```bash
git add pyproject.toml
git commit -m "chore: bump version to 0.2.0"
git push
```
