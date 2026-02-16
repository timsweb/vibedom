# Vibedom Usability Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make vibedom usable for daily work by installing Claude Code CLI, fixing mitmproxy logging to persist on host, and adding whitelist reload command.

**Architecture:** Install Claude Code in Dockerfile (Alpine-compatible binary), mount user's ~/.claude config files individually to avoid conflicts, change mitmproxy log path to session directory, add SIGHUP signal handler for whitelist reload with new CLI command.

**Tech Stack:** Docker, Alpine Linux, Python 3.11, mitmproxy, Click (CLI), pytest

**Design Doc:** `docs/plans/2026-02-16-vibedom-usability-improvements.md`

---

## Task 1: Install Claude Code in Dockerfile

**Files:**
- Modify: `vm/Dockerfile.alpine`

**Context:** Install Claude Code CLI in the container image using the official installer. Alpine Linux (musl-based) requires specific dependencies: libgcc, libstdc++, ripgrep, bash, curl. The installer downloads to `/root/.claude/bin/claude` by default.

**Step 1: Add dependencies and Claude installation to Dockerfile**

Add after the existing `apk add` commands in `vm/Dockerfile.alpine`:

```dockerfile
# Install Claude Code dependencies (Alpine/musl requirements)
RUN apk add --no-cache libgcc libstdc++ ripgrep bash curl

# Install Claude Code CLI (goes to /root/.claude/bin/claude)
RUN curl -fsSL https://claude.ai/install.sh | bash

# Configure for Alpine compatibility
ENV USE_BUILTIN_RIPGREP=0
ENV PATH="/root/.claude/bin:$PATH"
```

**Step 2: Build image to verify installation**

Run: `./vm/build.sh --runtime docker`
Expected: Build succeeds, no errors from curl or apk

**Step 3: Verify Claude binary exists in image**

Run: `docker run --rm vibedom-alpine:latest which claude`
Expected: `/root/.claude/bin/claude`

**Step 4: Verify Claude version**

Run: `docker run --rm vibedom-alpine:latest claude --version`
Expected: Claude Code version info (may fail if not authenticated, but binary should exist)

**Step 5: Commit**

```bash
git add vm/Dockerfile.alpine
git commit -m "feat: install Claude Code CLI in container image

- Add Alpine dependencies: libgcc, libstdc++, ripgrep, bash, curl
- Install via official installer (curl | bash)
- Set USE_BUILTIN_RIPGREP=0 for Alpine compatibility
- Add /root/.claude/bin to PATH

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Add Tests for Claude Config Mounts

**Files:**
- Modify: `tests/test_vm.py`

**Context:** The `VMManager.start()` method needs to mount user's `~/.claude` config files individually (api_key, settings.json, skills/) to avoid conflict with the installed Claude binary at `/root/.claude/bin/`. We'll test that the mount commands are constructed correctly.

**Step 1: Write failing test for api_key mount**

Add to `tests/test_vm.py`:

```python
from unittest.mock import patch, MagicMock
from pathlib import Path

def test_start_mounts_claude_api_key(test_workspace, test_config, tmp_path):
    """start() should mount ~/.claude/api_key if it exists."""
    # Create fake Claude config directory
    fake_claude_home = tmp_path / '.claude'
    fake_claude_home.mkdir()
    (fake_claude_home / 'api_key').write_text('fake-key')

    session_dir = tmp_path / 'session'
    session_dir.mkdir()

    with patch('lib.vibedom.vm.Path.home', return_value=tmp_path):
        with patch('shutil.which', return_value='/usr/bin/docker'):
            vm = VMManager(test_workspace, test_config, session_dir)

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('shutil.copy'):
                try:
                    vm.start()
                except RuntimeError:
                    pass  # May fail on readiness check, that's ok

            # Find the 'run' call
            calls = mock_run.call_args_list
            run_call = next(c for c in calls if 'run' in c[0][0])
            cmd = run_call[0][0]

            # Check that api_key is mounted
            assert '-v' in cmd
            mount_idx = cmd.index('-v')
            while mount_idx < len(cmd):
                if f'{fake_claude_home}/api_key:/root/.claude/api_key:ro' in cmd[mount_idx + 1]:
                    break
                mount_idx = cmd.index('-v', mount_idx + 1)
            else:
                pytest.fail("api_key mount not found in command")


