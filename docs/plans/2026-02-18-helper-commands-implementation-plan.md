# Helper Commands Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement `vibedom review`, `vibedom merge`, and `vibedom shell` commands to streamline the git bundle workflow.

**Architecture:** Three new CLI commands in `lib/vibedom/cli.py` using existing session-finding logic, VMManager runtime detection, and git subprocess operations. All commands follow TDD with unit tests in `tests/test_cli.py`.

**Tech Stack:** Click CLI framework, subprocess for git/container operations, pytest for testing

---

## Task 1: Add Session Finding Helper Function

**Files:**
- Modify: `lib/vibedom/cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write failing test for session finding**

Add to `tests/test_cli.py`:

```python
def test_find_latest_session_success(tmp_path):
    """find_latest_session should return most recent session for workspace."""
    from vibedom.cli import find_latest_session

    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    logs_dir = tmp_path / 'logs'
    logs_dir.mkdir()

    # Create two sessions
    session1 = logs_dir / 'session-20260218-100000-000000'
    session1.mkdir()
    (session1 / 'session.log').write_text(f'Session started for workspace: {workspace}')

    session2 = logs_dir / 'session-20260218-110000-000000'
    session2.mkdir()
    (session2 / 'session.log').write_text(f'Session started for workspace: {workspace}')

    result = find_latest_session(workspace, logs_dir)
    assert result == session2  # Most recent


def test_find_latest_session_not_found(tmp_path):
    """find_latest_session should return None if no session found."""
    from vibedom.cli import find_latest_session

    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    logs_dir = tmp_path / 'logs'
    logs_dir.mkdir()

    result = find_latest_session(workspace, logs_dir)
    assert result is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::test_find_latest_session_success tests/test_cli.py::test_find_latest_session_not_found -v`

Expected: FAIL with "ImportError: cannot import name 'find_latest_session'"

**Step 3: Implement session finding helper**

Add to `lib/vibedom/cli.py` after imports:

```python
def find_latest_session(workspace: Path, logs_dir: Path) -> Optional[Path]:
    """Find most recent session directory for a workspace.

    Args:
        workspace: Workspace path to search for
        logs_dir: Base logs directory (e.g., ~/.vibedom/logs)

    Returns:
        Path to session directory if found, None otherwise
    """
    if not logs_dir.exists():
        return None

    for session_dir in sorted(logs_dir.glob('session-*'), reverse=True):
        session_log = session_dir / 'session.log'
        if session_log.exists():
            log_content = session_log.read_text()
            if str(workspace.resolve()) in log_content:
                return session_dir
    return None
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py::test_find_latest_session_success tests/test_cli.py::test_find_latest_session_not_found -v`

Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add lib/vibedom/cli.py tests/test_cli.py
git commit -m "feat: add find_latest_session helper function

Extracts session-finding logic into reusable helper for review/merge commands.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Implement `vibedom shell` Command

**Files:**
- Modify: `lib/vibedom/cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write failing test for shell command**

Add to `tests/test_cli.py`:

```python
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

def test_shell_command_docker(tmp_path):
    """shell command should exec into docker container."""
    from vibedom.cli import main

    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    runner = CliRunner()

    with patch('vibedom.cli.VMManager') as mock_vm:
        mock_vm._detect_runtime.return_value = ('docker', 'docker')

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = runner.invoke(main, ['shell', str(workspace)])

            # Verify exec command called
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args[0] == 'docker'
            assert 'exec' in call_args
            assert '-it' in call_args
            assert '-w' in call_args
            assert '/work/repo' in call_args
            assert f'vibedom-{workspace.name}' in call_args
            assert 'bash' in call_args


def test_shell_command_apple_container(tmp_path):
    """shell command should exec into apple/container."""
    from vibedom.cli import main

    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    runner = CliRunner()

    with patch('vibedom.cli.VMManager') as mock_vm:
        mock_vm._detect_runtime.return_value = ('apple', 'container')

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = runner.invoke(main, ['shell', str(workspace)])

            call_args = mock_run.call_args[0][0]
            assert call_args[0] == 'container'
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::test_shell_command_docker tests/test_cli.py::test_shell_command_apple_container -v`

