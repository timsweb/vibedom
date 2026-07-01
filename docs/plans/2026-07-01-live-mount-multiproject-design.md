# Live Bind-Mount & Multi-Project Containers — Design

**Date**: 2026-07-01
**Status**: Design (approved in brainstorming; not yet planned/implemented)
**Scope**: Parts A + B (live mount + multi-project). Part C (multi-PHP base image) is a separate follow-on spec.

## Problem

The current persistent-container workflow copies the workspace into `~/.vibedom/containers/{name}/repo/` and requires manual `vibedom pull` / `vibedom push` (rsync) to move changes between host and container. Users find this sync cumbersome. Separately, some work spans multiple repositories at once (e.g. a backend API and a frontend), but a container is tied to exactly one workspace.

## Goals

1. Let a container operate **directly on the real host project directory** (live bind mount), eliminating the copy and the pull/push sync step.
2. Let a single container **map in several project directories at once**, each as a subdirectory of `/work`, so one "agent container" can span multiple projects.

## Non-Goals

- Multi-PHP-in-one-container (different PHP versions per project). Deferred to a separate spec (Part C). Projects grouped into a live/multi-project container are assumed to share a base image for now.
- Removing the existing copy+sync workflow. It remains the default and is fully preserved for backward compatibility.
- Automatic file-watching / continuous sync (not needed — the mount is live).

## Design Decision: Security Posture

Vibedom has two independent isolation layers:

1. **Filesystem**: read-only `/mnt/workspace` + agent works on a synced copy in `/work/repo`.
2. **Network**: mitmproxy whitelist + DLP scrubbing + audit log.

This design **trades away layer 1** for the opted-in live-mount containers and **keeps layer 2 fully intact**. The user has explicitly accepted this ("live bind mount, rely on git").

Consequences accepted:

- The agent can write to — and delete — real files. The recovery mechanism becomes **git** (commits, branches, reflog), not the read-only-original guarantee.
- Agent commits land on the user's **actual checked-out branch** in the real repo. There is no review-before-merge gate (`vibedom review`/`merge`/bundle are not part of this flow).
- Agent and the user's editor share one working tree — the intended usage is "hand the project to the agent", not simultaneous editing.
- Network/DLP isolation is unchanged and still applies to every mounted project.

## Design Decision: Backward Compatibility

The new behavior is **opt-in via the presence of a `mounts:` key** in `vibedom.yml`.

- `mounts:` **absent** → today's exact behavior (read-only `/mnt/workspace`, copy in `/work/repo`, `pull`/`push` sync). No change for existing containers.
- `mounts:` **present** → live/multi-project mode (below).

## Configuration

New `mounts:` field in `vibedom.yml`. Two entry forms:

Single-project live editing (`vibedom.yml` in the project root) — `.` resolves to the project dir:

```yaml
mounts:
  - .                             # host project dir -> live at /work/<projectname>
```

Multi-project, with an explicit alias and a read-only reference mount:

```yaml
mounts:
  - ~/Projects/www                # mounts live (rw) at /work/www
  - ~/Projects/API                # mounts live (rw) at /work/API
  - path: ~/Projects/legacy-src   # explicit alias to avoid basename collisions
    as: legacy
  - path: ~/Projects/shared-libs  # read-only reference material
    as: shared
    ro: true
```

- Scalar form: host path; container subdir = basename; read-write.
- Mapping form: `path:` (host) + optional `as:` (container subdir name under `/work`) + optional `ro:` (bool, default `false`).
- `~` and relative paths are expanded/resolved (relative to the directory containing `vibedom.yml`); `.` is the project dir itself.
- Each listed dir is bind-mounted at `/work/<name>` — read-write by default, read-only when `ro: true`.
- `mounts:` is the **complete, explicit list**. The directory passed to `vibedom up` supplies (a) the location of `vibedom.yml` and (b) the container name (its basename); it is **not** auto-mounted unless it also appears in `mounts:` (e.g. as `- .`). This keeps the mount set predictable and lets the `vibedom up` target be a lightweight config dir or one of the projects.
- Basename collisions across two scalar entries are a config error; the user resolves them with the `as:` form.

## Components & Changes

### `project_config.py`
- Add `mounts` to `KNOWN_FIELDS` and to the `ProjectConfig` dataclass (additive alongside the existing fields, including the recently-added `env`).
- Parse both scalar and `{path, as, ro}` mapping entries into a normalized list of `(host_path: Path, name: str, read_only: bool)`. Scalar entries default `read_only=False`.
- Expand `~`, resolve relative paths against the config file's directory (`.` → the project dir).
- Raise on duplicate resulting `name`s (collision) and on a mapping entry missing `path`.