def test_start_mounts_claude_settings(test_workspace, test_config, tmp_path):
    """start() should mount ~/.claude/settings.json if it exists."""
    fake_claude_home = tmp_path / '.claude'
    fake_claude_home.mkdir()
    (fake_claude_home / 'settings.json').write_text('{}')

    session_dir = tmp_path / 'session'
    session_dir.mkdir()

    with patch('lib.vibedom.vm.Path.home', return_value=tmp_path):
        with patch('shutil.which', return_value='/usr/bin/docker'):
            vm = VMManager(test_workspace, test_config, session_dir)

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('shutil.copy'):
                try:
                    vm.start()
                except RuntimeError:
                    pass

            calls = mock_run.call_args_list
            run_call = next(c for c in calls if 'run' in c[0][0])
            cmd = run_call[0][0]

            # Check that settings.json is mounted
            mount_found = any(
                f'{fake_claude_home}/settings.json:/root/.claude/settings.json:ro' in str(arg)
                for arg in cmd
            )
            assert mount_found, "settings.json mount not found"


def test_start_mounts_claude_skills(test_workspace, test_config, tmp_path):
    """start() should mount ~/.claude/skills directory if it exists."""
    fake_claude_home = tmp_path / '.claude'
    fake_claude_home.mkdir()
    skills_dir = fake_claude_home / 'skills'
    skills_dir.mkdir()

    session_dir = tmp_path / 'session'
    session_dir.mkdir()

    with patch('lib.vibedom.vm.Path.home', return_value=tmp_path):
        with patch('shutil.which', return_value='/usr/bin/docker'):
            vm = VMManager(test_workspace, test_config, session_dir)

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('shutil.copy'):
                try:
                    vm.start()
                except RuntimeError:
                    pass

            calls = mock_run.call_args_list
            run_call = next(c for c in calls if 'run' in c[0][0])
            cmd = run_call[0][0]

            # Check that skills directory is mounted
            mount_found = any(
                f'{skills_dir}:/root/.claude/skills:ro' in str(arg)
                for arg in cmd
            )
            assert mount_found, "skills directory mount not found"


def test_start_skips_claude_mounts_if_not_exists(test_workspace, test_config, tmp_path):
    """start() should not fail if ~/.claude doesn't exist."""
    session_dir = tmp_path / 'session'
    session_dir.mkdir()

    # No .claude directory exists
    with patch('lib.vibedom.vm.Path.home', return_value=tmp_path):
        with patch('shutil.which', return_value='/usr/bin/docker'):
            vm = VMManager(test_workspace, test_config, session_dir)

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('shutil.copy'):
                try:
                    vm.start()
                except RuntimeError:
                    pass

            # Should still succeed, just without Claude mounts
            assert mock_run.called
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_vm.py::test_start_mounts_claude_api_key tests/test_vm.py::test_start_mounts_claude_settings tests/test_vm.py::test_start_mounts_claude_skills tests/test_vm.py::test_start_skips_claude_mounts_if_not_exists -v`
Expected: FAIL (mount commands not in generated command)

**Step 3: Implement Claude config mounts in vm.py**

In `lib/vibedom/vm.py`, modify the `start()` method. After the existing session mounts, add:

```python
        # Claude Code config files (read-only)
        claude_home = Path.home() / '.claude'
        if claude_home.exists():
            # Mount API key if exists
            if (claude_home / 'api_key').exists():
                cmd += ['-v', f'{claude_home / "api_key"}:/root/.claude/api_key:ro']

            # Mount settings if exists
            if (claude_home / 'settings.json').exists():
                cmd += ['-v', f'{claude_home / "settings.json"}:/root/.claude/settings.json:ro']

            # Mount skills directory if exists
            if (claude_home / 'skills').is_dir():
                cmd += ['-v', f'{claude_home / "skills"}:/root/.claude/skills:ro']
```

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_vm.py -k "claude" -v`
Expected: PASS (all 4 new tests)

**Step 5: Commit**

```bash
git add lib/vibedom/vm.py tests/test_vm.py
git commit -m "feat: mount user's Claude Code config files in container

- Mount ~/.claude/api_key, settings.json, skills/ individually
- Read-only mounts for security
- Gracefully skip if files don't exist
- Tests verify mount commands constructed correctly

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Fix mitmproxy Log Path to Session Directory

**Files:**
- Modify: `vm/mitmproxy_addon.py`
- Modify: `tests/test_mitmproxy_addon.py` (if exists, otherwise create)

**Context:** Currently logs go to `/var/log/vibedom/network.jsonl` inside container (ephemeral). Need to change to `/mnt/session/network.jsonl` so logs persist on host at `~/.vibedom/logs/session-*/network.jsonl`.

**Step 1: Write failing test for log path**

Create or modify `tests/test_mitmproxy_addon.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

# Add vm directory to path for importing addon
sys.path.insert(0, str(Path(__file__).parent.parent / 'vm'))

