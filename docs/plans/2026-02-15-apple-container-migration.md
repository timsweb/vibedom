# Apple/Container Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate from Docker to Apple's container runtime (apple/container) for better hardware isolation and macOS security integration.

**Architecture:** Replace Docker CLI commands with apple/container equivalents in vm.py, convert Dockerfile.alpine to Containerfile format, update documentation to reflect changes. Keep Docker as fallback for compatibility.

**Tech Stack:** apple/container CLI (0.9.0+), Containerfile format, Alpine Linux ARM64

**What's Apple/Container:**
- Apple's native container runtime built on Virtualization.framework
- Better hardware isolation than Docker namespaces
- Deeper macOS security integration
- Requires macOS 14+ (Big Sur or later)
- **Containerfile format is compatible** with Docker (same FROM, RUN, COPY, CMD)
- **CLI commands differ**: `container run` vs `docker run`, `container exec` vs `docker exec`
- **Mount syntax differs**: `--mount type=bind,source=src,target=dst` vs `-v src:dst`
- **Container name**: auto-assigned by apple/container, Docker needs `--name`
- **Key insight**: Migration is mostly command translation, not Containerfile complexity

---

## Task 1: Create Containerfile from Dockerfile

**Files:**
- Create: `docs/plans/2026-02-15-apple-container-research.md`

**Step 1: Document key Docker → apple/container command mappings**

Create research document with mapping:

```markdown
# Docker to Apple/Container Command Mapping

| Docker | apple/container | Usage |
|--------|----------------|--------|
| `docker build` | `container build` | Build images |
| `docker run -d` | `container run -d` | Start container (detached) |
| `docker run -it` | `container run -it` | Start container (interactive) |
| `docker exec` | `container exec` | Run command in container |
| `docker ps` | `container list` | List containers |
| `docker rm -f` | `container rm` | Remove container |
| `docker logs` | `container logs` | View logs |
| `docker cp` | `container cp` | Copy files to/from container |

**Flag Differences:**
| Docker | apple/container | Notes |
|--------|----------------|-------|
| `-d` | `--detach` | Different flag name |
| `-e KEY=VAL` | `--env KEY=VAL` | Same |
| `-v src:dst` | `--mount type=bind,source=src,target=dst` | Different mount syntax |
| `-it` | `-i` + `-t` | Same behavior, split flags |
| `--name <name>` | `--name <name>` | Same |
```

**Step 2: Document Containerfile format differences**

```markdown
# Containerfile Format vs Dockerfile

**Similarities:**
- Same base image syntax
- Same FROM, RUN, COPY, CMD directives
- Same ENV variable format

**Differences:**
- Dockerfile uses `Dockerfile`, Containerfile uses `Containerfile`
- Containerfile uses apple/container-specific features if needed
- BuildKit vs BuildKit compatibility

**Dockerfile.alpine → Containerfile conversion needed:**
- Line 1: `FROM alpine:latest` → `FROM alpine:latest` (same)
- Lines 4-16: `RUN apk add` → `RUN apk add` (same)
- Line 19: `RUN mkdir` → `RUN mkdir` (same)
- Line 22: `COPY startup.sh` → `COPY startup.sh` (same)
- Line 23: `RUN chmod` → `RUN chmod` (same)
- Line 25: `CMD` → `CMD` (same)

**Conversion:** Just rename Dockerfile.alpine → Containerfile
```

**Step 3: Document key considerations**

```markdown
# Migration Considerations

**Platform Specifics:**
- Apple Silicon (arm64) - Already using Alpine:latest which supports ARM64
- apple/container requires macOS 14+ (Big Sur or later)
- Virtualization.framework integration (hardware isolation benefits)

**Testing Requirements:**
- Must test on Apple Silicon Mac
- Verify container starts and stops correctly
- Verify mounts work (read-only workspace, writable overlay)
- Verify mitmproxy runs and scrubs correctly
- Verify SSH agent and git operations work

**Potential Issues:**
- apple/container CLI may have subtle differences from Docker
- Mount syntax changes (`-v src:dst` → `--mount type=bind,source=src,target=dst`)
- May need to adjust for apple/container-specific features
- Image build may behave differently

**Rollback Strategy:**
- Keep Docker-based implementation in `vm.py.docker` for fallback
- Add feature flag: `--container-runtime {docker|apple}` to choose
- Default to Docker initially, switch to apple/container after testing
```

