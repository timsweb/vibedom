# Session Management Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace fragile log-file-based session tracking with a structured `state.json`, introduce human-readable session IDs, add `vibedom list` and `vibedom attach`, and clean up the OO model.

**Architecture:** Three new/updated classes — `SessionState` (owns `state.json` I/O), `Session` (owns lifecycle + logging, uses `SessionState`), `SessionRegistry` (discovers and resolves sessions from logs dir). CLI commands delegate to these classes; `SessionCleanup` is slimmed to filter/delete helpers only. Session IDs use `<workspace>-<adjective>-<noun>` format from a bundled word list.

**Tech Stack:** Python 3.12, Click, dataclasses, pathlib, pytest, Click test runner

**Design doc:** `docs/plans/2026-02-19-session-management-design.md`

---

## Important: Test Update Strategy

Many existing tests create session directories with `session.log` files. After this refactor, they must create `state.json` files instead. Update tests for each component as you work on that component — do not leave broken tests behind before moving to the next task.

Helper for tests — add to each test file that needs it:

```python
import json
from datetime import datetime

def make_state(session_dir, workspace='/Users/test/myapp', runtime='docker',
               status='running', session_id=None):
    """Write a state.json to a session directory for testing."""
    workspace_name = Path(workspace).name
    sid = session_id or f'{workspace_name}-happy-turing'
    state = {
        'session_id': sid,
        'workspace': workspace,
        'runtime': runtime,
        'container_name': f'vibedom-{workspace_name}',
        'status': status,
        'started_at': '2026-02-19T10:00:00',
        'ended_at': None,
        'bundle_path': None,
    }
    (session_dir / 'state.json').write_text(json.dumps(state))
    return state
```

---

## Task 1: Word List Module

**Files:**
- Create: `lib/vibedom/words.py`
- Create: `tests/test_words.py`

**Step 1: Write the failing test**

```python
# tests/test_words.py
from vibedom.words import generate_session_id

def test_generate_session_id_format():
    sid = generate_session_id('myapp')
    parts = sid.split('-')
    assert parts[0] == 'myapp'
    assert len(parts) == 3  # workspace, adjective, noun

def test_generate_session_id_workspace_with_hyphens():
    sid = generate_session_id('rabbitmq-talk')
    assert sid.startswith('rabbitmq-talk-')
    assert len(sid.split('-')) == 4  # two workspace parts + adjective + noun

def test_generate_session_id_is_random():
    ids = {generate_session_id('myapp') for _ in range(20)}
    assert len(ids) > 1  # should not always produce the same ID
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_words.py -v
```
Expected: `ImportError: cannot import name 'generate_session_id'`

**Step 3: Write minimal implementation**

```python
# lib/vibedom/words.py
import random

ADJECTIVES = [
    'bold', 'brave', 'bright', 'calm', 'clear', 'clever', 'eager',
    'fierce', 'gentle', 'happy', 'jolly', 'keen', 'kind', 'lively',
    'merry', 'noble', 'proud', 'quick', 'quiet', 'rapid', 'sharp',
    'sleek', 'smart', 'steady', 'swift', 'warm', 'wise', 'witty',
    'agile', 'amber', 'ancient', 'benign', 'candid', 'cosmic', 'deft',
    'early', 'earnest', 'fair', 'famous', 'fluid', 'fresh', 'grand',
    'great', 'hardy', 'honest', 'humble', 'ideal', 'known', 'large',
    'light', 'liquid', 'lucky', 'major', 'mental', 'micro', 'modern',
    'moral', 'nimble', 'novel', 'noted', 'open', 'patient', 'plain',
]

NOUNS = [
    'babbage', 'boole', 'curie', 'darwin', 'dijkstra', 'einstein',
    'euler', 'faraday', 'fermat', 'feynman', 'fibonacci', 'franklin',
    'gauss', 'goedel', 'hamilton', 'hawking', 'hilbert', 'hopper',
    'huffman', 'turing', 'knuth', 'laplace', 'leibniz', 'lovelace',
    'maxwell', 'mendel', 'newton', 'noether', 'pascal', 'planck',
    'poincare', 'ramanujan', 'shannon', 'shor', 'tesla', 'thompson',
    'torvalds', 'von-neumann', 'wiles', 'wozniak', 'ritchie', 'liskov',
    'mccarthy', 'minsky', 'naur', 'perlis', 'hamming', 'codd', 'chen',
    'backus', 'allen', 'adleman', 'rivest', 'shamir', 'diffie', 'hellman',
    'lamport', 'gray', 'brooks', 'floyd', 'hoare', 'wirth', 'stroustrup',
]


def generate_session_id(workspace_name: str) -> str:
    """Generate a human-readable session ID.

    Args:
        workspace_name: Name of the workspace directory

    Returns:
        ID in format '<workspace>-<adjective>-<noun>'

    Example:
        >>> generate_session_id('myapp')
        'myapp-happy-turing'
    """
    adjective = random.choice(ADJECTIVES)
    noun = random.choice(NOUNS)
    return f'{workspace_name}-{adjective}-{noun}'
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_words.py -v
```
Expected: 3 passed

**Step 5: Commit**

```bash
git add lib/vibedom/words.py tests/test_words.py
git commit -m "feat: add word list module for session ID generation"
```

---

## Task 2: SessionState Dataclass

**Files:**
- Modify: `lib/vibedom/session.py` (add `SessionState` class before `Session`)
- Create: `tests/test_session_state.py`

**Step 1: Write the failing test**

```python
# tests/test_session_state.py
import json
import pytest
from pathlib import Path
from datetime import datetime
from vibedom.session import SessionState


def test_create_sets_all_fields():
    workspace = Path('/Users/test/myapp')
    state = SessionState.create(workspace, 'docker')
    assert state.workspace == '/Users/test/myapp'
    assert state.runtime == 'docker'
    assert state.container_name == 'vibedom-myapp'
    assert state.status == 'running'
    assert state.session_id.startswith('myapp-')
    assert state.ended_at is None
    assert state.bundle_path is None


def test_create_apple_runtime():
    state = SessionState.create(Path('/Users/test/myapp'), 'apple')
    assert state.runtime == 'apple'


def test_save_and_load_roundtrip(tmp_path):
    state = SessionState.create(Path('/Users/test/myapp'), 'docker')
    state.save(tmp_path)
    assert (tmp_path / 'state.json').exists()
    loaded = SessionState.load(tmp_path)
    assert loaded.session_id == state.session_id
    assert loaded.workspace == state.workspace
    assert loaded.runtime == state.runtime
    assert loaded.status == state.status


def test_load_missing_state_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        SessionState.load(tmp_path)


def test_mark_complete(tmp_path):
    state = SessionState.create(Path('/Users/test/myapp'), 'docker')
    state.save(tmp_path)
    bundle = tmp_path / 'repo.bundle'
    state.mark_complete(bundle, tmp_path)
    assert state.status == 'complete'
    assert state.bundle_path == str(bundle)
    assert state.ended_at is not None
    # Verify persisted
    reloaded = SessionState.load(tmp_path)
    assert reloaded.status == 'complete'


def test_mark_abandoned(tmp_path):
    state = SessionState.create(Path('/Users/test/myapp'), 'docker')
    state.save(tmp_path)
    state.mark_abandoned(tmp_path)
    assert state.status == 'abandoned'
    assert state.ended_at is not None
    reloaded = SessionState.load(tmp_path)
    assert reloaded.status == 'abandoned'


def test_started_at_dt_is_datetime():
    state = SessionState.create(Path('/Users/test/myapp'), 'docker')
    assert isinstance(state.started_at_dt, datetime)
```

