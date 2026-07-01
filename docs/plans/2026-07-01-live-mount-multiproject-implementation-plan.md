# Live Bind-Mount & Multi-Project Containers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a `vibedom` container bind-mount one or more real host project directories live (read-write or read-only) under `/work/<name>`, replacing the copy+rsync workflow for opted-in containers.

**Architecture:** Opt-in via a new `mounts:` key in `vibedom.yml`. When present, `vm.py` bind-mounts each listed dir at `/work/<name>` (skipping the read-only `/mnt/workspace` mount and the synced `/work/repo` copy) and sets `VIBEDOM_LIVE=1`; `startup.sh` detects that and skips clone/init. When `mounts:` is absent, behavior is byte-for-byte unchanged. Network/DLP isolation is untouched throughout.

**Tech Stack:** Python 3, Click, PyYAML, pytest, POSIX sh (container `startup.sh`), Docker / apple-container CLIs.

## Global Constraints

- **Backward compatibility is mandatory:** with `mounts:` absent, every code path must behave exactly as today. The copy+sync path (`/mnt/workspace:ro`, `/work/repo`, `pull`/`push` rsync) is preserved and untouched.
- **Do not run `git commit`.** The user handles all git. Each task's final step is a **checkpoint** (stop, report, let the user commit) — never a `git commit` invocation.
- **Global git identity is already handled** by `startup.sh`'s `ensure_git_identity` (`git config --global`); no per-repo identity work is needed.
- Follow existing test-mocking patterns: `unittest.mock.patch` on `subprocess.run` / `vibedom.cli.*`, `click.testing.CliRunner` for CLI, `_extract_function` regex extraction for `startup.sh`.
- Run the suite with `pytest tests/ -v`. Docker-dependent tests may be skipped/failing without a runtime — that is pre-existing and acceptable.
- A normalized mount is the `Mount` dataclass from Task 1: `Mount(host_path: Path, name: str, read_only: bool)`.

---

### Task 1: `mounts:` parsing in `ProjectConfig`

**Files:**
- Modify: `lib/vibedom/project_config.py`
- Test: `tests/test_project_config.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `Mount` dataclass (frozen): `Mount(host_path: Path, name: str, read_only: bool = False)`.
  - `ProjectConfig.mounts: Optional[list[Mount]]` — `None` when `mounts:` absent.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_project_config.py`:

```python
from vibedom.project_config import ProjectConfig, Mount


def test_mounts_defaults_to_none(tmp_path):
    """mounts is optional and defaults to None."""
    (tmp_path / 'vibedom.yml').write_text('base_image: myimage:latest\n')
    config = ProjectConfig.load(tmp_path)
    assert config.mounts is None


def test_mounts_scalar_entry_is_rw(tmp_path):
    """A scalar entry mounts read-write; name is the basename."""
    target = tmp_path / 'www'
    target.mkdir()
    (tmp_path / 'vibedom.yml').write_text(f'mounts:\n  - {target}\n')
    config = ProjectConfig.load(tmp_path)
    assert config.mounts == [Mount(host_path=target.resolve(), name='www', read_only=False)]


def test_mounts_dot_resolves_to_config_dir(tmp_path):
    """'.' resolves to the directory containing vibedom.yml."""
    (tmp_path / 'vibedom.yml').write_text('mounts:\n  - .\n')
    config = ProjectConfig.load(tmp_path)
    assert config.mounts == [Mount(host_path=tmp_path.resolve(), name=tmp_path.name, read_only=False)]


def test_mounts_mapping_with_alias_and_ro(tmp_path):
    """Mapping form supports 'as' and 'ro'."""
    target = tmp_path / 'shared-libs'
    target.mkdir()
    (tmp_path / 'vibedom.yml').write_text(
        f'mounts:\n  - path: {target}\n    as: shared\n    ro: true\n'
    )
    config = ProjectConfig.load(tmp_path)
    assert config.mounts == [Mount(host_path=target.resolve(), name='shared', read_only=True)]


def test_mounts_duplicate_name_raises(tmp_path):
    """Two entries resolving to the same name is a config error."""
    (tmp_path / 'a').mkdir()
    (tmp_path / 'b').mkdir()
    (tmp_path / 'vibedom.yml').write_text(
        f'mounts:\n  - path: {tmp_path / "a"}\n    as: dup\n'
        f'  - path: {tmp_path / "b"}\n    as: dup\n'
    )
    with pytest.raises(ValueError, match='Duplicate mount name'):
        ProjectConfig.load(tmp_path)


def test_mounts_mapping_missing_path_raises(tmp_path):
    """A mapping entry without 'path' is a config error."""
    (tmp_path / 'vibedom.yml').write_text('mounts:\n  - as: oops\n')
    with pytest.raises(ValueError, match="missing 'path'"):
        ProjectConfig.load(tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_project_config.py -k mounts -v`