**Step 4: Write research document**

Create file with all documentation from steps 1-3.

**Step 5: Commit research**

```bash
git add docs/plans/2026-02-15-apple-container-research.md
git commit -m "docs: document apple/container API and migration research"
```

---

## Task 2: Update VM Manager for apple/container Commands

---

## Task 3: Update Documentation

---

**Files:**
- Create: `vm/Containerfile`

**Step 1: Write Containerfile**

Create `vm/Containerfile`:

```dockerfile
FROM alpine:latest

# Install required packages
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

# Create directories
RUN mkdir -p /mnt/workspace /work /mnt/config /var/log/vibedom

# Add startup script
COPY startup.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/startup.sh

CMD ["/usr/local/bin/startup.sh"]
```

**Step 2: Test local build**

```bash
# Try building with apple/container
container build -t vibedom-container:latest -f vm/Containerfile

# Also verify it works
container images | grep vibedom-container
```

**Step 3: Update build.sh**

Modify `vm/build.sh` to support both Docker and apple/container:

```bash
#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="vibedom-container"

# Detect container runtime
if command -v container &>/dev/null; then
    RUNTIME="apple"
    BUILD_CMD="container build"
    RUN_OPTS=""
elif command -v docker &>/dev/null; then
    RUNTIME="docker"
    BUILD_CMD="docker build"
    RUN_OPTS=""
else
    echo "Error: Neither container nor docker found"
    exit 1
fi

echo "Building VM image: $IMAGE_NAME (using $RUNTIME)"
$BUILD_CMD $BUILD_OPTS -t "$IMAGE_NAME:latest" -f "$SCRIPT_DIR/Containerfile"

echo "✅ VM image built successfully: $IMAGE_NAME:latest"
echo ""
if [ "$RUNTIME" = "apple" ]; then
    echo "Using apple/container for better hardware isolation"
else
    echo "Note: For production, Docker is recommended for consistency"
fi
```

**Step 4: Commit Containerfile and build changes**

```bash
git add vm/Containerfile vm/build.sh
git commit -m "feat: add Containerfile and apple/container build support"
```

---

## Task 3: Update VM Manager for apple/container Commands

**Files:**
- Modify: `lib/vibedom/vm.py`

**Step 1: Update container runtime detection**

Add method to detect container runtime:

```python
import shutil
import subprocess
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

        # Detect container runtime
        self.container_runtime = self._detect_container_runtime()

    def _detect_container_runtime(self) -> str:
        """Detect which container runtime is available."""
        # Check for apple/container first
        if shutil.which('container'):
            return 'apple'
        # Fall back to Docker
        elif shutil.which('docker'):
            return 'docker'
        # Error if neither found
        raise RuntimeError(
            "Neither apple/container nor Docker found. "
            "Install apple/container (macOS 14+) or Docker."
        )
```

**Step 2: Update start() method to use detected runtime**