**Step 2: Run to verify fails**

```bash
pytest tests/test_session_state.py -v
```
Expected: `ImportError: cannot import name 'SessionState'`

**Step 3: Write minimal implementation**

Add at the top of `lib/vibedom/session.py`, after existing imports:

```python
# Add to imports at top of session.py
from dataclasses import dataclass, asdict
```

Add `SessionState` class before the existing `Session` class:

```python
@dataclass
class SessionState:
    """Represents the persisted state of a session (state.json)."""

    session_id: str
    workspace: str
    runtime: str
    container_name: str
    status: str          # 'running' | 'complete' | 'abandoned'
    started_at: str      # ISO 8601 string
    ended_at: Optional[str] = None
    bundle_path: Optional[str] = None

    @classmethod
    def create(cls, workspace: Path, runtime: str) -> 'SessionState':
        """Create a new SessionState for a fresh session."""
        from vibedom.words import generate_session_id
        session_id = generate_session_id(workspace.name)
        return cls(
            session_id=session_id,
            workspace=str(workspace),
            runtime=runtime,
            container_name=f'vibedom-{workspace.name}',
            status='running',
            started_at=datetime.now().isoformat(timespec='seconds'),
        )

    @classmethod
    def load(cls, session_dir: Path) -> 'SessionState':
        """Load state from session directory."""
        state_file = session_dir / 'state.json'
        data = json.loads(state_file.read_text())
        return cls(**data)

    def save(self, session_dir: Path) -> None:
        """Persist state to session directory."""
        state_file = session_dir / 'state.json'
        state_file.write_text(json.dumps(asdict(self), indent=2))

    def mark_complete(self, bundle_path: Path, session_dir: Path) -> None:
        """Transition to complete status and persist."""
        self.status = 'complete'
        self.ended_at = datetime.now().isoformat(timespec='seconds')
        self.bundle_path = str(bundle_path)
        self.save(session_dir)

    def mark_abandoned(self, session_dir: Path) -> None:
        """Transition to abandoned status and persist."""
        self.status = 'abandoned'
        self.ended_at = datetime.now().isoformat(timespec='seconds')
        self.save(session_dir)

    @property
    def started_at_dt(self) -> datetime:
        """started_at as a datetime object."""
        return datetime.fromisoformat(self.started_at)
```

**Step 4: Run to verify passes**

```bash
pytest tests/test_session_state.py -v
```
Expected: 7 passed

**Step 5: Commit**

```bash
git add lib/vibedom/session.py tests/test_session_state.py
git commit -m "feat: add SessionState dataclass with state.json I/O"
```

---

## Task 3: Update Session Class

Replace ad-hoc `Session.__init__` with a `Session.start()` classmethod, add `Session.load()` for existing sessions, update `finalize()`, and add `is_container_running()` / display properties.

**Files:**
- Modify: `lib/vibedom/session.py` (`Session` class)
- Modify: `tests/test_session.py` (update existing tests)

**Step 1: Write the failing tests**

Add to `tests/test_session.py` (keep existing tests, add these):

```python
from vibedom.session import Session, SessionState

def test_session_start_creates_state_json(tmp_path):
    """Session.start() should write state.json."""
    session = Session.start(tmp_path / 'myapp', 'docker', tmp_path / 'logs')
    assert (session.session_dir / 'state.json').exists()
    assert session.state.status == 'running'
    assert session.state.runtime == 'docker'

def test_session_load_from_existing_dir(tmp_path):
    """Session.load() should restore session from state.json."""
    # Create a session first
    session = Session.start(tmp_path / 'myapp', 'docker', tmp_path / 'logs')
    session_dir = session.session_dir
    # Load it back
    loaded = Session.load(session_dir)
    assert loaded.state.session_id == session.state.session_id
    assert loaded.state.workspace == session.state.workspace

def test_session_is_container_running_docker(tmp_path):
    """is_container_running uses state.runtime, not a parameter."""
    from unittest.mock import patch, MagicMock
    session = Session.start(tmp_path / 'myapp', 'docker', tmp_path / 'logs')
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout='vibedom-myapp\n')
        assert session.is_container_running() is True
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == 'docker'

def test_session_is_container_running_apple(tmp_path):
    """is_container_running uses 'container' command for apple runtime."""
    from unittest.mock import patch, MagicMock
    session = Session.start(tmp_path / 'myapp', 'apple', tmp_path / 'logs')
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout='vibedom-myapp\n')
        session.is_container_running()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == 'container'

def test_session_is_not_running_for_complete_status(tmp_path):
    """is_container_running returns False without subprocess for non-running sessions."""
    from unittest.mock import patch
    session = Session.start(tmp_path / 'myapp', 'docker', tmp_path / 'logs')
    session.state.status = 'complete'
    with patch('subprocess.run') as mock_run:
        assert session.is_container_running() is False
        mock_run.assert_not_called()

def test_session_age_str(tmp_path):
    """age_str should return human-readable age."""
    session = Session.start(tmp_path / 'myapp', 'docker', tmp_path / 'logs')
    # Just started — should be seconds old
    assert 'second' in session.age_str or 'minute' in session.age_str

def test_session_display_name(tmp_path):
    """display_name includes session_id, workspace name, status, and age."""
    session = Session.start(tmp_path / 'myapp', 'docker', tmp_path / 'logs')
    name = session.display_name
    assert 'myapp' in name
    assert 'running' in name
```

**Step 2: Run to verify fails**

```bash
pytest tests/test_session.py -v -k "start or load or is_container or age_str or display_name"
```
Expected: failures — `Session` has no `start`, `load`, `is_container_running`, `age_str`, `display_name`

**Step 3: Rewrite the Session class**

Replace the existing `Session` class in `lib/vibedom/session.py` with:

```python
class Session:
    """Manages a sandbox session: lifecycle, state, and logging."""

    def __init__(self, state: SessionState, session_dir: Path):
        self.state = state
        self.session_dir = session_dir
        self.network_log = session_dir / 'network.jsonl'
        self.session_log = session_dir / 'session.log'

    @classmethod
    def start(cls, workspace: Path, runtime: str, logs_dir: Path) -> 'Session':
        """Create and initialise a new session.

        Args:
            workspace: Resolved path to workspace directory
            runtime: Container runtime ('docker' or 'apple')
            logs_dir: Base directory for all session logs

        Returns:
            New Session with state.json written and initial log entry

        Example:
            >>> session = Session.start(Path('/projects/myapp'), 'docker', logs_dir)
        """
        state = SessionState.create(workspace, runtime)
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        session_dir = logs_dir / f'session-{timestamp}'
        session_dir.mkdir(parents=True, exist_ok=True)
        state.save(session_dir)
        session = cls(state, session_dir)
        session.log_event(f'Session started for workspace: {workspace}')
        return session

    @classmethod
    def load(cls, session_dir: Path) -> 'Session':
        """Load an existing session from its directory.

        Args:
            session_dir: Path to session directory containing state.json

        Returns:
            Session restored from state.json
        """
        state = SessionState.load(session_dir)
        return cls(state, session_dir)

    def is_container_running(self) -> bool:
        """Check if this session's container is currently running.

        Returns False immediately (without subprocess call) if state is not 'running'.
        """
        if self.state.status != 'running':
            return False
        runtime_cmd = 'container' if self.state.runtime == 'apple' else 'docker'
        try:
            result = subprocess.run(
                [runtime_cmd, 'ps', '--filter', f'name={self.state.container_name}',
                 '--format', '{{.Names}}'],
                capture_output=True, text=True, check=False
            )
            return any(
                line.strip() == self.state.container_name
                for line in result.stdout.splitlines()
            )
        except Exception:
            return False

    @property
    def age_str(self) -> str:
        """Human-readable age of this session (e.g. '2h ago', '3d ago')."""
        age = datetime.now() - self.state.started_at_dt
        if age.days > 0:
            n = age.days
            return f"{n} day{'s' if n > 1 else ''} ago"
        hours = age.seconds // 3600
        if hours > 0:
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        minutes = age.seconds // 60
        if minutes > 0:
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        n = age.seconds
        return f"{n} second{'s' if n != 1 else ''} ago"

    @property
    def display_name(self) -> str:
        """One-line display string for list output."""
        workspace_name = Path(self.state.workspace).name
        return f"{self.state.session_id} ({workspace_name}, {self.state.status}, {self.age_str})"

    def log_network_request(
        self,
        method: str,
        url: str,
        allowed: bool,
        reason: Optional[str] = None
    ) -> None:
        """Log a network request to network.jsonl."""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'method': method,
            'url': url,
            'allowed': allowed,
            'reason': reason,
        }
        try:
            with open(self.network_log, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except (IOError, OSError) as e:
            import sys
            print(f"Warning: Failed to log network request: {e}", file=sys.stderr)

    def log_event(self, message: str, level: str = 'INFO') -> None:
        """Log an event to session.log."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        entry = f'[{timestamp}] {level}: {message}\n'
        try:
            with open(self.session_log, 'a') as f:
                f.write(entry)
        except (IOError, OSError) as e:
            import sys
            print(f"Warning: Failed to log event: {e}", file=sys.stderr)

    def create_bundle(self) -> Optional[Path]:
        """Create git bundle from session repository.

        Returns:
            Path to bundle file if successful, None if creation failed

        Example:
            >>> bundle_path = session.create_bundle()
            >>> if bundle_path:
            ...     # git remote add vibedom bundle_path
        """
        bundle_path = self.session_dir / 'repo.bundle'
        repo_dir = self.session_dir / 'repo'
        try:
            self.log_event('Creating git bundle...')
            if not repo_dir.exists():
                self.log_event('Repository directory not found', level='ERROR')
                return None
            subprocess.run(
                ['git', '-C', str(repo_dir), 'bundle', 'create', str(bundle_path), '--all'],
                capture_output=True, check=True, text=True
            )
            verify = subprocess.run(
                ['git', 'bundle', 'verify', str(bundle_path)],
                capture_output=True, check=False, text=True
            )
            if verify.returncode == 0:
                self.log_event(f'Bundle created: {bundle_path}')
                return bundle_path
            else:
                self.log_event(f'Bundle verification failed: {verify.stderr}', level='ERROR')
                return None
        except subprocess.CalledProcessError as e:
            self.log_event(f'Bundle creation failed: {e.stderr}', level='ERROR')
            return None
        except Exception as e:
            self.log_event(f'Unexpected error creating bundle: {e}', level='ERROR')
            return None

    def finalize(self) -> None:
        """Finalize session: create bundle, update state, log end.

        Updates state to 'complete' if bundle is created, 'abandoned' otherwise.
        """
        self.log_event('Finalizing session...')
        bundle_path = self.create_bundle()
        if bundle_path:
            self.state.mark_complete(bundle_path, self.session_dir)
            self.log_event('Session complete')
        else:
            self.state.mark_abandoned(self.session_dir)
            self.log_event('Session abandoned (bundle creation failed)', level='WARN')
```

**Step 4: Update existing session tests**

In `tests/test_session.py`, the existing tests create `Session(workspace, logs_dir)` directly. Update them to use `Session.start()`. For tests that check bundle creation, the interface is the same but `finalize()` now also updates state. Check each test still makes sense and update accordingly.

The key change: replace `Session(workspace_path, logs_dir)` with `Session.start(workspace_path, 'docker', logs_dir)`.

**Step 5: Run all session tests**

```bash
pytest tests/test_session.py tests/test_session_state.py -v
```
Expected: all pass

**Step 6: Commit**

```bash
git add lib/vibedom/session.py tests/test_session.py
git commit -m "feat: update Session class with start/load classmethods and is_container_running"
```

---

## Task 4: SessionRegistry Class

**Files:**
- Modify: `lib/vibedom/session.py` (add `SessionRegistry` after `Session`)
- Create: `tests/test_session_registry.py`

**Step 1: Write the failing tests**

