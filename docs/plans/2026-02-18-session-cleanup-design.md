# Session Cleanup Design

**Date**: 2026-02-18
**Status**: Design Phase
**Related**: Phase 3 Production Hardening

## Overview

Add two CLI commands for cleaning up old vibedom session directories (`~/.vibedom/logs/session-*`):

- `vibedom prune` - Delete all sessions without running containers
- `vibedom housekeeping` - Delete sessions older than N days (default: 7)

Both commands support interactive prompts with YES default, or a `--force` flag for non-interactive mode.

## Architecture

### New Class: `SessionCleanup`

Located in `lib/vibedom/session.py`, handles:

- **Session Discovery**: Scan logs directory, parse timestamps, extract workspace paths
- **Container Status**: Check if `vibedom-<workspace>` container is running
- **Filtering**: Apply command-specific criteria (not running vs. older than N days)
- **Deletion**: Remove session directories with proper error handling

### CLI Commands

Located in `lib/vibedom/cli.py`, thin wrappers around `SessionCleanup`:

- `vibedom prune [--force] [--dry-run]`
- `vibedom housekeeping [--days 7] [--force] [--dry-run]`

Both commands show a summary before any deletion and skip sessions with running containers.

## CLI Commands

### `vibedom prune`

**Usage:**
```bash
vibedom prune [--force] [--dry-run]
```

**Behavior:**
- Scans all sessions in `~/.vibedom/logs/`
- Checks if corresponding `vibedom-<workspace>` container exists
- Skips any sessions with running containers
- Interactive prompt: "Delete session-20260216-171057-102366? [Y/n]: " (YES default)
- With `--force`: Deletes without prompting
- With `--dry-run`: Shows what would be deleted, exits without changes
- Summary output: "Deleted 12 sessions, skipped 3 (still running)"

### `vibedom housekeeping`

**Usage:**
```bash
vibedom housekeeping [--days 7] [--force] [--dry-run]
```

**Behavior:**
- Default: `--days 7`
- Filters sessions by comparing directory timestamp with current date
- Interactive prompt for each session (same as prune)
- With `--force`: Deletes all matching sessions without prompting
- With `--dry-run`: Shows what would be deleted, exits without changes
- Summary output: "Deleted 8 sessions older than 7 days"

## Data Flow

### Session Discovery

```python
def find_all_sessions(logs_dir: Path, runtime: str = 'auto') -> List[Dict]:
    """Return all sessions with metadata."""
    sessions = []
    for session_dir in logs_dir.glob('session-*'):
        timestamp = parse_session_timestamp(session_dir.name)
        workspace = extract_workspace_from_log(session_dir / 'session.log')
        is_running = check_container_status(workspace, runtime)
        sessions.append({
            'dir': session_dir,
            'timestamp': timestamp,
            'workspace': workspace,
            'is_running': is_running
        })
    return sorted(sessions, key=lambda x: x['timestamp'], reverse=True)
```

### Prune Flow

1. Find all sessions
2. Filter: `not session['is_running']`
3. Interactive: prompt each (YES default)
4. Delete: `shutil.rmtree(session['dir'])`
5. Show summary with deleted and skipped counts

### Housekeeping Flow

1. Find all sessions
2. Filter: `session['timestamp'] < (now - timedelta(days=N))`
3. Filter: `not session['is_running']`
4. Skip future-dated sessions (clock issues)
5. Same interactive/delete flow as prune
6. Show summary with deleted and skipped counts

## Error Handling

### Filesystem Errors

- **Session directory missing**: Skip with warning (may have been deleted already)
- **Permission denied**: Show error, skip to next session
- **Disk full**: Stop deletion process, show error

### Container Detection Errors

- **Runtime unavailable** (docker/container not installed): Show warning, assume containers not running
- **Permission denied**: Show warning, assume containers not running

### User Interaction

- **Ctrl+C during prompts**: Show summary of what was deleted so far
- **Force flag failures**: Exit with error code 1

### Timestamp Parsing

- **Invalid session directory name**: Skip with warning
- **Malformed timestamp**: Skip with warning
- **Future-dated sessions**: Skip with warning (do not auto-delete)

All errors use `click.secho()` for consistent formatting with contextual information.

## Testing Strategy

### Unit Tests (`tests/test_session_cleanup.py`)

