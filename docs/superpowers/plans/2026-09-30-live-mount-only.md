# Live-mount-only Vibedom Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove ephemeral sessions and copy+sync so `vibedom up <dir>` always creates a persistent container with the project's real directories bind-mounted under `/work`.

**Architecture:** This is a removal. `session.py`, `words.py`, eleven CLI commands and the rsync/clone plumbing are deleted; `VMManager` always receives a non-empty mount list (the CLI computes a default of "mount the `up` directory at `/work/<basename>`"); `ContainerState` drops `repo_dir`/`live` and instead flags pre-live-mount state files as `legacy`, which `up`/`shell`/`--recreate` refuse with rescue instructions. Docs are rewritten for the single model.

**Tech Stack:** Python 3.12, Click, PyYAML, pytest with `unittest.mock`, POSIX sh (startup.sh), Docker / apple/container.

**Spec:** `docs/superpowers/specs/2026-09-30-live-mount-only-design.md`

## Global Constraints

- Tests are unit tests with subprocess/`VMManager`/`ProxyManager` mocked; nothing in this plan needs a container runtime.
- Baseline: 27 tests already fail in this sandbox (no container runtime, `vibedom` not on PATH). Run `python -m pytest tests/ -q 2>&1 | tail -1` before starting and record the number; the end state must show no *new* failures. Several baseline failures are in files this plan deletes, so the number goes down.
- Commit messages use conventional commits and end with `Co-Authored-By: Claude Fable 5.1 <[REDACTED_EMAIL]>`.
- Work on a branch, not `main`. Suggested: `git checkout -b live-mount-only` in a `.worktrees/live-mount-only` worktree.
- The `/work/<name>` path convention and `Mount(host_path, name, read_only)` dataclass in `lib/vibedom/project_config.py` are unchanged.
- Existing `vibedom.yml` files with `mounts:` must keep working unchanged.
- The `Mount` import in `vm.py` is not needed; `VMManager` only reads `.host_path`, `.name`, `.read_only`.

## Review Focus

Input classes the spec implies that no task's tests exercised until they were added here. Each has its pinning test in the named task.

1. `vibedom.yml` present but with no `mounts:` key (only `setup:` or `env:`) — the default mount must still apply. Pinned in Task 6 (`test_up_yml_without_mounts_uses_default_mount`).
2. A `container.json` that has `live: true` from before this change — must load cleanly and NOT be flagged legacy. Pinned in Task 3 (`test_load_live_true_json_is_not_legacy`).
3. `vibedom status` when one of several containers is legacy — must still list the others and mark the legacy one. Pinned in Task 7.
4. `vibedom shell` on a container whose `vibedom.yml` was edited to add a second mount after creation — cwd should follow the config (`/work`), the shell must not crash. Pinned in Task 8 (`test_shell_workdir_follows_current_config`).
5. Old `vibedom.yml` containing `sync_exclude:` — must warn, not raise. Pinned in Task 2.

---

### Task 1: Delete ephemeral sessions

Everything that exists only for `vibedom run`/`stop`/`attach`/`review`/`merge` and the session registry goes. This task ends with a green suite (minus baseline) because every test of the removed code is removed with it.

**Files:**
- Delete: `lib/vibedom/session.py`, `lib/vibedom/words.py`
- Delete: `tests/test_session.py`, `tests/test_session_cleanup.py`, `tests/test_session_state.py`, `tests/test_session_registry.py`, `tests/test_git_workflow.py`, `tests/test_prune.py`, `tests/test_list.py`, `tests/test_words.py`, `tests/test_integration.py`
- Modify: `lib/vibedom/cli.py` (remove commands `run`, `stop`, `attach`, `list`, `review`, `merge`, `rm`, `prune`, `housekeeping`; helper `_execute_deletions`; session half of `proxy-restart`; session-scanning half of `reload-whitelist`)
- Modify: `tests/test_cli.py` (remove session tests), `tests/test_vm.py` (remove the two `Session`-based integration tests)

**Interfaces:**
- Consumes: nothing.
- Produces: `cli.py` no longer imports `vibedom.session`; `proxy-restart` takes a `workspace` argument and only resolves `ContainerRegistry`.

- [ ] **Step 1: Record the baseline**

Run: `python -m pytest tests/ -q 2>&1 | tail -1`
Expected: `27 failed, 264 passed` (or whatever the current number is; write it down).

- [ ] **Step 2: Delete the session modules and their tests**

```bash
git rm -q lib/vibedom/session.py lib/vibedom/words.py \
  tests/test_session.py tests/test_session_cleanup.py tests/test_session_state.py \
  tests/test_session_registry.py tests/test_git_workflow.py tests/test_prune.py \
  tests/test_list.py tests/test_words.py tests/test_integration.py
```

- [ ] **Step 3: Remove the session tests from `tests/test_cli.py`**

Delete these test functions and any helper only they use (`_make_running_state` is used by the `reload_whitelist` tests; check before deleting it):
`test_cli_shows_help` (asserts `'run' in result.stdout`; rewrite it, see step 4), `test_reload_whitelist_sends_sighup_to_all_running`, `test_reload_whitelist_no_running_sessions`, `test_reload_whitelist_fails_gracefully`, `test_reload_whitelist_warns_if_no_proxy_pid`, `test_review_*` (6), `test_merge_*` (4), `test_attach_*` (3), `test_run_*` (5), `test_stop_uses_session_registry`, `test_rm_*` (4), `test_reload_whitelist_sends_sighup_via_pid`, `test_proxy_restart_stops_and_restarts`, `test_proxy_restart_when_proxy_already_dead`, `test_proxy_restart_fails_if_no_port_recorded`.

Keep: the `test_up_*`, `test_proxy_restart_persistent_container`, `test_proxy_restart_uses_live_status_not_persisted`, `test_proxy_restart_container_not_running`, `test_shell_*`, `test_live_container_status_*` tests. Remove now-unused imports (`json`, `signal`) only if nothing left uses them.

- [ ] **Step 4: Rewrite `test_cli_shows_help` and add a reload-whitelist container test**

Replace `test_cli_shows_help` with an in-process version that pins the surviving command set:

```python
def test_cli_help_lists_only_container_commands():
    result = CliRunner().invoke(main, ['--help'])
    assert result.exit_code == 0
    for cmd in ('init', 'up', 'down', 'destroy', 'status', 'shell',
                'reload-whitelist', 'proxy-restart'):
        assert cmd in result.output
    for gone in ('run', 'attach', 'review', 'merge', 'pull', 'push',
                 'prune', 'housekeeping'):
        assert f'  {gone} ' not in result.output


def test_reload_whitelist_sends_sighup_to_running_containers(tmp_path):
    proj = tmp_path / 'agent'
    proj.mkdir()
    cdir = tmp_path / '.vibedom' / 'containers' / 'agent'
    cdir.mkdir(parents=True)
    state = ContainerState.create(proj, 'docker')
    state.mark_running(54321, 99999, cdir)

    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        with patch('os.kill') as mock_kill:
            result = CliRunner().invoke(main, ['reload-whitelist'])

    assert result.exit_code == 0, result.output
    mock_kill.assert_called_once_with(99999, signal.SIGHUP)


def test_reload_whitelist_no_running_containers(tmp_path):
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        result = CliRunner().invoke(main, ['reload-whitelist'])
    assert result.exit_code == 0
    assert 'No running containers' in result.output
```

- [ ] **Step 5: Remove the two `Session` integration tests from `tests/test_vm.py`**