```python
# tests/test_session_registry.py
import json
import pytest
from pathlib import Path
from unittest.mock import patch
from vibedom.session import Session, SessionRegistry


def make_session_dir(logs_dir, name, workspace='/Users/test/myapp',
                     status='running', session_id=None):
    """Helper to create a valid session directory with state.json."""
    ws_name = Path(workspace).name
    sid = session_id or f'{ws_name}-happy-turing'
    d = logs_dir / name
    d.mkdir(parents=True)
    state = {
        'session_id': sid,
        'workspace': workspace,
        'runtime': 'docker',
        'container_name': f'vibedom-{ws_name}',
        'status': status,
        'started_at': '2026-02-19T10:00:00',
        'ended_at': None,
        'bundle_path': None,
    }
    (d / 'state.json').write_text(json.dumps(state))
    return d


def test_all_returns_all_sessions(tmp_path):
    make_session_dir(tmp_path, 'session-20260219-100000-000000')
    make_session_dir(tmp_path, 'session-20260219-110000-000000')
    registry = SessionRegistry(tmp_path)
    sessions = registry.all()
    assert len(sessions) == 2


def test_all_returns_newest_first(tmp_path):
    make_session_dir(tmp_path, 'session-20260219-100000-000000',
                     session_id='myapp-old-session')
    make_session_dir(tmp_path, 'session-20260219-110000-000000',
                     session_id='myapp-new-session')
    registry = SessionRegistry(tmp_path)
    sessions = registry.all()
    assert sessions[0].state.session_id == 'myapp-new-session'


def test_all_skips_dirs_without_state_json(tmp_path):
    (tmp_path / 'session-20260219-100000-000000').mkdir()  # no state.json
    make_session_dir(tmp_path, 'session-20260219-110000-000000')
    registry = SessionRegistry(tmp_path)
    assert len(registry.all()) == 1


def test_all_empty_logs_dir(tmp_path):
    registry = SessionRegistry(tmp_path)
    assert registry.all() == []


def test_running_filters_by_status(tmp_path):
    make_session_dir(tmp_path, 'session-20260219-100000-000000', status='running')
    make_session_dir(tmp_path, 'session-20260219-110000-000000',
                     status='complete', session_id='myapp-complete-one')
    registry = SessionRegistry(tmp_path)
    running = registry.running()
    assert len(running) == 1
    assert running[0].state.status == 'running'


def test_find_by_session_id(tmp_path):
    make_session_dir(tmp_path, 'session-20260219-100000-000000',
                     session_id='myapp-happy-turing')
    registry = SessionRegistry(tmp_path)
    session = registry.find('myapp-happy-turing')
    assert session is not None
    assert session.state.session_id == 'myapp-happy-turing'


def test_find_by_workspace_name(tmp_path):
    make_session_dir(tmp_path, 'session-20260219-100000-000000',
                     workspace='/Users/test/rabbitmq-talk',
                     session_id='rabbitmq-talk-happy-turing')
    registry = SessionRegistry(tmp_path)
    session = registry.find('rabbitmq-talk')
    assert session is not None
    assert 'rabbitmq-talk' in session.state.workspace


def test_find_returns_none_for_unknown(tmp_path):
    registry = SessionRegistry(tmp_path)
    assert registry.find('nonexistent') is None


def test_find_returns_most_recent_for_workspace(tmp_path):
    make_session_dir(tmp_path, 'session-20260219-100000-000000',
                     workspace='/Users/test/myapp', session_id='myapp-old-one')
    make_session_dir(tmp_path, 'session-20260219-110000-000000',
                     workspace='/Users/test/myapp', session_id='myapp-new-one')
    registry = SessionRegistry(tmp_path)
    session = registry.find('myapp')
    assert session.state.session_id == 'myapp-new-one'


def test_resolve_single_running_auto_selects(tmp_path):
    make_session_dir(tmp_path, 'session-20260219-100000-000000', status='running')
    registry = SessionRegistry(tmp_path)
    with patch.object(registry.all()[0].__class__, 'is_container_running', return_value=True):
        session = registry.resolve(None, running_only=True, sessions=registry.running())
    assert session is not None


def test_resolve_with_id_returns_match(tmp_path):
    make_session_dir(tmp_path, 'session-20260219-100000-000000',
                     session_id='myapp-happy-turing')
    registry = SessionRegistry(tmp_path)
    session = registry.resolve('myapp-happy-turing')
    assert session.state.session_id == 'myapp-happy-turing'


def test_resolve_raises_for_unknown_id(tmp_path):
    registry = SessionRegistry(tmp_path)
    import click
    with pytest.raises(SystemExit):
        registry.resolve('nonexistent')
```

**Step 2: Run to verify fails**

```bash
pytest tests/test_session_registry.py -v
```
Expected: `ImportError: cannot import name 'SessionRegistry'`

**Step 3: Write minimal implementation**

Add after the `Session` class in `lib/vibedom/session.py`:

```python
class SessionRegistry:
    """Discovers and resolves sessions from the logs directory."""

    def __init__(self, logs_dir: Path):
        self.logs_dir = logs_dir

    def all(self) -> list[Session]:
        """All sessions, sorted newest first."""
        sessions = []
        for session_dir in sorted(self.logs_dir.glob('session-*'), reverse=True):
            if not session_dir.is_dir():
                continue
            try:
                sessions.append(Session.load(session_dir))
            except (FileNotFoundError, KeyError, json.JSONDecodeError):
                continue
        return sessions

    def running(self) -> list[Session]:
        """Sessions with status 'running'."""
        return [s for s in self.all() if s.state.status == 'running']

    def find(self, id_or_name: str) -> Optional[Session]:
        """Find a session by session ID or workspace name (most recent match)."""
        for session in self.all():
            if session.state.session_id == id_or_name:
                return session
            if Path(session.state.workspace).name == id_or_name:
                return session
        return None

    def resolve(
        self,
        id_or_name: Optional[str],
        running_only: bool = False,
        sessions: Optional[list[Session]] = None,
    ) -> Session:
        """Resolve to a single session, auto-selecting or prompting as needed.

        Args:
            id_or_name: Session ID or workspace name; None means auto-select
            running_only: If True, restrict candidates to running sessions
            sessions: Pre-filtered session list (avoids double-loading)

        Raises:
            SystemExit (via click.ClickException) if no match or ambiguous
        """
        import click
        if id_or_name:
            session = self.find(id_or_name)
            if not session:
                raise click.ClickException(f"No session found for '{id_or_name}'")
            return session

        candidates = sessions if sessions is not None else (
            self.running() if running_only else self.all()
        )

        noun = "running sessions" if running_only else "sessions"
        if not candidates:
            raise click.ClickException(f"No {noun} found")
        if len(candidates) == 1:
            return candidates[0]

        click.echo(f"Multiple {noun} found:")
        for i, s in enumerate(candidates, 1):
            click.echo(f"  {i}. {s.display_name}")
        choice = click.prompt("Select session", type=click.IntRange(1, len(candidates)))
        return candidates[choice - 1]
```

**Step 4: Run to verify passes**

```bash
pytest tests/test_session_registry.py -v
```
Note: `test_resolve_single_running_auto_selects` may need adjustment based on the mock — fix the test rather than the implementation if needed.

**Step 5: Commit**

```bash
git add lib/vibedom/session.py tests/test_session_registry.py
git commit -m "feat: add SessionRegistry for session discovery and resolution"
```

---

## Task 5: Slim Down SessionCleanup

Remove methods that have moved to `Session`/`SessionRegistry`. Update `_filter_by_age` and `_filter_not_running` to work with `Session` objects instead of dicts. Remove `--runtime` parameter since runtime now comes from `state.json`.