Expected: FAIL with "Error: No such command 'shell'"

**Step 3: Implement shell command**

Add to `lib/vibedom/cli.py` after existing commands:

```python
@main.command('shell')
@click.argument('workspace', type=click.Path(exists=True))
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple'], case_sensitive=False),
              default='auto', help='Container runtime (auto-detect, docker, or apple)')
def shell(workspace, runtime):
    """Open shell in container's working directory (/work/repo)."""
    workspace_path = Path(workspace).resolve()

    if not workspace_path.is_dir():
        click.secho(f"❌ Error: {workspace_path} is not a directory", fg='red')
        sys.exit(1)

    # Detect runtime
    try:
        runtime_name, runtime_cmd = VMManager._detect_runtime(
            runtime if runtime != 'auto' else None
        )
    except RuntimeError as e:
        click.secho(f"❌ {e}", fg='red')
        sys.exit(1)

    # Build container name
    container_name = f'vibedom-{workspace_path.name}'

    # Build exec command
    cmd = [
        runtime_cmd, 'exec',
        '-it',
        '-w', '/work/repo',
        container_name,
        'bash'
    ]

    # Execute (give user interactive shell)
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        click.secho(f"❌ Container not running", fg='red')
        click.echo(f"Start it with: vibedom run {workspace_path}")
        sys.exit(1)
    except FileNotFoundError:
        click.secho(f"❌ Error: {runtime_cmd} command not found", fg='red')
        sys.exit(1)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py::test_shell_command_docker tests/test_cli.py::test_shell_command_apple_container -v`

Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add lib/vibedom/cli.py tests/test_cli.py
git commit -m "feat: add vibedom shell command

Shortcuts 'docker exec -it container bash' to 'vibedom shell workspace'.
Opens interactive shell in /work/repo directory.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Implement `vibedom review` Command

**Files:**
- Modify: `lib/vibedom/cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write failing test for review command**

Add to `tests/test_cli.py`:

```python
def test_review_command_success(tmp_path):
    """review command should add remote, fetch, show commits and diff."""
    from vibedom.cli import main

    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    # Create fake session
    logs_dir = tmp_path / 'logs'
    session_dir = logs_dir / 'session-20260218-120000-000000'
    session_dir.mkdir(parents=True)
    (session_dir / 'session.log').write_text(f'Session started for workspace: {workspace}')
    (session_dir / 'repo.bundle').write_text('fake bundle')

    runner = CliRunner()

    with patch('vibedom.cli.Path.home') as mock_home:
        mock_home.return_value = tmp_path

        with patch('subprocess.run') as mock_run:
            # Mock git commands
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout='main\n'),  # git rev-parse --abbrev-ref HEAD
                MagicMock(returncode=1),  # git remote get-url (doesn't exist)
                MagicMock(returncode=0),  # git remote add
                MagicMock(returncode=0),  # git fetch
                MagicMock(returncode=0, stdout='abc123 commit message\n'),  # git log
                MagicMock(returncode=0, stdout='diff content\n'),  # git diff
            ]

            result = runner.invoke(main, ['review', str(workspace)])

            assert result.exit_code == 0
            assert 'session-20260218-120000-000000' in result.output
            assert 'git remote add' in [' '.join(call[0][0]) for call in mock_run.call_args_list]
            assert 'git fetch' in [' '.join(call[0][0]) for call in mock_run.call_args_list]
            assert 'git log' in [' '.join(call[0][0]) for call in mock_run.call_args_list]
            assert 'git diff' in [' '.join(call[0][0]) for call in mock_run.call_args_list]