Delete `test_vm_git_repo_initialized` and `test_vm_mounts_session_repo` (lines 41–88). Leave `test_vm_start_stop`.

- [ ] **Step 6: Run the suite to see it fail on imports**

Run: `python -m pytest tests/test_cli.py -q 2>&1 | tail -3`
Expected: `ImportError` / `ModuleNotFoundError: No module named 'vibedom.session'` from `cli.py`.

- [ ] **Step 7: Strip `cli.py`**

Remove the import line `from vibedom.session import Session, SessionCleanup, SessionRegistry`.

Delete these whole command functions and their decorators: `run`, `stop`, `list_sessions`, `attach`, `review`, `merge`, `rm`, `prune`, `housekeeping`, and the helper `_execute_deletions` at the top of the file.

Rewrite `reload_whitelist` to scan only containers:

```python
@main.command('reload-whitelist')
def reload_whitelist() -> None:
    """Reload the domain whitelist in every running container's proxy.

    Sends SIGHUP to each host proxy so mitmproxy re-reads whitelist.txt
    without restarting containers.
    """
    registry = ContainerRegistry(Path.home() / '.vibedom' / 'containers')
    running = [c for c in registry.all() if c.status == 'running']
    if not running:
        click.echo("No running containers.")
        return

    failed = 0
    for c in running:
        name = Path(c.workspace).name
        if not c.proxy_pid:
            click.secho(f"⚠️  {name}: no proxy PID recorded — run 'vibedom proxy-restart {name}'", fg='yellow')
            failed += 1
            continue
        try:
            os.kill(c.proxy_pid, signal_module.SIGHUP)
            click.echo(f"✅ {name}: whitelist reloaded (proxy PID {c.proxy_pid})")
        except ProcessLookupError:
            click.secho(f"❌ {name}: proxy PID {c.proxy_pid} not running — run 'vibedom proxy-restart {name}'", fg='red')
            failed += 1
    if failed:
        sys.exit(1)
```

Rewrite `proxy_restart` to be container-only:

```python
@main.command('proxy-restart')
@click.argument('workspace', required=False)
def proxy_restart(workspace: Optional[str]) -> None:
    """Restart the host proxy for a running container.

    WORKSPACE is a workspace name, path, or container name. If omitted and
    exactly one container is running, that one is used.

    The proxy restarts on the same port so the container's HTTP_PROXY
    setting stays valid. Use this to reload the mitmproxy addon code.
    """
    config_dir = Path.home() / '.vibedom'
    registry = ContainerRegistry(config_dir / 'containers')
    container = registry.find(workspace) if workspace else None
    if container is None and not workspace:
        running = [c for c in registry.all() if c.status == 'running']
        if len(running) == 1:
            container = running[0]
        elif len(running) > 1:
            click.secho("Multiple running containers. Specify a workspace name.", fg='red')
            sys.exit(1)
    if container is None:
        click.secho(f"No container found for '{workspace or ''}'.", fg='red')
        sys.exit(1)
    _restart_container_proxy(container, config_dir)
```

Keep `_restart_container_proxy` as is. Remove `shutil` from imports only if `destroy` no longer needs it (it does: `shutil.rmtree`). Keep it.

- [ ] **Step 8: Run the suite**

Run: `python -m pytest tests/ -q 2>&1 | tail -1`
Expected: passes minus baseline. The baseline count drops because `test_integration.py` and `test_cli_shows_help` are gone. Note the new number.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor!: remove ephemeral sessions (run/stop/attach/review/merge, session.py)

Co-Authored-By: Claude Fable 5.1 <[REDACTED_EMAIL]>"
```

---

### Task 2: Project config: retire `sync_exclude` with a warning

**Files:**
- Modify: `lib/vibedom/project_config.py`
- Test: `tests/test_project_config.py`

**Interfaces:**
- Produces: `ProjectConfig` without a `sync_exclude` attribute; module constant `OBSOLETE_FIELDS = {'sync_exclude'}`.

- [ ] **Step 1: Replace the two `sync_exclude` tests with a warning test**

Delete `test_project_config_loads_sync_exclude` and `test_project_config_sync_exclude_defaults_to_none`. Add:

```python
def test_sync_exclude_is_obsolete_and_warns(tmp_path, capsys):
    (tmp_path / 'vibedom.yml').write_text('sync_exclude:\n  - vendor/\n')
    config = ProjectConfig.load(tmp_path)
    assert config is not None
    assert not hasattr(config, 'sync_exclude')
    err = capsys.readouterr().err
    assert 'sync_exclude' in err and 'no longer' in err


def test_project_config_still_rejects_truly_unknown_fields(tmp_path):
    (tmp_path / 'vibedom.yml').write_text('bogus: 1\n')
    with pytest.raises(ValueError, match='bogus'):
        ProjectConfig.load(tmp_path)
```

(Add `import pytest` if the file lacks it.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_project_config.py -q -k "obsolete or truly_unknown" 2>&1 | tail -3`
Expected: `test_sync_exclude_is_obsolete_and_warns` FAILS on `assert not hasattr(...)`.

- [ ] **Step 3: Implement**

In `lib/vibedom/project_config.py`:

```python
import sys
...
KNOWN_FIELDS = {
    'base_image', 'network', 'host_aliases', 'setup',
    'memory', 'env', 'mounts',
}

# Fields from removed features. Present in old vibedom.yml files; warn, don't fail.
OBSOLETE_FIELDS = {'sync_exclude'}
```

Remove `sync_exclude: Optional[list] = None` from the dataclass and the `sync_exclude=data.get('sync_exclude'),` line from `load()`. In `load()`, before the unknown-field check:

```python
        for field in sorted(OBSOLETE_FIELDS & set(data.keys())):
            print(
                f"Warning: vibedom.yml '{field}:' is no longer supported and was ignored "
                f"(copy+sync was removed; projects are live-mounted).",
                file=sys.stderr,
            )
        unknown = set(data.keys()) - KNOWN_FIELDS - OBSOLETE_FIELDS
```

- [ ] **Step 4: Run**

Run: `python -m pytest tests/test_project_config.py -q 2>&1 | tail -1`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add lib/vibedom/project_config.py tests/test_project_config.py
git commit -m "refactor: retire sync_exclude in vibedom.yml with a warning

Co-Authored-By: Claude Fable 5.1 <[REDACTED_EMAIL]>"
```

---

### Task 3: ContainerState: drop `repo_dir`/`live`, add `legacy` detection

**Files:**
- Modify: `lib/vibedom/container_state.py`
- Test: `tests/test_container_state.py`

**Interfaces:**
- Produces: `ContainerState.create(workspace: Path, runtime: str) -> ContainerState` (no `live` param); attribute `legacy: bool` (never persisted); `ContainerState.load()` sets `legacy=True` when the JSON lacks `live` or has `live: false`.

- [ ] **Step 1: Rewrite the affected tests**

In `tests/test_container_state.py`, delete the `repo_dir` assertion in `test_container_state_create`, delete `test_create_defaults_live_false` and `test_create_live_roundtrips`, and replace `test_load_legacy_json_without_live` with:

```python
def _write_state(tmp_path, **extra):
    data = {
        'workspace': str(tmp_path / 'myapp'),
        'container_name': 'vibedom-myapp',
        'runtime': 'docker',
        'created_at': '2026-01-01T00:00:00',
        'status': 'stopped',
    }
    data.update(extra)
    (tmp_path / 'container.json').write_text(json.dumps(data))


