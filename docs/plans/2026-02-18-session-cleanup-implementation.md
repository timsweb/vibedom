# Session Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `vibedom prune` and `vibedom housekeeping` commands to clean up old session directories.

**Architecture:** New `SessionCleanup` class in `lib/vibedom/session.py` handles discovery, filtering, and deletion. CLI commands in `lib/vibedom/cli.py` are thin wrappers. Uses existing VM runtime detection pattern.

**Tech Stack:** Python 3.10+, Click CLI, pathlib, subprocess, shutil

---

### Task 1: Add SessionCleanup class skeleton

**Files:**
- Modify: `lib/vibedom/session.py`

**Step 1: Write the failing test**

Create `tests/test_session_cleanup.py`:

```python
"""Tests for session cleanup functionality."""

import pytest
from pathlib import Path
from datetime import datetime
from vibedom.session import SessionCleanup


def test_class_exists():
    """Test that SessionCleanup class exists."""
    assert hasattr(SessionCleanup, 'find_all_sessions')
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_cleanup.py::test_class_exists -v`
Expected: FAIL with "module 'vibedom.session' has no attribute 'SessionCleanup'"

**Step 3: Write minimal implementation**

Add to end of `lib/vibedom/session.py`:

```python
class SessionCleanup:
    """Handles session discovery and cleanup operations."""

    @staticmethod
    def find_all_sessions(logs_dir: Path, runtime: str = 'auto') -> list:
        """Discover all sessions with metadata."""
        return []
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_cleanup.py::test_class_exists -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/vibedom/session.py tests/test_session_cleanup.py
git commit -m "feat: add SessionCleanup class skeleton

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Implement _parse_timestamp

**Files:**
- Modify: `lib/vibedom/session.py`
- Test: `tests/test_session_cleanup.py`

**Step 1: Write the failing test**

Add to `tests/test_session_cleanup.py`:

```python
def test_parse_timestamp_valid():
    """Test timestamp parsing from valid directory name."""
    timestamp = SessionCleanup._parse_timestamp('session-20260216-171057-123456')
    assert timestamp == datetime(2026, 2, 16, 17, 10, 57, 123456)

def test_parse_timestamp_invalid():
    """Test timestamp parsing from invalid directory name."""
    timestamp = SessionCleanup._parse_timestamp('invalid-name')
    assert timestamp is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_cleanup.py::test_parse_timestamp_valid -v`
Expected: FAIL with "'SessionCleanup' object has no attribute '_parse_timestamp'"

**Step 3: Write minimal implementation**

Add to `SessionCleanup` class:

```python
@staticmethod
def _parse_timestamp(session_dir_name: str) -> datetime | None:
    """Parse timestamp from session directory name.

    Args:
        session_dir_name: Directory name like 'session-20260216-171057-123456'

    Returns:
        datetime object if valid, None otherwise
    """
    try:
        prefix = 'session-'
        if not session_dir_name.startswith(prefix):
            return None
        timestamp_str = session_dir_name[len(prefix):]
        return datetime.strptime(timestamp_str, '%Y%m%d-%H%M%S-%f')
    except (ValueError, IndexError):
        return None
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_cleanup.py::test_parse_timestamp -v`
Expected: PASS (both tests)

**Step 5: Commit**

```bash
git add lib/vibedom/session.py tests/test_session_cleanup.py
git commit -m "feat: add timestamp parsing to SessionCleanup

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Implement _extract_workspace

**Files:**
- Modify: `lib/vibedom/session.py`
- Test: `tests/test_session_cleanup.py`

**Step 1: Write the failing test**

Add to `tests/test_session_cleanup.py`:

```python
def test_extract_workspace_valid(tmp_path):
    """Test workspace extraction from valid session.log."""
    session_log = tmp_path / 'session.log'
    session_log.write_text('Session started for workspace: /Users/test/workspace')
    workspace = SessionCleanup._extract_workspace(tmp_path)
    assert workspace == Path('/Users/test/workspace')

def test_extract_workspace_no_log(tmp_path):
    """Test workspace extraction when session.log is missing."""
    workspace = SessionCleanup._extract_workspace(tmp_path)
    assert workspace is None

def test_extract_workspace_no_workspace_line(tmp_path):
    """Test workspace extraction when log has no workspace line."""
    session_log = tmp_path / 'session.log'
    session_log.write_text('Some other log line')
    workspace = SessionCleanup._extract_workspace(tmp_path)
    assert workspace is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_cleanup.py::test_extract_workspace_valid -v`
Expected: FAIL with "'SessionCleanup' object has no attribute '_extract_workspace'"

**Step 3: Write minimal implementation**

Add to `SessionCleanup` class:

```python
@staticmethod
def _extract_workspace(session_dir: Path) -> Path | None:
    """Extract workspace path from session.log.

    Args:
        session_dir: Path to session directory containing session.log

    Returns:
        Path to workspace if found, None otherwise
    """
    session_log = session_dir / 'session.log'
    if not session_log.exists():
        return None

    try:
        log_content = session_log.read_text()
        for line in log_content.split('\n'):
            if 'Session started for workspace:' in line:
                workspace_str = line.split('Session started for workspace:')[-1].strip()
                return Path(workspace_str)
    except (IOError, OSError):
        pass
    return None
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_cleanup.py::test_extract_workspace -v`
Expected: PASS (all three tests)

**Step 5: Commit**

```bash
git add lib/vibedom/session.py tests/test_session_cleanup.py
git commit -m "feat: add workspace extraction from session.log

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Implement _is_container_running

**Files:**
- Modify: `lib/vibedom/session.py`
- Test: `tests/test_session_cleanup.py`

**Step 1: Write the failing test**

Add to `tests/test_session_cleanup.py`:

```python
from unittest.mock import patch, MagicMock

def test_is_container_running_true():
    """Test container detection when container is running."""
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout='vibedom-test\n')
        result = SessionCleanup._is_container_running(Path('/Users/test'), 'docker')
        assert result is True

def test_is_container_running_false():
    """Test container detection when container is not running."""
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout='')
        result = SessionCleanup._is_container_running(Path('/Users/test'), 'docker')
        assert result is False

def test_is_container_running_error():
    """Test container detection on error (assume not running)."""
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = Exception('Runtime error')
        result = SessionCleanup._is_container_running(Path('/Users/test'), 'docker')
        assert result is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_cleanup.py::test_is_container_running_true -v`
Expected: FAIL with "'SessionCleanup' object has no attribute '_is_container_running'"

**Step 3: Write minimal implementation**

Add to `SessionCleanup` class:

```python
@staticmethod
def _is_container_running(workspace: Path, runtime: str) -> bool:
    """Check if vibedom container for workspace is running.

    Args:
        workspace: Path to workspace
        runtime: Runtime type ('docker', 'apple', or 'auto')

    Returns:
        True if container is running, False otherwise
    """
    try:
        runtime_cmd = runtime if runtime in ('docker', 'apple') else 'docker'
        container_name = f'vibedom-{workspace.name}'

        result = subprocess.run(
            [runtime_cmd, 'ps', '--filter', f'name={container_name}',
             '--format', '{{.Names}}'],
            capture_output=True, text=True, check=False
        )

        return container_name in result.stdout
    except Exception:
        return False
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_cleanup.py::test_is_container_running -v`
Expected: PASS (all three tests)

**Step 5: Commit**

```bash
git add lib/vibedom/session.py tests/test_session_cleanup.py
git commit -m "feat: add container running detection

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Implement find_all_sessions

**Files:**
- Modify: `lib/vibedom/session.py`
- Test: `tests/test_session_cleanup.py`

**Step 1: Write the failing test**

Add to `tests/test_session_cleanup.py`:

```python
def test_find_all_sessions(tmp_path):
    """Test session discovery returns all sessions."""
    # Create test session directories
    session1 = tmp_path / 'session-20260216-171057-123456'
    session2 = tmp_path / 'session-20260217-171057-123456'
    session1.mkdir()
    session2.mkdir()

    # Create session.log files
    log1 = session1 / 'session.log'
    log1.write_text('Session started for workspace: /Users/test/workspace1')
    log2 = session2 / 'session.log'
    log2.write_text('Session started for workspace: /Users/test/workspace2')

    with patch.object(SessionCleanup, '_is_container_running', return_value=False):
        sessions = SessionCleanup.find_all_sessions(tmp_path)

    assert len(sessions) == 2
    assert all('dir' in s for s in sessions)
    assert all('timestamp' in s for s in sessions)
    assert all('workspace' in s for s in sessions)
    assert all('is_running' in s for s in sessions)
    # Should be sorted by timestamp descending
    assert sessions[0]['dir'].name == 'session-20260217-171057-123456'
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_cleanup.py::test_find_all_sessions -v`
Expected: FAIL (find_all_sessions returns empty list)

**Step 3: Write minimal implementation**

Replace `find_all_sessions` in `SessionCleanup` class:

```python
@staticmethod
def find_all_sessions(logs_dir: Path, runtime: str = 'auto') -> list:
    """Discover all sessions with metadata.

    Args:
        logs_dir: Base logs directory containing session-* subdirectories
        runtime: Runtime type for container detection

    Returns:
        List of session dictionaries with keys: dir, timestamp, workspace, is_running
    """
    sessions = []

    for session_dir in logs_dir.glob('session-*'):
        if not session_dir.is_dir():
            continue

        timestamp = SessionCleanup._parse_timestamp(session_dir.name)
        if timestamp is None:
            continue

        workspace = SessionCleanup._extract_workspace(session_dir)
        is_running = SessionCleanup._is_container_running(
            workspace, runtime
        ) if workspace else False

        sessions.append({
            'dir': session_dir,
            'timestamp': timestamp,
            'workspace': workspace,
            'is_running': is_running
        })

    return sorted(sessions, key=lambda x: x['timestamp'], reverse=True)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_cleanup.py::test_find_all_sessions -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/vibedom/session.py tests/test_session_cleanup.py
git commit -m "feat: implement session discovery

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Implement _filter_by_age

**Files:**
- Modify: `lib/vibedom/session.py`
- Test: `tests/test_session_cleanup.py`

**Step 1: Write the failing test**

Add to `tests/test_session_cleanup.py`:

```python
from datetime import timedelta

def test_filter_by_age():
    """Test age-based filtering."""
    sessions = [
        {'timestamp': datetime.now() - timedelta(days=10)},
        {'timestamp': datetime.now() - timedelta(days=5)},
        {'timestamp': datetime.now() - timedelta(days=7, seconds=1)},
    ]
    old = SessionCleanup._filter_by_age(sessions, days=7)
    assert len(old) == 2

def test_filter_by_age_future():
    """Test filtering skips future-dated sessions."""
    sessions = [
        {'timestamp': datetime.now() + timedelta(days=1)},
        {'timestamp': datetime.now() - timedelta(days=10)},
    ]
    old = SessionCleanup._filter_by_age(sessions, days=7)
    assert len(old) == 1
    assert old[0]['timestamp'] < datetime.now()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_cleanup.py::test_filter_by_age -v`
Expected: FAIL with "'SessionCleanup' object has no attribute '_filter_by_age'"

**Step 3: Write minimal implementation**

Add to `SessionCleanup` class:

```python
@staticmethod
def _filter_by_age(sessions: list, days: int) -> list:
    """Filter sessions older than N days.

    Args:
        sessions: List of session dictionaries
        days: Number of days threshold

    Returns:
        List of sessions older than N days (excluding future-dated)
    """
    from datetime import timedelta

    cutoff = datetime.now() - timedelta(days=days)
    return [
        s for s in sessions
        if s['timestamp'] < cutoff and s['timestamp'] < datetime.now()
    ]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_cleanup.py::test_filter_by_age -v`
Expected: PASS (both tests)

**Step 5: Commit**

```bash
git add lib/vibedom/session.py tests/test_session_cleanup.py
git commit -m "feat: add age-based session filtering

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Implement _filter_not_running