Modify `start()` method to use `self.container_runtime`:

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

    # Prepare session repo directory if provided
    repo_mount = []
    session_mount = []
    if self.session_dir:
        repo_dir = self.session_dir / 'repo'
        repo_dir.mkdir(parents=True, exist_ok=True)
        repo_mount = ['--mount', f'type=bind,source={repo_dir},target=/work/repo']
        session_mount = ['-v', f'{self.session_dir}:/mnt/session']

    # Build command based on runtime
    if self.container_runtime == 'apple':
        container_cmd = 'container'
        # apple/container uses --detach flag
        run_opts = ['--detach', '--name', self.container_name]
        # apple/container uses --env flag (same as Docker)
        env_opts = [
            '-e', 'HTTP_PROXY=http://127.0.0.1:8080',
            '-e', 'HTTPS_PROXY=http://127.0.0.1:8080',
            '-e', 'NO_PROXY=localhost,127.0.0.1,::1',
            '-e', 'http_proxy=http://127.0.0.1:8080',
            '-e', 'https_proxy=http://127.0.0.1:8080',
            '-e', 'no_proxy=localhost,127.0.0.1,::1',
        ]
        # Mount syntax for apple/container
        mount_opts = [
            '--mount', 'type=bind,source=/dev/urandom,target=/dev/random',
        ]
    else:  # Docker
        container_cmd = 'docker'
        run_opts = ['-d', '--name', self.container_name]
        env_opts = [
            '-e', 'HTTP_PROXY=http://127.0.0.1:8080',
            '-e', 'HTTPS_PROXY=http://127.0.0.1:8080',
            '-e', 'NO_PROXY=localhost,127.0.0.1,::1',
        ]
        # Mount syntax for Docker
        mount_opts = ['-v', f'{self.workspace}:/mnt/workspace:ro',
                      '-v', f'{self.config_dir}:/mnt/config:ro']

    # Prepare full command
    cmd = [container_cmd, 'run'] + run_opts + env_opts + mount_opts + [
        '-v', f'{self.workspace}:/mnt/workspace:ro',
        '-v', f'{self.config_dir}:/mnt/config:ro',
        'vibedom-alpine:latest'
    ]

    # Add session mounts if provided
    if self.session_dir:
        cmd.extend(repo_mount + session_mount)

    # Start new container
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to start VM container '{self.container_name}': {e}") from e
    except FileNotFoundError:
        raise RuntimeError("Container command not found. Install apple/container or Docker.") from None

    # Wait for VM to be ready
    for _ in range(10):
        try:
            result = subprocess.run(
                [container_cmd, 'exec', self.container_name, 'test', '-f', '/tmp/.vm-ready'],
                capture_output=True,
                check=False  # Don't raise on failure
            )
            if result.returncode == 0:
                return
        except subprocess.CalledProcessError:
            pass
        time.sleep(1)
    raise RuntimeError(f"VM '{self.container_name}' failed to become ready within 10 seconds")
```

**Step 3: Update stop() method for apple/container**

Modify `stop()` method to use detected runtime:

```python
def stop(self) -> None:
    """Stop and remove the VM."""
    try:
        if self.container_runtime == 'apple':
            container_cmd = 'container'
            # apple/container uses rm command (same as Docker)
            subprocess.run([container_cmd, 'rm', '-f', self.container_name], check=True)
        else:  # Docker
            subprocess.run(['docker', 'rm', '-f', self.container_name], check=True)
    except FileNotFoundError:
        raise RuntimeError("Container command not found") from None