Expected: FAIL — `ImportError: cannot import name 'Mount'` (and attribute errors).

- [ ] **Step 3: Implement `Mount` and parsing**

Replace the contents of `lib/vibedom/project_config.py` with:

```python
"""Parse vibedom.yml project configuration."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

KNOWN_FIELDS = {
    'base_image', 'network', 'host_aliases', 'setup',
    'sync_exclude', 'memory', 'env', 'mounts',
}


@dataclass(frozen=True)
class Mount:
    """A normalized bind mount: host_path -> /work/<name>, optionally read-only."""
    host_path: Path
    name: str
    read_only: bool = False


def _parse_mounts(raw, base_dir: Path) -> Optional[list]:
    """Normalize the raw `mounts:` value into a list of Mount, or None if absent.

    Scalar entries mount read-write at /work/<basename>. Mapping entries take
    `path` (required), optional `as` (subdir name), and optional `ro` (bool).
    Relative paths (including '.') resolve against base_dir (the vibedom.yml dir).
    """
    if raw is None:
        return None

    mounts = []
    seen = set()
    for entry in raw:
        if isinstance(entry, str):
            host, name, read_only = entry, None, False
        elif isinstance(entry, dict):
            if 'path' not in entry:
                raise ValueError(f"mounts entry missing 'path': {entry!r}")
            host = entry['path']
            name = entry.get('as')
            read_only = bool(entry.get('ro', False))
        else:
            raise ValueError(f"Invalid mounts entry: {entry!r}")

        host_path = Path(str(host)).expanduser()
        if not host_path.is_absolute():
            host_path = base_dir / host_path
        host_path = host_path.resolve()

        if name is None:
            name = host_path.name
        if name in seen:
            raise ValueError(
                f"Duplicate mount name '{name}' — use 'as:' to disambiguate"
            )
        seen.add(name)

        mounts.append(Mount(host_path=host_path, name=name, read_only=read_only))
    return mounts


@dataclass
class ProjectConfig:
    """Project-specific vibedom configuration from vibedom.yml."""
    base_image: Optional[str] = None
    network: Optional[str] = None
    host_aliases: Optional[dict] = None
    setup: Optional[list] = None
    sync_exclude: Optional[list] = None
    memory: Optional[str] = None
    env: Optional[dict] = None
    mounts: Optional[list] = None

    @classmethod
    def load(cls, workspace: Path) -> Optional['ProjectConfig']:
        """Load vibedom.yml from workspace root. Returns None if not present."""
        config_file = workspace / 'vibedom.yml'
        if not config_file.exists():
            return None

        with open(config_file, encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}

        unknown = set(data.keys()) - KNOWN_FIELDS
        if unknown:
            raise ValueError(f"Unknown vibedom.yml field(s): {', '.join(sorted(unknown))}")

        return cls(
            base_image=data.get('base_image'),
            network=data.get('network'),
            host_aliases=data.get('host_aliases'),
            setup=data.get('setup'),
            sync_exclude=data.get('sync_exclude'),
            memory=data.get('memory'),
            env=data.get('env'),
            mounts=_parse_mounts(data.get('mounts'), workspace.resolve()),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_project_config.py -v`
Expected: PASS (all existing tests plus the six new ones).

- [ ] **Step 5: Checkpoint** — report results; the user commits.

---

### Task 2: Live bind mounts in `VMManager.start()`

**Files:**
- Modify: `lib/vibedom/vm.py` (`VMManager.__init__`, `VMManager.start`)
- Test: `tests/test_vm.py`