def test_review_no_session_found(tmp_path):
    """review should error if no session found."""
    from vibedom.cli import main

    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    logs_dir = tmp_path / 'logs'
    logs_dir.mkdir()

    runner = CliRunner()

    with patch('vibedom.cli.Path.home') as mock_home:
        mock_home.return_value = tmp_path

        result = runner.invoke(main, ['review', str(workspace)])

        assert result.exit_code == 1
        assert 'No session found' in result.output
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::test_review_command_success tests/test_cli.py::test_review_no_session_found -v`

Expected: FAIL with "Error: No such command 'review'"

**Step 3: Implement review command**

Add to `lib/vibedom/cli.py`:

```python
@main.command('review')
@click.argument('workspace', type=click.Path(exists=True))
@click.option('--branch', help='Branch to review from bundle (default: current branch)')
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple'], case_sensitive=False),
              default='auto', help='Container runtime (auto-detect, docker, or apple)')
def review(workspace, branch, runtime):
    """Review changes from most recent session."""
    workspace_path = Path(workspace).resolve()

    if not workspace_path.is_dir():
        click.secho(f"❌ Error: {workspace_path} is not a directory", fg='red')
        sys.exit(1)

    # Check if workspace is a git repository
    try:
        subprocess.run(
            ['git', '-C', str(workspace_path), 'rev-parse', '--git-dir'],
            capture_output=True, check=True
        )
    except subprocess.CalledProcessError:
        click.secho(f"❌ Error: {workspace_path} is not a git repository", fg='red')
        sys.exit(1)

    # Find latest session
    logs_dir = Path.home() / '.vibedom' / 'logs'
    session_dir = find_latest_session(workspace_path, logs_dir)

    if not session_dir:
        click.secho(f"❌ No session found for {workspace_path.name}", fg='red')
        click.echo(f"Run 'vibedom run {workspace_path}' first.")
        sys.exit(1)

    # Check if bundle exists
    bundle_path = session_dir / 'repo.bundle'
    if not bundle_path.exists():
        click.secho(f"❌ Bundle not found at {bundle_path}", fg='red')
        click.echo("Session may have failed or been deleted.")
        sys.exit(1)

    # Get current branch or use --branch argument
    if not branch:
        try:
            result = subprocess.run(
                ['git', '-C', str(workspace_path), 'rev-parse', '--abbrev-ref', 'HEAD'],
                capture_output=True, text=True, check=True
            )
            branch = result.stdout.strip()
        except subprocess.CalledProcessError:
            click.secho(f"❌ Error: Could not determine current branch", fg='red')
            sys.exit(1)

    # Generate remote name from session timestamp
    session_id = session_dir.name.replace('session-', '')
    remote_name = f'vibedom-{session_id}'

    # Check if remote already exists
    result = subprocess.run(
        ['git', '-C', str(workspace_path), 'remote', 'get-url', remote_name],
        capture_output=True
    )

    if result.returncode != 0:
        # Add remote
        click.echo(f"Adding remote: {remote_name}")
        subprocess.run(
            ['git', '-C', str(workspace_path), 'remote', 'add', remote_name, str(bundle_path)],
            check=True
        )
    else:
        click.echo(f"Using existing remote: {remote_name}")

    # Fetch bundle
    click.echo("Fetching bundle...")
    try:
        subprocess.run(
            ['git', '-C', str(workspace_path), 'fetch', remote_name],
            check=True
        )
    except subprocess.CalledProcessError:
        click.secho(f"❌ Error: Failed to fetch bundle", fg='red')
        sys.exit(1)

    # Show session info
    click.echo(f"\n✅ Session: {session_dir.name}")
    click.echo(f"📦 Bundle: {bundle_path}")
    click.echo(f"🌿 Branch: {branch}\n")

    # Show commit log
    click.echo("📝 Commits:")
    result = subprocess.run(
        ['git', '-C', str(workspace_path), 'log', '--oneline',
         f'{branch}..{remote_name}/{branch}'],
        capture_output=True, text=True
    )
    if result.stdout:
        click.echo(result.stdout)
    else:
        click.echo("  (no new commits)")

    # Show diff
    click.echo("\n📊 Changes:")
    result = subprocess.run(
        ['git', '-C', str(workspace_path), 'diff',
         f'{branch}..{remote_name}/{branch}'],
        capture_output=True, text=True
    )
    if result.stdout:
        click.echo(result.stdout)
    else:
        click.echo("  (no changes)")

    # Show merge hint
    click.echo(f"\n💡 To merge: vibedom merge {workspace_path}")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py::test_review_command_success tests/test_cli.py::test_review_no_session_found -v`

Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add lib/vibedom/cli.py tests/test_cli.py
git commit -m "feat: add vibedom review command

Shows commit log and diff from most recent session bundle.
Adds bundle as git remote automatically.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Implement `vibedom merge` Command

**Files:**
- Modify: `lib/vibedom/cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write failing test for merge command (squash)**

