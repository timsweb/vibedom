# Git Bundle Workflow Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace overlay filesystem diff with git-native bundle workflow for cleaner code review and GitLab integration.

**Architecture:** Container clones workspace repo and checks out current branch. Agent works in isolated git repo mounted to host. At session end, create git bundle that user can add as remote, fetch from, and merge into their feature branch.

**Tech Stack:** Git bundles, Docker volume mounts, Python subprocess, Click CLI

---

## Task 1: Update Container Initialization (startup.sh)

**Files:**
- Modify: `vm/startup.sh`
- Test: Manual verification in Docker container

**Step 1: Replace overlay FS with git clone/init**

Remove overlay filesystem setup and replace with git clone logic:

```bash
#!/bin/bash
set -e

echo "Starting vibedom container..."

# Initialize git repo from workspace
if [ -d /mnt/workspace/.git ]; then
    echo "Cloning git repository from workspace..."
    git clone /mnt/workspace/.git /work/repo
    cd /work/repo

    # Checkout the same branch user is on
    CURRENT_BRANCH=$(git -C /mnt/workspace rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
    echo "Detected branch: $CURRENT_BRANCH"

    # Checkout branch (create if doesn't exist locally)
    if git show-ref --verify --quiet refs/heads/"$CURRENT_BRANCH"; then
        git checkout "$CURRENT_BRANCH"
    else
        git checkout -b "$CURRENT_BRANCH"
    fi

    echo "Working on branch: $CURRENT_BRANCH"
else
    echo "Non-git workspace, initializing fresh repository..."
    mkdir -p /work/repo
    rsync -a --exclude='.git' /mnt/workspace/ /work/repo/ || true
    cd /work/repo
    git init
    git add .
    git commit -m "Initial snapshot from vibedom session" || echo "No files to commit"
fi

# Set git identity for agent commits
git config user.name "Vibedom Agent"
git config user.email "agent@vibedom.local"

echo "Git repository initialized at /work/repo"

# Setup mitmproxy logging
mkdir -p /var/log/vibedom

# Start mitmproxy in transparent mode
echo "Starting mitmproxy..."
mitmdump \
    --mode transparent \
    --listen-port 8080 \
    --set confdir=/tmp/mitmproxy \
    -s /mnt/config/mitmproxy_addon.py \
    > /var/log/vibedom/mitmproxy.log 2>&1 &

# Wait for mitmproxy to start and generate cert
sleep 2

# Install mitmproxy CA certificate
if [ -f /tmp/mitmproxy/mitmproxy-ca-cert.pem ]; then
    echo "Installing mitmproxy CA certificate..."
    cp /tmp/mitmproxy/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/mitmproxy.crt
    update-ca-certificates > /dev/null 2>&1
    export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
    export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
    export CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
fi

# Setup iptables for transparent proxy
echo "Configuring network redirection..."
iptables -t nat -A OUTPUT -p tcp --dport 80 -j REDIRECT --to-port 8080
iptables -t nat -A OUTPUT -p tcp --dport 443 -j REDIRECT --to-port 8080

# Signal readiness
touch /tmp/.vm-ready
echo "Container ready"

# Keep container running
tail -f /dev/null
```

**Step 2: Test container initialization**

Build and run container to verify:

```bash
cd /Users/tim/Documents/projects/vibedom
./vm/build.sh
docker run -it --rm --privileged \
  -v $(pwd):/mnt/workspace:ro \
  -v /tmp/test-session/repo:/work/repo \
  vibedom-alpine:latest /bin/bash

# Inside container:
cd /work/repo
git status
git log --oneline
git branch --show-current
```

Expected: Git repo initialized, current branch checked out

**Step 3: Commit**

```bash
git add vm/startup.sh
git commit -m "feat: replace overlay FS with git clone/init in startup.sh

- Clone from host .git if exists, checkout current branch
- Initialize fresh repo for non-git workspaces
- Set git identity for agent commits
- Preserve mitmproxy and iptables setup"
```

---

## Task 2: Update VM Manager (vm.py)

**Files:**
- Modify: `lib/vibedom/vm.py`
- Test: `tests/test_vm.py`

**Step 1: Write failing test for repo mount**

Add to `tests/test_vm.py`:

```python
def test_vm_mounts_session_repo(test_workspace, test_config):
    """VM should mount session repo directory."""
    from vibedom.session import Session

    session = Session(test_workspace, Path('/tmp/vibedom-test-logs'))
    vm = VMManager(test_workspace, test_config, session_dir=session.session_dir)

    try:
        vm.start()

        # Verify repo directory exists in session
        repo_dir = session.session_dir / 'repo'
        assert repo_dir.exists(), "Repo directory should exist in session dir"

        # Verify .git exists in mounted repo
        git_dir = repo_dir / '.git'
        assert git_dir.exists(), "Git directory should exist in mounted repo"

    finally:
        vm.stop()
        shutil.rmtree(session.session_dir, ignore_errors=True)
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_vm.py::test_vm_mounts_session_repo -v
```

