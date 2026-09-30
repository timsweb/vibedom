# Live-mount-only Vibedom: drop ephemeral sessions and copy+sync

**Date:** 2026-09-30
**Status:** Approved 2026-09-30

## Goal

Vibedom currently offers three ways to get a project into a container:
ephemeral sessions (`run`/`stop` with a git bundle), persistent copy+sync
containers (`/mnt/workspace` read-only plus a repo copy moved with
`pull`/`push`), and persistent live-mount containers (`mounts:`). Users find
the first two confusing. After this change there is exactly one model:

> `vibedom up <dir>` creates a persistent container in which the project's
> real directories are bind-mounted under `/work`. Git is the safety net.
> Network whitelisting, DLP scrubbing and pre-flight secret scanning are
> unchanged.

This is a removal-and-simplification change delivered as one sweep on a
single branch. Nothing new is added beyond what the single model needs.

## Decisions already taken

| Question | Decision |
|---|---|
| Container models | Persistent only. Ephemeral sessions removed outright, no stubs. |
| Filesystem model | Live mount only. Copy+sync removed, including `pull`/`push`. |
| No `mounts:` in `vibedom.yml` (or no yml) | The directory passed to `up` is mounted read-write at `/work/<basename>`. |
| `mounts:` present | It is the complete list, as today. The `up` directory is not auto-mounted; use `- .` to include it. Existing configs keep working. |
| Existing copy+sync containers | `up`, `shell` and `--recreate` refuse with instructions (rescue from the host-side repo copy, then `destroy`). No automatic migration. |
| `vibedom shell` working dir | `/work/<name>` when the container has exactly one mount, `/work` otherwise. |
| Sequencing | One branch, one sweep, one green suite at the end. |

## What goes

### CLI commands (`lib/vibedom/cli.py`)

Removed: `run`, `stop`, `attach`, `review`, `merge`, `list`, `rm`, `prune`,
`housekeeping`, `pull`, `push`. The session-handling half of `proxy-restart`
goes; it becomes container-only. `up --yes/--force` goes: with live mounts
`--recreate` never loses data, so it no longer prompts.

Helpers that exist only for the removed commands go with them:
`_execute_deletions`, `_validate_sync_paths`, `_make_workspace_relative`,
`_build_rsync_cmd`, `_find_deletions`, and any session lookup helpers.

Remaining commands: `init`, `up`, `down`, `destroy`, `status`, `shell`,
`reload-whitelist`, `proxy-restart`.

### Modules

- `lib/vibedom/session.py` deleted (Session, SessionRegistry, bundle logic).
- `lib/vibedom/words.py` deleted (only used for session names).
- `lib/vibedom/review_ui.py` stays: it is the gitleaks findings UI used by `up`.

### VM layer (`lib/vibedom/vm.py`)

- `VMManager.__init__` loses `session_dir`. `mounts` becomes required
  (a non-empty list); the CLI computes the default mount.
- The `/mnt/workspace:ro`, `/work/repo` and `/mnt/session` bind mounts go.
  Only `/mnt/config:ro`, the Claude config volume and the user's mounts remain.
- The `VIBEDOM_LIVE=1` env var goes; startup.sh no longer branches on it.
- `stop()` keeps its stop-and-delete semantics (used by `destroy` and
  `--recreate`); `pause()`/`restart()` unchanged.

### Container image (`lib/vibedom/container/startup.sh`)

`init_repo` shrinks to `cd /work`. The clone-from-`/mnt/workspace`, git-init
snapshot, `.env` copying and rsync fallbacks all go. `ensure_git_identity`,
`start_ssh_agent`, proxy/CA setup and Claude config persistence are unchanged.
`rsync` is removed from `Dockerfile.alpine`; the clone path was its only user.

### Container state (`lib/vibedom/container_state.py`)

`ContainerState` loses `repo_dir` and `live`. `create()` loses the `live`
parameter. Loading an old `container.json` that has `live: false` (or no
`live` key at all, which pre-dates live mounts) marks the state as
**legacy**; loading one with `live: true` is fine and simply ignores the key.

```python
@dataclass
class ContainerState:
    workspace: str
    container_name: str
    runtime: str
    created_at: str
    status: str
    proxy_port: Optional[int] = None
    proxy_pid: Optional[int] = None
    legacy: bool = False   # not persisted; set by load() for pre-live-mount state files
```

### Proxy (`lib/vibedom/proxy.py`)

`ProxyManager(session_dir=...)` is renamed to `ProxyManager(log_dir=...)`.
Behaviour is unchanged; the name just stops lying.

### Project config (`lib/vibedom/project_config.py`)

`sync_exclude` leaves `KNOWN_FIELDS`. Because unknown keys currently raise,
it moves to a small `OBSOLETE_FIELDS` set that prints a one-line warning and
is ignored, so an old `vibedom.yml` does not brick `up`.

## What changes

### `vibedom up`

```
up <dir> [--runtime] [--recreate]
```

1. Resolve `<dir>`; load `vibedom.yml` if present.
2. Compute mounts: `project_config.mounts` if set, else
   `[Mount(host_path=<dir>, name=<dir>.name, read_only=False)]`.
   Every mount must be a directory (existing check).
