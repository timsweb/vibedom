# Apple/Container Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add apple/container as the preferred container runtime, with Docker as fallback, so vibedom uses hardware-isolated VMs on supported Macs.

**Architecture:** Extract container commands behind a runtime abstraction in `vm.py`. Detect which runtime is available (prefer apple/container, fall back to Docker). Both runtimes use the same `Dockerfile.alpine` image — no rename needed. The CLI's `stop --all` also needs runtime awareness.

**Tech Stack:** apple/container CLI (0.9.0+), Docker CLI (fallback), Alpine Linux ARM64

**Key facts about apple/container** (from [docs](https://github.com/apple/container)):
- Requires **macOS 26** (Tahoe) for full functionality. Limited support on macOS 15.
- Requires **Apple Silicon**.
- Uses lightweight VM per container (Virtualization.framework) — true hardware isolation.
- CLI: `container run`, `container exec`, `container stop`, `container delete`
- `container build` reads **`Dockerfile` first**, falls back to `Containerfile`. No rename needed.
- Mount syntax: `--volume src:dst` or `--mount type=bind,source=src,target=dst,readonly`
- Env vars: `-e KEY=VAL` (same as Docker)
- Detach: `--detach` (Docker uses `-d`, but also accepts `--detach`)
- Name: `--name <name>` (same as Docker)
- **No `--privileged` flag** — not needed since we dropped overlay FS for git workflow.
- Requires `container system start` before first use (launch agent).
- Stop: `container stop <name>`, Remove: `container delete --force <name>` (not `rm`).
- List: `container list --filter name=vibedom-` or `container list --all`.

---

### Task 1: Add Container Runtime Abstraction to VMManager

**Files:**
- Modify: `lib/vibedom/vm.py`
- Modify: `tests/test_vm.py`

**Context:** Currently `vm.py` hardcodes `docker` in every subprocess call. We need a runtime abstraction that picks the right command and flags. The key differences are:
- Docker: `docker rm -f` → apple/container: `container stop` + `container delete --force`
- Docker: `-d` → apple/container: `--detach`
- Docker: `--privileged` → apple/container: not needed (drop it for both runtimes — the git workflow doesn't need it)
- Docker: `-v src:dst:ro` → apple/container: `--volume src:dst:ro` (same syntax, different flag name also works)

**Step 1: Write failing test for runtime detection**

Add to `tests/test_vm.py`:

```python
from unittest.mock import patch

def test_detect_runtime_prefers_apple(test_workspace, test_config):
    """Should prefer apple/container when available."""
    with patch('shutil.which') as mock_which:
        mock_which.side_effect = lambda cmd: '/usr/local/bin/container' if cmd == 'container' else None
        vm = VMManager(test_workspace, test_config)
        assert vm.runtime == 'apple'
        assert vm.runtime_cmd == 'container'


def test_detect_runtime_falls_back_to_docker(test_workspace, test_config):
    """Should fall back to Docker when apple/container not available."""
    with patch('shutil.which') as mock_which:
        mock_which.side_effect = lambda cmd: '/usr/local/bin/docker' if cmd == 'docker' else None
        vm = VMManager(test_workspace, test_config)
        assert vm.runtime == 'docker'
        assert vm.runtime_cmd == 'docker'


def test_detect_runtime_raises_when_neither(test_workspace, test_config):
    """Should raise RuntimeError when no runtime found."""
    with patch('shutil.which', return_value=None):
        with pytest.raises(RuntimeError, match="No container runtime found"):
            VMManager(test_workspace, test_config)
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_vm.py::test_detect_runtime_prefers_apple tests/test_vm.py::test_detect_runtime_falls_back_to_docker tests/test_vm.py::test_detect_runtime_raises_when_neither -v`
Expected: FAIL (no `runtime` attribute on VMManager)

**Step 3: Implement runtime detection**

Replace the `VMManager.__init__` and add `_detect_runtime` in `lib/vibedom/vm.py`:

```python
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
        self.runtime, self.runtime_cmd = self._detect_runtime()

    @staticmethod
    def _detect_runtime() -> tuple[str, str]:
        """Detect available container runtime.

        Returns:
            Tuple of (runtime_name, command) — e.g. ('apple', 'container')
        """
        if shutil.which('container'):
            return 'apple', 'container'
        if shutil.which('docker'):
            return 'docker', 'docker'
        raise RuntimeError(
            "No container runtime found. Install apple/container (macOS 26+) or Docker."
        )
```

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_vm.py::test_detect_runtime_prefers_apple tests/test_vm.py::test_detect_runtime_falls_back_to_docker tests/test_vm.py::test_detect_runtime_raises_when_neither -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/vibedom/vm.py tests/test_vm.py
git commit -m "feat: add container runtime detection (apple/container preferred, Docker fallback)"
```

---

### Task 2: Update start() for Runtime Abstraction

**Files:**
- Modify: `lib/vibedom/vm.py`
- Modify: `tests/test_vm.py`

**Context:** The `start()` method currently hardcodes `docker run` with Docker-specific flags. We need to build the command dynamically based on `self.runtime`. Key differences:
- Docker uses `-d`, apple/container uses `--detach`
- Docker uses `--privileged` — **drop this for both** (no longer needed)
- Mount syntax is the same (`-v src:dst:ro` works for both)
- Env var syntax is the same (`-e KEY=VAL`)
- Image name stays `vibedom-alpine:latest` for both

**Step 1: Write failing test for start command construction**

Add to `tests/test_vm.py`:

```python
def test_start_uses_apple_runtime(test_workspace, test_config):
    """start() should use 'container' command when runtime is apple."""
    with patch('shutil.which') as mock_which:
        mock_which.side_effect = lambda cmd: '/usr/local/bin/container' if cmd == 'container' else None
        vm = VMManager(test_workspace, test_config)

    with patch('subprocess.run') as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        try:
            vm.start()
        except RuntimeError:
            pass  # May fail on readiness check, that's ok

        # First call should be stop (container delete), second should be container run
        calls = mock_run.call_args_list
        # Find the 'run' call
        run_call = next(c for c in calls if 'run' in c[0][0])
        assert run_call[0][0][0] == 'container'
        assert '--detach' in run_call[0][0]
        assert '--privileged' not in run_call[0][0]


def test_start_uses_docker_runtime(test_workspace, test_config):
    """start() should use 'docker' command when runtime is docker."""
    with patch('shutil.which') as mock_which:
        mock_which.side_effect = lambda cmd: '/usr/local/bin/docker' if cmd == 'docker' else None
        vm = VMManager(test_workspace, test_config)

    with patch('subprocess.run') as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        try:
            vm.start()
        except RuntimeError:
            pass

        calls = mock_run.call_args_list
        run_call = next(c for c in calls if 'run' in c[0][0])
        assert run_call[0][0][0] == 'docker'
        assert '-d' in run_call[0][0]
        assert '--privileged' not in run_call[0][0]
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_vm.py::test_start_uses_apple_runtime tests/test_vm.py::test_start_uses_docker_runtime -v`
Expected: FAIL

**Step 3: Rewrite start() method**

Replace the `start()` method in `lib/vibedom/vm.py`:

```python
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

        # Wait for VM to be ready
        for _ in range(10):
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
            f"VM '{self.container_name}' failed to become ready within 10 seconds"
        )
```

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_vm.py -k "detect_runtime or start_uses" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/vibedom/vm.py tests/test_vm.py
git commit -m "feat: update start() for runtime-agnostic container launch

- Use detected runtime command (container/docker)
- Drop --privileged (no longer needed with git workflow)
- Use --detach for apple/container, -d for Docker
- Same -v mount syntax works for both runtimes"
```

---

### Task 3: Update stop() and exec() for Runtime Abstraction

**Files:**
- Modify: `lib/vibedom/vm.py`
- Modify: `tests/test_vm.py`

**Context:** `stop()` and `exec()` also hardcode `docker`. Key difference for stop: Docker uses `docker rm -f`, apple/container uses `container stop` then `container delete --force`.

**Step 1: Write failing tests**

Add to `tests/test_vm.py`:

```python
def test_stop_uses_apple_commands(test_workspace, test_config):
    """stop() should use 'container stop' + 'container delete' for apple runtime."""
    with patch('shutil.which') as mock_which:
        mock_which.side_effect = lambda cmd: '/usr/local/bin/container' if cmd == 'container' else None
        vm = VMManager(test_workspace, test_config)

    with patch('subprocess.run') as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        vm.stop()

        calls = [c[0][0] for c in mock_run.call_args_list]
        # Should call container stop then container delete
        assert calls[0][:2] == ['container', 'stop']
        assert calls[1][:2] == ['container', 'delete']


def test_stop_uses_docker_command(test_workspace, test_config):
    """stop() should use 'docker rm -f' for docker runtime."""
    with patch('shutil.which') as mock_which:
        mock_which.side_effect = lambda cmd: '/usr/local/bin/docker' if cmd == 'docker' else None
        vm = VMManager(test_workspace, test_config)

    with patch('subprocess.run') as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        vm.stop()

        calls = [c[0][0] for c in mock_run.call_args_list]
        assert calls[0] == ['docker', 'rm', '-f', vm.container_name]


def test_exec_uses_detected_runtime(test_workspace, test_config):
    """exec() should use detected runtime command."""
    with patch('shutil.which') as mock_which:
        mock_which.side_effect = lambda cmd: '/usr/local/bin/container' if cmd == 'container' else None
        vm = VMManager(test_workspace, test_config)

    with patch('subprocess.run') as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='hello', stderr=''
        )
        vm.exec(['echo', 'hello'])

        call_args = mock_run.call_args[0][0]
        assert call_args[:2] == ['container', 'exec']
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_vm.py -k "stop_uses or exec_uses" -v`
Expected: FAIL

**Step 3: Update stop() and exec()**

Replace `stop()` and `exec()` in `lib/vibedom/vm.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_vm.py -k "stop_uses or exec_uses or detect_runtime" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/vibedom/vm.py tests/test_vm.py
git commit -m "feat: update stop() and exec() for runtime abstraction

- apple/container: stop + delete --force (no rm command)
- Docker: rm -f (unchanged behavior)
- exec() uses detected runtime command"
```

---

### Task 4: Update CLI stop-all for Runtime Awareness

**Files:**
- Modify: `lib/vibedom/cli.py`
- Modify: `tests/test_cli.py` (if it exists and tests stop-all)

**Context:** The `stop` command with no workspace arg calls `docker ps` and `docker rm -f` directly. This needs runtime awareness too. We can reuse `VMManager._detect_runtime()` for this.

**Step 1: Read current CLI tests**

Check `tests/test_cli.py` to understand existing test patterns.

**Step 2: Update stop-all in cli.py**

Replace the stop-all block in `lib/vibedom/cli.py` (the `if workspace is None:` branch):

```python
    if workspace is None:
        # Stop all vibedom containers
        try:
            runtime, runtime_cmd = VMManager._detect_runtime()
        except RuntimeError as e:
            click.secho(f"❌ {e}", fg='red')
            sys.exit(1)

        try:
            if runtime == 'apple':
                result = subprocess.run(
                    ['container', 'list', '--all', '--format', '{{.Names}}'],
                    capture_output=True, text=True, check=True,
                )
            else:
                result = subprocess.run(
                    ['docker', 'ps', '-a', '--filter', 'name=vibedom-',
                     '--format', '{{.Names}}'],
                    capture_output=True, text=True, check=True,
                )

            containers = [
                name.strip() for name in result.stdout.split('\n')
                if name.strip() and name.strip().startswith('vibedom-')
            ]

            if not containers:
                click.echo("No vibedom containers running")
                return

            click.echo(f"Stopping {len(containers)} container(s)...")
            for name in containers:
                if runtime == 'apple':
                    subprocess.run(['container', 'stop', name], capture_output=True)
                    subprocess.run(['container', 'delete', '--force', name],
                                   capture_output=True)
                else:
                    subprocess.run(['docker', 'rm', '-f', name], capture_output=True)

            click.echo(f"✅ Stopped {len(containers)} container(s)")

        except subprocess.CalledProcessError as e:
            click.secho(f"❌ Error stopping containers: {e}", fg='red')
            sys.exit(1)
        return
```

**Step 3: Run existing CLI tests**

Run: `source .venv/bin/activate && pytest tests/test_cli.py -v`
Expected: PASS (no regressions)

**Step 4: Commit**

```bash
git add lib/vibedom/cli.py
git commit -m "feat: update CLI stop-all for runtime-agnostic container cleanup"
```

---

### Task 5: Update build.sh for Dual Runtime

**Files:**
- Modify: `vm/build.sh`

**Context:** `build.sh` currently hardcodes `docker build`. Both `container build` and `docker build` accept `-f Dockerfile.alpine` — no file rename needed. `container build` looks for `Dockerfile` first, then `Containerfile`.

**Step 1: Update build.sh**

Replace `vm/build.sh`:

```bash
#!/bin/bash
# Build Alpine Linux VM image for vibedom
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="vibedom-alpine"

# Detect container runtime
if command -v container &>/dev/null; then
    RUNTIME="apple/container"
    BUILD_CMD="container build"
elif command -v docker &>/dev/null; then
    RUNTIME="docker"
    BUILD_CMD="docker build"
else
    echo "Error: No container runtime found. Install apple/container (macOS 26+) or Docker."
    exit 1
fi

echo "Building VM image: $IMAGE_NAME (using $RUNTIME)"
$BUILD_CMD -t "$IMAGE_NAME:latest" -f "$SCRIPT_DIR/Dockerfile.alpine" "$SCRIPT_DIR"

echo "✅ VM image built successfully: $IMAGE_NAME:latest"
```

**Step 2: Verify script is valid**

Run: `bash -n vm/build.sh`
Expected: No errors (syntax check only)

**Step 3: Commit**

```bash
git add vm/build.sh
git commit -m "feat: update build.sh to detect and use available container runtime"
```

---

### Task 6: Drop --privileged Flag

**Files:**
- Modify: `lib/vibedom/vm.py` (already done in Task 2, verify here)
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CLAUDE.md`

**Context:** The `--privileged` flag was originally needed for overlay filesystem mounts and iptables. Both were removed: overlay FS replaced by git workflow, iptables replaced by explicit proxy. The flag is already dropped from `start()` in Task 2. This task cleans up documentation that still references it.

**Step 1: Search for --privileged references**

Run: `grep -rn "privileged" lib/ vm/ docs/ CLAUDE.md tests/`

Fix any remaining references. Expected locations:
- `CLAUDE.md` — mentions `--privileged` in architecture and security sections
- `docs/ARCHITECTURE.md` — may reference privileged mode
- `vm.py` — should already be clean from Task 2

**Step 2: Update documentation**

Remove or update all `--privileged` references to reflect the current state:
- Architecture: No longer requires privileged mode
- Security: Improved isolation (no privileged containers)
- Code review checklist: Remove "No `--privileged` additions without security review" (no longer relevant)

**Step 3: Commit**

```bash
git add CLAUDE.md docs/ARCHITECTURE.md
git commit -m "docs: remove --privileged references (no longer needed with git workflow)"
```

---

### Task 7: Update Documentation for Dual Runtime

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/USAGE.md`
- Modify: `CLAUDE.md`
- Modify: `docs/TESTING.md`

**Context:** Documentation currently says "Docker-based PoC" everywhere. Update to reflect the dual-runtime support with apple/container as the preferred runtime.

**Step 1: Update ARCHITECTURE.md**

Add a "Container Runtime" subsection to the VM Isolation section:

```markdown
### Container Runtime

Vibedom supports two container runtimes:

| | apple/container | Docker |
|---|---|---|
| **Isolation** | Hardware VM (Virtualization.framework) | Namespace-based |
| **macOS** | 26+ (Tahoe) | Any |
| **CPU** | Apple Silicon only | Any |
| **Security** | Full VM isolation per container | Shared kernel |
| **Status** | Preferred | Fallback |

Runtime is auto-detected at startup. apple/container is preferred when available.
Both runtimes use the same `Dockerfile.alpine` image.
```

**Step 2: Update USAGE.md**

Add after the Quick Start section:

```markdown
### Container Runtime

Vibedom auto-detects your container runtime:

- **apple/container** (preferred) — hardware-isolated VMs via Virtualization.framework. Requires macOS 26+ and Apple Silicon. Install from [github.com/apple/container](https://github.com/apple/container).
- **Docker** (fallback) — namespace-based containers. Works on any platform.

Before first use with apple/container, start the system service:
```bash
container system start
```
```

**Step 3: Update CLAUDE.md**

Update the "Docker Dependency" section under Known Limitations and the Phase 3 roadmap to reflect that apple/container support is now implemented.

**Step 4: Update TESTING.md**

Add a note about running tests with either runtime.

**Step 5: Commit**

```bash
git add docs/ARCHITECTURE.md docs/USAGE.md CLAUDE.md docs/TESTING.md
git commit -m "docs: update documentation for dual container runtime support"
```

---

### Task 8: Manual Testing

**Files:**
- Modify: `docs/TESTING.md` (document results)

**Context:** Verify the runtime detection and container lifecycle work end-to-end with whichever runtime is available.

**Step 1: Build image**

```bash
./vm/build.sh
# Expected: Detects runtime, builds successfully
```

**Step 2: Test container lifecycle**

```bash
# Create test workspace
mkdir -p /tmp/test-runtime-vibedom
echo "print('hello')" > /tmp/test-runtime-vibedom/app.py

# Start
vibedom run /tmp/test-runtime-vibedom

# Verify container is running and ready
# (the CLI will print success or error)

# Verify exec works
docker exec vibedom-test-runtime-vibedom echo "runtime test"
# OR
container exec vibedom-test-runtime-vibedom echo "runtime test"

# Stop
vibedom stop /tmp/test-runtime-vibedom

# Cleanup
rm -rf /tmp/test-runtime-vibedom
```

**Step 3: Document results in TESTING.md**

Add an "Apple/Container Runtime" section with actual test results.

**Step 4: Commit**

```bash
git add docs/TESTING.md
git commit -m "test: validate container runtime detection and lifecycle"
```

---

## Summary

**Tasks:**
1. Add runtime detection to VMManager (15 min)
2. Update `start()` for runtime abstraction (20 min)
3. Update `stop()` and `exec()` for runtime abstraction (15 min)
4. Update CLI `stop --all` for runtime awareness (15 min)
5. Update `build.sh` for dual runtime (10 min)
6. Drop `--privileged` from docs (10 min)
7. Update documentation for dual runtime (15 min)
8. Manual testing (20 min)

**Estimated effort:** 2-3 hours

**What changes:**
- `lib/vibedom/vm.py` — runtime detection, all methods use `self.runtime_cmd`
- `lib/vibedom/cli.py` — stop-all uses detected runtime
- `vm/build.sh` — detects runtime for image build
- `tests/test_vm.py` — runtime detection and command construction tests
- Documentation — reflects dual runtime support

**What does NOT change:**
- `vm/Dockerfile.alpine` — same file, same name, works with both runtimes
- `vm/startup.sh` — runs inside container, runtime-agnostic
- `vm/mitmproxy_addon.py` — runs inside container, runtime-agnostic
- `vm/dlp_scrubber.py` — runs inside container, runtime-agnostic
- `lib/vibedom/config/gitleaks.toml` — pattern config, unchanged

**Key decisions:**
- **No Containerfile rename** — `container build` reads `Dockerfile` natively
- **No `--privileged`** — git workflow eliminated the need
- **Auto-detect with fallback** — no config needed, just works
- **Same image for both** — OCI-compatible, no separate build paths
- **`container system start` is user responsibility** — documented in USAGE.md, not automated