def test_create_is_not_legacy(tmp_path):
    state = ContainerState.create(tmp_path / 'myapp', 'docker')
    assert state.legacy is False


def test_save_writes_live_marker_and_no_dropped_fields(tmp_path):
    """save() writes `live: true` as the new-model marker (so load() can tell
    new files from copy+sync ones) and nothing else from the old schema."""
    state = ContainerState.create(tmp_path / 'myapp', 'docker')
    state.save(tmp_path)
    data = json.loads((tmp_path / 'container.json').read_text())
    assert data['live'] is True
    assert 'legacy' not in data
    assert 'repo_dir' not in data


def test_load_json_without_live_key_is_legacy(tmp_path):
    """State written before live mounts existed = copy+sync container."""
    _write_state(tmp_path, repo_dir=str(tmp_path / 'repo'))
    assert ContainerState.load(tmp_path).legacy is True


def test_load_live_false_json_is_legacy(tmp_path):
    _write_state(tmp_path, repo_dir=str(tmp_path / 'repo'), live=False)
    assert ContainerState.load(tmp_path).legacy is True


def test_load_live_true_json_is_not_legacy(tmp_path):
    """Containers created with mounts: before this change keep working."""
    _write_state(tmp_path, repo_dir=str(tmp_path / 'repo'), live=True)
    state = ContainerState.load(tmp_path)
    assert state.legacy is False
    assert state.container_name == 'vibedom-myapp'


def test_load_ignores_dropped_fields(tmp_path):
    _write_state(tmp_path, repo_dir='/x', live=True)
    state = ContainerState.load(tmp_path)
    assert not hasattr(state, 'repo_dir')
    assert not hasattr(state, 'live')
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_container_state.py -q 2>&1 | tail -3`
Expected: failures on `legacy` attribute and on `live`/`repo_dir` still being present.

- [ ] **Step 3: Implement**

Replace the dataclass and `create`/`load`/`save` in `lib/vibedom/container_state.py`:

```python
from dataclasses import dataclass, asdict, field

# Keys written by older vibedom versions that no longer exist on the dataclass.
_DROPPED_KEYS = {'repo_dir', 'live'}


@dataclass
class ContainerState:
    """Persisted state for a long-lived project container (container.json).

    Example:
        state = ContainerState.create(workspace, 'docker')
        state.save(container_dir)
        # later:
        state = ContainerState.load(container_dir)
        if state.legacy:
            ...  # created by the removed copy+sync model; must be destroyed
    """

    workspace: str
    container_name: str
    runtime: str
    created_at: str
    status: str           # 'running' | 'stopped'
    proxy_port: Optional[int] = None
    proxy_pid: Optional[int] = None
    # True when container.json predates live mounts (copy+sync container).
    # Set by load(); never written to disk.
    legacy: bool = field(default=False, compare=False)

    @classmethod
    def create(cls, workspace: Path, runtime: str) -> 'ContainerState':
        """Create a new ContainerState for a fresh container."""
        workspace = workspace.resolve()
        return cls(
            workspace=str(workspace),
            container_name=f'vibedom-{workspace.name}',
            runtime=runtime,
            created_at=datetime.now().isoformat(timespec='seconds'),
            status='stopped',
        )

    @classmethod
    def load(cls, container_dir: Path) -> 'ContainerState':
        """Load state from container directory.

        A container.json without `live: true` was written for a copy+sync
        container, a model that no longer exists; it loads with legacy=True so
        commands can refuse it with instructions instead of crashing.
        """
        state_file = container_dir / 'container.json'
        if not state_file.exists():
            raise FileNotFoundError(f"No container.json in {container_dir}")
        try:
            data = json.loads(state_file.read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"Malformed container.json in {container_dir}: {e}") from e
        legacy = data.get('live') is not True
        clean = {k: v for k, v in data.items() if k not in _DROPPED_KEYS and k != 'legacy'}
        try:
            state = cls(**clean)
        except TypeError as e:
            raise ValueError(f"Invalid container.json schema in {container_dir}: {e}") from e
        state.legacy = legacy
        return state

    def save(self, container_dir: Path) -> None:
        """Persist state to container directory."""
        container_dir.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data.pop('legacy')
        # Marker so a future load() knows this file post-dates copy+sync.
        data['live'] = True
        (container_dir / 'container.json').write_text(json.dumps(data, indent=2))
```

`save()` writes `live: true` on purpose: it is the only signal `load()` has to tell a new-model file from an old one, and it keeps files readable by the previous release.

- [ ] **Step 4: Run**

Run: `python -m pytest tests/test_container_state.py -q 2>&1 | tail -1`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add lib/vibedom/container_state.py tests/test_container_state.py
git commit -m "refactor: ContainerState drops repo_dir/live, flags pre-live-mount files as legacy

Co-Authored-By: Claude Fable 5.1 <[REDACTED_EMAIL]>"
```

---

### Task 4: ProxyManager: rename `session_dir` to `log_dir`

**Files:**
- Modify: `lib/vibedom/proxy.py`, `lib/vibedom/vm.py` (one call site), `lib/vibedom/cli.py` (call sites in `up` and `_restart_container_proxy`)
- Test: `tests/test_proxy_manager.py`, `tests/test_cli.py`

- [ ] **Step 1: Update the tests**

In `tests/test_proxy_manager.py` replace every `ProxyManager(session_dir=` with `ProxyManager(log_dir=` and rename local variables `session_dir` to `log_dir`. In `tests/test_cli.py` do the same wherever `ProxyManager(` is asserted on (grep `session_dir=`).

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_proxy_manager.py -q 2>&1 | tail -2`
Expected: `TypeError: ... unexpected keyword argument 'log_dir'`.

- [ ] **Step 3: Implement**

In `lib/vibedom/proxy.py`:

```python
class ProxyManager:
    """Manages a host-side mitmproxy process for one container."""

    def __init__(self, log_dir: Path, config_dir: Path):
        self.log_dir = log_dir
```

and replace the two `self.session_dir` uses (`network.jsonl`, `mitmproxy.log`) with `self.log_dir`. Fix the docstring example near line 131. Then:

```bash
grep -rn "session_dir=" lib/ | cat
```

and change each `ProxyManager(session_dir=X, ...)` to `ProxyManager(log_dir=X, ...)`. In `vm.py` this is the `self._proxy = ProxyManager(...)` call; in `cli.py` the calls in `up` (restart branch) and `_restart_container_proxy`.

- [ ] **Step 4: Run**

Run: `python -m pytest tests/test_proxy_manager.py tests/test_cli.py tests/test_vm.py -q 2>&1 | tail -1`
Expected: no new failures.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: ProxyManager(session_dir=) -> ProxyManager(log_dir=)

Co-Authored-By: Claude Fable 5.1 <[REDACTED_EMAIL]>"
```

---

### Task 5: VMManager: mounts required, no workspace/repo/session mounts, no VIBEDOM_LIVE

**Files:**
- Modify: `lib/vibedom/vm.py:43-60` (init), `lib/vibedom/vm.py:305-372` (start)
- Test: `tests/test_vm.py`

**Interfaces:**
- Produces: `VMManager(workspace, config_dir, *, container_dir, runtime=None, network=None, base_image=None, host_aliases=None, memory=None, mounts: list, extra_env=None)`. `session_dir` is gone. `mounts` must be a non-empty list or `ValueError("VMManager requires at least one mount")`.

- [ ] **Step 1: Rewrite the mount tests**

In `tests/test_vm.py`:

Delete `test_vm_start_mounts_repo_from_container_dir` and `test_start_without_mounts_still_mounts_workspace_ro`.

Rewrite `test_start_with_live_mounts_emits_rw_and_ro` to assert no `VIBEDOM_LIVE`:

```python
def test_start_bind_mounts_each_mount_at_work_name(test_config, tmp_path):
    """start() bind-mounts each Mount at /work/<name>, honouring ro, and emits no
    workspace/repo/session mounts and no VIBEDOM_LIVE flag."""
    www = tmp_path / 'www'
    www.mkdir()
    shared = tmp_path / 'shared'
    shared.mkdir()
    mounts = [
        Mount(host_path=www, name='www', read_only=False),
        Mount(host_path=shared, name='shared', read_only=True),
    ]
    with patch('shutil.which') as mock_which:
        mock_which.side_effect = lambda cmd: '/usr/local/bin/docker' if cmd == 'docker' else None
        vm = VMManager(www, test_config, container_dir=tmp_path / 'cdir', mounts=mounts)

    with patch('subprocess.run') as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        with patch('vibedom.vm.ProxyManager') as mock_proxy_cls:
            mock_proxy = MagicMock()
            mock_proxy.start.return_value = 54321
            mock_proxy.ca_cert_path = None
            mock_proxy_cls.return_value = mock_proxy
            with patch('shutil.copy'):
                try:
                    vm.start()
                except RuntimeError:
                    pass

    cmd = _run_argv(mock_run)
    assert f'{www}:/work/www' in cmd
    assert f'{shared}:/work/shared:ro' in cmd
    assert 'VIBEDOM_LIVE=1' not in cmd
    assert not any('/mnt/workspace' in a for a in cmd)
    assert not any('/mnt/session' in a for a in cmd)
    assert not any(a.endswith(':/work/repo') for a in cmd)
    volumes = [cmd[i + 1] for i, a in enumerate(cmd) if a == '-v']
    assert len(volumes) == 4  # config, www, shared, claude config


def test_vm_requires_mounts(test_workspace, test_config, tmp_path):
    with patch('shutil.which', return_value='/usr/local/bin/docker'):
        with pytest.raises(ValueError, match='at least one mount'):
            VMManager(test_workspace, test_config, container_dir=tmp_path / 'c', mounts=[])
        with pytest.raises(ValueError, match='at least one mount'):
            VMManager(test_workspace, test_config, container_dir=tmp_path / 'c')


def test_vm_rejects_session_dir_kwarg(test_workspace, test_config, tmp_path):
    with patch('shutil.which', return_value='/usr/local/bin/docker'):
        with pytest.raises(TypeError):
            VMManager(test_workspace, test_config, session_dir=tmp_path, mounts=[_mount(test_workspace)])
```

Add near the top of the file a helper used by every remaining `VMManager(...)` construction:

```python
def _mount(path):
    return Mount(host_path=path, name=path.name, read_only=False)
```

Then update every other `VMManager(...)` call in `test_vm.py` that currently has no `mounts=` to pass `mounts=[_mount(test_workspace)]` (or the workspace variable in scope) and a `container_dir=` if it passes `session_dir=` (replace `session_dir=X` with `container_dir=X`). This includes `test_vm_start_stop`, `test_start_uses_*`, `test_start_sets_ssh_auth_sock_env`, `test_start_mounts_claude_volume`, `test_start_skips_claude_mounts_if_not_exists`, `test_vm_start_uses_host_proxy`, `test_vm_start_with_project_network`, `test_vm_start_network_ignored_with_apple_runtime`, `test_vm_stop_stops_proxy`, `test_vm_start_adds_host_aliases_*`, `test_vm_start_passes_extra_env_vars`, `test_vm_start_extra_env_does_not_override_proxy_vars`, `test_vm_start_injects_host_git_identity`, `test_vm_start_omits_git_identity_when_host_has_none`, `test_vm_start_no_host_aliases_adds_no_add_host`. Tests that only construct `VMManager` to call `exists`/`is_running`/`pause`/`restart`/`stop` need `mounts=` too.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_vm.py -q 2>&1 | tail -3`
Expected: `test_vm_requires_mounts` and `test_vm_rejects_session_dir_kwarg` fail; `test_start_bind_mounts_each_mount_at_work_name` fails on `VIBEDOM_LIVE`.

- [ ] **Step 3: Implement**

In `lib/vibedom/vm.py` `__init__`:

```python
    def __init__(self, workspace: Path, config_dir: Path,
                 runtime: Optional[str] = None, network: Optional[str] = None,
                 base_image: Optional[str] = None,
                 host_aliases: Optional[dict] = None,
                 container_dir: Optional[Path] = None,
                 memory: Optional[str] = None,
                 mounts: Optional[list] = None,
                 extra_env: Optional[dict] = None):
        """Initialize VM manager.

        Args:
            workspace: Directory passed to `vibedom up`; names the container.
            config_dir: ~/.vibedom (mounted read-only at /mnt/config).
            runtime: 'docker', 'apple', or None to auto-detect.
            network: Docker network to join (ignored on apple/container).
            base_image: Project base image; the vibedom layer is built on top.
            host_aliases: {hostname: ip|'host'} resolved inside the container.
            container_dir: ~/.vibedom/containers/<name>; proxy logs live here.
            memory: Memory limit (apple/container defaults to 4g).
            mounts: Non-empty list of Mount(host_path, name, read_only), each
                bind-mounted at /work/<name>. Required.
            extra_env: Extra env vars from vibedom.yml `env:`.
        """
        if not mounts:
            raise ValueError("VMManager requires at least one mount")
        self.workspace = workspace.resolve()
        self.config_dir = config_dir.resolve()
        self.container_dir = container_dir.resolve() if container_dir else None
        ...
        self.mounts = list(mounts)
```

Remove `self.session_dir`. In `start()`:

```python
        if self.container_dir is None:
            raise RuntimeError("container_dir must be set to start the VM")
        self._proxy = ProxyManager(log_dir=self.container_dir, config_dir=self.config_dir)
```

and replace the whole `if self.mounts: ... else: ... if self.session_dir:` block (currently lines ~369–393) with:

```python
        # Project mounts: each host dir bind-mounted live at /work/<name>.
        for m in self.mounts:
            spec = f'{m.host_path}:/work/{m.name}'
            if m.read_only:
                spec += ':ro'
            cmd += ['-v', spec]
```

Update the readiness comment `# Wait for VM to be ready (increased timeout for git cloning)` to `# Wait for startup.sh to touch /tmp/.vm-ready`.

- [ ] **Step 4: Run**

Run: `python -m pytest tests/test_vm.py -q 2>&1 | tail -1`
Expected: only baseline failures (the `test_vm_*` runtime-dependent ones).

- [ ] **Step 5: Commit**

```bash
git add lib/vibedom/vm.py tests/test_vm.py
git commit -m "refactor!: VMManager requires mounts; drop workspace/repo/session mounts and VIBEDOM_LIVE

Co-Authored-By: Claude Fable 5.1 <[REDACTED_EMAIL]>"
```

---

### Task 6: `vibedom up`: default mount, legacy refusal, no `--yes`, remove `pull`/`push`