from mitmproxy_addon import VibedomProxy


def test_proxy_uses_session_log_path(tmp_path):
    """Proxy should write logs to /mnt/session/network.jsonl."""
    whitelist_file = tmp_path / 'trusted_domains.txt'
    whitelist_file.write_text('example.com\n')

    session_dir = tmp_path / 'session'
    session_dir.mkdir()

    with patch('mitmproxy_addon.Path') as mock_path:
        # Mock Path('/mnt/config/trusted_domains.txt')
        mock_path.return_value.exists.return_value = True

        # Mock the __init__ to use our test paths
        proxy = VibedomProxy.__new__(VibedomProxy)
        proxy.whitelist = set(['example.com'])
        proxy.network_log_path = session_dir / 'network.jsonl'
        proxy.network_log_path.parent.mkdir(parents=True, exist_ok=True)

        # Create mock flow
        mock_flow = MagicMock()
        mock_flow.request.method = 'GET'
        mock_flow.request.pretty_url = 'https://example.com'
        mock_flow.request.host_header = 'example.com'
        mock_flow.request.host = 'example.com'

        # Log a request
        proxy.log_request(mock_flow, allowed=True)

        # Verify log written to session directory
        assert proxy.network_log_path.exists()
        content = proxy.network_log_path.read_text()
        assert 'example.com' in content
        assert '"allowed": true' in content
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_mitmproxy_addon.py::test_proxy_uses_session_log_path -v`
Expected: FAIL (may fail due to import issues or wrong path)

**Step 3: Update log path in mitmproxy_addon.py**

In `vm/mitmproxy_addon.py`, change the `__init__` method:

```python
    def __init__(self):
        self.whitelist = self.load_whitelist()
        # Write to session directory instead of container-local /var/log
        self.network_log_path = Path('/mnt/session/network.jsonl')
        self.network_log_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize DLP scrubber
        gitleaks_config = Path(__file__).parent / 'gitleaks.toml'
        config_path = str(gitleaks_config) if gitleaks_config.exists() else None
        self.scrubber = DLPScrubber(gitleaks_config=config_path)
```

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/test_mitmproxy_addon.py::test_proxy_uses_session_log_path -v`
Expected: PASS

**Step 5: Commit**

```bash
git add vm/mitmproxy_addon.py tests/test_mitmproxy_addon.py
git commit -m "fix: write mitmproxy logs to session directory instead of container

- Change log path from /var/log/vibedom to /mnt/session
- Logs now persist on host at ~/.vibedom/logs/session-*/network.jsonl
- Logs accessible in real-time from host
- Add test for log path

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Add SIGHUP Signal Handler for Whitelist Reload

**Files:**
- Modify: `vm/mitmproxy_addon.py`

**Context:** Add signal handler to reload whitelist when SIGHUP signal received. This allows reloading without restarting the container.

**Step 1: Add signal import and handler to mitmproxy_addon.py**

At the top of `vm/mitmproxy_addon.py`, add signal import:

```python
import signal
```

In the `VibedomProxy.__init__()` method, add signal handler registration:

```python
    def __init__(self):
        self.whitelist = self.load_whitelist()
        self.network_log_path = Path('/mnt/session/network.jsonl')
        self.network_log_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize DLP scrubber
        gitleaks_config = Path(__file__).parent / 'gitleaks.toml'
        config_path = str(gitleaks_config) if gitleaks_config.exists() else None
        self.scrubber = DLPScrubber(gitleaks_config=config_path)

        # Register SIGHUP handler for whitelist reload
        signal.signal(signal.SIGHUP, self._reload_whitelist)
```

Add the handler method to the `VibedomProxy` class:

```python
    def _reload_whitelist(self, signum, frame):
        """Reload whitelist when SIGHUP received."""
        self.whitelist = self.load_whitelist()
        print(f"Reloaded whitelist: {len(self.whitelist)} domains", file=sys.stderr)
```

**Step 2: Manual test (can't easily unit test signal handlers)**

Build and start container:
```bash
./vm/build.sh --runtime docker
vibedom run ~/projects/test-workspace --runtime docker
```

In another terminal, send SIGHUP:
```bash
docker exec vibedom-test-workspace pkill -HUP mitmdump
docker logs vibedom-test-workspace | grep "Reloaded whitelist"
```
Expected: "Reloaded whitelist: N domains" in logs

**Step 3: Commit**

```bash
git add vm/mitmproxy_addon.py
git commit -m "feat: add SIGHUP signal handler for whitelist reload