**Files:**
- Modify: `lib/vibedom/session.py` (`SessionCleanup` class)
- Modify: `tests/test_session_cleanup.py` (update all tests)

**Step 1: Rewrite the tests first**

Replace `tests/test_session_cleanup.py` entirely:

```python
"""Tests for SessionCleanup filter and delete helpers."""
import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from vibedom.session import Session, SessionCleanup


def make_session(logs_dir, name, status='running', days_old=0,
                 workspace='/Users/test/myapp'):
    """Create a session directory with state.json for testing."""
    d = logs_dir / name
    d.mkdir(parents=True)
    ws_name = Path(workspace).name
    started = (datetime.now() - timedelta(days=days_old)).isoformat(timespec='seconds')
    state = {
        'session_id': f'{ws_name}-happy-turing',
        'workspace': workspace,
        'runtime': 'docker',
        'container_name': f'vibedom-{ws_name}',
        'status': status,
        'started_at': started,
        'ended_at': None,
        'bundle_path': None,
    }
    (d / 'state.json').write_text(json.dumps(state))
    return Session.load(d)


def test_filter_by_age_returns_old_sessions(tmp_path):
    sessions = [
        make_session(tmp_path, 'session-a', days_old=10),
        make_session(tmp_path, 'session-b', days_old=5),
        make_session(tmp_path, 'session-c', days_old=8),
    ]
    old = SessionCleanup._filter_by_age(sessions, days=7)
    assert len(old) == 2


def test_filter_by_age_excludes_recent(tmp_path):
    sessions = [make_session(tmp_path, 'session-a', days_old=2)]
    assert SessionCleanup._filter_by_age(sessions, days=7) == []


def test_filter_not_running_excludes_complete(tmp_path):
    sessions = [
        make_session(tmp_path, 'session-a', status='running'),
        make_session(tmp_path, 'session-b', status='complete'),
        make_session(tmp_path, 'session-c', status='abandoned'),
    ]
    not_running = SessionCleanup._filter_not_running(sessions)
    assert len(not_running) == 2
    assert all(s.state.status != 'running' for s in not_running)


def test_delete_session(tmp_path):
    d = tmp_path / 'session-to-delete'
    d.mkdir()
    (d / 'file.txt').write_text('test')
    SessionCleanup._delete_session(d)
    assert not d.exists()


def test_delete_session_handles_missing_dir(tmp_path):
    # Should not raise
    SessionCleanup._delete_session(tmp_path / 'nonexistent')
```

**Step 2: Run to verify tests fail for the right reason**

```bash
pytest tests/test_session_cleanup.py -v
```
Expected: failures because `_filter_by_age`/`_filter_not_running` still expect dicts, not Session objects

**Step 3: Rewrite SessionCleanup**

Replace the entire `SessionCleanup` class in `lib/vibedom/session.py`:

```python
class SessionCleanup:
    """Filter and delete helpers for prune/housekeeping commands."""

    @staticmethod
    def _filter_by_age(sessions: list[Session], days: int) -> list[Session]:
        """Return sessions older than N days."""
        cutoff = datetime.now() - timedelta(days=days)
        return [s for s in sessions if s.state.started_at_dt < cutoff]

    @staticmethod
    def _filter_not_running(sessions: list[Session]) -> list[Session]:
        """Return sessions whose status is not 'running'."""
        return [s for s in sessions if s.state.status != 'running']

    @staticmethod
    def _delete_session(session_dir: Path) -> None:
        """Delete a session directory."""
        try:
            shutil.rmtree(session_dir, ignore_errors=True)
        except Exception:
            pass
```

Note: `_filter_not_running` no longer calls `subprocess` — it relies on `state.status`. If a container crashed without updating state, `prune` will still skip it (status says 'running'). This is the safe failure mode: we skip rather than accidentally delete an active session.

**Step 4: Run to verify passes**

```bash
pytest tests/test_session_cleanup.py -v
```
Expected: all pass

**Step 5: Run full suite to check no regressions**

```bash
pytest tests/ -v --ignore=tests/test_vm.py --ignore=tests/test_proxy.py \
  --ignore=tests/test_https_proxy.py --ignore=tests/test_git_workflow.py
```
Fix any failures before continuing.

**Step 6: Commit**

```bash
git add lib/vibedom/session.py tests/test_session_cleanup.py
git commit -m "refactor: slim SessionCleanup to filter/delete helpers, use Session objects"
```

---

## Task 6: Update vibedom run

Update `vibedom run` to use `Session.start()` and write `state.json`. Remove `--runtime` from all commands except `run` (those commands will read it from state).

**Files:**
- Modify: `lib/vibedom/cli.py`

**Step 1: Write a failing test**

Add to `tests/test_cli.py`:

```python
def test_run_writes_state_json(tmp_path):
    """vibedom run should write state.json to the session directory."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    logs_dir = tmp_path / '.vibedom' / 'logs'

    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        with patch('vibedom.cli.scan_workspace', return_value=[]):
            with patch('vibedom.cli.review_findings', return_value=True):
                with patch('vibedom.cli.VMManager') as mock_vm_cls:
                    mock_vm = MagicMock()
                    mock_vm_cls.return_value = mock_vm
                    with patch('vibedom.cli.VMManager._detect_runtime',
                               return_value=('docker', 'docker')):
                        result = runner.invoke(main, ['run', str(workspace)])

    # Find the session directory that was created
    session_dirs = list((tmp_path / '.vibedom' / 'logs').glob('session-*'))
    assert len(session_dirs) == 1
    state_file = session_dirs[0] / 'state.json'
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state['status'] == 'running'
    assert state['workspace'] == str(workspace)
```

**Step 2: Run to verify fails**

```bash
pytest tests/test_cli.py::test_run_writes_state_json -v
```
Expected: FAIL — `state.json` not created

**Step 3: Update `vibedom run` in cli.py**

Find the `run` command and update it to use `Session.start()`:

```python
@main.command()
@click.argument('workspace', type=click.Path(exists=True))
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple'],
              case_sensitive=False), default='auto',
              help='Container runtime (auto-detect, docker, or apple)')
def run(workspace, runtime):
    """Run AI agent in sandboxed environment."""
    workspace_path = Path(workspace).resolve()
    if not workspace_path.is_dir():
        click.secho(f"❌ Error: {workspace_path} is not a directory", fg='red')
        sys.exit(1)

    logs_dir = Path.home() / '.vibedom' / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Resolve runtime before starting session
    try:
        resolved_runtime, _ = VMManager._detect_runtime(
            runtime if runtime != 'auto' else None
        )
    except RuntimeError as e:
        click.secho(f"❌ {e}", fg='red')
        sys.exit(1)

    session = Session.start(workspace_path, resolved_runtime, logs_dir)
    session.log_event('Starting sandbox...')

    try:
        click.echo("🔍 Scanning for secrets...")
        findings = scan_workspace(workspace_path)

        if not review_findings(findings):
            session.log_event('Cancelled by user', level='WARN')
            session.state.mark_abandoned(session.session_dir)
            click.secho("❌ Cancelled", fg='yellow')
            sys.exit(1)

        click.echo("🚀 Starting sandbox...")
        config_dir = Path.home() / '.vibedom'
        vm = VMManager(workspace_path, config_dir,
                       session_dir=session.session_dir, runtime=resolved_runtime)
        vm.start()

        session.log_event('VM started successfully')

        click.echo(f"\n✅ Sandbox running!")
        click.echo(f"📋 Session ID: {session.state.session_id}")
        click.echo(f"📁 Session: {session.session_dir}")
        click.echo(f"📦 Live repo: {session.session_dir / 'repo'}")
        click.echo(f"\n💡 To test changes mid-session:")
        click.echo(f"  git remote add vibedom-live {session.session_dir / 'repo'}")
        click.echo(f"  git fetch vibedom-live")
        click.echo(f"\n🛑 To stop:")
        click.echo(f"  vibedom stop {session.state.session_id}")

    except Exception as e:
        session.log_event(f'Error: {e}', level='ERROR')
        session.state.mark_abandoned(session.session_dir)
        click.secho(f"❌ Error: {e}", fg='red')
        sys.exit(1)
```

Also remove the `find_latest_session` function and `_format_session_info` from `cli.py` — these are no longer needed. Session display goes through `session.display_name` and `session.age_str`.

Also remove the `_execute_deletions` dependency on `_format_session_info` — update it to use `session.display_name` (see Task 10).

**Step 4: Run to verify passes**

```bash
pytest tests/test_cli.py::test_run_writes_state_json -v
```

**Step 5: Commit**

```bash
git add lib/vibedom/cli.py
git commit -m "feat: update vibedom run to use Session.start() and write state.json"
```

---

## Task 7: Update vibedom stop

Replace log-file-based session lookup with `SessionRegistry.resolve()`. Remove `--runtime` flag (runtime read from state). Support session ID or workspace name as argument.

**Files:**
- Modify: `lib/vibedom/cli.py`
- Modify: `tests/test_cli.py`

**Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def test_stop_uses_session_registry(tmp_path):
    """stop should find session via SessionRegistry, not log parsing."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260219-100000-000000'
    session_dir.mkdir(parents=True)
    state = {
        'session_id': 'myapp-happy-turing',
        'workspace': str(workspace),
        'runtime': 'docker',
        'container_name': 'vibedom-myapp',
        'status': 'running',
        'started_at': '2026-02-19T10:00:00',
        'ended_at': None,
        'bundle_path': None,
    }
    (session_dir / 'state.json').write_text(json.dumps(state))

    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        with patch('vibedom.cli.VMManager') as mock_vm_cls:
            mock_vm = MagicMock()
            mock_vm_cls.return_value = mock_vm
            # Mock bundle creation (no real repo dir)
            with patch('vibedom.session.Session.create_bundle', return_value=None):
                result = runner.invoke(main, ['stop', 'myapp-happy-turing'])

    assert result.exit_code == 0
```

**Step 2: Run to verify fails**

```bash
pytest tests/test_cli.py::test_stop_uses_session_registry -v
```

**Step 3: Rewrite `vibedom stop` in cli.py**

```python
@main.command()
@click.argument('session_id', required=False)
def stop(session_id):
    """Stop a sandbox session and create git bundle.

    SESSION_ID is a session ID (e.g. myapp-happy-turing) or workspace name.
    If omitted, auto-selects the only running session or prompts.
    """
    logs_dir = Path.home() / '.vibedom' / 'logs'
    registry = SessionRegistry(logs_dir)

    if session_id is None:
        # Auto-select or prompt from running sessions
        running = registry.running()
        try:
            session = registry.resolve(None, running_only=True, sessions=running)
        except SystemExit:
            click.echo("No running sessions")
            return
    else:
        session = registry.find(session_id)
        if not session:
            click.secho(f"❌ No session found for '{session_id}'", fg='red')
            sys.exit(1)

    # Determine runtime command from state
    runtime_cmd = 'container' if session.state.runtime == 'apple' else 'docker'

    # Create bundle + finalize (updates state.json)
    click.echo("Creating git bundle...")
    session.finalize()

    # Stop the container
    config_dir = Path.home() / '.vibedom'
    vm = VMManager(Path(session.state.workspace), config_dir,
                   session_dir=session.session_dir,
                   runtime=session.state.runtime)
    vm.stop()

    if session.state.status == 'complete' and session.state.bundle_path:
        bundle_path = Path(session.state.bundle_path)
        try:
            current_branch = subprocess.run(
                ['git', '-C', session.state.workspace, 'rev-parse',
                 '--abbrev-ref', 'HEAD'],
                capture_output=True, text=True, check=True
            ).stdout.strip()
        except subprocess.CalledProcessError:
            current_branch = 'main'

        click.echo(f"\n✅ Session complete!")
        click.echo(f"📋 Session ID: {session.state.session_id}")
        click.echo(f"📦 Bundle: {bundle_path}")
        click.echo(f"\n📋 To review: vibedom review {session.state.session_id}")
        click.echo(f"🔀 To merge:  vibedom merge {session.state.session_id}")
    else:
        click.secho(f"⚠️  Bundle creation failed", fg='yellow')
        click.echo(f"📁 Live repo available: {session.session_dir / 'repo'}")

    # Handle "stop all" by removing --no-workspace path; users run vibedom stop
    # with no args and get prompted if multiple sessions running.
```

Also update the "stop all containers" path: since `stop` no longer has a workspace argument that can be a path, the old "stop all" behavior (no workspace → stop all containers) is replaced by the prompt logic. If users want to stop all, they run `vibedom stop` and select each one in turn. Document this change.

**Step 4: Update tests for the old stop command that used workspace path**

The existing stop-related tests in `test_cli.py` use workspace paths. These need to be updated to use session IDs or removed if duplicated by the new test.

**Step 5: Run to verify**

```bash
pytest tests/test_cli.py -v -k "stop"
```

**Step 6: Commit**

```bash
git add lib/vibedom/cli.py tests/test_cli.py
git commit -m "feat: update vibedom stop to use SessionRegistry, accept session ID"
```

---

## Task 8: Add vibedom list

**Files:**
- Modify: `lib/vibedom/cli.py`
- Create: `tests/test_list.py`

**Step 1: Write the failing test**

```python
# tests/test_list.py
import json
from pathlib import Path
from click.testing import CliRunner
from unittest.mock import patch
from vibedom.cli import main


def make_state(logs_dir, session_name, session_id, workspace, status):
    d = logs_dir / session_name
    d.mkdir(parents=True)
    ws_name = Path(workspace).name
    (d / 'state.json').write_text(json.dumps({
        'session_id': session_id,
        'workspace': workspace,
        'runtime': 'docker',
        'container_name': f'vibedom-{ws_name}',
        'status': status,
        'started_at': '2026-02-19T10:00:00',
        'ended_at': None,
        'bundle_path': None,
    }))


def test_list_shows_sessions(tmp_path):
    logs_dir = tmp_path / '.vibedom' / 'logs'
    make_state(logs_dir, 'session-20260219-100000-000000',
               'myapp-happy-turing', '/Users/test/myapp', 'running')
    make_state(logs_dir, 'session-20260219-090000-000000',
               'ifs-bridge-calm-lovelace', '/Users/test/ifs-bridge', 'complete')

    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        result = runner.invoke(main, ['list'])

    assert result.exit_code == 0
    assert 'myapp-happy-turing' in result.output
    assert 'ifs-bridge-calm-lovelace' in result.output
    assert 'running' in result.output
    assert 'complete' in result.output


def test_list_no_sessions(tmp_path):
    (tmp_path / '.vibedom' / 'logs').mkdir(parents=True)
    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        result = runner.invoke(main, ['list'])
    assert result.exit_code == 0
    assert 'No sessions' in result.output


def test_list_no_logs_dir(tmp_path):
    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        result = runner.invoke(main, ['list'])
    assert result.exit_code == 0
    assert 'No sessions' in result.output
```

**Step 2: Run to verify fails**

```bash
pytest tests/test_list.py -v
```
Expected: `list` command not found

**Step 3: Add `vibedom list` to cli.py**

```python
@main.command('list')
def list_sessions():
    """List all sessions with their status."""
    logs_dir = Path.home() / '.vibedom' / 'logs'
    if not logs_dir.exists():
        click.echo("No sessions found")
        return

    registry = SessionRegistry(logs_dir)
    sessions = registry.all()

    if not sessions:
        click.echo("No sessions found")
        return

    # Header
    click.echo(f"{'ID':<40} {'WORKSPACE':<20} {'STATUS':<12} {'STARTED'}")
    click.echo('-' * 85)
    for session in sessions:
        workspace_name = Path(session.state.workspace).name
        click.echo(
            f"{session.state.session_id:<40} "
            f"{workspace_name:<20} "
            f"{session.state.status:<12} "
            f"{session.age_str}"
        )
```

Also add `SessionRegistry` to the import from `vibedom.session` at the top of `cli.py`.

**Step 4: Run to verify passes**

```bash
pytest tests/test_list.py -v
```

**Step 5: Commit**

```bash
git add lib/vibedom/cli.py tests/test_list.py
git commit -m "feat: add vibedom list command"
```

---

## Task 9: Add vibedom attach, Remove vibedom shell

**Files:**
- Modify: `lib/vibedom/cli.py` (add `attach`, remove `shell`)
- Modify: `tests/test_cli.py` (remove shell tests, add attach tests)

**Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def test_attach_execs_into_running_session(tmp_path):
    """attach should exec into the running session's container."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260219-100000-000000'
    session_dir.mkdir(parents=True)
    (session_dir / 'state.json').write_text(json.dumps({
        'session_id': 'myapp-happy-turing',
        'workspace': str(workspace),
        'runtime': 'docker',
        'container_name': 'vibedom-myapp',
        'status': 'running',
        'started_at': '2026-02-19T10:00:00',
        'ended_at': None,
        'bundle_path': None,
    }))

    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(main, ['attach', 'myapp-happy-turing'])

    assert result.exit_code == 0
    cmd = mock_run.call_args[0][0]
    assert 'exec' in cmd
    assert '-it' in cmd
    assert '/work/repo' in cmd
    assert 'vibedom-myapp' in cmd
    assert 'bash' in cmd