**Files:**
- Modify: `lib/vibedom/cli.py` (`up`, delete `pull`, `push`, `_validate_sync_paths`, `_make_workspace_relative`, `_build_rsync_cmd`, `_find_deletions`)
- Delete: `tests/test_sync.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `ContainerState.create(workspace, runtime)`, `state.legacy` (Task 3); `VMManager(..., mounts=...)` (Task 5).
- Produces: module functions in `cli.py`:
  - `_resolve_mounts(workspace_path: Path, project_config) -> list[Mount]` — returns `project_config.mounts` if set, else `[Mount(host_path=workspace_path, name=workspace_path.name, read_only=False)]`.
  - `_refuse_legacy(state: ContainerState, container_dir: Path) -> None` — prints the rescue message and `sys.exit(1)` when `state.legacy`.
  Tasks 7 and 8 call both.

- [ ] **Step 1: Delete `tests/test_sync.py` and rewrite the `up` tests**

```bash
git rm -q tests/test_sync.py
```

In `tests/test_cli.py`:

Delete `test_up_recreate_copy_sync_container_prompts_and_aborts_on_no` and `test_up_recreate_preserves_repo_dir`. In `_recreate_setup` drop the `live` parameter and the `repo/keep.txt` lines; call `ContainerState.create(proj, 'docker')`. In every `_invoke_recreate(...)` call remove `'--yes'` from the args. In `test_up_recreate_removes_container_and_starts_fresh` delete `assert state.live is True`. In `test_up_live_mounts_passes_mounts_and_persists_live` rename to `test_up_with_mounts_passes_exactly_that_list` and replace `assert state.live is True` with `assert state.legacy is False`. In `test_up_already_running_live_container_shows_live_note_not_repo_path` replace `ContainerState.create(proj, 'docker', live=True)` with `ContainerState.create(proj, 'docker')` and keep the assertions.

Add:

```python
def _up_first_run(proj, home, args=()):
    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli.scan_workspace', return_value=[]) as mock_scan:
            with patch('vibedom.cli.review_findings', return_value=True):
                with patch('vibedom.cli.VMManager') as mock_vm_cls:
                    mock_vm_cls._detect_runtime.return_value = ('docker', 'docker')
                    mock_vm = MagicMock()
                    mock_vm.is_running.return_value = False
                    mock_vm.exists.return_value = False
                    mock_vm._proxy = MagicMock(port=54321, pid=99999)
                    mock_vm_cls.return_value = mock_vm
                    result = runner.invoke(main, ['up', str(proj), *args], catch_exceptions=False)
    return result, mock_vm_cls, mock_scan


def test_up_without_yml_mounts_the_workspace_itself(tmp_path):
    proj = tmp_path / 'myapp'
    proj.mkdir()
    result, mock_vm_cls, mock_scan = _up_first_run(proj, tmp_path / 'home')

    assert result.exit_code == 0, result.output
    mounts = mock_vm_cls.call_args.kwargs['mounts']
    assert [(m.host_path, m.name, m.read_only) for m in mounts] == [(proj.resolve(), 'myapp', False)]
    mock_scan.assert_called_once_with(proj.resolve())
    assert '/work/myapp' in result.output


def test_up_yml_without_mounts_uses_default_mount(tmp_path):
    proj = tmp_path / 'myapp'
    proj.mkdir()
    (proj / 'vibedom.yml').write_text('setup:\n  - echo hi\n')
    result, mock_vm_cls, _ = _up_first_run(proj, tmp_path / 'home')

    assert result.exit_code == 0, result.output
    mounts = mock_vm_cls.call_args.kwargs['mounts']
    assert [m.name for m in mounts] == ['myapp']


def test_up_with_mounts_does_not_auto_mount_workspace(tmp_path):
    proj = tmp_path / 'agent'
    proj.mkdir()
    (tmp_path / 'www').mkdir()
    (proj / 'vibedom.yml').write_text(f'mounts:\n  - {tmp_path / "www"}\n')
    result, mock_vm_cls, _ = _up_first_run(proj, tmp_path / 'home')

    assert result.exit_code == 0, result.output
    assert [m.name for m in mock_vm_cls.call_args.kwargs['mounts']] == ['www']


def _legacy_setup(tmp_path):
    proj = tmp_path / 'old'
    proj.mkdir()
    home = tmp_path / 'home'
    cdir = home / '.vibedom' / 'containers' / 'old'
    cdir.mkdir(parents=True)
    (cdir / 'container.json').write_text(json.dumps({
        'workspace': str(proj), 'container_name': 'vibedom-old', 'runtime': 'docker',
        'created_at': '2026-01-01T00:00:00', 'repo_dir': str(cdir / 'repo'),
        'status': 'stopped', 'live': False,
    }))
    return proj, home, cdir


def test_up_refuses_legacy_container(tmp_path):
    proj, home, cdir = _legacy_setup(tmp_path)
    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli.VMManager') as mock_vm_cls:
            mock_vm_cls._detect_runtime.return_value = ('docker', 'docker')
            result = runner.invoke(main, ['up', str(proj)])

    assert result.exit_code == 1
    assert 'copy+sync' in result.output
    assert str(cdir / 'repo') in result.output
    assert 'vibedom destroy old' in result.output
    mock_vm_cls.return_value.start.assert_not_called()


def test_up_recreate_refuses_legacy_container(tmp_path):
    proj, home, _ = _legacy_setup(tmp_path)
    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli.VMManager') as mock_vm_cls:
            mock_vm_cls._detect_runtime.return_value = ('docker', 'docker')
            result = runner.invoke(main, ['up', str(proj), '--recreate'])

    assert result.exit_code == 1
    assert 'vibedom destroy old' in result.output
    mock_vm_cls.return_value.stop.assert_not_called()


def test_up_recreate_has_no_yes_flag(tmp_path):
    proj = tmp_path / 'myapp'
    proj.mkdir()
    result = CliRunner().invoke(main, ['up', str(proj), '--recreate', '--yes'])
    assert result.exit_code == 2
    assert 'No such option' in result.output


def test_up_has_no_pull_or_push():
    result = CliRunner().invoke(main, ['pull', 'x'])
    assert result.exit_code == 2
    result = CliRunner().invoke(main, ['push', 'x'])
    assert result.exit_code == 2
```

(`json` is needed; make sure it is imported at the top of `test_cli.py`.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_cli.py -q -k "up_" 2>&1 | tail -5`
Expected: the new tests fail (`--yes` still accepted, `pull` still exists, legacy not refused, default mount missing so `VMManager` mock receives `mounts=None`).

- [ ] **Step 3: Implement**

In `lib/vibedom/cli.py`:

Add `from vibedom.project_config import ProjectConfig, Mount`.

Delete the `pull` and `push` commands and the helpers `_validate_sync_paths`, `_make_workspace_relative`, `_build_rsync_cmd`, `_find_deletions` (everything from `def _validate_sync_paths` to the end of `push`).

Add above `_run_setup_commands`:

```python
def _resolve_mounts(workspace_path: Path, project_config) -> list[Mount]:
    """Mounts for a container: vibedom.yml `mounts:` if set, else the workspace itself.

    Example:
        # no vibedom.yml, or one without mounts:
        _resolve_mounts(Path('~/projects/myapp'), None)
        -> [Mount(host_path=~/projects/myapp, name='myapp', read_only=False)]
    """
    if project_config and project_config.mounts:
        return project_config.mounts
    return [Mount(host_path=workspace_path, name=workspace_path.name, read_only=False)]


LEGACY_MESSAGE = """\
Container '{container}' was created with the old copy+sync model, which has
been removed. Its repo copy is still at:

  {repo}

That is a normal git repo — push or copy anything you need from it, then:

  vibedom destroy {name}
  vibedom up {workspace}
"""


def _refuse_legacy(state: ContainerState, container_dir: Path) -> None:
    """Exit with rescue instructions if `state` is a pre-live-mount container."""
    if not state.legacy:
        return
    click.secho(LEGACY_MESSAGE.format(
        container=state.container_name,
        repo=container_dir / 'repo',
        name=Path(state.workspace).name,
        workspace=state.workspace,
    ), fg='red')
    sys.exit(1)
```