3. Load state. If `state.legacy`, print and exit 1:

   ```
   Container 'vibedom-myapp' was created with the old copy+sync model, which
   has been removed. Its repo copy is at ~/.vibedom/containers/myapp/repo
   (a normal git repo — push or copy anything you need from it), then run:
     vibedom destroy myapp
     vibedom up <dir>
   ```
4. Otherwise the existing branches apply: already running, stopped
   (restart), missing (recreate with setup), `--recreate` (remove, rebuild
   image when no `base_image:`, create, setup), first run (secret-scan every
   mount, create, setup). `--recreate` no longer prompts.
5. Final output lists every mount as `host -> /work/<name> [ro]`, then the
   `shell` and `down` hints.

### `vibedom shell`

Refuses legacy state with the same message as `up`. Working directory is
`/work/<name>` for a single mount, `/work` for several. The mount list is
derived by re-reading `vibedom.yml` from `state.workspace` with the same
default rule as `up`, so `shell` needs no new persisted data.

### `vibedom status`

Shows a `legacy (copy+sync) — run vibedom destroy` marker for legacy state
files so they are discoverable. Otherwise unchanged.

### `vibedom destroy`

Unchanged. It already removes the container, kills the proxy and deletes
`~/.vibedom/containers/<name>/`, which is how a legacy container (and its
repo copy) is cleaned up once the user has rescued what they need.

### Secret scanning

Every mount is gitleaks-scanned before first creation, including `ro:`
mounts and the default mount. Unchanged from live-mount behaviour today.

## Storage layout after the change

```
~/.vibedom/
├── keys/                 deploy key
├── whitelist.txt
├── mitmproxy/            CA
└── containers/<name>/
    ├── container.json
    ├── network.jsonl
    └── mitmproxy.log
```

`~/.vibedom/logs/session-*/` is no longer created. Existing session
directories are left alone; users can delete them by hand.

## Error handling

- Legacy state: explicit refusal with the rescue instructions above, exit 1.
- Missing mount directory: existing fast fail before anything is created.
- Obsolete `sync_exclude:`: warning, not an error.
- All other paths keep their current error handling.

## Testing

Deleted with their subjects: `test_session.py`, `test_session_cleanup.py`,
`test_session_state.py`, `test_session_registry.py`, `test_git_workflow.py`,
`test_prune.py`, `test_list.py`, `test_sync.py`, `test_words.py`,
`test_startup_live_mode.py` (its surviving assertion, "init_repo cds to
/work", moves into a small `test_startup_workdir.py`).

Pruned: session, sync, `/mnt/workspace`, `/work/repo` and `live`-flag cases
in `test_cli.py`, `test_vm.py`, `test_container_state.py`,
`test_proxy_manager.py`, `test_project_config.py`, `test_integration.py`.

Added (TDD, all mocked, no runtime needed):

- `up` with no `vibedom.yml` passes a single rw mount named after the dir.
- `up` with `mounts:` passes exactly that list (no auto-mount of the dir).
- `up`, `shell` and `up --recreate` refuse a legacy `container.json`.
- `status` marks a legacy container.
- `ContainerState.load` sets `legacy` for `live: false` and for a missing
  `live` key, and not for `live: true`.
- `shell` uses `/work/<name>` for one mount and `/work` for several.
- `VMManager.start` emits only config, Claude and user mounts; no
  `VIBEDOM_LIVE`.
- `sync_exclude:` warns and is ignored.
- `--recreate` runs without a prompt and without `--yes`.

Baseline reminder: 27 tests already fail in this sandbox for environmental
reasons (no container runtime, `vibedom` not on PATH). The target is the
same set or smaller, with no new failures.

## Documentation

Rewritten, not patched: `docs/USAGE.md` (single workflow; the live-mount
section becomes the main body; "Two Workflows", "Syncing Code" and the
ephemeral section go), `docs/ARCHITECTURE.md` (drop Sync Layer, ephemeral
data flow and session storage), `docs/TESTING.md` (drop the git-bundle
section and stale results tables), `README.md`, `CLAUDE.md` (component list,
key decisions, workflows, command tables, security model), and
`docs/technical-debt.md` (session/bundle items removed).

A **"Upgrading from copy+sync or ephemeral sessions"** section is added
near the top of `docs/USAGE.md` and summarised in `README.md` and
`CLAUDE.md`. It states plainly: containers created before this change
(copy+sync) cannot be started; you must rescue anything from
`~/.vibedom/containers/<name>/repo/`, run `vibedom destroy <name>`, then
`vibedom up <dir>` to recreate it as a live-mount container. It also notes
that `pull`/`push`/`run`/`stop`/`attach`/`review`/`merge` no longer exist and
that old `~/.vibedom/logs/session-*` directories can be deleted by hand.

Security model wording: the "read-only workspace" bullet is replaced by
"live mounts: the agent edits real files; git is the safety net; `ro:`
mounts for reference code". `docs/plans/` is historical and untouched.

## Out of scope

- Automatic migration of copy+sync containers.
- Any change to networking, DLP, gitleaks patterns, proxy lifecycle,
  host aliases, `setup:`, `env:`, `base_image:` or `--recreate` semantics.
- Config-change detection for `up`.
- Cleaning up old `~/.vibedom/logs/session-*` directories.