Add to `tests/test_cli.py`:

```python
def test_merge_command_squash(tmp_path):
    """merge command should squash by default."""
    from vibedom.cli import main

    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    # Create fake session
    logs_dir = tmp_path / 'logs'
    session_dir = logs_dir / 'session-20260218-130000-000000'
    session_dir.mkdir(parents=True)
    (session_dir / 'session.log').write_text(f'Session started for workspace: {workspace}')
    (session_dir / 'repo.bundle').write_text('fake bundle')

    runner = CliRunner()

    with patch('vibedom.cli.Path.home') as mock_home:
        mock_home.return_value = tmp_path

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=''),  # git status --porcelain (clean)
                MagicMock(returncode=0, stdout='main\n'),  # git rev-parse (branch)
                MagicMock(returncode=1),  # git remote get-url (doesn't exist)
                MagicMock(returncode=0),  # git remote add
                MagicMock(returncode=0),  # git fetch
                MagicMock(returncode=0),  # git merge --squash
                MagicMock(returncode=0),  # git commit
                MagicMock(returncode=0),  # git remote remove
            ]

            result = runner.invoke(main, ['merge', str(workspace)])

            assert result.exit_code == 0
            # Verify squash merge was called
            merge_calls = [call for call in mock_run.call_args_list
                          if 'merge' in ' '.join(call[0][0])]
            assert any('--squash' in ' '.join(call[0][0]) for call in merge_calls)


def test_merge_command_keep_history(tmp_path):
    """merge command with --merge flag should keep full history."""
    from vibedom.cli import main

    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    logs_dir = tmp_path / 'logs'
    session_dir = logs_dir / 'session-20260218-130000-000000'
    session_dir.mkdir(parents=True)
    (session_dir / 'session.log').write_text(f'Session started for workspace: {workspace}')
    (session_dir / 'repo.bundle').write_text('fake bundle')

    runner = CliRunner()

    with patch('vibedom.cli.Path.home') as mock_home:
        mock_home.return_value = tmp_path

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=''),  # git status
                MagicMock(returncode=0, stdout='main\n'),  # git rev-parse
                MagicMock(returncode=1),  # git remote get-url
                MagicMock(returncode=0),  # git remote add
                MagicMock(returncode=0),  # git fetch
                MagicMock(returncode=0),  # git merge (no squash)
                MagicMock(returncode=0),  # git remote remove
            ]

            result = runner.invoke(main, ['merge', str(workspace), '--merge'])

            assert result.exit_code == 0
            # Verify regular merge (no --squash)
            merge_calls = [call for call in mock_run.call_args_list
                          if 'merge' in ' '.join(call[0][0])]
            assert not any('--squash' in ' '.join(call[0][0]) for call in merge_calls)


def test_merge_fails_with_uncommitted_changes(tmp_path):
    """merge should abort if workspace has uncommitted changes."""
    from vibedom.cli import main

    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    logs_dir = tmp_path / 'logs'
    session_dir = logs_dir / 'session-20260218-130000-000000'
    session_dir.mkdir(parents=True)
    (session_dir / 'session.log').write_text(f'Session started for workspace: {workspace}')
    (session_dir / 'repo.bundle').write_text('fake bundle')

    runner = CliRunner()

    with patch('vibedom.cli.Path.home') as mock_home:
        mock_home.return_value = tmp_path

        with patch('subprocess.run') as mock_run:
            # git status returns dirty state
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=' M file.txt\n'
            )

            result = runner.invoke(main, ['merge', str(workspace)])

            assert result.exit_code == 1
            assert 'uncommitted changes' in result.output
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::test_merge_command_squash tests/test_cli.py::test_merge_command_keep_history tests/test_cli.py::test_merge_fails_with_uncommitted_changes -v`