**Files:**
- Modify: `lib/vibedom/session.py`
- Test: `tests/test_session_cleanup.py`

**Step 1: Write the failing test**

Add to `tests/test_session_cleanup.py`:

```python
def test_filter_not_running():
    """Test filter for non-running containers."""
    sessions = [
        {'is_running': True, 'dir': Path('/a')},
        {'is_running': False, 'dir': Path('/b')},
        {'is_running': True, 'dir': Path('/c')},
    ]
    not_running = SessionCleanup._filter_not_running(sessions)
    assert len(not_running) == 1
    assert not_running[0]['dir'] == Path('/b')
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_cleanup.py::test_filter_not_running -v`
Expected: FAIL with "'SessionCleanup' object has no attribute '_filter_not_running'"

**Step 3: Write minimal implementation**

Add to `SessionCleanup` class:

```python
@staticmethod
def _filter_not_running(sessions: list) -> list:
    """Filter sessions without running containers.

    Args:
        sessions: List of session dictionaries

    Returns:
        List of sessions where is_running is False
    """
    return [s for s in sessions if not s['is_running']]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_cleanup.py::test_filter_not_running -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/vibedom/session.py tests/test_session_cleanup.py
git commit -m "feat: add non-running session filter

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Implement _delete_session

**Files:**
- Modify: `lib/vibedom/session.py`
- Test: `tests/test_session_cleanup.py`

**Step 1: Write the failing test**

Add to `tests/test_session_cleanup.py`:

```python
def test_delete_session(tmp_path):
    """Test session directory deletion."""
    (tmp_path / 'file.txt').write_text('test')
    SessionCleanup._delete_session(tmp_path)
    assert not tmp_path.exists()

def test_delete_session_error(tmp_path):
    """Test deletion error is handled gracefully."""
    # Create a file (not directory)
    SessionCleanup._delete_session(tmp_path)
    # Should not raise exception
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_cleanup.py::test_delete_session -v`
Expected: FAIL with "'SessionCleanup' object has no attribute '_delete_session'"

**Step 3: Write minimal implementation**

Add to `SessionCleanup` class:

```python
@staticmethod
def _delete_session(session_dir: Path) -> None:
    """Delete session directory.

    Args:
        session_dir: Path to session directory to delete
    """
    try:
        import shutil
        shutil.rmtree(session_dir, ignore_errors=True)
    except Exception:
        pass
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_cleanup.py::test_delete_session -v`
Expected: PASS (both tests)

**Step 5: Commit**

```bash
git add lib/vibedom/session.py tests/test_session_cleanup.py
git commit -m "feat: add session deletion

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: Add prune CLI command

**Files:**
- Modify: `lib/vibedom/cli.py`
- Test: `tests/test_cli.py` (or create `tests/test_prune.py`)

**Step 1: Write the failing test**

Create `tests/test_prune.py`:

```python
"""Tests for prune CLI command."""

import click
from pathlib import Path
from click.testing import CliRunner
from vibedom.cli import main


def test_prune_help():
    """Test prune command has help text."""
    runner = CliRunner()
    result = runner.invoke(main, ['prune', '--help'])
    assert result.exit_code == 0
    assert 'prune' in result.output.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_prune.py::test_prune_help -v`
Expected: FAIL with "No such command: prune"

**Step 3: Write minimal implementation**

Add to `lib/vibedom/cli.py` (before `if __name__ == '__main__'`):