Rewrite the `up` command's decorators and body. Remove the `--yes` option and the `yes` parameter:

```python
@main.command()
@click.argument('workspace', type=click.Path(exists=True))
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple'],
              case_sensitive=False), default='auto',
              help='Container runtime (auto-detect, docker, or apple)')
@click.option('--recreate', is_flag=True,
              help='Remove the existing container and create it again from the current '
                   'vibedom.yml (picks up new mounts, env, image changes). Container '
                   'state is kept; setup commands re-run. Your files are untouched — '
                   'they are bind-mounted, not copied.')
def up(workspace, runtime, recreate):
    """Start a persistent project container.

    The project directory (or the dirs listed under `mounts:` in vibedom.yml)
    is bind-mounted live under /work. Creates the container on first use,
    restarts it if stopped, does nothing if already running.
    """
```

Body changes, in order:

1. After `project_config = ProjectConfig.load(workspace_path)` replace the `mounts = project_config.mounts if project_config else None` line and the `if mounts:` directory check with:

```python
    mounts = _resolve_mounts(workspace_path, project_config)
    for m in mounts:
        if not m.host_path.is_dir():
            click.secho(f"Error: mount path is not a directory: {m.host_path}", fg='red')
            sys.exit(1)
```

2. After `container_state = registry.find(workspace_path.name)` add:

```python
    if container_state is not None:
        _refuse_legacy(container_state, container_dir)
```

3. In the `recreate` block delete the `if not (mounts or yes) and not click.confirm(...)` prompt entirely, and replace `ContainerState.create(workspace_path, resolved_runtime, live=bool(mounts))` / `container_state.live = bool(mounts)` with `ContainerState.create(workspace_path, resolved_runtime)` and no `live` assignment.

4. In the already-running branch replace the `if container_state and container_state.live: ... else: click.echo(f"Repo: ...")` with a single `click.echo("Files are bind-mounted from your host — edit them directly.")`.

5. In the restart branch and first-run branch replace every `ContainerState.create(workspace_path, resolved_runtime, live=bool(mounts))` with `ContainerState.create(workspace_path, resolved_runtime)`.

6. First-run secret scan: replace the `if mounts: ... else: findings = scan_workspace(workspace_path)` with:

```python
        findings = []
        for m in mounts:
            findings.extend(scan_workspace(m.host_path))
```

7. Final output: delete the `if mounts: ... else: ...` split and keep only the mount listing:

```python
    click.echo("\nContainer running!")
    click.echo("Mounted:")
    for m in mounts:
        ro = ' (ro)' if m.read_only else ''
        click.echo(f"  {m.host_path} -> /work/{m.name}{ro}")
    click.echo(f"\nTo open a shell:\n  vibedom shell {workspace_path.name}")
    click.echo(f"\nTo stop:\n  vibedom down {workspace_path.name}")
```

- [ ] **Step 4: Run**

Run: `python -m pytest tests/test_cli.py -q 2>&1 | tail -1`
Expected: all `test_up_*` pass; `test_shell_non_live_container_uses_work_repo_dir` may fail — it is rewritten in Task 8.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor!: vibedom up always live-mounts; remove pull/push and copy+sync

Co-Authored-By: Claude Fable 5.1 <[REDACTED_EMAIL]>"
```

---

### Task 7: `vibedom status` marks legacy containers

**Files:**
- Modify: `lib/vibedom/cli.py` (`status`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `state.legacy` (Task 3).

- [ ] **Step 1: Write the failing test**

```python
def test_status_marks_legacy_container_and_lists_others(tmp_path):
    home = tmp_path / 'home'
    old, _, _ = _legacy_setup(tmp_path)          # writes home/.vibedom/containers/old
    new = tmp_path / 'new'
    new.mkdir()
    cdir = home / '.vibedom' / 'containers' / 'new'
    cdir.mkdir(parents=True)
    ContainerState.create(new, 'docker').save(cdir)

    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli._live_container_status', return_value='stopped'):
            result = CliRunner().invoke(main, ['status'])

    assert result.exit_code == 0, result.output
    lines = {l.split()[0]: l for l in result.output.splitlines() if l.startswith(('old', 'new'))}
    assert 'legacy' in lines['old'] and 'vibedom destroy' in lines['old']
    assert 'legacy' not in lines['new']
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_cli.py -q -k status_marks_legacy 2>&1 | tail -2`
Expected: FAIL, `'legacy' in lines['old']` is false.

- [ ] **Step 3: Implement**

In `status`, inside the `for c in containers:` loop, replace the `live_status = _live_container_status(c)` line with:

```python
        if c.legacy:
            live_status = 'legacy'
            proxy_info = 'copy+sync container — run: vibedom destroy ' + workspace_name
        else:
            live_status = _live_container_status(c)
```

(`proxy_info` is computed just above; overwriting it for legacy rows keeps the table aligned.)

- [ ] **Step 4: Run**

Run: `python -m pytest tests/test_cli.py -q -k status 2>&1 | tail -1`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add lib/vibedom/cli.py tests/test_cli.py
git commit -m "feat: vibedom status flags legacy copy+sync containers

Co-Authored-By: Claude Fable 5.1 <[REDACTED_EMAIL]>"
```

---

### Task 8: `vibedom shell`: refuse legacy, cwd from mount count