Expected: FAIL with "Error: No such command 'merge'"

**Step 3: Implement merge command**

Add to `lib/vibedom/cli.py`:

```python
@main.command('merge')
@click.argument('workspace', type=click.Path(exists=True))
@click.option('--branch', help='Branch to merge from bundle (default: current branch)')
@click.option('--merge', 'keep_history', is_flag=True,
              help='Keep full commit history (default: squash)')
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple'], case_sensitive=False),
              default='auto', help='Container runtime (auto-detect, docker, or apple)')
def merge(workspace, branch, keep_history, runtime):
    """Merge changes from most recent session (squash by default)."""
    workspace_path = Path(workspace).resolve()

    if not workspace_path.is_dir():
        click.secho(f"❌ Error: {workspace_path} is not a directory", fg='red')
        sys.exit(1)

    # Check if workspace is a git repository
    try:
        subprocess.run(
            ['git', '-C', str(workspace_path), 'rev-parse', '--git-dir'],
            capture_output=True, check=True
        )
    except subprocess.CalledProcessError:
        click.secho(f"❌ Error: {workspace_path} is not a git repository", fg='red')
        sys.exit(1)

    # Check for uncommitted changes
    result = subprocess.run(
        ['git', '-C', str(workspace_path), 'status', '--porcelain'],
        capture_output=True, text=True
    )
    if result.stdout.strip():
        click.secho(f"❌ Cannot merge: you have uncommitted changes", fg='red')
        click.echo("Commit or stash them first, then try again.")
        sys.exit(1)

    # Find latest session
    logs_dir = Path.home() / '.vibedom' / 'logs'
    session_dir = find_latest_session(workspace_path, logs_dir)

    if not session_dir:
        click.secho(f"❌ No session found for {workspace_path.name}", fg='red')
        click.echo(f"Run 'vibedom run {workspace_path}' first.")
        sys.exit(1)

    # Check if bundle exists
    bundle_path = session_dir / 'repo.bundle'
    if not bundle_path.exists():
        click.secho(f"❌ Bundle not found at {bundle_path}", fg='red')
        click.echo("Session may have failed or been deleted.")
        sys.exit(1)

    # Get current branch or use --branch argument
    if not branch:
        try:
            result = subprocess.run(
                ['git', '-C', str(workspace_path), 'rev-parse', '--abbrev-ref', 'HEAD'],
                capture_output=True, text=True, check=True
            )
            branch = result.stdout.strip()
        except subprocess.CalledProcessError:
            click.secho(f"❌ Error: Could not determine current branch", fg='red')
            sys.exit(1)

    # Generate remote name
    session_id = session_dir.name.replace('session-', '')
    remote_name = f'vibedom-{session_id}'

    # Check if remote exists (might have been added by review)
    result = subprocess.run(
        ['git', '-C', str(workspace_path), 'remote', 'get-url', remote_name],
        capture_output=True
    )

    if result.returncode != 0:
        # Add remote
        click.echo(f"Adding remote: {remote_name}")
        subprocess.run(
            ['git', '-C', str(workspace_path), 'remote', 'add', remote_name, str(bundle_path)],
            check=True
        )

        # Fetch bundle
        click.echo("Fetching bundle...")
        subprocess.run(
            ['git', '-C', str(workspace_path), 'fetch', remote_name],
            check=True
        )
    else:
        click.echo(f"Using existing remote: {remote_name}")

    # Perform merge
    remote_branch = f'{remote_name}/{branch}'

    try:
        if keep_history:
            # Regular merge (keep commits)
            click.echo(f"Merging {remote_branch} (keeping commit history)...")
            subprocess.run(
                ['git', '-C', str(workspace_path), 'merge', remote_branch],
                check=True
            )
        else:
            # Squash merge (default)
            click.echo(f"Merging {remote_branch} (squash)...")
            subprocess.run(
                ['git', '-C', str(workspace_path), 'merge', '--squash', remote_branch],
                check=True
            )

            # Create commit with summary message
            commit_msg = f"""Apply changes from vibedom session

Session: {session_id}
Bundle: {bundle_path}
Branch: {branch}

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"""

            subprocess.run(
                ['git', '-C', str(workspace_path), 'commit', '-m', commit_msg],
                check=True
            )
    except subprocess.CalledProcessError:
        click.secho(f"❌ Merge failed", fg='red')
        click.echo("Resolve conflicts manually and commit.")
        # Don't remove remote - user might need it
        sys.exit(1)

    # Clean up remote
    click.echo(f"Cleaning up remote: {remote_name}")
    subprocess.run(
        ['git', '-C', str(workspace_path), 'remote', 'remove', remote_name],
        check=True
    )

    click.echo(f"\n✅ Merge complete!")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py::test_merge_command_squash tests/test_cli.py::test_merge_command_keep_history tests/test_cli.py::test_merge_fails_with_uncommitted_changes -v`

Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add lib/vibedom/cli.py tests/test_cli.py
git commit -m "feat: add vibedom merge command