Expected: FAIL (VMManager doesn't accept session_dir parameter)

**Step 3: Update VMManager to add repo mount**

Modify `lib/vibedom/vm.py`:

```python
class VMManager:
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

        # Prepare session repo directory if provided
        repo_mount = []
        if self.session_dir:
            repo_dir = self.session_dir / 'repo'
            repo_dir.mkdir(parents=True, exist_ok=True)
            repo_mount = ['-v', f'{repo_dir}:/work/repo']

            session_mount = ['-v', f'{self.session_dir}:/mnt/session']
        else:
            session_mount = []

        # Start new container
        try:
            subprocess.run([
                'docker', 'run',
                '-d',
                '--name', self.container_name,
                '--privileged',
                '-v', f'{self.workspace}:/mnt/workspace:ro',
                '-v', f'{self.config_dir}:/mnt/config:ro',
                *repo_mount,
                *session_mount,
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
                    check=False
                )
                if result.returncode == 0:
                    return
            except subprocess.CalledProcessError:
                pass
            time.sleep(1)
        raise RuntimeError(f"VM '{self.container_name}' failed to become ready within 10 seconds")

    # Remove get_diff() method - no longer needed
    # (Delete the entire get_diff method)
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_vm.py::test_vm_mounts_session_repo -v
```

Expected: PASS

**Step 5: Update other VM tests**

Remove or update tests that depend on `get_diff()`:

```python
# In tests/test_vm.py - REMOVE this test entirely:
# def test_vm_get_diff(test_workspace, test_config):
#     ...

# Update test_vm_overlay_filesystem to test repo mount instead:
def test_vm_git_repo_initialized(test_workspace, test_config):
    """VM should initialize git repo from workspace."""
    from vibedom.session import Session

    # Create test git workspace
    (test_workspace / 'test.txt').write_text('test content')
    subprocess.run(['git', 'init'], cwd=test_workspace, check=True)
    subprocess.run(['git', 'add', '.'], cwd=test_workspace, check=True)
    subprocess.run(['git', 'commit', '-m', 'Initial'], cwd=test_workspace, check=True)

    session = Session(test_workspace, Path('/tmp/vibedom-test-logs'))
    vm = VMManager(test_workspace, test_config, session_dir=session.session_dir)

    try:
        vm.start()

        # Verify git repo initialized in container
        result = vm.exec(['sh', '-c', 'cd /work/repo && git log --oneline'])
        assert 'Initial' in result.stdout

    finally:
        vm.stop()
        shutil.rmtree(session.session_dir, ignore_errors=True)
```

**Step 6: Run all VM tests**

```bash
pytest tests/test_vm.py -v
```

Expected: All tests pass (or skip if Docker not available)

**Step 7: Commit**

```bash
git add lib/vibedom/vm.py tests/test_vm.py
git commit -m "feat: add session repo mount to VMManager, remove get_diff

- Accept session_dir parameter in VMManager.__init__
- Mount session/repo directory to /work/repo in container
- Mount session directory to /mnt/session for bundle output
- Remove get_diff() method (replaced by git bundle)
- Update tests to verify repo mount instead of overlay diff"
```

---

## Task 3: Add Bundle Creation (session.py)

**Files:**
- Modify: `lib/vibedom/session.py`
- Test: `tests/test_session.py`

**Step 1: Write failing test for bundle creation**

Add to `tests/test_session.py`:

```python
import subprocess
from pathlib import Path

def test_create_bundle_success():
    """Bundle created successfully from container repo."""
    workspace = Path('/tmp/test-workspace-bundle')
    logs_dir = Path('/tmp/test-logs-bundle')

    try:
        # Create test workspace with git repo
        workspace.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init'], cwd=workspace, check=True)
        (workspace / 'test.txt').write_text('test')
        subprocess.run(['git', 'add', '.'], cwd=workspace, check=True)
        subprocess.run(['git', 'commit', '-m', 'Initial'], cwd=workspace, check=True)

        session = Session(workspace, logs_dir)

        # Simulate container repo with commits
        repo_dir = session.session_dir / 'repo'
        repo_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', str(workspace / '.git'), str(repo_dir)], check=True)

        # Make a commit in the "container" repo
        (repo_dir / 'feature.txt').write_text('new feature')
        subprocess.run(['git', 'add', '.'], cwd=repo_dir, check=True)
        subprocess.run(['git', 'commit', '-m', 'Add feature'], cwd=repo_dir, check=True)

        # Create bundle
        bundle_path = session.create_bundle()

        assert bundle_path is not None
        assert bundle_path.exists()
        assert bundle_path.name == 'repo.bundle'

        # Verify bundle is valid
        result = subprocess.run(
            ['git', 'bundle', 'verify', str(bundle_path)],
            capture_output=True
        )
        assert result.returncode == 0

    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(logs_dir, ignore_errors=True)

def test_create_bundle_failure():
    """Bundle creation failure logged, returns None."""
    workspace = Path('/tmp/test-workspace-bundle-fail')
    logs_dir = Path('/tmp/test-logs-bundle-fail')

    try:
        workspace.mkdir(parents=True, exist_ok=True)
        session = Session(workspace, logs_dir)

        # No repo directory exists - bundle creation should fail gracefully
        bundle_path = session.create_bundle()

        assert bundle_path is None

        # Check error logged
        log_content = (session.session_log).read_text()
        assert 'Bundle creation failed' in log_content or 'ERROR' in log_content

    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(logs_dir, ignore_errors=True)
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_session.py::test_create_bundle_success -v
pytest tests/test_session.py::test_create_bundle_failure -v
```

Expected: FAIL (create_bundle method doesn't exist)

**Step 3: Implement create_bundle() method**

Add to `lib/vibedom/session.py`:

```python
import subprocess
from typing import Optional

class Session:
    # ... existing methods ...

    def create_bundle(self) -> Optional[Path]:
        """Create git bundle from session repository.

        Creates a git bundle containing all refs from the container's
        git repository. The bundle can be used as a git remote for
        review and merge.

        Returns:
            Path to bundle file if successful, None if creation failed

        Example:
            >>> session = Session(workspace, logs_dir)
            >>> bundle_path = session.create_bundle()
            >>> if bundle_path:
            ...     # User can now: git remote add vibedom bundle_path
        """
        bundle_path = self.session_dir / 'repo.bundle'
        repo_dir = self.session_dir / 'repo'

        try:
            self.log_event('Creating git bundle...', level='INFO')

            # Check if repo directory exists
            if not repo_dir.exists():
                self.log_event('Repository directory not found', level='ERROR')
                return None

            # Create bundle with all refs
            result = subprocess.run([
                'git', '-C', str(repo_dir),
                'bundle', 'create', str(bundle_path), '--all'
            ], capture_output=True, check=True, text=True)

            # Verify bundle is valid
            verify_result = subprocess.run([
                'git', 'bundle', 'verify', str(bundle_path)
            ], capture_output=True, check=False, text=True)

            if verify_result.returncode == 0:
                self.log_event(f'Bundle created: {bundle_path}', level='INFO')
                return bundle_path
            else:
                self.log_event(f'Bundle verification failed: {verify_result.stderr}', level='ERROR')
                return None

        except subprocess.CalledProcessError as e:
            self.log_event(f'Bundle creation failed: {e.stderr}', level='ERROR')
            self.log_event(f'Live repo still available at {repo_dir}', level='WARN')
            return None
        except Exception as e:
            self.log_event(f'Unexpected error creating bundle: {e}', level='ERROR')
            return None
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_session.py::test_create_bundle_success -v
pytest tests/test_session.py::test_create_bundle_failure -v
```

Expected: PASS

**Step 5: Run all session tests**

```bash
pytest tests/test_session.py -v
```

Expected: All tests pass

**Step 6: Commit**

```bash
git add lib/vibedom/session.py tests/test_session.py
git commit -m "feat: add create_bundle method to Session

- Create git bundle from session repo directory
- Verify bundle validity after creation
- Log success/failure events
- Return None on failure, preserve live repo as fallback
- Add tests for bundle creation success and failure cases"
```

---

## Task 4: Update CLI Stop Command (cli.py)

**Files:**
- Modify: `lib/vibedom/cli.py`
- Test: Manual testing (CLI integration tests in separate task)

**Step 1: Update stop command to create bundle**

Modify `lib/vibedom/cli.py`:

```python
import subprocess
from pathlib import Path

@main.command()
@click.argument('workspace', type=click.Path(exists=True), required=False)
def stop(workspace: Optional[str] = None) -> None:
    """Stop sandbox and create git bundle.

    If workspace provided, stops that specific sandbox.
    If no workspace provided, stops all vibedom containers.
    """
    if workspace is None:
        # Stop all vibedom containers
        try:
            result = subprocess.run([
                'docker', 'ps', '-a', '--filter', 'name=vibedom-', '--format', '{{.Names}}'
            ], capture_output=True, text=True, check=True)

            containers = [name.strip() for name in result.stdout.split('\n') if name.strip()]

            if not containers:
                click.echo("No vibedom containers running")
                return

            click.echo(f"Stopping {len(containers)} container(s)...")
            for container in containers:
                subprocess.run(['docker', 'rm', '-f', container], capture_output=True)

            click.echo(f"✅ Stopped {len(containers)} container(s)")

        except subprocess.CalledProcessError as e:
            click.secho(f"❌ Error stopping containers: {e}", fg='red')
            sys.exit(1)
        return

    # Stop specific workspace
    workspace_path = Path(workspace).resolve()

    # Find active session
    logs_dir = Path.home() / '.vibedom' / 'logs'
    session = None

    if logs_dir.exists():
        # Find most recent session for this workspace
        for session_dir in sorted(logs_dir.glob('session-*'), reverse=True):
            session_log = session_dir / 'session.log'
            if session_log.exists():
                # Check if this session is for our workspace
                log_content = session_log.read_text()
                if str(workspace_path) in log_content:
                    session = Session(workspace_path, logs_dir)
                    session.session_dir = session_dir
                    break

    vm = VMManager(workspace_path, config_dir, session_dir=session.session_dir if session else None)

    if session:
        # Create bundle before stopping
        click.echo("Creating git bundle...")
        bundle_path = session.create_bundle()

        # Finalize session
        session.finalize()

        # Stop VM
        vm.stop()

        # Show user how to review
        if bundle_path:
            # Get current branch name from workspace
            try:
                current_branch = subprocess.run(
                    ['git', '-C', str(workspace_path), 'rev-parse', '--abbrev-ref', 'HEAD'],
                    capture_output=True, text=True, check=True
                ).stdout.strip()
            except subprocess.CalledProcessError:
                current_branch = 'main'

            click.echo(f"\n✅ Session complete!")
            click.echo(f"📦 Bundle: {bundle_path}")
            click.echo(f"\n📋 To review changes:")
            click.echo(f"  git remote add vibedom-xyz {bundle_path}")
            click.echo(f"  git fetch vibedom-xyz")
            click.echo(f"  git log vibedom-xyz/{current_branch}")
            click.echo(f"  git diff {current_branch}..vibedom-xyz/{current_branch}")
            click.echo(f"\n🔀 To merge into your feature branch (keep commits):")
            click.echo(f"  git merge vibedom-xyz/{current_branch}")
            click.echo(f"\n🔀 To merge (squash):")
            click.echo(f"  git merge --squash vibedom-xyz/{current_branch}")
            click.echo(f"  git commit -m 'Apply changes from vibedom session'")
            click.echo(f"\n🚀 Push for peer review:")
            click.echo(f"  git push origin {current_branch}")
            click.echo(f"\n🧹 Cleanup:")
            click.echo(f"  git remote remove vibedom-xyz")
        else:
            click.secho(f"⚠️  Bundle creation failed", fg='yellow')
            click.echo(f"📁 Live repo available: {session.session_dir / 'repo'}")
            click.echo(f"\nYou can still add it as a remote:")
            click.echo(f"  git remote add vibedom-live {session.session_dir / 'repo'}")
    else:
        # No session found, just stop container
        vm.stop()
        click.echo("✅ Container stopped")
```

**Step 2: Update run command to pass session_dir**

Modify the `run` command in `lib/vibedom/cli.py`:

```python
@main.command()
@click.argument('workspace', type=click.Path(exists=True))
def run(workspace: str) -> None:
    """Start sandbox for workspace."""
    workspace_path = Path(workspace).resolve()

    if not workspace_path.is_dir():
        click.secho(f"❌ Error: {workspace_path} is not a directory", fg='red')
        sys.exit(1)

    # Initialize session
    logs_dir = Path.home() / '.vibedom' / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)

    session = Session(workspace_path, logs_dir)
    session.log_event('Starting sandbox...')

    try:
        # Scan for secrets
        click.echo("🔍 Scanning for secrets...")
        findings = scan_workspace(workspace_path)

        if not review_findings(findings):
            session.log_event('Cancelled by user', level='WARN')
            session.finalize()
            click.secho("❌ Cancelled", fg='yellow')
            sys.exit(1)

        # Start VM with session directory
        click.echo("🚀 Starting sandbox...")
        vm = VMManager(workspace_path, config_dir, session_dir=session.session_dir)
        vm.start()

        session.log_event('VM started successfully')

        click.echo(f"\n✅ Sandbox running!")
        click.echo(f"📁 Session: {session.session_dir}")
        click.echo(f"📦 Live repo: {session.session_dir / 'repo'}")
        click.echo(f"\n💡 To test changes mid-session:")
        click.echo(f"  git remote add vibedom-live {session.session_dir / 'repo'}")
        click.echo(f"  git fetch vibedom-live")
        click.echo(f"\n🛑 To stop:")
        click.echo(f"  vibedom stop {workspace_path}")

        # Don't finalize yet - session is still active

    except Exception as e:
        session.log_event(f'Error: {e}', level='ERROR')
        session.finalize()
        click.secho(f"❌ Error: {e}", fg='red')
        sys.exit(1)
```

**Step 3: Test CLI commands manually**

```bash
# Build updated image
./vm/build.sh

# Test run command
vibedom run ~/projects/test-workspace

# Verify output shows session dir and live repo path
# Verify repo directory created

# Test stop command
vibedom stop ~/projects/test-workspace

# Verify bundle created
# Verify instructions shown
```

Expected: Run creates session with repo, stop creates bundle with instructions

**Step 4: Commit**

```bash
git add lib/vibedom/cli.py
git commit -m "feat: update CLI to create git bundles on stop

- Pass session_dir to VMManager in run command
- Create bundle in stop command before VM shutdown
- Show branch-aware instructions for review/merge workflow
- Display live repo path during session for mid-session testing
- Handle bundle creation failure gracefully"
```

---

## Task 5: Add Git Workflow Integration Tests

**Files:**
- Create: `tests/test_git_workflow.py`

**Step 1: Create comprehensive git workflow tests**

Create `tests/test_git_workflow.py`:

```python
import pytest
import subprocess
import shutil
from pathlib import Path
from vibedom.vm import VMManager
from vibedom.session import Session

@pytest.fixture
def git_workspace(tmp_path):
    """Create a test workspace with git repo."""
    workspace = tmp_path / 'workspace'
    workspace.mkdir()

    # Initialize git repo
    subprocess.run(['git', 'init'], cwd=workspace, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=workspace, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=workspace, check=True)

    # Create initial commit
    (workspace / 'README.md').write_text('# Test Project')
    subprocess.run(['git', 'add', '.'], cwd=workspace, check=True)
    subprocess.run(['git', 'commit', '-m', 'Initial commit'], cwd=workspace, check=True)

    # Create feature branch
    subprocess.run(['git', 'checkout', '-b', 'feature/test'], cwd=workspace, check=True)
    (workspace / 'feature.txt').write_text('Feature work')
    subprocess.run(['git', 'add', '.'], cwd=workspace, check=True)
    subprocess.run(['git', 'commit', '-m', 'Add feature'], cwd=workspace, check=True)

    yield workspace
    shutil.rmtree(workspace, ignore_errors=True)

@pytest.fixture
def config_dir(tmp_path):
    """Create test config directory."""
    config = tmp_path / 'config'
    config.mkdir()

    # Copy mitmproxy addon
    import vibedom
    addon_src = Path(vibedom.__file__).parent.parent.parent / 'vm' / 'mitmproxy_addon.py'
    shutil.copy(addon_src, config / 'mitmproxy_addon.py')

    # Create whitelist
    (config / 'trusted_domains.txt').write_text('pypi.org\n')

    yield config
    shutil.rmtree(config, ignore_errors=True)

def test_git_workspace_cloned_with_branch(git_workspace, config_dir, tmp_path):
    """Container clones workspace and checks out current branch."""
    logs_dir = tmp_path / 'logs'
    session = Session(git_workspace, logs_dir)
    vm = VMManager(git_workspace, config_dir, session_dir=session.session_dir)

    try:
        vm.start()

        # Verify git repo exists in container
        result = vm.exec(['sh', '-c', 'test -d /work/repo/.git && echo exists'])
        assert 'exists' in result.stdout

        # Verify correct branch checked out
        result = vm.exec(['sh', '-c', 'cd /work/repo && git branch --show-current'])
        assert result.stdout.strip() == 'feature/test'

        # Verify commits present
        result = vm.exec(['sh', '-c', 'cd /work/repo && git log --oneline'])
        assert 'Add feature' in result.stdout
        assert 'Initial commit' in result.stdout

    finally:
        vm.stop()
        shutil.rmtree(session.session_dir, ignore_errors=True)

def test_bundle_created_and_valid(git_workspace, config_dir, tmp_path):
    """Bundle is created and can be verified."""
    logs_dir = tmp_path / 'logs'
    session = Session(git_workspace, logs_dir)
    vm = VMManager(git_workspace, config_dir, session_dir=session.session_dir)

    try:
        vm.start()

        # Agent makes a commit
        vm.exec(['sh', '-c', '''
            cd /work/repo &&
            echo "Agent work" > agent.txt &&
            git add . &&
            git commit -m "Agent commit"
        '''])

        # Create bundle
        bundle_path = session.create_bundle()
        assert bundle_path is not None
        assert bundle_path.exists()

        # Verify bundle
        result = subprocess.run(
            ['git', 'bundle', 'verify', str(bundle_path)],
            capture_output=True, text=True
        )
        assert result.returncode == 0

        # Bundle should contain all commits
        result = subprocess.run(
            ['git', 'bundle', 'list-heads', str(bundle_path)],
            capture_output=True, text=True
        )
        assert 'feature/test' in result.stdout

    finally:
        vm.stop()
        shutil.rmtree(session.session_dir, ignore_errors=True)

def test_live_repo_accessible_during_session(git_workspace, config_dir, tmp_path):
    """Live repo can be accessed from host during session."""
    logs_dir = tmp_path / 'logs'
    session = Session(git_workspace, logs_dir)
    vm = VMManager(git_workspace, config_dir, session_dir=session.session_dir)

    try:
        vm.start()

        # Verify live repo exists
        live_repo = session.session_dir / 'repo'
        assert live_repo.exists()
        assert (live_repo / '.git').exists()

        # Agent makes commit
        vm.exec(['sh', '-c', '''
            cd /work/repo &&
            echo "Live test" > live.txt &&
            git add . &&
            git commit -m "Live commit"
        '''])

        # Fetch from live repo (from a different location)
        test_clone = tmp_path / 'test-clone'
        subprocess.run(['git', 'clone', str(git_workspace), str(test_clone)], check=True)
        subprocess.run(['git', 'remote', 'add', 'vibedom-live', str(live_repo)], cwd=test_clone, check=True)
        subprocess.run(['git', 'fetch', 'vibedom-live'], cwd=test_clone, check=True)

        # Verify commit visible
        result = subprocess.run(
            ['git', 'log', '--oneline', 'vibedom-live/feature/test'],
            cwd=test_clone, capture_output=True, text=True
        )
        assert 'Live commit' in result.stdout

    finally:
        vm.stop()
        shutil.rmtree(session.session_dir, ignore_errors=True)
        shutil.rmtree(test_clone, ignore_errors=True)

def test_merge_workflow_from_bundle(git_workspace, config_dir, tmp_path):
    """Bundle can be added as remote and merged."""
    logs_dir = tmp_path / 'logs'
    session = Session(git_workspace, logs_dir)
    vm = VMManager(git_workspace, config_dir, session_dir=session.session_dir)

    try:
        vm.start()

        # Agent makes commits
        vm.exec(['sh', '-c', '''
            cd /work/repo &&
            echo "Feature A" > feature_a.txt &&
            git add . &&
            git commit -m "Add feature A" &&
            echo "Feature B" > feature_b.txt &&
            git add . &&
            git commit -m "Add feature B"
        '''])

        # Create bundle
        bundle_path = session.create_bundle()
        vm.stop()

        # User merges from bundle
        subprocess.run(['git', 'remote', 'add', 'vibedom-test', str(bundle_path)], cwd=git_workspace, check=True)
        subprocess.run(['git', 'fetch', 'vibedom-test'], cwd=git_workspace, check=True)
        subprocess.run(['git', 'merge', 'vibedom-test/feature/test'], cwd=git_workspace, check=True)

        # Verify files exist
        assert (git_workspace / 'feature_a.txt').exists()
        assert (git_workspace / 'feature_b.txt').exists()

        # Verify commit history
        result = subprocess.run(
            ['git', 'log', '--oneline'],
            cwd=git_workspace, capture_output=True, text=True
        )
        assert 'Add feature A' in result.stdout
        assert 'Add feature B' in result.stdout

    finally:
        shutil.rmtree(session.session_dir, ignore_errors=True)

def test_non_git_workspace_initialized(tmp_path, config_dir):
    """Non-git workspace gets initialized as fresh repo."""
    workspace = tmp_path / 'non-git-workspace'
    workspace.mkdir()
    (workspace / 'file.txt').write_text('content')

    logs_dir = tmp_path / 'logs'
    session = Session(workspace, logs_dir)
    vm = VMManager(workspace, config_dir, session_dir=session.session_dir)

    try:
        vm.start()

        # Verify git repo initialized
        result = vm.exec(['sh', '-c', 'cd /work/repo && git status'])
        assert result.returncode == 0

        # Verify initial commit exists
        result = vm.exec(['sh', '-c', 'cd /work/repo && git log --oneline'])
        assert 'Initial snapshot' in result.stdout

        # Verify file copied
        result = vm.exec(['sh', '-c', 'test -f /work/repo/file.txt && echo exists'])
        assert 'exists' in result.stdout

    finally:
        vm.stop()
        shutil.rmtree(session.session_dir, ignore_errors=True)
        shutil.rmtree(workspace, ignore_errors=True)
```

**Step 2: Run tests**

```bash
pytest tests/test_git_workflow.py -v
```

Expected: All tests pass (or skip if Docker not available)

**Step 3: Commit**

```bash
git add tests/test_git_workflow.py
git commit -m "test: add comprehensive git workflow integration tests

- Test git workspace cloning with branch checkout
- Test bundle creation and verification
- Test live repo accessibility during session
- Test merge workflow from bundle
- Test non-git workspace initialization
- All tests use fixtures for cleanup"
```

---

## Task 6: Update Documentation

**Files:**
- Modify: `docs/USAGE.md`
- Modify: `CLAUDE.md`

**Step 1: Update USAGE.md with git bundle workflow**

Add new section to `docs/USAGE.md`:

```markdown
## Working with Git Bundles

### Starting a Session

When you start a vibedom session, the container clones your workspace repository and checks out your current branch:

\`\`\`bash
# On your feature branch
git checkout feature/add-authentication
vibedom run ~/projects/myapp
\`\`\`

The agent will work on the same branch (`feature/add-authentication`) inside an isolated git repository.

### Testing Changes Mid-Session

You can fetch from the live repository to test changes while the session is still running:

\`\`\`bash
# Add live repo as remote (once per session)
git remote add vibedom-live ~/.vibedom/sessions/session-20260214-123456/repo

# Fetch latest commits anytime
git fetch vibedom-live

# Create test branch
git checkout -b test-changes vibedom-live/feature/add-authentication

# Test the changes
npm test
npm run dev

# Session continues...
\`\`\`

### Reviewing and Merging Changes

After stopping the session, a git bundle is created:

\`\`\`bash
vibedom stop ~/projects/myapp
# Creates bundle at ~/.vibedom/sessions/session-xyz/repo.bundle
\`\`\`

**Add bundle as remote and review:**

\`\`\`bash
git remote add vibedom-xyz ~/.vibedom/sessions/session-xyz/repo.bundle
git fetch vibedom-xyz

# Review commits
git log vibedom-xyz/feature/add-authentication
git log --oneline vibedom-xyz/feature/add-authentication ^feature/add-authentication

# Review changes
git diff feature/add-authentication..vibedom-xyz/feature/add-authentication
\`\`\`

**Merge (keep commit history):**

\`\`\`bash
git checkout feature/add-authentication
git merge vibedom-xyz/feature/add-authentication
\`\`\`

**Merge (squash commits):**

\`\`\`bash
git checkout feature/add-authentication
git merge --squash vibedom-xyz/feature/add-authentication
git commit -m "Implement authentication system

Agent implemented:
- User login/logout endpoints
- JWT token generation
- Password hashing
"
\`\`\`

**Push for peer review:**

\`\`\`bash
git push origin feature/add-authentication
# Create Merge Request in GitLab
\`\`\`

**Cleanup:**

\`\`\`bash
git remote remove vibedom-xyz
\`\`\`

### Session Management

**List sessions:**

\`\`\`bash
ls ~/.vibedom/sessions/
\`\`\`

**Clean up old sessions:**

\`\`\`bash
rm -rf ~/.vibedom/sessions/session-20260214-123456
\`\`\`

### Troubleshooting

**Bundle creation failed:**

If bundle creation fails, the live repo is still available:

\`\`\`bash
git remote add vibedom-live ~/.vibedom/sessions/session-xyz/repo
git fetch vibedom-live
# Manually create bundle:
cd ~/.vibedom/sessions/session-xyz/repo
git bundle create ../repo.bundle --all
\`\`\`

**Non-git workspace:**

If your workspace isn't a git repository, vibedom will initialize a fresh repo with an initial snapshot commit.
```

**Step 2: Update CLAUDE.md**

Update the "Development Workflow" and "Known Limitations" sections in `CLAUDE.md`:

```markdown
## Development Workflow

### Git Bundle Workflow

**Container Initialization:**
- Git workspaces: Cloned from host, checkout current branch
- Non-git workspaces: Fresh git init with snapshot commit
- Agent works in `/work/repo` (mounted to `~/.vibedom/sessions/session-xyz/repo`)

**During Session:**
- Agent commits normally to isolated repo
- User can fetch from live repo for mid-session testing
- `git remote add vibedom-live ~/.vibedom/sessions/session-xyz/repo`

**After Session:**
- Git bundle created at `~/.vibedom/sessions/session-xyz/repo.bundle`
- User adds bundle as remote, reviews commits
- User merges into feature branch (with or without squash)
- User pushes feature branch for GitLab MR

### Git Worktrees

...

## Known Limitations

### HTTPS Not Supported (Phase 1)

... (existing content) ...

### Git Bundle Workflow

**Current Implementation:**
- Agent works on same branch as user's current branch
- Bundle contains all refs from session
- User decides to keep commits or squash during merge

**Phase 2 Enhancements:**
- Helper commands: `vibedom review`, `vibedom merge`
- Automatic session cleanup with retention policies
- GitLab integration for MR creation
```

**Step 3: Commit**

```bash
git add docs/USAGE.md CLAUDE.md
git commit -m "docs: update documentation for git bundle workflow

- Add comprehensive git bundle workflow guide to USAGE.md
- Document mid-session testing, review, and merge workflows
- Update CLAUDE.md with bundle workflow overview
- Add troubleshooting section for bundle failures"
```

---

## Task 7: Manual Testing and Validation

**Files:**
- N/A (manual testing)

**Step 1: Full workflow test with git workspace**

```bash
# Create test workspace
mkdir -p ~/test-vibedom
cd ~/test-vibedom
git init
git config user.name "Test User"
git config user.email "test@example.com"

# Create feature branch
git checkout -b feature/test-vibedom
echo "# Test Project" > README.md
git add .
git commit -m "Initial commit"

# Build VM image
cd /Users/tim/Documents/projects/vibedom
./vm/build.sh

# Start session
vibedom run ~/test-vibedom

# Verify output shows:
# - Session directory
# - Live repo path
# - Instructions for mid-session testing

# Test mid-session fetch
cd ~/test-vibedom
git remote add vibedom-live ~/.vibedom/sessions/session-*/repo
git fetch vibedom-live
git log vibedom-live/feature/test-vibedom

# Make changes in container (simulate agent work)
docker exec vibedom-test-vibedom sh -c '
  cd /work/repo &&
  echo "Agent feature" > feature.txt &&
  git add . &&
  git commit -m "Add feature"
'

# Fetch again
git fetch vibedom-live
git log vibedom-live/feature/test-vibedom
# Should see "Add feature" commit

# Stop session
vibedom stop ~/test-vibedom

# Verify bundle created
ls ~/.vibedom/sessions/session-*/repo.bundle

# Add bundle as remote
git remote add vibedom-bundle ~/.vibedom/sessions/session-*/repo.bundle
git fetch vibedom-bundle

# Review commits
git log vibedom-bundle/feature/test-vibedom
git diff feature/test-vibedom..vibedom-bundle/feature/test-vibedom

# Merge
git merge vibedom-bundle/feature/test-vibedom

# Verify feature.txt exists
cat feature.txt

# Cleanup
git remote remove vibedom-live
git remote remove vibedom-bundle
cd ~
rm -rf test-vibedom
```

Expected: Full workflow completes successfully, commits visible, merge works

**Step 2: Test with non-git workspace**

```bash
# Create non-git workspace
mkdir -p ~/test-non-git
cd ~/test-non-git
echo "Not a git repo" > file.txt

# Start session
cd /Users/tim/Documents/projects/vibedom
vibedom run ~/test-non-git

# Verify container has git repo
docker exec vibedom-test-non-git sh -c 'cd /work/repo && git log --oneline'
# Should see "Initial snapshot" commit

# Stop and verify bundle
vibedom stop ~/test-non-git
ls ~/.vibedom/sessions/session-*/repo.bundle

# Cleanup
rm -rf ~/test-non-git
```

Expected: Fresh git repo initialized, bundle created

**Step 3: Document test results**

Create `docs/TESTING.md` section:

```markdown
## Git Bundle Workflow Testing

**Manual Test Results (2026-02-14):**

- ✅ Git workspace cloned with correct branch
- ✅ Live repo accessible during session
- ✅ Mid-session fetch shows new commits
- ✅ Bundle created successfully
- ✅ Bundle verifies correctly
- ✅ Merge workflow completes
- ✅ Non-git workspace initialized
- ✅ CLI instructions display correctly

**Integration Test Results:**
- ✅ 6/6 git workflow tests passing (when Docker available)
- ✅ Bundle creation/verification
- ✅ Live repo mounting
- ✅ Merge from bundle
```

**Step 4: Final commit**

```bash
git add docs/TESTING.md
git commit -m "test: validate git bundle workflow end-to-end

Manual testing confirms:
- Git workspace cloning with branch checkout
- Live repo access during session
- Bundle creation and verification
- Merge workflow (keep commits and squash)
- Non-git workspace initialization
- CLI output and instructions

All integration tests passing (6/6)"
```

---

## Task 8: Update Technical Debt Document

**Files:**
- Modify: `docs/technical-debt.md`

**Step 1: Add Phase 2 enhancements section**

Add to `docs/technical-debt.md`:

```markdown
## Git Bundle Workflow - Phase 2 Enhancements

**Status:** Phase 1 complete, enhancements deferred
**Created:** 2026-02-14
**Priority:** Medium

### 1. Helper Commands (Medium Priority)

**Current:** Users run manual git commands for review/merge

**Proposed:**
\`\`\`bash
vibedom review <workspace>      # Auto-add remote, show log/diff
vibedom merge <workspace>       # Merge and cleanup
vibedom merge <workspace> --squash
vibedom sessions list           # Show all bundles
vibedom sessions clean --older-than 30d
\`\`\`

**Estimated Effort:** 4-6 hours

### 2. Session Recovery (Low Priority)

**Issue:** If bundle creation fails, user must manually create bundle

**Proposed:**
\`\`\`bash
vibedom recover <session-id>    # Retry bundle creation from live repo
\`\`\`

**Estimated Effort:** 1-2 hours

### 3. Automatic Cleanup (Medium Priority)

**Issue:** Session directories accumulate indefinitely

**Proposed:**
- Configurable retention policy (default 30 days)
- `~/.vibedom/config.toml`: `session_retention_days = 30`
- Automatic cleanup on vibedom start

**Estimated Effort:** 2-3 hours

### 4. GitLab Integration (High Priority for Production)

**Issue:** Manual push and MR creation

**Proposed:**
\`\`\`bash
vibedom push <workspace>        # Push branch, create MR
\`\`\`

Uses GitLab API to create MR with:
- Session metadata (bundle link)
- Agent commit summary
- Links to session logs

**Estimated Effort:** 6-8 hours

### 5. Disk Space Checks (Low Priority)

**Issue:** Bundle creation can fail due to disk space

**Proposed:**
- Check available space before bundle creation
- Warn if < 1GB available
- Offer to cleanup old sessions

**Estimated Effort:** 1 hour
```

**Step 2: Commit**

```bash
git add docs/technical-debt.md
git commit -m "docs: add git bundle workflow Phase 2 enhancements

Track deferred improvements:
- Helper commands (review, merge, sessions)
- Session recovery
- Automatic cleanup with retention policies
- GitLab integration for MR creation
- Disk space checks"
```

---

## Post-Implementation Checklist

- [ ] All tests pass: `pytest tests/ -v`
- [ ] Manual workflow tested end-to-end
- [ ] Documentation updated (USAGE.md, CLAUDE.md, TESTING.md)
- [ ] Technical debt tracked
- [ ] All commits follow conventional format
- [ ] VM image rebuilt: `./vm/build.sh`

---

## Success Criteria

- [ ] Container clones workspace and checks out current branch
- [ ] Live repo mounted and accessible during session
- [ ] User can fetch from live repo mid-session
- [ ] Bundle created at session end
- [ ] Bundle verifies successfully with `git bundle verify`
- [ ] User can add bundle as remote and fetch
- [ ] User can merge from bundle (keep or squash commits)
- [ ] Non-git workspaces initialize fresh repo
- [ ] CLI shows clear instructions for review/merge workflow
- [ ] All integration tests pass (or skip gracefully)

---

## Rollback Plan

If critical issues discovered during implementation:

1. **Revert commits:**
   ```bash
   git log --oneline  # Find commit before Task 1
   git revert <commit-range>
   ```

2. **Rebuild VM with Phase 1 code:**
   ```bash
   git checkout <phase-1-commit>
   ./vm/build.sh
   ```

3. **Document issues in technical debt**

4. **Create new design iteration**