### `vm.py` (`VMManager`)
- Accept a normalized `mounts: list[tuple[Path, str, bool]]` (or `None`).
- When `mounts` is set:
  - Do **not** emit the `-v {workspace}:/mnt/workspace:ro` mount or the `{container_dir}/repo:/work/repo` copy mount.
  - Emit one `-v {host_path}:/work/{name}` per mount entry, appending `:ro` when the entry's `read_only` flag is set (read-write otherwise).
  - The container name is still derived from the primary workspace name / `up` target.
- When `mounts` is `None`: unchanged (current copy + read-only behavior).
- `container_dir` still holds `container.json`, `network.jsonl`, and mitmproxy logs (unchanged) — only the `repo/` copy mount goes away in live mode.

### `startup.sh`
- **Detect live/multi-mount mode** (via an env var the runtime sets, e.g. `VIBEDOM_MOUNTS`/`VIBEDOM_LIVE`) and **skip the entire clone/init block**, just `cd /work`. This is required: in pure multi-mount mode there is no `/work/repo` and no `/mnt/workspace`, so the current logic would fall through to the "Non-git workspace" branch and wrongly `git init` an empty `/work/repo`.
- **No per-repo git-identity handling needed.** `ensure_git_identity` now writes to `--global` (`~/.gitconfig` in the container's writable root fs), so identity applies to every mounted repo automatically and never writes into a mounted `.git/config`. The existing call is sufficient; leave it as-is.
- No clone / branch-checkout logic runs in live mode (files already present).

### `cli.py`
- **`up`**: load `vibedom.yml`; if `mounts:` present, validate each host path exists and is a directory; run the **gitleaks pre-flight scan over each** mounted tree (today it scans one), including read-only mounts (a read-only secret is still exfiltratable), and aggregate findings through the existing review UI before starting; pass the normalized mount list to `VMManager`.
- **`shell`** (and `attach`): when the container is a live/multi-project container, open the shell at `/work` instead of `/work/repo`. (Detect via `mounts:` in config, or a flag persisted in `container.json`.)
- **`pull` / `push`**: detect a live-mount container and no-op with a clear message ("This is a live-mount container — changes are already on your host; no sync needed.").
- Persist a marker (e.g. `live: true` / the mount list) in `container.json` so lifecycle commands don't need to re-read `vibedom.yml` to know the mode.

### `container_state.py`
- Optionally record the live/multi-project marker (and mount names) in `ContainerState` so `shell`, `pull`, `push`, and `status` can behave correctly without reloading `vibedom.yml`.

## Data Flow (live/multi-project `vibedom up`)

1. `up <dir>` reads `<dir>/vibedom.yml`, normalizes `mounts:`.
2. Gitleaks scans each mounted tree; user reviews findings.
3. Host proxy starts (unchanged).
4. Container starts with one rw `-v` per mount at `/work/<name>`; no `/mnt/workspace`, no copy.
5. `startup.sh` detects live mode and skips clone/init; global git identity (`~/.gitconfig`) already applies to all mounts; network CA + proxy env applied as today.
6. `vibedom shell` drops the user at `/work`; the agent edits real files directly.

## Testing (TDD)

- `project_config`: parses scalar + mapping mount entries; expands `~`/relative (`.` → project dir); defaults `read_only=False`; honors `ro: true`; errors on collision and on mapping without `path`; `mounts` absent still parses as today.
- `vm.py`: with `mounts`, the run command contains one `-v .../work/<name>` per entry, `:ro`-suffixed exactly for entries flagged read-only and rw otherwise, and contains neither `/mnt/workspace:ro` nor the `repo` copy mount; without `mounts`, the command is unchanged from today.
- `cli up`: rejects a non-existent mount path; runs gitleaks per mount (mock/scan each); passes normalized mounts to `VMManager`.
- `cli shell`: working dir is `/work` for a live container, `/work/repo` otherwise.
- `cli pull`/`push`: no-op with message for a live container.
- `startup.sh`: in live/multi-mount mode the clone/init block is skipped (no stray `git init` at `/work/repo`); global git identity still applies (extend `tests/test_startup_git_identity.py`).

## Rollout / Coordination Note

A change set that was in flight when this design started (vibedom.yml `env` vars, host git-identity lifting, non-login-shell PATH/SSH, and mirroring the host global git identity — `git config --global`) has now landed on `main` (through commit `3011425`); the working tree is clean apart from this doc. The global-identity change means the mount work needs **no per-repo git-config handling**. Implementation should branch from current `main`. Git operations are left to the user.

## Follow-on (separate spec): Part C — Multi-PHP base image

Build/select a base image with multiple PHP versions installed side-by-side (e.g. Debian + `ondrej/php`, or `asdf`/`phpenv`) plus a per-directory switch: a `.php-version` file per project read by a `php` shim on `PATH`. `base_image:` then points at that image. Independent of Parts A/B; A/B deliver value for same-PHP project groups without it.