```python
@main.command()
@click.option('--force', '-f', is_flag=True, help='Delete without prompting')
@click.option('--dry-run', is_flag=True, help='Preview without deleting')
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple']),
              default='auto', help='Container runtime (auto-detect, docker, or apple)')
def prune(force: bool, dry_run: bool, runtime: str) -> None:
    """Remove all session directories without running containers."""
    logs_dir = Path.home() / '.vibedom' / 'logs'
    sessions = SessionCleanup.find_all_sessions(logs_dir, runtime)
    to_delete = SessionCleanup._filter_not_running(sessions)
    skipped = len(sessions) - len(to_delete)

    if not to_delete:
        click.echo("No sessions to delete")
        return

    click.echo(f"Found {len(to_delete)} session(s) to delete")

    deleted = 0
    for session in to_delete:
        if dry_run:
            click.echo(f"Would delete: {session['dir'].name}")
            deleted += 1
        elif force or click.confirm(f"Delete {session['dir'].name}?", default=True):
            SessionCleanup._delete_session(session['dir'])
            click.echo(f"✓ Deleted {session['dir'].name}")
            deleted += 1

    if dry_run:
        click.echo(f"\nWould delete {deleted} session(s), skip {skipped} (still running)")
    else:
        click.echo(f"\n✅ Deleted {deleted} session(s), skipped {skipped} (still running)")
```

Also add import at top:
```python
from vibedom.session import Session, SessionCleanup
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_prune.py::test_prune_help -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/vibedom/cli.py tests/test_prune.py
git commit -m "feat: add prune CLI command

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: Add housekeeping CLI command

**Files:**
- Modify: `lib/vibedom/cli.py`
- Test: `tests/test_prune.py`

**Step 1: Write the failing test**

Add to `tests/test_prune.py`:

```python
def test_housekeeping_help():
    """Test housekeeping command has help text."""
    runner = CliRunner()
    result = runner.invoke(main, ['housekeeping', '--help'])
    assert result.exit_code == 0
    assert 'housekeeping' in result.output.lower()
    assert '--days' in result.output
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_prune.py::test_housekeeping_help -v`
Expected: FAIL with "No such command: housekeeping"

**Step 3: Write minimal implementation**

Add to `lib/vibedom/cli.py` (after prune command):

```python
@main.command()
@click.option('--days', '-d', default=7, help='Delete sessions older than N days')
@click.option('--force', '-f', is_flag=True, help='Delete without prompting')
@click.option('--dry-run', is_flag=True, help='Preview without deleting')
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple']),
              default='auto', help='Container runtime (auto-detect, docker, or apple)')
def housekeeping(days: int, force: bool, dry_run: bool, runtime: str) -> None:
    """Remove sessions older than N days."""
    logs_dir = Path.home() / '.vibedom' / 'logs'
    sessions = SessionCleanup.find_all_sessions(logs_dir, runtime)
    old_sessions = SessionCleanup._filter_by_age(sessions, days)
    to_delete = SessionCleanup._filter_not_running(old_sessions)
    skipped = len(old_sessions) - len(to_delete)

    if not to_delete:
        click.echo(f"No sessions older than {days} days")
        return

    click.echo(f"Found {len(to_delete)} session(s) older than {days} days")

    deleted = 0
    for session in to_delete:
        if dry_run:
            click.echo(f"Would delete: {session['dir'].name}")
            deleted += 1
        elif force or click.confirm(f"Delete {session['dir'].name}?", default=True):
            SessionCleanup._delete_session(session['dir'])
            click.echo(f"✓ Deleted {session['dir'].name}")
            deleted += 1

    if dry_run:
        click.echo(f"\nWould delete {deleted} session(s), skip {skipped} (still running)")
    else:
        click.echo(f"\n✅ Deleted {deleted} session(s), skipped {skipped} (still running)")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_prune.py::test_housekeeping_help -v`
Expected: PASS

**Step 5: Commit**

```bash
git add lib/vibedom/cli.py tests/test_prune.py
git commit -m "feat: add housekeeping CLI command

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 11: Add integration tests

**Files:**
- Test: `tests/test_prune.py`

**Step 1: Write integration tests**

Add to `tests/test_prune.py`:

```python
def test_prune_dry_run(tmp_path, monkeypatch):
    """Test prune with dry-run doesn't delete anything."""
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
    logs_dir = tmp_path / '.vibedom' / 'logs'
    logs_dir.mkdir(parents=True)

    session = logs_dir / 'session-20260216-171057-123456'
    session.mkdir()
    (session / 'session.log').write_text('Session started for workspace: /Users/test')

    runner = CliRunner()
    result = runner.invoke(main, ['prune', '--dry-run'])
    assert result.exit_code == 0
    assert 'Would delete' in result.output
    assert session.exists()

def test_housekeeping_dry_run(tmp_path, monkeypatch):
    """Test housekeeping with dry-run doesn't delete anything."""
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
    logs_dir = tmp_path / '.vibedom' / 'logs'
    logs_dir.mkdir(parents=True)

    old_session = logs_dir / 'session-20260210-171057-123456'
    old_session.mkdir()
    (old_session / 'session.log').write_text('Session started for workspace: /Users/test')

    runner = CliRunner()
    result = runner.invoke(main, ['housekeeping', '--days', '3', '--dry-run'])
    assert result.exit_code == 0
    assert 'Would delete' in result.output
    assert old_session.exists()
```

**Step 2: Run test to verify it passes**

Run: `pytest tests/test_prune.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_prune.py
git commit -m "test: add integration tests for prune and housekeeping

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 12: Run full test suite and verify

**Files:**
- None (verification step)

**Step 1: Run all tests**

Run: `pytest tests/ -v --tb=short`
Expected: All tests pass (including existing tests)

**Step 2: Run lint check**

Run: `ruff check lib/vibedom/ tests/`
Expected: No errors

**Step 3: Commit**

```bash
git commit --allow-empty -m "test: verify full test suite passes

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 13: Manual testing

**Files:**
- None (manual verification)

**Step 1: Test prune with real sessions**

```bash
# Create test sessions (use existing ones or create mock ones)
ls ~/.vibedom/logs/

# Test dry-run
vibedom prune --dry-run

# Test interactive (should prompt)
vibedom prune

# Test force (should delete without prompt)
vibedom prune --force
```

Expected: Commands work as designed, sessions are deleted or skipped appropriately

**Step 2: Test housekeeping with real sessions**

```bash
# Test dry-run with 1-day threshold
vibedom housekeeping --days 1 --dry-run

# Test with default 7 days
vibedom housekeeping --dry-run

# Test force
vibedom housekeeping --days 30 --force
```

Expected: Only sessions older than N days are deleted, running sessions are skipped

**Step 3: Test help text**

```bash
vibedom prune --help
vibedom housekeeping --help
```

Expected: Clear help text with all options documented

**Step 4: Test error handling**

```bash
# Test with non-existent logs directory
mv ~/.vibedom/logs ~/.vibedom/logs.bak
vibedom prune
mv ~/.vibedom/logs.bak ~/.vibedom/logs
```

Expected: Graceful error handling, no crash

**Step 5: Document in USAGE.md**

Add to `docs/USAGE.md`:

```markdown
### Session Cleanup

**Prune old sessions:**
```bash
# Preview what will be deleted
vibedom prune --dry-run

# Delete all non-running sessions (interactive)
vibedom prune

# Delete without prompting
vibedom prune --force
```

**Clean up old sessions by age:**
```bash
# Delete sessions older than 7 days (default)
vibedom housekeeping --dry-run
vibedom housekeeping

# Delete sessions older than 30 days
vibedom housekeeping --days 30 --force
```

Both commands skip sessions with running containers.
```

**Step 6: Commit**

```bash
git add docs/USAGE.md
git commit -m "docs: add session cleanup usage documentation

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Completion Checklist

- [ ] All tests pass
- [ ] Lint passes
- [ ] Manual testing completed
- [ ] Documentation updated
- [ ] Code follows project conventions (DRY, YAGNI, TDD)
- [ ] All commits have descriptive messages with co-authorship