```python
from datetime import datetime, timedelta
from pathlib import Path
from vibedom.session import SessionCleanup

def test_find_all_sessions(logs_dir_with_sessions):
    """Test session discovery returns all sessions."""
    sessions = SessionCleanup.find_all_sessions(logs_dir_with_sessions)
    assert len(sessions) == 3
    assert all('dir' in s for s in sessions)

def test_parse_timestamp():
    """Test timestamp parsing from directory name."""
    timestamp = SessionCleanup._parse_timestamp('session-20260216-171057-123456')
    assert timestamp == datetime(2026, 2, 16, 17, 10, 57, 123456)

def test_extract_workspace(tmp_path):
    """Test workspace extraction from session.log."""
    session_log = tmp_path / 'session.log'
    session_log.write_text('Session started for workspace: /Users/test/workspace')
    workspace = SessionCleanup._extract_workspace(tmp_path)
    assert workspace == Path('/Users/test/workspace')

def test_filter_by_age():
    """Test age-based filtering."""
    sessions = [
        {'timestamp': datetime.now() - timedelta(days=10)},
        {'timestamp': datetime.now() - timedelta(days=5)},
    ]
    old = SessionCleanup._filter_by_age(sessions, days=7)
    assert len(old) == 1

def test_filter_not_running():
    """Test filter for non-running containers."""
    sessions = [
        {'is_running': True},
        {'is_running': False},
    ]
    not_running = SessionCleanup._filter_not_running(sessions)
    assert len(not_running) == 1

def test_delete_session(tmp_path):
    """Test session directory deletion."""
    SessionCleanup._delete_session(tmp_path)
    assert not tmp_path.exists()
```

### Integration Tests

- Test `vibedom prune --dry-run` doesn't delete anything
- Test `vibedom housekeeping --days 1` with real sessions
- Test force flag behavior
- Test summary output formatting

### Mock Tests

- Mock `subprocess.run` for container detection
- Mock `click.confirm` for interactive prompts
- Mock `shutil.rmtree` for deletion

## Implementation Details

### New Class in `lib/vibedom/session.py`

```python
class SessionCleanup:
    """Handles session discovery and cleanup operations."""

    @staticmethod
    def find_all_sessions(logs_dir: Path, runtime: str = 'auto') -> List[Dict]:
        """Discover all sessions with metadata."""

    @staticmethod
    def _parse_timestamp(session_dir_name: str) -> Optional[datetime]:
        """Parse timestamp from session directory name."""

    @staticmethod
    def _extract_workspace(session_dir: Path) -> Optional[Path]:
        """Extract workspace path from session.log."""

    @staticmethod
    def _is_container_running(workspace: Path, runtime: str) -> bool:
        """Check if vibedom container for workspace is running."""

    @staticmethod
    def _filter_by_age(sessions: List[Dict], days: int) -> List[Dict]:
        """Filter sessions older than N days."""

    @staticmethod
    def _filter_not_running(sessions: List[Dict]) -> List[Dict]:
        """Filter sessions without running containers."""

    @staticmethod
    def _delete_session(session_dir: Path) -> None:
        """Delete session directory."""
```

### New CLI Commands in `lib/vibedom/cli.py`

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

### Helper Function Reuse

- `find_latest_session()` (helper-commands branch): Stays as-is, used by review/merge workflow
- `SessionCleanup.find_all_sessions()`: Complementary for cleanup, follows similar pattern

### Technical Debt

Extract shared workspace-from-log parsing logic into `Session` class when merging helper-commands branch into main. Currently:

- `find_latest_session()` in cli.py: Reads session.log, checks if workspace path is in log
- `SessionCleanup._extract_workspace()`: Reads session.log, extracts workspace path

Both use similar pattern but serve different purposes (search vs. extraction). Refactor deferred to avoid merge conflicts.

## Edge Cases & Gotchas

### Race Conditions

- **Container starts/stops between detection and deletion**: Acceptable risk, unlikely in practice
- **Session deleted by another process**: Handle with try/except on delete, log warning

### Empty Logs Directory

- No sessions exist: Print "No sessions found" and exit cleanly

### Corrupted Session Directories

- **Missing session.log or network.jsonl**: Delete anyway (user wants cleanup)
- **Partially deleted directories**: Handle with `shutil.rmtree(ignore_errors=True)`

### Session Timestamp Edge Cases

- **Sessions exactly N days old**: Use `<` (not `<=`) so 7-day-old sessions survive default
- **Future-dated sessions** (clock issues): Skip with warning, don't auto-delete

### Runtime Detection

- Prune needs runtime to check container status: Auto-detect like other commands
- If detection fails, assume containers not running (safe default)

## Open Questions

None at this time.

## Future Enhancements

- Add `--workspace` filter to restrict cleanup to specific workspace
- Add retention policies (keep last N sessions per workspace)
- Add automatic cleanup on `vibedom run` (e.g., keep last 10 sessions)