def test_attach_uses_container_cmd_for_apple(tmp_path):
    """attach should use 'container' command for apple runtime."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260219-100000-000000'
    session_dir.mkdir(parents=True)
    (session_dir / 'state.json').write_text(json.dumps({
        'session_id': 'myapp-happy-turing',
        'workspace': str(workspace),
        'runtime': 'apple',
        'container_name': 'vibedom-myapp',
        'status': 'running',
        'started_at': '2026-02-19T10:00:00',
        'ended_at': None,
        'bundle_path': None,
    }))

    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(main, ['attach', 'myapp-happy-turing'])

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == 'container'
```

**Step 2: Run to verify fails**

```bash
pytest tests/test_cli.py::test_attach_execs_into_running_session -v
```
Expected: `attach` command not found

**Step 3: Add attach, remove shell in cli.py**

Remove the entire `shell` command from `cli.py`.

Add in its place:

```python
@main.command('attach')
@click.argument('session_id', required=False)
def attach(session_id):
    """Open a shell in a running session's workspace (/work/repo).

    SESSION_ID is a session ID or workspace name.
    If omitted, auto-selects the only running session or prompts.
    """
    logs_dir = Path.home() / '.vibedom' / 'logs'
    registry = SessionRegistry(logs_dir)
    running = registry.running()

    try:
        session = registry.resolve(session_id, running_only=True, sessions=running)
    except SystemExit:
        click.secho("❌ No running sessions found", fg='red')
        sys.exit(1)

    runtime_cmd = 'container' if session.state.runtime == 'apple' else 'docker'
    cmd = [runtime_cmd, 'exec', '-it', '-w', '/work/repo',
           session.state.container_name, 'bash']
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        click.secho(f"❌ Failed to attach to container", fg='red')
        sys.exit(1)
    except FileNotFoundError:
        click.secho(f"❌ Error: {runtime_cmd} command not found", fg='red')
        sys.exit(1)
```

**Step 4: Delete shell tests from test_cli.py**

Remove `test_shell_command_docker` and `test_shell_command_apple_container`.

**Step 5: Run to verify**

```bash
pytest tests/test_cli.py -v -k "attach"
```

**Step 6: Commit**

```bash
git add lib/vibedom/cli.py tests/test_cli.py
git commit -m "feat: add vibedom attach command, remove vibedom shell"
```

---

## Task 10: Update prune, housekeeping, review, merge

Update these commands to use `SessionRegistry` and drop `--runtime` flags. Update `_execute_deletions` to use `session.display_name`.

**Files:**
- Modify: `lib/vibedom/cli.py`
- Modify: `tests/test_prune.py`
- Modify: `tests/test_cli.py` (review/merge tests)

**Step 1: Update test_prune.py**

Replace the session directory setup in both dry-run tests to use `state.json` instead of `session.log`:

```python
def test_prune_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260216-171057-123456'
    session_dir.mkdir(parents=True)
    (session_dir / 'state.json').write_text(json.dumps({
        'session_id': 'myapp-happy-turing',
        'workspace': '/Users/test/myapp',
        'runtime': 'docker',
        'container_name': 'vibedom-myapp',
        'status': 'complete',   # not running → eligible for prune
        'started_at': '2026-02-16T17:10:57',
        'ended_at': '2026-02-16T18:00:00',
        'bundle_path': None,
    }))

    runner = CliRunner()
    result = runner.invoke(main, ['prune', '--dry-run'])
    assert result.exit_code == 0
    assert 'Would delete' in result.output
    assert session_dir.exists()


def test_housekeeping_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260210-171057-123456'
    session_dir.mkdir(parents=True)
    (session_dir / 'state.json').write_text(json.dumps({
        'session_id': 'myapp-old-session',
        'workspace': '/Users/test/myapp',
        'runtime': 'docker',
        'container_name': 'vibedom-myapp',
        'status': 'complete',
        'started_at': '2026-02-10T17:10:57',
        'ended_at': '2026-02-10T18:00:00',
        'bundle_path': None,
    }))

    runner = CliRunner()
    result = runner.invoke(main, ['housekeeping', '--days', '3', '--dry-run'])
    assert result.exit_code == 0
    assert 'Would delete' in result.output
    assert session_dir.exists()
```

**Step 2: Update prune and housekeeping commands**

In `cli.py`, update `prune`:

```python
@main.command()
@click.option('--force', '-f', is_flag=True, help='Delete without prompting')
@click.option('--dry-run', is_flag=True, help='Preview without deleting')
def prune(force: bool, dry_run: bool) -> None:
    """Remove all session directories without running containers."""
    logs_dir = Path.home() / '.vibedom' / 'logs'
    registry = SessionRegistry(logs_dir)
    sessions = registry.all()
    to_delete = SessionCleanup._filter_not_running(sessions)
    skipped = len(sessions) - len(to_delete)

    if not to_delete:
        click.echo("No sessions to delete")
        return

    click.echo(f"Found {len(to_delete)} session(s) to delete")
    _execute_deletions(to_delete, skipped, force, dry_run)
```

Update `housekeeping`:

```python
@main.command()
@click.option('--days', '-d', default=7, help='Delete sessions older than N days')
@click.option('--force', '-f', is_flag=True, help='Delete without prompting')
@click.option('--dry-run', is_flag=True, help='Preview without deleting')
def housekeeping(days: int, force: bool, dry_run: bool) -> None:
    """Remove sessions older than N days without running containers."""
    logs_dir = Path.home() / '.vibedom' / 'logs'
    registry = SessionRegistry(logs_dir)
    sessions = registry.all()
    old_sessions = SessionCleanup._filter_by_age(sessions, days)
    to_delete = SessionCleanup._filter_not_running(old_sessions)
    skipped = len(old_sessions) - len(to_delete)

    if not to_delete:
        click.echo(f"No sessions older than {days} days")
        return

    click.echo(f"Found {len(to_delete)} session(s) older than {days} days")
    _execute_deletions(to_delete, skipped, force, dry_run)
```

Update `_execute_deletions` to use `session.display_name` instead of `_format_session_info`:

```python
def _execute_deletions(to_delete: list, skipped: int, force: bool, dry_run: bool) -> None:
    deleted = 0
    for session in to_delete:
        name = session.display_name
        if dry_run:
            click.echo(f"Would delete: {name}")
            deleted += 1
        elif force or click.confirm(f"Delete {name}?", default=True):
            SessionCleanup._delete_session(session.session_dir)
            click.echo(f"✓ Deleted {name}")
            deleted += 1

    if dry_run:
        click.echo(f"\nWould delete {deleted} session(s), skip {skipped} (still running)")
    else:
        click.echo(f"\n✅ Deleted {deleted} session(s), skipped {skipped} (still running)")
```

Remove `_format_session_info` from `cli.py` — it's no longer used.

**Step 3: Update review and merge to use SessionRegistry**

Both commands currently use `find_latest_session()` (now removed) and `--runtime` flag (now removed). Update them to use `SessionRegistry.find()`:

In `review` and `merge`, replace:
```python
# OLD
logs_dir = Path.home() / '.vibedom' / 'logs'
session_dir = find_latest_session(workspace_path, logs_dir)
```

With:
```python
# NEW
logs_dir = Path.home() / '.vibedom' / 'logs'
registry = SessionRegistry(logs_dir)
session_obj = registry.find(workspace_path.name)
if not session_obj:
    click.secho(f"❌ No session found for {workspace_path.name}", fg='red')
    sys.exit(1)
session_dir = session_obj.session_dir
```

Also remove `--runtime` flag from both `review` and `merge` commands and replace `VMManager._detect_runtime()` calls with reading from `session_obj.state.runtime`.

In `review`, replace the container running check:
```python
# OLD
result = subprocess.run([runtime_cmd, 'ps', '-q', '--filter', ...], ...)
if result.stdout.strip():
    # running
```
With:
```python
# NEW
if session_obj.is_container_running():
    click.secho(f"❌ Session is still running", fg='red')
    sys.exit(1)
```

**Step 4: Update review/merge tests in test_cli.py**

The existing tests create session directories with `session.log`. Update them to create `state.json` using the helper at the top of this plan. Remove the `--runtime` mock from tests that use `VMManager._detect_runtime`.

**Step 5: Run full suite**

```bash
pytest tests/ -v --ignore=tests/test_vm.py --ignore=tests/test_proxy.py \
  --ignore=tests/test_https_proxy.py --ignore=tests/test_git_workflow.py
```

All non-Docker tests must pass.

**Step 6: Commit**

```bash
git add lib/vibedom/cli.py tests/test_prune.py tests/test_cli.py
git commit -m "feat: update prune/housekeeping/review/merge to use SessionRegistry, drop --runtime flag"
```

---

## Task 11: Final Cleanup and Verification

**Step 1: Remove dead code**

Check for and remove:
- `find_latest_session()` function in `cli.py` (replaced by `SessionRegistry.find()`)
- `_format_session_info()` in `cli.py` (replaced by `session.display_name`)
- `SessionCleanup._parse_timestamp()` — no longer needed
- `SessionCleanup._extract_workspace()` — no longer needed
- `SessionCleanup._is_container_running()` — moved to `Session.is_container_running()`
- `SessionCleanup.find_all_sessions()` — moved to `SessionRegistry.all()`

**Step 2: Run full non-Docker test suite**

```bash
pytest tests/ -v --ignore=tests/test_vm.py --ignore=tests/test_proxy.py \
  --ignore=tests/test_https_proxy.py --ignore=tests/test_git_workflow.py
```

All must pass.

**Step 3: Run ruff lint check**

```bash
ruff check lib/ tests/
```

Fix any violations before committing.

**Step 4: Manual smoke test**

```bash
vibedom --help              # verify list, attach present; shell absent
vibedom list --help
vibedom attach --help
vibedom prune --help        # verify no --runtime flag
vibedom housekeeping --help # verify no --runtime flag
```

**Step 5: Final commit**

```bash
git add -u
git commit -m "refactor: remove dead code after session management redesign"
```
