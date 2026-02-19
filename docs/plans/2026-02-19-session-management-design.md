# Session Management Redesign

**Date:** 2026-02-19
**Status:** Approved

## Problem

Session management has grown organically and has several issues:

- Session state is inferred by parsing `session.log` text — fragile and implicit
- `SessionCleanup` is a bag of static methods, not a real class
- Business logic (formatting, discovery, selection) is scattered across `cli.py`
- Every command that operates on an existing session requires a `--runtime` flag the user has to remember
- No human-readable session identifiers — only opaque timestamp directories
- No `list` command to see what's running
- `shell` and `attach` are conceptually the same thing

## Goals

- Structured session state via `state.json`
- Clean OO model: each class has one clear responsibility
- Session identifiers that are human-readable and unique
- `vibedom list` — see all sessions at a glance
- `vibedom attach` — get a shell into a running session (replaces `shell`)
- Runtime auto-resolved from session state — no `--runtime` flag on post-run commands

## Object Model

### `SessionState`

Owns the `state.json` file. Single source of truth for everything about a session.

```python
@dataclass
class SessionState:
    session_id: str          # e.g. "rabbitmq-talk-happy-einstein"
    workspace: Path
    runtime: str             # "docker" or "apple"
    container_name: str      # e.g. "vibedom-rabbitmq-talk"
    status: str              # "running" | "complete" | "abandoned"
    started_at: datetime
    ended_at: Optional[datetime] = None
    bundle_path: Optional[Path] = None

    @classmethod
    def create(cls, workspace: Path, runtime: str) -> 'SessionState': ...
    @classmethod
    def load(cls, session_dir: Path) -> 'SessionState': ...
    def save(self, session_dir: Path) -> None: ...
    def mark_complete(self, bundle_path: Path) -> None: ...
    def mark_abandoned(self) -> None: ...
```

`create()` generates the session ID and container name. `load()`/`save()` handle JSON serialisation.

### `Session`

Owns the lifecycle of a single sandbox session. Holds a `SessionState` and manages logging.

```python
class Session:
    state: SessionState
    session_dir: Path

    @classmethod
    def start(cls, workspace: Path, runtime: str, logs_dir: Path) -> 'Session': ...

    def log_event(self, message: str, level: str = 'INFO') -> None: ...
    def log_network_request(self, method, url, allowed, reason=None) -> None: ...
    def create_bundle(self) -> Optional[Path]: ...
    def finalize(self, status: str) -> None: ...

    # Derived properties for display
    @property
    def age_str(self) -> str: ...          # "2h ago", "3d ago"
    @property
    def display_name(self) -> str: ...     # "rabbitmq-talk (2h ago) - running"
```

`finalize()` replaces the current split of `session.finalize()` + manual status inference. It accepts the final status explicitly and updates `state.json`.

### `SessionRegistry`

Discovers all sessions from the logs directory. Replaces `SessionCleanup.find_all_sessions()` and the ad-hoc discovery logic in `cli.py`.

```python
class SessionRegistry:
    def __init__(self, logs_dir: Path): ...

    def all(self) -> list[Session]: ...
    def running(self) -> list[Session]: ...
    def find(self, id_or_name: str) -> Optional[Session]: ...
    def resolve(self, id_or_name: Optional[str]) -> Session:
        """Resolve a session from an ID/name, auto-selecting if unambiguous,
        prompting the user if multiple match."""
```

`resolve()` centralises the "one running → auto-select, multiple → prompt, none → error" logic that `stop` and `attach` both need.

### `SessionCleanup` (retained, slimmed down)

Keeps `_filter_by_age`, `_filter_not_running`, and `_delete_session` as static helpers for `prune` and `housekeeping`. Runtime is no longer a parameter — it's read from each session's `state.json`. The `find_all_sessions` method moves to `SessionRegistry`.

## Session ID Format

`<workspace-name>-<adjective>-<noun>` — e.g. `rabbitmq-talk-happy-einstein`

- Generated at `run` time using a bundled word list
- Stored in `state.json` as `session_id`
- Used as the argument to `attach` and `stop`
- Unique enough for practical use; no counter to maintain

## `state.json` Schema

Written to `~/.vibedom/logs/<session-dir>/state.json`:

```json
{
  "session_id": "rabbitmq-talk-happy-einstein",
  "workspace": "/Users/tim/Documents/projects/rabbitmq-talk",
  "runtime": "apple",
  "container_name": "vibedom-rabbitmq-talk",
  "status": "running",
  "started_at": "2026-02-19T17:13:30",
  "ended_at": null,
  "bundle_path": null
}
```

Status transitions:
- `run` writes `status: "running"`
- `stop` writes `status: "complete"` (bundle created) or `status: "abandoned"` (bundle failed)

## CLI Changes

### Removed
- `vibedom shell` — replaced by `vibedom attach`
- `--runtime` flag on `stop`, `attach`, `review`, `merge`, `prune`, `housekeeping` — read from `state.json`

### Modified

**`vibedom run`** — still accepts `--runtime`. Writes `state.json` on start.

**`vibedom stop [id-or-name]`** — now accepts session ID or workspace name in addition to (or instead of) workspace path. Uses `SessionRegistry.resolve()` for selection logic.

### New

**`vibedom list`** — reads all `state.json` files via `SessionRegistry`, displays:

```
ID                            WORKSPACE        STATUS    STARTED
rabbitmq-talk-happy-einstein  rabbitmq-talk    running   2h ago
vibedom-brave-turing          vibedom          complete  3d ago
ifs-bridge-calm-lovelace      ifs-bridge       complete  4d ago
```

**`vibedom attach [id-or-name]`** — replaces `shell`. Restricted to `running` sessions. Uses `SessionRegistry.resolve()`. Runs `exec -it -w /work/repo <container> bash`.

## Testing

- `SessionState`: unit tests for create, load, save, mark_complete, mark_abandoned
- `SessionRegistry`: unit tests for all, running, find, resolve (auto-select, prompt, error cases)
- `Session`: existing tests updated to use new interface
- CLI commands: existing integration tests updated; new tests for `list` and `attach`
- No Docker required for unit tests (mock subprocess)

## Word List

A small bundled word list (100–200 adjectives × 100–200 nouns) gives 10,000–40,000 combinations per workspace. Stored as a Python module in `lib/vibedom/words.py`. No external dependency.