**Files:**
- Modify: `lib/vibedom/cli.py` (`shell_cmd`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `_resolve_mounts`, `_refuse_legacy` (Task 6).

- [ ] **Step 1: Rewrite the shell tests**

Delete `test_shell_live_container_uses_work_dir` and `test_shell_non_live_container_uses_work_repo_dir`. Add:

```python
def _shell_setup(tmp_path, yml=''):
    proj = tmp_path / 'myapp'
    proj.mkdir()
    if yml:
        (proj / 'vibedom.yml').write_text(yml)
    home = tmp_path / 'home'
    cdir = home / '.vibedom' / 'containers' / 'myapp'
    cdir.mkdir(parents=True)
    state = ContainerState.create(proj, 'docker')
    state.mark_running(54321, 4242, cdir)
    return proj, home


def _invoke_shell(home):
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli._ensure_proxy_running'):
            with patch('vibedom.cli.subprocess.run') as mock_run:
                result = CliRunner().invoke(main, ['shell', 'myapp'], catch_exceptions=False)
    return result, mock_run


def test_shell_single_mount_opens_in_that_mount(tmp_path):
    _, home = _shell_setup(tmp_path)
    result, mock_run = _invoke_shell(home)
    assert result.exit_code == 0, result.output
    cmd = mock_run.call_args.args[0]
    assert cmd[cmd.index('-w') + 1] == '/work/myapp'


def test_shell_multiple_mounts_opens_in_work(tmp_path):
    (tmp_path / 'a').mkdir()
    (tmp_path / 'b').mkdir()
    _, home = _shell_setup(tmp_path, f'mounts:\n  - {tmp_path / "a"}\n  - {tmp_path / "b"}\n')
    result, mock_run = _invoke_shell(home)
    assert result.exit_code == 0, result.output
    cmd = mock_run.call_args.args[0]
    assert cmd[cmd.index('-w') + 1] == '/work'


def test_shell_workdir_follows_current_config(tmp_path):
    """Editing vibedom.yml after creation changes the shell cwd without crashing."""
    proj, home = _shell_setup(tmp_path)
    (tmp_path / 'lib').mkdir()
    (proj / 'vibedom.yml').write_text(f'mounts:\n  - .\n  - {tmp_path / "lib"}\n')
    result, mock_run = _invoke_shell(home)
    assert result.exit_code == 0, result.output
    assert mock_run.call_args.args[0][mock_run.call_args.args[0].index('-w') + 1] == '/work'


def test_shell_refuses_legacy_container(tmp_path):
    _, home, _ = _legacy_setup(tmp_path)
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli.subprocess.run') as mock_run:
            result = CliRunner().invoke(main, ['shell', 'old'])
    assert result.exit_code == 1
    assert 'vibedom destroy old' in result.output
    mock_run.assert_not_called()
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_cli.py -q -k shell 2>&1 | tail -3`
Expected: `AttributeError: 'ContainerState' object has no attribute 'live'` or wrong cwd.

- [ ] **Step 3: Implement**

In `shell_cmd`, after the `if container_state is None:` exit and before `_ensure_proxy_running`, add:

```python
    container_dir = containers_dir / Path(container_state.workspace).name
    _refuse_legacy(container_state, container_dir)
```

(and delete the later duplicate `container_dir = ...` line). Replace `workdir = '/work' if container_state.live else '/work/repo'` with:

```python
    workspace_path = Path(container_state.workspace)
    mounts = _resolve_mounts(workspace_path, ProjectConfig.load(workspace_path))
    workdir = f'/work/{mounts[0].name}' if len(mounts) == 1 else '/work'
```

Update the docstring: `"""Open a shell in a running container (cwd: /work/<name>, or /work with several mounts)."""`

- [ ] **Step 4: Run**

Run: `python -m pytest tests/test_cli.py -q 2>&1 | tail -1`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add lib/vibedom/cli.py tests/test_cli.py
git commit -m "feat: vibedom shell opens in the single mount, refuses legacy containers

Co-Authored-By: Claude Fable 5.1 <[REDACTED_EMAIL]>"
```

---

### Task 9: startup.sh and image: drop the clone path and rsync

**Files:**
- Modify: `lib/vibedom/container/startup.sh:19-21,52-110`, `lib/vibedom/container/Dockerfile.alpine:13`
- Delete: `tests/test_startup_live_mode.py`
- Create: `tests/test_startup_workdir.py`

- [ ] **Step 1: Write the new test**

```bash
git rm -q tests/test_startup_live_mode.py
```

`tests/test_startup_workdir.py`:

```python
"""startup.sh init_repo: projects are bind-mounted under /work, so the only job
left is to cd there. No clone, no git init, no VIBEDOM_LIVE branch."""

import re
import subprocess
from pathlib import Path

STARTUP_SH = (
    Path(__file__).resolve().parent.parent
    / 'lib' / 'vibedom' / 'container' / 'startup.sh'
)


def _extract_function(name: str) -> str:
    text = STARTUP_SH.read_text()
    match = re.search(rf'^{name}\(\) \{{.*?^\}}', text, re.DOTALL | re.MULTILINE)
    assert match, f"{name}() not found in startup.sh"
    return match.group(0)


def test_init_repo_only_cds_to_work_dir(tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    script = _extract_function('init_repo') + '\ninit_repo\npwd\n'
    result = subprocess.run(
        ['sh', '-c', script], cwd=str(tmp_path),
        env={'PATH': '/usr/bin:/bin', 'WORK_DIR': str(work)},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == str(work)
    assert not (work / '.git').exists()


def test_startup_has_no_clone_or_live_flag():
    text = STARTUP_SH.read_text()
    for token in ('VIBEDOM_LIVE', 'git clone', 'REPO_DIR', 'WORKSPACE_DIR', 'rsync'):
        assert token not in text, f"{token} should be gone from startup.sh"


def test_alpine_image_does_not_install_rsync():
    dockerfile = STARTUP_SH.parent / 'Dockerfile.alpine'
    assert 'rsync' not in dockerfile.read_text()
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_startup_workdir.py -q 2>&1 | tail -3`
Expected: `test_startup_has_no_clone_or_live_flag` and `test_alpine_image_does_not_install_rsync` FAIL.

- [ ] **Step 3: Implement**

In `startup.sh` replace lines 19–24 (`WORK_DIR=...`, `REPO_DIR=...`, `WORKSPACE_DIR=...` and the comment) with:

```sh
WORK_DIR="${WORK_DIR:-/work}"

# Projects are bind-mounted live under $WORK_DIR by vibedom; nothing to clone.
```

Replace the whole `init_repo()` function with:

```sh
init_repo() {
    echo "Using live-mounted project(s) under $WORK_DIR"
    cd "$WORK_DIR"
}
```

Change `echo "Git repository initialized at $WORK_DIR"` to `echo "Working directory: $WORK_DIR"`.

In `Dockerfile.alpine` delete the `    rsync \` line from the `apk add` list.

- [ ] **Step 4: Run**

Run: `sh -n lib/vibedom/container/startup.sh && python -m pytest tests/test_startup_workdir.py tests/test_startup_git_identity.py tests/test_startup_ssh_agent.py -q 2>&1 | tail -1`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: startup.sh no longer clones; drop rsync from the image

Co-Authored-By: Claude Fable 5.1 <[REDACTED_EMAIL]>"
```

---

### Task 10: Whole-suite check and dead-code sweep

**Files:**
- Modify: anything `grep` turns up.

- [ ] **Step 1: Grep for leftovers**

```bash
grep -rn "session_dir\|SessionRegistry\|VIBEDOM_LIVE\|/mnt/workspace\|/work/repo\|sync_exclude\|repo_dir\|\.live\b\|words\.py\|random_name" lib/ tests/ pyproject.toml
```

Expected: no hits in `lib/`. Fix any that remain (docstrings included). `pyproject.toml` `pythonpath` and `package-data` need no change.

- [ ] **Step 2: Run the full suite**

Run: `python -m pytest tests/ -q 2>&1 | tail -1`
Expected: failures are a subset of the Task 1 baseline set (runtime-dependent `test_vm_*` tests only). Confirm with:

```bash
python -m pytest tests/ -q 2>&1 | grep FAILED | grep -v "tests/test_vm.py" ; echo "non-vm failures above (should be none)"
```

- [ ] **Step 3: Commit if anything changed**

```bash
git add -A
git commit -m "chore: remove leftovers from ephemeral/copy+sync removal

Co-Authored-By: Claude Fable 5.1 <[REDACTED_EMAIL]>"
```

---

### Task 11: Documentation rewrite

**Files:**
- Modify: `docs/USAGE.md`, `docs/ARCHITECTURE.md`, `docs/TESTING.md`, `README.md`, `CLAUDE.md`, `docs/technical-debt.md`

Rewrite, don't patch. Concrete content per file:

- [ ] **Step 1: `docs/USAGE.md`**

Keep Installation, First-Time Setup, Container Runtime. Then this structure:

```markdown
## Upgrading from an earlier vibedom

Vibedom now has a single model: the project directory is bind-mounted live into
the container. Ephemeral sessions (`vibedom run/stop/attach/review/merge`) and
copy+sync containers (`vibedom pull/push`, the `/work/repo` copy) have been
removed.

**If you have a container created before this change, you must destroy and
recreate it.** `vibedom up`, `vibedom shell` and `vibedom status` will tell you
when a container is one of these ("legacy"). Steps:

1. Anything the agent changed lives in the host-side copy at
   `~/.vibedom/containers/<name>/repo/`. It is a normal git repo: commit and
   push from there, or copy files out.
2. `vibedom destroy <name>`
3. `vibedom up <dir>` — the container is recreated with `<dir>` mounted live.

Old `~/.vibedom/logs/session-*` directories are no longer used and can be deleted.
`sync_exclude:` in `vibedom.yml` is ignored with a warning.

## Workflow

### Starting a container
`vibedom up ~/projects/myapp` — first run: secret scan, image build, container
created with `~/projects/myapp` mounted at `/work/myapp`, `setup:` commands run.
Later runs: restart / already-running / missing (recreated, setup re-run) /
`--recreate` (rebuilt from current vibedom.yml, setup re-run, no prompt).

### Project setup (vibedom.yml)
base_image, network, host_aliases, setup, memory, env, mounts — with the
existing examples, minus sync_exclude.

### Mounts
The current "Live Mount Mode" section, rewritten as the only mode: default
mount rule (no `mounts:` → the up dir at /work/<basename>); `mounts:` is the
complete list; scalar/mapping forms; `as:`/`ro:`; relative paths; mounts are
fixed at creation → `vibedom up --recreate`.

### Working in the container
`vibedom shell` opens `/work/<name>` (single mount) or `/work` (several).
Git is the safety net: work on branches, commit often. Agent commits land on
your real checkout.

### Reaching host services
host_aliases + HOST_IP, with the Docker Desktop "publish on 0.0.0.0" caveat
and the Valet/apple-container port 53 note.

### Status / Stopping / Destroying / Whitelist / Proxy restart
As today, with `destroy` noting it deletes only vibedom's state — never your
mounted directories.
```

Delete "Two Workflows", "Syncing Code", "Ephemeral Session Workflow", "Manual Git Access".

- [ ] **Step 2: `docs/ARCHITECTURE.md`**

Delete "Sync Layer" and "### Ephemeral session" data flow. Rewrite "Container Lifecycle", "VM Configuration" and "Storage Layout" so the only mounts are `/mnt/config:ro`, the Claude config volume, and `/work/<name>` per mount; storage layout is `~/.vibedom/{keys,whitelist.txt,mitmproxy,containers/<name>/{container.json,network.jsonl,mitmproxy.log}}`. In "Security Layer" replace "Path traversal protection in sync commands" with "Live mounts: the agent edits real files; `ro:` mounts for reference code; git is the safety net". Persistent-container data flow: `up` → scan mounts → build → proxy → run with mounts → setup; `shell`; `down`; `--recreate`.

- [ ] **Step 3: `docs/TESTING.md`**

Delete "Git Bundle Workflow Testing" and the stale "Test Results Summary" tables. Replace "Manual Testing" with the `up`/`shell`/`down`/`up --recreate`/`destroy` sequence and the in-container checks (`cat /tmp/.vm-ready`, `ls /work`, `curl https://pypi.org/simple/`). Mention the environmental baseline (runtime-dependent `test_vm.py` tests fail without Docker/apple-container).

- [ ] **Step 4: `README.md`**

Features: replace "Git bundle workflow" with "Live-mounted projects: the agent edits your real files inside an isolated VM; git is the safety net". Quick Start:

```bash
vibedom init
vibedom up ~/projects/myapp     # mounts ~/projects/myapp at /work/myapp
vibedom shell myapp             # run claude / your agent here
vibedom down myapp
```

How It Works: 1 VM isolation, 2 live bind mounts under /work, 3 forced proxy + whitelist + DLP, 4 deploy keys, 5 pre-flight secret scan. Add a two-line "Upgrading" note pointing to USAGE.md's section (legacy containers must be destroyed and recreated).

- [ ] **Step 5: `CLAUDE.md`**

- Current Status line: "Single live-mount container model (ephemeral sessions and copy+sync removed 2026-09-30)."
- Core Components: item 1 mounts = `/mnt/config:ro`, Claude config, `/work/<name>` per mount; delete item 5 (Session Management); item 6 CLI lists `init`, `up`, `down`, `destroy`, `status`, `shell`, `reload-whitelist`, `proxy-restart`.
- Key Design Decisions: replace "Two container models" and "Two filesystem models" with one "Single model: persistent, live-mounted" paragraph (default mount rule; `mounts:` complete list; legacy refusal); delete "Host-side rsync" and "Git Bundle Workflow"; keep idempotent startup (minus clone), explicit proxy, deploy keys.
- Development Workflow: persistent only; delete the ephemeral section; iterative loop is `shell` → work → commit.
- Known Limitations: delete "Persistent Container Sync" and "Git Bundle Workflow"; add "Legacy containers: must be destroyed and recreated (see USAGE.md Upgrading)".
- Project Structure: remove `session.py`; add `words.py` removal implicitly.
- Common Commands / Manual Testing / Debugging: remove `run/attach/stop/review/merge/pull/push/list` lines and session log paths.
- Security Considerations: "Read-only workspace" bullet → "Live mounts: agent edits real files; `ro:` mounts available; git is the safety net"; drop "Sync path validation".
- Roadmap: mark Phase 2b bullets as superseded (persistent containers remain; sync removed).
- Footer: `Last Updated: 2026-09-30 (single live-mount model)`.

- [ ] **Step 6: `docs/technical-debt.md`**

Delete sections "Git Bundle Workflow - Phase 2 Enhancements", "Task 6: Session Management", "Task 8: Run Command Integration", "Session Cleanup - Deferred Improvements". Keep HTTPS, Mitmproxy, Host Proxy, Future Considerations.

- [ ] **Step 7: Verify no stale references**

```bash
grep -rn "vibedom run\|vibedom pull\|vibedom push\|vibedom attach\|vibedom review\|vibedom merge\|/work/repo\|/mnt/workspace\|repo.bundle\|sync_exclude" README.md CLAUDE.md docs/USAGE.md docs/ARCHITECTURE.md docs/TESTING.md docs/technical-debt.md
```

Expected: hits only inside the "Upgrading" section (which names the removed commands on purpose) and USAGE's `sync_exclude` warning line.

- [ ] **Step 8: Commit**

```bash
git add README.md CLAUDE.md docs/
git commit -m "docs: single live-mount model; upgrading notes for legacy containers

Co-Authored-By: Claude Fable 5.1 <[REDACTED_EMAIL]>"
```

---

## Self-review notes

- Spec coverage: CLI removals (T1, T6), modules (T1), VM layer (T5), startup.sh + rsync (T9), ContainerState legacy (T3), ProxyManager rename (T4), project config obsolete key (T2), `up` default mount + legacy refusal + no prompt (T6), `shell` cwd + legacy (T8), `status` legacy marker (T7), secret scan over all mounts (T6 step 3.6), storage layout + docs + upgrading section (T11), dead-code sweep (T10). `destroy` is unchanged and needs no task.
- Type consistency: `_resolve_mounts(workspace_path, project_config) -> list[Mount]` and `_refuse_legacy(state, container_dir)` are defined in T6 and used in T7/T8; `ContainerState.create(workspace, runtime)` from T3 is used in T6/T7/T8 tests; `ProxyManager(log_dir=...)` from T4 is used in T5.
- Review Focus items 1–5 are pinned in T6, T3, T7, T8, T2 respectively.