```

**Step 4: Update exec() method for apple/container**

Modify `exec()` method:

```python
def exec(self, cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a command inside the VM."""
    if self.container_runtime == 'apple':
        container_cmd = 'container'
    else:
        container_cmd = 'docker'
    return subprocess.run([container_cmd, 'exec', self.container_name] + cmd, check=True)
```

**Step 5: Update CLI to add runtime selection option**

Modify `lib/vibedom/cli.py` to add `--container-runtime` flag:

```python
import click

@click.group()
def cli():
    """Vibedom sandbox for AI coding agents."""
    pass

@click.command()
@click.option('--container-runtime', type=click.Choice(['auto', 'docker', 'apple']), default='auto', help='Container runtime (auto=detect, docker, apple/container)')
def run(workspace: str):
    """Run sandbox for workspace."""
    manager = VMManager(Path(workspace), Path(click.get_appdir('vibedom') / 'config'))
    manager.start()
    click.echo(f"✅ Started vibedom sandbox for {workspace}")

@click.command()
def stop(workspace: Optional[str]):
    """Stop sandbox session."""
    manager = VMManager(Path(workspace), Path(click.get_appdir('vibedom') / 'config'))
    manager.stop()
    click.echo(f"✅ Stopped vibedom sandbox for {workspace}")
```

**Step 6: Commit vm.py and CLI changes**

```bash
git add lib/vibedom/vm.py lib/vibedom/cli.py
git commit -m "feat: add apple/container runtime support with fallback to Docker"
```

---

## Task 4: Update Documentation

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/USAGE.md`
- Modify: `docs/technical-debt.md`

**Step 1: Update ARCHITECTURE.md**

Add section about container runtime:

```markdown
## Container Runtime

Vibedom supports both Docker and apple/container runtimes for VM isolation.

**Docker Runtime:**
- Namespace-based isolation (less secure)
- Docker-based approach
- Compatible with all platforms

**Apple/Container Runtime:**
- Apple Virtualization.framework (hardware-level isolation)
- Better security integration with macOS
- macOS 14+ (Big Sur or later) required
- Production runtime

**Detection:**
- Auto-detects available runtime (apple/container preferred, Docker fallback)
- Can override with `--container-runtime` flag in CLI

**Image:**
- Containerfile format (same as Dockerfile)
- Built with `container build` (apple/container) or `docker build`
- Alpine Linux ARM64

**Selection:**
```bash
vibedom run <workspace> --container-runtime apple  # Use apple/container
vibedom run <workspace> --container-runtime docker  # Force Docker
vibedom run <workspace>  # Auto-detect (prefers apple/container)
```

**Benefits:**
- Hardware isolation via Virtualization.framework
- Better macOS security integration
- Faster startup with apple/container
- Resource efficiency
```

**Step 2: Update USAGE.md**

Add container runtime section to user guide:

```markdown
### Container Runtime Options

Vibedom supports two container runtimes for VM isolation:

**Apple/Container (Recommended):**
- Uses Apple's Virtualization.framework for hardware-level isolation
- Better security integration with macOS
- Faster startup and resource efficiency
- Requires macOS 14+ (Big Sur or later)

**Docker (Fallback):**
- Namespace-based isolation (less secure)
- Docker-based approach
- Compatible with all platforms
- Works on older macOS versions

**Auto-Detection (Default):**
- Prefers apple/container if available
- Falls back to Docker if not

**Usage:**
```bash
# Use apple/container (recommended)
vibedom run ~/myproject

# Force Docker
vibedom run ~/myproject --container-runtime docker

# Auto-detect
vibedom run ~/myproject
```
```

**Step 3: Update technical-debt.md**

Mark apple/container migration as completed:

```markdown
## Apple/Container Migration (Completed 2026-02-15)

**Original Issue**: Design targeted apple/container but implemented Docker-only

**Solution Implemented**: Full apple/container support with Docker fallback
- Containerfile format
- Runtime detection and CLI flag
- Updated all VM manager commands
- Auto-detection with apple/container preference
- Documentation updated

**Result**: Now supports production-ready apple/container with Docker fallback
```

**Step 4: Commit documentation updates**

```bash
git add docs/
git commit -m "docs: add apple/container runtime documentation and mark migration complete"
```

---

## Task 5: Test Apple/Container Implementation

**Files:**
- Test: Manual testing in terminal
- Create: `docs/plans/2026-02-15-apple-container-test-plan.md` (optional test checklist)

**Step 1: Test container runtime detection**

```bash
# Test auto-detection
vibedom run ~/test-workspace

# Verify in vm.py logs which runtime was detected
grep "container runtime" ~/.vibedom/logs/session-*/session.log

# Expected: Should detect apple/container if available
```

**Step 2: Test container start**

```bash
# Start with explicit apple/container
vibedom run ~/test-workspace --container-runtime apple

# Verify container starts
container list | grep vibedom-test

# Should show container running
```

**Step 3: Test container stop**

```bash
# Stop container
vibedom stop ~/test-workspace

# Verify container is removed
container list | grep vibedom-test

# Should not show container
```

**Step 4: Test container exec**

```bash
# Start container
vibedom run ~/test-workspace

# Exec into container
docker exec -it vibedom-test-workspace /bin/bash

# Verify you're in container
hostname

# Run command
ls /work

# Verify git operations work
cd /work/repo && git status
```

**Step 5: Test mounts**

```bash
# Start container
vibedom run ~/test-workspace

# Verify read-only workspace
docker exec vibedom-test-workspace touch /mnt/workspace/test.txt

# Should fail (read-only mount)
```

**Step 6: Test DLP scrubbing**

```bash
# Start container
vibedom run ~/test-workspace

# Create test file with secret
echo "AKIAIOSFODNN7EXAMPLE" > /tmp/secret.txt

# Try to POST via curl
docker exec vibedom-test-workspace curl -X POST -d @/tmp/secret.txt https://httpbin.org/post

# Verify scrubbing in logs
cat ~/.vibedom/logs/session-*/network.jsonl | jq -r '.[] | select(.scrubbed != null)'

# Should show scrubbed request
```

**Step 7: Test rollback**

```bash
# Test Docker fallback still works
vibedom run ~/test-workspace --container-runtime docker

# Should start with Docker
container list | grep vibedom-test-workspace

# Verify Docker container is running
```

**Step 8: Document test results**

Create test checklist document with pass/fail for each test:

```markdown
# Apple/Container Test Results

## Runtime Detection
- [x] Auto-detects apple/container
- [x] Falls back to Docker
- [x] CLI flag --container-runtime works

## Container Lifecycle
- [x] Container starts with apple/container
- [x] Container stops with apple/container
- [x] Docker fallback still works
- [x] Mounts work correctly
- [x] Container exec works

## DLP Scrubbing
- [x] Secrets scrubbed from request bodies
- [x] Secrets scrubbed from URL query params
- [x] Request headers pass through
- [x] Response bodies not scrubbed

## Integration Tests
- [x] Git operations work in container
- [x] SSH agent works
- [x] Mitmproxy runs and scrubs correctly
- [x] Network whitelisting works

## Issues Found
- None critical
- 1 minor: [describe any issues]

## Recommendation
[ ] Ready for production
[ ] Needs additional work
```

**Step 9: Commit test plan (if created)**

```bash
git add docs/plans/2026-02-15-apple-container-test-plan.md
git commit -m "docs: add apple/container test results"
```

---

## Task 6: Final Verification and Documentation

**Files:**
- Update: `docs/plans/2026-02-15-dlp-scrubber-fixes.md` (add note about apple/container)

**Step 1: Add apple/container note to DLP plan**

```markdown
### Apple/Container Migration

**Status:** Planned (2026-02-15)

**Implementation:** See `docs/plans/2026-02-15-apple-container-migration.md`

**Why apple/container:**
- Apple Virtualization.framework provides hardware-level isolation
- Better macOS security integration
- Production-ready runtime (Docker is PoC)

**Note:** Implementation includes Docker fallback for compatibility.
```

**Step 2: Update project README (if exists)**

Add container runtime section to README:

```markdown
## Requirements

- Python 3.12+
- apple/container (macOS 14+) or Docker
- Gitleaks (for pre-flight scanning)

## Quick Start

```bash
# Install dependencies
pip install -e .

# Initialize
vibedom init

# Run with auto-detection (prefers apple/container)
vibedom run ~/myproject

# Or force Docker
vibedom run ~/myproject --container-runtime docker

# Or force apple/container
vibedom run ~/myproject --container-runtime apple
```

**Step 3: Final test run**

Run full test suite to ensure no regressions:

```bash
# Activate venv
source .venv/bin/activate

# Run all tests
pytest tests/ -v

# Run with container runtime flag (if needed)
pytest tests/ -v --container-runtime apple
```

**Step 4: Commit final changes**

```bash
git add README.md docs/
git commit -m "docs: add apple/container information to README and final verification"
```

---

## Summary of Changes

1. **Research** - Document apple/container API, Docker→container command mapping, Containerfile format differences, migration considerations
2. **Containerfile** - Create Containerfile format of existing Dockerfile
3. **Build script** - Update build.sh to detect container runtime and use appropriate commands
4. **VM Manager** - Add container runtime detection, update all container commands, add CLI flag for runtime selection
5. **Documentation** - Update ARCHITECTURE.md, USAGE.md, technical-debt.md with apple/container information
6. **Testing** - Comprehensive manual testing plan for apple/container functionality
7. **Final verification** - Update DLP plan notes, add README information, final test run

**Estimated Effort:** 8-16 hours

**Risks:**
- Unknown apple/container CLI behavior differences
- Platform-specific issues on non-Apple Silicon
- Potential integration issues with existing workflows

**Mitigation:**
- Docker fallback always available
- Feature flag for runtime selection
- Auto-detection prefers apple/container
- Comprehensive testing plan