- Register signal.SIGHUP handler in VibedomProxy.__init__
- Handler calls load_whitelist() and prints confirmation
- Enables whitelist reload without container restart

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Add reload-whitelist CLI Command

**Files:**
- Modify: `lib/vibedom/cli.py`
- Modify: `tests/test_cli.py`

**Context:** Add `vibedom reload-whitelist <workspace>` command that sends SIGHUP to mitmdump process inside container.

**Step 1: Write failing test for reload-whitelist command**

Add to `tests/test_cli.py`:

```python
from unittest.mock import patch, MagicMock
import subprocess

def test_reload_whitelist_sends_sighup(tmp_path):
    """reload-whitelist should send SIGHUP to mitmdump in container."""
    workspace = tmp_path / 'test-workspace'
    workspace.mkdir()

    with patch('lib.vibedom.cli.VMManager._detect_runtime', return_value=('docker', 'docker')):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr='')

            from click.testing import CliRunner
            from lib.vibedom.cli import cli

            runner = CliRunner()
            result = runner.invoke(cli, ['reload-whitelist', str(workspace)])

            # Should call docker exec ... pkill -HUP mitmdump
            assert mock_run.called
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == 'docker'
            assert 'exec' in cmd
            assert 'pkill' in cmd
            assert '-HUP' in cmd
            assert 'mitmdump' in cmd
            assert result.exit_code == 0


def test_reload_whitelist_fails_if_container_not_running(tmp_path):
    """reload-whitelist should fail gracefully if container not running."""
    workspace = tmp_path / 'test-workspace'
    workspace.mkdir()

    with patch('lib.vibedom.cli.VMManager._detect_runtime', return_value=('docker', 'docker')):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr='Error: No such container')

            from click.testing import CliRunner
            from lib.vibedom.cli import cli

            runner = CliRunner()
            result = runner.invoke(cli, ['reload-whitelist', str(workspace)])

            assert result.exit_code == 1
            assert 'Failed to reload' in result.output
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_cli.py::test_reload_whitelist_sends_sighup tests/test_cli.py::test_reload_whitelist_fails_if_container_not_running -v`
Expected: FAIL (command doesn't exist yet)

**Step 3: Implement reload-whitelist command in cli.py**

Add to `lib/vibedom/cli.py`:

```python
@cli.command('reload-whitelist')
@click.argument('workspace', type=click.Path(exists=True))
def reload_whitelist(workspace: str) -> None:
    """Reload domain whitelist without restarting container.

    After editing ~/.vibedom/config/trusted_domains.txt, use this command
    to reload the whitelist in the running container.
    """
    workspace_path = Path(workspace).resolve()
    container_name = f'vibedom-{workspace_path.name}'

    try:
        runtime, runtime_cmd = VMManager._detect_runtime()
    except RuntimeError as e:
        click.secho(f"❌ {e}", fg='red')
        sys.exit(1)

    # Send SIGHUP to mitmdump process
    result = subprocess.run(
        [runtime_cmd, 'exec', container_name, 'pkill', '-HUP', 'mitmdump'],
        capture_output=True, text=True
    )

    if result.returncode == 0:
        click.echo(f"✅ Reloaded whitelist for {workspace_path.name}")
    else:
        click.secho(f"❌ Failed to reload: {result.stderr}", fg='red')
        sys.exit(1)
```

**Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/test_cli.py -k "reload_whitelist" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/vibedom/cli.py tests/test_cli.py
git commit -m "feat: add reload-whitelist CLI command

- New command: vibedom reload-whitelist <workspace>
- Sends SIGHUP to mitmdump process via docker/container exec
- Shows success/failure message
- Add tests for command behavior

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 6: Integration Testing

**Files:**
- None (manual testing)

**Context:** Verify the entire workflow end-to-end with a real container.

**Step 1: Build image with Claude Code**

Run: `./vm/build.sh --runtime docker`
Expected: Build succeeds, no errors

**Step 2: Verify Claude binary in image**

Run: `docker run --rm vibedom-alpine:latest which claude`
Expected: `/root/.claude/bin/claude`

Run: `docker run --rm vibedom-alpine:latest claude --version`
Expected: Version info (or auth error if not authenticated)

**Step 3: Start container with test workspace**

```bash
mkdir -p /tmp/test-vibedom-workspace
echo "print('hello')" > /tmp/test-vibedom-workspace/test.py
vibedom run /tmp/test-vibedom-workspace --runtime docker
```
Expected: Container starts successfully

**Step 4: Verify Claude config mounted**

Run: `docker exec vibedom-test-vibedom-workspace ls -la /root/.claude/`
Expected: api_key, settings.json, skills visible (if they exist on host)

**Step 5: Verify network logs go to session directory**

```bash
docker exec vibedom-test-vibedom-workspace curl https://pypi.org
ls ~/.vibedom/logs/session-*/network.jsonl
cat ~/.vibedom/logs/session-*/network.jsonl
```
Expected: Log file exists on host, contains pypi.org request

**Step 6: Test whitelist reload**

Edit whitelist:
```bash
echo "example.com" >> ~/.vibedom/config/trusted_domains.txt
```

Reload:
```bash
vibedom reload-whitelist /tmp/test-vibedom-workspace
```
Expected: "✅ Reloaded whitelist for test-vibedom-workspace"

Test domain works:
```bash
docker exec vibedom-test-vibedom-workspace curl https://example.com
```
Expected: Request succeeds (not blocked)

**Step 7: Cleanup**

```bash
vibedom stop /tmp/test-vibedom-workspace
rm -rf /tmp/test-vibedom-workspace
```

**Step 8: Document results**

No commit needed - this is verification only.

---

## Task 7: Update Documentation

**Files:**
- Modify: `docs/USAGE.md`
- Modify: `CLAUDE.md`

**Context:** Document the new features for users.

**Step 1: Update USAGE.md with Claude Code section**

Add a new section after "Container Runtime":

```markdown
### Using Claude Code Inside Container

Claude Code CLI is pre-installed in the container and available at `/root/.claude/bin/claude`.

Your Claude Code configuration is automatically mounted from `~/.claude/`:
- API key (`~/.claude/api_key`) - for authentication
- Settings (`~/.claude/settings.json`) - for preferences
- Skills (`~/.claude/skills/`) - for custom skills

**Usage:**

```bash
# Start vibedom
vibedom run ~/projects/myapp --runtime docker

# Exec into container
docker exec -it vibedom-myapp /bin/bash

# Inside container, use claude normally
claude --version
claude "help me refactor this code"
```

**Note:** Claude Code runs inside the isolated container with network whitelisting and DLP scrubbing active.
```

**Step 2: Add whitelist reload documentation**

Add to the "Whitelist Management" section:

```markdown
### Reloading Whitelist

When a domain is blocked, you can add it to the whitelist and reload without restarting:

1. Edit whitelist: `~/.vibedom/config/trusted_domains.txt`
2. Add the domain: `echo "npmjs.com" >> ~/.vibedom/config/trusted_domains.txt`
3. Reload: `vibedom reload-whitelist ~/projects/myapp`
4. Retry your request

The container will immediately recognize the new whitelist without interruption.
```

**Step 3: Update CLAUDE.md**

In the "Common Commands" section, add:

```markdown
# Reload whitelist after editing
vibedom reload-whitelist ~/projects/myapp

# Use Claude Code inside container
docker exec -it vibedom-myapp /bin/bash
claude "help me debug this"
```

**Step 4: Commit**

```bash
git add docs/USAGE.md CLAUDE.md
git commit -m "docs: add Claude Code and whitelist reload documentation

- Document Claude Code CLI availability in container
- Document automatic config mounting from ~/.claude
- Add whitelist reload workflow
- Update common commands

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Summary

**Tasks completed:**
1. Install Claude Code in Dockerfile (build-time)
2. Add tests and implementation for Claude config mounts (TDD)
3. Fix mitmproxy log path to session directory (TDD)
4. Add SIGHUP signal handler for whitelist reload
5. Add reload-whitelist CLI command (TDD)
6. Integration testing (manual verification)
7. Update documentation

**Estimated time:** 2-3 hours

**Testing strategy:**
- Unit tests for mount logic and CLI commands
- Manual testing for Docker build and signal handling
- Integration testing for end-to-end workflow

**What changes:**
- `vm/Dockerfile.alpine` - Claude Code installation
- `lib/vibedom/vm.py` - Claude config mounts
- `vm/mitmproxy_addon.py` - Log path + signal handler
- `lib/vibedom/cli.py` - reload-whitelist command
- `tests/test_vm.py` - Tests for mounts
- `tests/test_cli.py` - Tests for reload command
- `tests/test_mitmproxy_addon.py` - Test for log path
- `docs/USAGE.md`, `CLAUDE.md` - Documentation

**What does NOT change:**
- VM isolation architecture
- Network whitelisting logic
- DLP scrubbing behavior
- Git bundle workflow
- Session management

**Key decisions:**
- Use `--runtime docker` for all testing (DNS bug in apple/container)
- Mount Claude config files individually (not entire ~/.claude)
- Use SIGHUP for reload (standard Unix pattern)
- Gracefully skip Claude mounts if ~/.claude doesn't exist