Merges bundle into current branch with automatic cleanup.
Squashes by default, --merge flag keeps full history.
Aborts if uncommitted changes detected.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Update Documentation

**Files:**
- Modify: `docs/USAGE.md`
- Modify: `CLAUDE.md`

**Step 1: Update USAGE.md with helper commands**

Add new section after "Working with Git Bundles" in `docs/USAGE.md`:

```markdown
### Helper Commands

**Quick review of changes:**
```bash
vibedom review ~/projects/myapp
# Shows commit log and diff from most recent session
```

**Merge changes into workspace:**
```bash
vibedom merge ~/projects/myapp
# Squash merge (single commit) - default

vibedom merge ~/projects/myapp --merge
# Keep full commit history

vibedom merge ~/projects/myapp --branch experimental
# Merge specific branch from bundle
```

**Shell access to container:**
```bash
vibedom shell ~/projects/myapp
# Opens bash in /work/repo directory
```

**Full workflow:**
```bash
# 1. Start session
vibedom run ~/projects/myapp

# 2. Work in container
vibedom shell ~/projects/myapp
# (make changes, exit shell)

# 3. Stop and create bundle
vibedom stop ~/projects/myapp

# 4. Review changes
vibedom review ~/projects/myapp

# 5. Merge into workspace
vibedom merge ~/projects/myapp
```
```

**Step 2: Update CLAUDE.md with new commands**

Update CLI section in `CLAUDE.md`:

```markdown
5. **CLI** (`lib/vibedom/cli.py`)
   - `vibedom run <workspace>` - Start sandbox
   - `vibedom stop <workspace>` - Stop specific sandbox
   - `vibedom stop` - Stop all vibedom containers
   - `vibedom init` - First-time setup (SSH keys, whitelist)
   - `vibedom reload-whitelist <workspace>` - Reload whitelist without restart
   - `vibedom review <workspace>` - Review changes from session bundle
   - `vibedom merge <workspace>` - Merge changes from session bundle
   - `vibedom shell <workspace>` - Open shell in container
```

**Step 3: Update Common Commands section**

Add to Usage section in `CLAUDE.md`:

```bash
# Review session changes
vibedom review ~/projects/myapp

# Merge session changes
vibedom merge ~/projects/myapp

# Shell into container
vibedom shell ~/projects/myapp
```

**Step 4: Commit documentation updates**

```bash
git add docs/USAGE.md CLAUDE.md
git commit -m "docs: add helper commands to documentation

Updated USAGE.md and CLAUDE.md with review, merge, and shell commands.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

**Step 5: Run full test suite**

Run: `pytest tests/ -v`

Expected: All new tests pass, existing tests still pass

---

## Implementation Complete

**New commands added:**
- ✅ `vibedom review` - Review session changes
- ✅ `vibedom merge` - Merge session changes (squash by default)
- ✅ `vibedom shell` - Quick container access

**Tests added:** 8 new unit tests in `tests/test_cli.py`

**Documentation updated:** USAGE.md and CLAUDE.md

**Next steps:**
- Manual integration testing with real workflows
- Update Phase 2 roadmap (helper commands now complete)