**Interfaces:**
- Consumes: `Mount` from Task 1 (accessed by attribute: `.host_path`, `.name`, `.read_only`).
- Produces: `VMManager(..., mounts: Optional[list] = None)`. When `mounts` is set, the `run` argv includes `-e VIBEDOM_LIVE=1`, one `-v {host_path}:/work/{name}[:ro]` per mount, and NO `:/mnt/workspace:ro` and NO `/work/repo` copy mount.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_vm.py` (top-level imports already include `patch`, `MagicMock`, `subprocess`):

```python
from vibedom.project_config import Mount


def _run_argv(mock_run):
    """Extract the container-runtime 'run' argv from a patched subprocess.run."""
    return next(c[0][0] for c in mock_run.call_args_list if 'run' in c[0][0])


def test_start_with_live_mounts_emits_rw_and_ro(test_config, tmp_path):
    """With mounts set, start() bind-mounts each dir at /work/<name>, honoring ro,
    and omits the read-only workspace mount and the /work/repo copy."""
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
    assert 'VIBEDOM_LIVE=1' in cmd
    assert f'{www}:/work/www' in cmd
    assert f'{shared}:/work/shared:ro' in cmd
    assert not any(':/mnt/workspace:ro' in a for a in cmd)
    assert not any(a.endswith(':/work/repo') for a in cmd)


def test_start_without_mounts_still_mounts_workspace_ro(test_workspace, test_config, tmp_path):
    """With no mounts, start() keeps the read-only workspace mount (unchanged)."""
    with patch('shutil.which') as mock_which:
        mock_which.side_effect = lambda cmd: '/usr/local/bin/docker' if cmd == 'docker' else None
        vm = VMManager(test_workspace, test_config, session_dir=tmp_path / 'session')

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
    assert f'{test_workspace}:/mnt/workspace:ro' in cmd
    assert 'VIBEDOM_LIVE=1' not in cmd
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_vm.py -k "live_mounts or without_mounts" -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'mounts'`.

- [ ] **Step 3: Add the `mounts` parameter**

In `lib/vibedom/vm.py`, `VMManager.__init__`, add the parameter (after `memory`) and store it. Update the signature line and add the assignment:

```python
                 memory: Optional[str] = None,
                 mounts: Optional[list] = None):
```

Add with the other assignments in `__init__`:

```python
        self.mounts = mounts
```

- [ ] **Step 4: Branch the mount construction in `start()`**

In `start()`, find this block:

```python
            # Mounts
            '-v', f'{self.workspace}:/mnt/workspace:ro',
            '-v', f'{self.config_dir}:/mnt/config:ro',
        ]

        # Repo mount: prefer container_dir (persistent), fall back to session_dir (legacy)
        if self.container_dir:
            repo_dir = self.container_dir / 'repo'
            repo_dir.mkdir(parents=True, exist_ok=True)
            cmd += ['-v', f'{repo_dir}:/work/repo']
        elif self.session_dir:
            repo_dir = self.session_dir / 'repo'
            repo_dir.mkdir(parents=True, exist_ok=True)
            cmd += ['-v', f'{repo_dir}:/work/repo']

        if self.session_dir:
            cmd += ['-v', f'{self.session_dir}:/mnt/session']
```

Replace it with:

```python
            # Mounts
            '-v', f'{self.config_dir}:/mnt/config:ro',
        ]

        if self.mounts:
            # Live mode: bind-mount the real project dir(s) directly. No read-only
            # workspace mount and no synced /work/repo copy. startup.sh detects
            # this via VIBEDOM_LIVE and skips the clone/init step.
            cmd += ['-e', 'VIBEDOM_LIVE=1']
            for m in self.mounts:
                spec = f'{m.host_path}:/work/{m.name}'
                if m.read_only:
                    spec += ':ro'
                cmd += ['-v', spec]
        else:
            cmd += ['-v', f'{self.workspace}:/mnt/workspace:ro']
            # Repo mount: prefer container_dir (persistent), fall back to session_dir (legacy)
            if self.container_dir:
                repo_dir = self.container_dir / 'repo'
                repo_dir.mkdir(parents=True, exist_ok=True)
                cmd += ['-v', f'{repo_dir}:/work/repo']
            elif self.session_dir:
                repo_dir = self.session_dir / 'repo'
                repo_dir.mkdir(parents=True, exist_ok=True)
                cmd += ['-v', f'{repo_dir}:/work/repo']

        if self.session_dir:
            cmd += ['-v', f'{self.session_dir}:/mnt/session']
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_vm.py -v`
Expected: PASS (new tests plus all existing vm tests).

- [ ] **Step 6: Checkpoint** — report results; the user commits.

---

### Task 3: `startup.sh` live-mode detection

**Files:**
- Modify: `lib/vibedom/container/startup.sh`
- Test: `tests/test_startup_live_mode.py` (create)

**Interfaces:**
- Consumes: `VIBEDOM_LIVE=1` env var (set by Task 2).
- Produces: an extractable `init_repo()` shell function honoring `WORK_DIR`/`REPO_DIR`/`WORKSPACE_DIR` (defaulting to `/work`, `/work/repo`, `/mnt/workspace`) that returns early (just `cd "$WORK_DIR"`) when `VIBEDOM_LIVE` is set.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_startup_live_mode.py`:

```python
"""Behavioral tests for live-mount detection in startup.sh.

In live-mount mode (VIBEDOM_LIVE set) the real project dirs are bind-mounted
under $WORK_DIR, so init_repo must NOT clone or git-init anything — it just
cd's into $WORK_DIR. We extract the real init_repo function and run it.
"""

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


def _run_init_repo(cwd: Path, env_overrides: dict) -> subprocess.CompletedProcess:
    script = _extract_function('init_repo') + '\ninit_repo\npwd\n'
    env = {
        'PATH': '/usr/bin:/bin:/usr/local/bin',
        'HOME': str(cwd),
        'GIT_CONFIG_GLOBAL': '/dev/null',
        'GIT_CONFIG_SYSTEM': '/dev/null',
    }
    env.update(env_overrides)
    return subprocess.run(
        ['sh', '-c', script], cwd=str(cwd), env=env,
        capture_output=True, text=True,
    )


def test_live_mode_skips_clone_and_cds_to_work(tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    result = _run_init_repo(tmp_path, {
        'VIBEDOM_LIVE': '1',
        'WORK_DIR': str(work),
        'REPO_DIR': str(tmp_path / 'repo'),
        'WORKSPACE_DIR': str(tmp_path / 'ws'),
    })
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == str(work)
    assert not (tmp_path / 'repo').exists()


def test_existing_repo_still_skips_clone(tmp_path):
    repo = tmp_path / 'repo'
    (repo / '.git').mkdir(parents=True)
    result = _run_init_repo(tmp_path, {
        'WORK_DIR': str(tmp_path / 'work'),
        'REPO_DIR': str(repo),
        'WORKSPACE_DIR': str(tmp_path / 'ws'),
    })
    assert result.returncode == 0, result.stderr
    assert 'skipping clone' in result.stdout
    assert result.stdout.strip().splitlines()[-1] == str(repo)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_startup_live_mode.py -v`
Expected: FAIL — `AssertionError: init_repo() not found in startup.sh`.

- [ ] **Step 3: Refactor the repo-init block into `init_repo()` with a live guard**

In `lib/vibedom/container/startup.sh`, replace the whole block from the comment `# Initialize git repository from workspace (skip if already initialized)` through the line `echo "Git repository initialized at /work/repo"` with:

```sh
WORK_DIR="${WORK_DIR:-/work}"
REPO_DIR="${REPO_DIR:-/work/repo}"
WORKSPACE_DIR="${WORKSPACE_DIR:-/mnt/workspace}"

# Prepare the working tree. In live-mount mode (VIBEDOM_LIVE) the real project
# dir(s) are bind-mounted under $WORK_DIR, so there is nothing to clone or init.
init_repo() {
    if [ -n "$VIBEDOM_LIVE" ]; then
        echo "Live mount mode: using mounted project(s) directly"
        cd "$WORK_DIR"
        return
    fi

    if [ -d "$REPO_DIR/.git" ]; then
        echo "Existing repo found at $REPO_DIR, skipping clone"
        cd "$REPO_DIR"
    elif [ -d "$WORKSPACE_DIR/.git" ]; then
        echo "Cloning git repository from workspace..."
        git clone "$WORKSPACE_DIR/.git" "$REPO_DIR"
        cd "$REPO_DIR"

        # Checkout the same branch user is on
        CURRENT_BRANCH=$(git -C "$WORKSPACE_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
        echo "Detected branch: $CURRENT_BRANCH"

        if git show-ref --verify --quiet refs/heads/"$CURRENT_BRANCH"; then
            git checkout "$CURRENT_BRANCH"
        else
            git checkout -b "$CURRENT_BRANCH"
        fi

        echo "Working on branch: $CURRENT_BRANCH"

        # Copy .env* files from workspace (typically gitignored but needed at runtime)
        for env_file in "$WORKSPACE_DIR"/.env "$WORKSPACE_DIR"/.env.*; do
            [ -f "$env_file" ] && cp "$env_file" "$REPO_DIR"/ && echo "Copied $(basename $env_file)"
        done
    else
        echo "Non-git workspace, initializing fresh repository..."
        mkdir -p "$REPO_DIR"
        rsync -a --exclude='.git' "$WORKSPACE_DIR"/ "$REPO_DIR"/ || true
        cd "$REPO_DIR"
        git init

        # Set a default identity so the initial snapshot commit succeeds
        ensure_git_identity

        git add .
        git commit -m "Initial snapshot from vibedom session" || echo "No files to commit"
    fi
}

init_repo

# Apply the default agent identity only if the user has not set their own
ensure_git_identity

echo "Git repository initialized at $WORK_DIR"
```

(The `ensure_git_identity` function definition above this block is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_startup_live_mode.py tests/test_startup_git_identity.py -v`
Expected: PASS (both the new live-mode tests and the existing identity tests).

- [ ] **Step 5: Checkpoint** — report results; the user commits.

---

### Task 4: `live` marker on `ContainerState`

**Files:**
- Modify: `lib/vibedom/container_state.py` (`ContainerState` dataclass, `create`)
- Test: `tests/test_container_state.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `ContainerState.live: bool` (default `False`), persisted in `container.json`; `ContainerState.create(workspace, runtime, live: bool = False)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_container_state.py`:

```python
def test_create_defaults_live_false(tmp_path):
    state = ContainerState.create(tmp_path / 'myapp', 'docker')
    assert state.live is False


def test_create_live_roundtrips(tmp_path):
    state = ContainerState.create(tmp_path / 'myapp', 'docker', live=True)
    state.save(tmp_path)
    reloaded = ContainerState.load(tmp_path)
    assert reloaded.live is True


def test_load_legacy_json_without_live(tmp_path):
    """A container.json written before the `live` field loads with live=False."""
    import json
    (tmp_path / 'container.json').write_text(json.dumps({
        'workspace': str(tmp_path / 'myapp'),
        'container_name': 'vibedom-myapp',
        'runtime': 'docker',
        'created_at': '2026-01-01T00:00:00',
        'repo_dir': str(tmp_path / 'repo'),
        'status': 'stopped',
    }))
    state = ContainerState.load(tmp_path)
    assert state.live is False
```

(`ContainerState` is already imported at the top of `tests/test_container_state.py`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_container_state.py -k live -v`
Expected: FAIL — `AttributeError: 'ContainerState' object has no attribute 'live'`.

- [ ] **Step 3: Add the `live` field**

In `lib/vibedom/container_state.py`, add the field to the dataclass (after `proxy_pid`):

```python
    proxy_pid: Optional[int] = None
    live: bool = False
```

Update `create` to accept and set it:

```python
    @classmethod
    def create(cls, workspace: Path, runtime: str, live: bool = False) -> 'ContainerState':
        """Create a new ContainerState for a fresh container."""
        workspace = workspace.resolve()
        name = workspace.name
        container_name = f'vibedom-{name}'
        repo_dir = Path.home() / '.vibedom' / 'containers' / name / 'repo'
        return cls(
            workspace=str(workspace),
            container_name=container_name,
            runtime=runtime,
            created_at=datetime.now().isoformat(timespec='seconds'),
            repo_dir=str(repo_dir),
            status='stopped',
            live=live,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_container_state.py -v`
Expected: PASS (new tests plus all existing state tests — the defaulted field keeps `load(**data)` backward compatible).

- [ ] **Step 5: Checkpoint** — report results; the user commits.

---

### Task 5: Wire mounts into `vibedom up`

**Files:**
- Modify: `lib/vibedom/cli.py` (`up`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `ProjectConfig.mounts` (Task 1), `VMManager(..., mounts=)` (Task 2), `ContainerState.create(..., live=)` (Task 4).
- Produces: an `up` that validates mount paths, gitleaks-scans each mounted tree, passes `mounts` to `VMManager`, and persists `live=True` in `container.json`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py` (imports at top already include `patch`, `MagicMock`, `CliRunner`, `main`):

```python
from vibedom.container_state import ContainerState


def test_up_live_mounts_passes_mounts_and_persists_live(tmp_path):
    """up with a mounts: config passes normalized mounts to VMManager and marks the
    container live; it does not scan or mount a /work/repo copy."""
    proj = tmp_path / 'agent'
    proj.mkdir()
    target = tmp_path / 'www'
    target.mkdir()
    (proj / 'vibedom.yml').write_text(f'mounts:\n  - {target}\n')

    home = tmp_path / 'home'
    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli.scan_workspace', return_value=[]):
            with patch('vibedom.cli.review_findings', return_value=True):
                with patch('vibedom.cli.VMManager') as mock_vm_cls:
                    mock_vm_cls._detect_runtime.return_value = ('docker', 'docker')
                    mock_vm = MagicMock()
                    mock_vm.is_running.return_value = False
                    mock_vm.exists.return_value = False
                    mock_vm._proxy = MagicMock(port=54321, pid=99999)
                    mock_vm_cls.return_value = mock_vm
                    result = runner.invoke(main, ['up', str(proj)], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    _, kwargs = mock_vm_cls.call_args
    mounts = kwargs['mounts']
    assert [(m.name, m.read_only) for m in mounts] == [('www', False)]

    state = ContainerState.load(home / '.vibedom' / 'containers' / 'agent')
    assert state.live is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::test_up_live_mounts_passes_mounts_and_persists_live -v`
Expected: FAIL — `KeyError: 'mounts'` (VMManager not yet called with a `mounts` kwarg).

- [ ] **Step 3: Compute + validate mounts and pass them through**

In `lib/vibedom/cli.py`, in `up`, find:

```python
    project_config = ProjectConfig.load(workspace_path)
    registry = ContainerRegistry(containers_dir)
    container_state = registry.find(workspace_path.name)

    vm = VMManager(
        workspace_path, config_dir,
        container_dir=container_dir,
        runtime=resolved_runtime,
        network=project_config.network if project_config else None,
        base_image=project_config.base_image if project_config else None,
        host_aliases=project_config.host_aliases if project_config else None,
        memory=project_config.memory if project_config else None,
    )
```

Replace with:

```python
    project_config = ProjectConfig.load(workspace_path)
    mounts = project_config.mounts if project_config else None
    if mounts:
        for m in mounts:
            if not m.host_path.is_dir():
                click.secho(
                    f"Error: mount path is not a directory: {m.host_path}", fg='red'
                )
                sys.exit(1)

    registry = ContainerRegistry(containers_dir)
    container_state = registry.find(workspace_path.name)

    vm = VMManager(
        workspace_path, config_dir,
        container_dir=container_dir,
        runtime=resolved_runtime,
        network=project_config.network if project_config else None,
        base_image=project_config.base_image if project_config else None,
        host_aliases=project_config.host_aliases if project_config else None,
        memory=project_config.memory if project_config else None,
        mounts=mounts,
    )
```

- [ ] **Step 4: Scan each mount and mark the container live**

Still in `up`, in the restart branch find:

```python
        if container_state is None:
            container_state = ContainerState.create(workspace_path, resolved_runtime)
```

Replace with:

```python
        if container_state is None:
            container_state = ContainerState.create(
                workspace_path, resolved_runtime, live=bool(mounts)
            )
```

Then in the first-time-creation `else` branch, find:

```python
        # First-time creation
        click.echo("Scanning for secrets...")
        findings = scan_workspace(workspace_path)
        if not review_findings(findings):
            click.secho("Cancelled", fg='yellow')
            sys.exit(1)
```

Replace with:

```python
        # First-time creation
        click.echo("Scanning for secrets...")
        if mounts:
            findings = []
            for m in mounts:
                findings.extend(scan_workspace(m.host_path))
        else:
            findings = scan_workspace(workspace_path)
        if not review_findings(findings):
            click.secho("Cancelled", fg='yellow')
            sys.exit(1)
```

And a few lines below, find:

```python
        container_state = ContainerState.create(workspace_path, resolved_runtime)
        if vm._proxy:
```

Replace with:

```python
        container_state = ContainerState.create(
            workspace_path, resolved_runtime, live=bool(mounts)
        )
        if vm._proxy:
```

- [ ] **Step 5: Give live-appropriate final guidance**

Still in `up`, find the trailing guidance block:

```python
    click.echo(f"\nContainer running!")
    click.echo(f"Workspace: {workspace_path}")
    click.echo(f"Repo: {container_dir / 'repo'}")
    click.echo(f"\nTo sync code:")
    click.echo(f"  vibedom pull {workspace_path.name}   # container -> host")
    click.echo(f"  vibedom push {workspace_path.name}   # host -> container")
    click.echo(f"\nTo open a shell:")
    click.echo(f"  vibedom shell {workspace_path.name}")
    click.echo(f"\nTo stop:")
    click.echo(f"  vibedom down {workspace_path.name}")
```

Replace with:

```python
    if mounts:
        click.echo(f"\nContainer running (live mount)!")
        click.echo("Mounted:")
        for m in mounts:
            ro = ' (ro)' if m.read_only else ''
            click.echo(f"  {m.host_path} -> /work/{m.name}{ro}")
        click.echo(f"\nTo open a shell:")
        click.echo(f"  vibedom shell {workspace_path.name}")
        click.echo(f"\nTo stop:")
        click.echo(f"  vibedom down {workspace_path.name}")
    else:
        click.echo(f"\nContainer running!")
        click.echo(f"Workspace: {workspace_path}")
        click.echo(f"Repo: {container_dir / 'repo'}")
        click.echo(f"\nTo sync code:")
        click.echo(f"  vibedom pull {workspace_path.name}   # container -> host")
        click.echo(f"  vibedom push {workspace_path.name}   # host -> container")
        click.echo(f"\nTo open a shell:")
        click.echo(f"  vibedom shell {workspace_path.name}")
        click.echo(f"\nTo stop:")
        click.echo(f"  vibedom down {workspace_path.name}")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (new test plus all existing CLI tests).

- [ ] **Step 7: Checkpoint** — report results; the user commits.

---

### Task 6: `vibedom shell` opens at `/work` for live containers

**Files:**
- Modify: `lib/vibedom/cli.py` (`shell_cmd`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `ContainerState.live` (Task 4).
- Produces: `shell` uses `-w /work` when `container_state.live`, else `-w /work/repo` (unchanged).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def test_shell_live_container_uses_work_dir(tmp_path):
    """shell into a live container opens /work, not /work/repo."""
    state = ContainerState.create(tmp_path / 'myapp', 'docker', live=True)
    state.status = 'running'

    runner = CliRunner()
    with patch('vibedom.cli.ContainerRegistry') as mock_registry_cls:
        mock_registry = MagicMock()
        mock_registry.find.return_value = state
        mock_registry_cls.return_value = mock_registry
        with patch('vibedom.cli._ensure_proxy_running'):
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = runner.invoke(main, ['shell', 'myapp'], catch_exceptions=False)

    assert result.exit_code == 0
    cmd = mock_run.call_args[0][0]
    assert '-w' in cmd
    assert cmd[cmd.index('-w') + 1] == '/work'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::test_shell_live_container_uses_work_dir -v`
Expected: FAIL — assertion error: the working dir is `/work/repo`.

- [ ] **Step 3: Choose the working dir by live flag**

In `lib/vibedom/cli.py`, in `shell_cmd`, find:

```python
    runtime_cmd = 'container' if container_state.runtime == 'apple' else 'docker'
    cmd = [runtime_cmd, 'exec', '-it', '-w', '/work/repo',
           container_state.container_name, 'bash', '--login']
```

Replace with:

```python
    runtime_cmd = 'container' if container_state.runtime == 'apple' else 'docker'
    workdir = '/work' if container_state.live else '/work/repo'
    cmd = [runtime_cmd, 'exec', '-it', '-w', workdir,
           container_state.container_name, 'bash', '--login']
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -k shell -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint** — report results; the user commits.

---

### Task 7: `pull` / `push` no-op for live containers

**Files:**
- Modify: `lib/vibedom/cli.py` (`pull`, `push`)
- Test: `tests/test_sync.py`

**Interfaces:**
- Consumes: `ContainerState.live` (Task 4).
- Produces: `pull` and `push` print a "no sync needed" message and return without invoking rsync when the target container is live.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sync.py` (reuses the existing `sync_env` fixture):

```python
def test_pull_noop_for_live_container(sync_env):
    """pull on a live-mount container does no rsync."""
    sync_env['state'].live = True
    runner = CliRunner()
    with patch('vibedom.cli.ContainerRegistry') as mock_registry_cls:
        mock_registry = MagicMock()
        mock_registry.find.return_value = sync_env['state']
        mock_registry_cls.return_value = mock_registry
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(main, ['pull', 'myapp', '--yes'], catch_exceptions=False)

    assert result.exit_code == 0
    assert 'no sync needed' in result.output
    assert not any('rsync' in str(c) for c in mock_run.call_args_list)


def test_push_noop_for_live_container(sync_env):
    """push on a live-mount container does no rsync."""
    sync_env['state'].live = True
    runner = CliRunner()
    with patch('vibedom.cli.ContainerRegistry') as mock_registry_cls:
        mock_registry = MagicMock()
        mock_registry.find.return_value = sync_env['state']
        mock_registry_cls.return_value = mock_registry
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(main, ['push', 'myapp', '--yes'], catch_exceptions=False)

    assert result.exit_code == 0
    assert 'no sync needed' in result.output
    assert not any('rsync' in str(c) for c in mock_run.call_args_list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sync.py -k live -v`
Expected: FAIL — rsync is invoked and no "no sync needed" text appears.

- [ ] **Step 3: Add the live guard to both commands**

In `lib/vibedom/cli.py`, in `pull`, find:

```python
    container_state = registry.find(workspace)
    if container_state is None:
        click.secho(f"No container found for '{workspace}'.", fg='red')
        sys.exit(1)

    workspace_path = Path(container_state.workspace)
```

Replace with (note: this exact block appears in both `pull` and `push` — apply to both):

```python
    container_state = registry.find(workspace)
    if container_state is None:
        click.secho(f"No container found for '{workspace}'.", fg='red')
        sys.exit(1)

    if container_state.live:
        click.echo(
            "This is a live-mount container — changes are already on your host; "
            "no sync needed."
        )
        return

    workspace_path = Path(container_state.workspace)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sync.py -v`
Expected: PASS (new tests plus all existing sync tests).

- [ ] **Step 5: Full suite**

Run: `pytest tests/ -v`
Expected: PASS for all non-Docker-dependent tests (Docker-runtime integration tests may skip/fail without a runtime — pre-existing).

- [ ] **Step 6: Checkpoint** — report results; the user commits.

---

## Self-Review

**Spec coverage:**
- Live bind mount replacing copy+sync → Tasks 2 (vm), 3 (startup skip), 5 (up wiring). ✓
- `mounts:` config, scalar + `{path, as, ro}`, `.` resolution, collision error → Task 1. ✓
- Read-write default + `:ro` → Tasks 1 (parse) + 2 (argv). ✓
- Backward compatibility (mounts absent = unchanged) → asserted in Task 2 (`test_start_without_mounts_still_mounts_workspace_ro`), Task 4 (legacy json), and preserved branches in Task 5. ✓
- Gitleaks scan per mount → Task 5. ✓
- Shell opens `/work` → Task 6. ✓
- `pull`/`push` no-op → Task 7. ✓
- `live` marker in `container.json` → Task 4, consumed by Tasks 5/6/7. ✓
- Global git identity needs no per-repo work → honored (Task 3 leaves `ensure_git_identity` as-is). ✓

**Placeholder scan:** none — every code step contains complete code and exact commands.

**Type consistency:** `Mount(host_path, name, read_only)` defined in Task 1 and used by attribute in Tasks 2 and 5; `VMManager(..., mounts=)` defined in Task 2 and called in Task 5; `ContainerState.create(..., live=)` and `.live` defined in Task 4 and used in Tasks 5/6/7. Consistent.
