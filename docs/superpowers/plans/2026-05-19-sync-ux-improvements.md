# Sync UX Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two `vibedom push`/`pull` pain points: paths that are hard to get right because they must be workspace-root-relative, and `--delete` silently removing files that only exist on the destination side.

**Architecture:** Two self-contained changes to `lib/vibedom/cli.py`. (1) A new helper `_make_workspace_relative` pre-processes path arguments before validation — if CWD is inside the workspace it resolves relative to CWD, otherwise it falls through unchanged. (2) A new helper `_find_deletions` runs a silent rsync dry-run and parses `deleting …` lines; when `--delete` is used without `--force` or `--dry-run`, `push`/`pull` call it and gate on user confirmation. A new `--force`/`-f` flag skips all confirmations.

**Tech Stack:** Python 3.11+, Click, rsync, pytest, `unittest.mock`

---

### Task 1: `_make_workspace_relative` unit

**Files:**
- Modify: `lib/vibedom/cli.py` (add function after `_validate_sync_paths`)
- Modify: `tests/test_sync.py` (add unit tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sync.py`:

```python
from vibedom.cli import _make_workspace_relative


def test_make_workspace_relative_from_cwd_inside_workspace(tmp_path):
    workspace = tmp_path / 'myapp'
    (workspace / 'src' / 'app').mkdir(parents=True)
    cwd = workspace / 'src'
    result = _make_workspace_relative('app', workspace, cwd=cwd)
    assert result == 'src/app'


def test_make_workspace_relative_from_cwd_at_workspace_root(tmp_path):
    workspace = tmp_path / 'myapp'
    (workspace / 'src').mkdir(parents=True)
    result = _make_workspace_relative('src', workspace, cwd=workspace)
    assert result == 'src'


def test_make_workspace_relative_from_cwd_outside_workspace(tmp_path):
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    cwd = tmp_path  # outside workspace
    result = _make_workspace_relative('src/app', workspace, cwd=cwd)
    assert result == 'src/app'  # unchanged


def test_make_workspace_relative_from_cwd_deeply_nested(tmp_path):
    workspace = tmp_path / 'myapp'
    (workspace / 'src' / 'app' / 'Controllers').mkdir(parents=True)
    cwd = workspace / 'src' / 'app'
    result = _make_workspace_relative('Controllers', workspace, cwd=cwd)
    assert result == 'src/app/Controllers'
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/tim/Documents/projects/vibedom && source .venv/bin/activate && pytest tests/test_sync.py::test_make_workspace_relative_from_cwd_inside_workspace -v
```

Expected: `ImportError` or `AttributeError` — `_make_workspace_relative` doesn't exist yet.

- [ ] **Step 3: Implement `_make_workspace_relative`**

Add this function in `lib/vibedom/cli.py` immediately after `_validate_sync_paths` (around line 1158):

```python
def _make_workspace_relative(raw: str, workspace_root: Path, cwd: Path | None = None) -> str:
    """Resolve a path argument relative to CWD if CWD is inside workspace_root.

    Returns a workspace-root-relative path string. Falls back to raw unchanged
    if CWD is outside workspace_root or if the resolved path escapes the root.
    """
    if cwd is None:
        cwd = Path.cwd()
    workspace_resolved = workspace_root.resolve()
    try:
        cwd.resolve().relative_to(workspace_resolved)
    except ValueError:
        return raw
    try:
        return str((cwd / raw).resolve().relative_to(workspace_resolved))
    except ValueError:
        return raw
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_sync.py::test_make_workspace_relative_from_cwd_inside_workspace tests/test_sync.py::test_make_workspace_relative_from_cwd_at_workspace_root tests/test_sync.py::test_make_workspace_relative_from_cwd_outside_workspace tests/test_sync.py::test_make_workspace_relative_from_cwd_deeply_nested -v
```

Expected: all 4 PASS.

- [ ] **Step 5: Run full sync test suite to check no regressions**

```bash
pytest tests/test_sync.py -v
```

Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add lib/vibedom/cli.py tests/test_sync.py
git commit -m "feat: add _make_workspace_relative for CWD-relative path resolution"
```

---

### Task 2: Wire CWD-relative resolution into `pull` and `push`

**Files:**
- Modify: `lib/vibedom/cli.py` (`pull` and `push` commands)
- Modify: `tests/test_sync.py` (integration tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sync.py`:

```python
def test_pull_resolves_paths_via_make_workspace_relative(sync_env):
    """pull should call _make_workspace_relative for each path argument."""
    runner = CliRunner()

    with patch('vibedom.cli.ContainerRegistry') as mock_registry_cls:
        mock_registry = MagicMock()
        mock_registry.find.return_value = sync_env['state']
        mock_registry_cls.return_value = mock_registry

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('vibedom.cli._make_workspace_relative', return_value='src/app.php') as mock_resolve:
                result = runner.invoke(
                    main, ['pull', 'myapp', 'app.php'], catch_exceptions=False
                )

    assert result.exit_code == 0
    mock_resolve.assert_called_once()
    assert mock_resolve.call_args[0][0] == 'app.php'


def test_push_resolves_paths_via_make_workspace_relative(sync_env):
    """push should call _make_workspace_relative for each path argument."""
    runner = CliRunner()

    with patch('vibedom.cli.ContainerRegistry') as mock_registry_cls:
        mock_registry = MagicMock()
        mock_registry.find.return_value = sync_env['state']
        mock_registry_cls.return_value = mock_registry

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('vibedom.cli._make_workspace_relative', return_value='src/app.php') as mock_resolve:
                result = runner.invoke(
                    main, ['push', 'myapp', 'app.php'], catch_exceptions=False
                )

    assert result.exit_code == 0
    mock_resolve.assert_called_once()
    assert mock_resolve.call_args[0][0] == 'app.php'


def test_pull_prints_resolved_paths(sync_env):
    """pull should print the resolved workspace-relative path before syncing."""
    runner = CliRunner()

    with patch('vibedom.cli.ContainerRegistry') as mock_registry_cls:
        mock_registry = MagicMock()
        mock_registry.find.return_value = sync_env['state']
        mock_registry_cls.return_value = mock_registry

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('vibedom.cli._make_workspace_relative', return_value='src/app/Controllers'):
                result = runner.invoke(
                    main, ['pull', 'myapp', 'app/Controllers'], catch_exceptions=False
                )

    assert 'src/app/Controllers' in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_sync.py::test_pull_resolves_paths_via_make_workspace_relative tests/test_sync.py::test_push_resolves_paths_via_make_workspace_relative tests/test_sync.py::test_pull_prints_resolved_paths -v
```

Expected: all 3 FAIL — `_make_workspace_relative` is not called yet.

- [ ] **Step 3: Wire resolution into `pull`**

In `lib/vibedom/cli.py`, inside the `pull` function, replace the `if paths:` validation block:

Old code (around line 1238):
```python
    if paths:
        try:
            _validate_sync_paths(paths, repo_dir)
        except click.ClickException as e:
            click.secho(f"Error: {e.format_message()}", fg='red')
            sys.exit(1)
```

New code:
```python
    if paths:
        paths = tuple(_make_workspace_relative(p, workspace_path) for p in paths)
        click.echo("Resolved: " + ", ".join(paths))
        try:
            _validate_sync_paths(paths, repo_dir)
        except click.ClickException as e:
            click.secho(f"Error: {e.format_message()}", fg='red')
            sys.exit(1)
```

- [ ] **Step 4: Wire resolution into `push`**

In the `push` function, replace its `if paths:` validation block:

Old code (around line 1306):
```python
    if paths:
        try:
            _validate_sync_paths(paths, workspace_path)
        except click.ClickException as e:
            click.secho(f"Error: {e.format_message()}", fg='red')
            sys.exit(1)
```

New code:
```python
    if paths:
        paths = tuple(_make_workspace_relative(p, workspace_path) for p in paths)
        click.echo("Resolved: " + ", ".join(paths))
        try:
            _validate_sync_paths(paths, workspace_path)
        except click.ClickException as e:
            click.secho(f"Error: {e.format_message()}", fg='red')
            sys.exit(1)
```

- [ ] **Step 5: Run new tests to verify they pass**

```bash
pytest tests/test_sync.py::test_pull_resolves_paths_via_make_workspace_relative tests/test_sync.py::test_push_resolves_paths_via_make_workspace_relative tests/test_sync.py::test_pull_prints_resolved_paths -v
```

Expected: all 3 PASS.

- [ ] **Step 6: Run full sync suite to check no regressions**

```bash
pytest tests/test_sync.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add lib/vibedom/cli.py tests/test_sync.py
git commit -m "feat: resolve push/pull paths relative to CWD when inside workspace"
```

---

### Task 3: `_find_deletions` unit

**Files:**
- Modify: `lib/vibedom/cli.py` (add function after `_build_rsync_cmd`)
- Modify: `tests/test_sync.py` (add unit tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sync.py`:

```python
from vibedom.cli import _find_deletions


def test_find_deletions_returns_deleted_paths(tmp_path):
    cmd = ['rsync', '-av', '--delete', f'{tmp_path}/', str(tmp_path / 'dst')]
    mock_stdout = 'sending incremental file list\ndeleting .env.secrets\ndeleting tmp/scratch.txt\nsrc/app.php\n'
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_stdout)
        result = _find_deletions(cmd)
    assert result == ['.env.secrets', 'tmp/scratch.txt']


def test_find_deletions_adds_dry_run_flag(tmp_path):
    cmd = ['rsync', '-av', '--delete', f'{tmp_path}/', str(tmp_path / 'dst')]
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout='')
        _find_deletions(cmd)
    called_cmd = mock_run.call_args[0][0]
    assert '--dry-run' in called_cmd


def test_find_deletions_does_not_duplicate_dry_run(tmp_path):
    cmd = ['rsync', '-av', '--delete', '--dry-run', f'{tmp_path}/', str(tmp_path / 'dst')]
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout='')
        _find_deletions(cmd)
    called_cmd = mock_run.call_args[0][0]
    assert called_cmd.count('--dry-run') == 1


def test_find_deletions_returns_empty_when_nothing_deleted(tmp_path):
    cmd = ['rsync', '-av', '--delete', f'{tmp_path}/', str(tmp_path / 'dst')]
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout='src/app.php\nsrc/other.py\n')
        result = _find_deletions(cmd)
    assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_sync.py::test_find_deletions_returns_deleted_paths tests/test_sync.py::test_find_deletions_adds_dry_run_flag tests/test_sync.py::test_find_deletions_does_not_duplicate_dry_run tests/test_sync.py::test_find_deletions_returns_empty_when_nothing_deleted -v
```

Expected: `ImportError` or `AttributeError` — `_find_deletions` doesn't exist yet.

- [ ] **Step 3: Implement `_find_deletions`**

Add this function in `lib/vibedom/cli.py` immediately after `_build_rsync_cmd` (around line 1210):

```python
def _find_deletions(cmd: list) -> list[str]:
    """Run a silent rsync dry-run and return paths that would be deleted.

    Parses lines beginning with 'deleting ' from rsync's stdout.
    """
    dry_cmd = list(cmd)
    if '--dry-run' not in dry_cmd:
        dry_cmd.append('--dry-run')
    result = subprocess.run(dry_cmd, capture_output=True, text=True)
    return [
        line[len('deleting '):]
        for line in result.stdout.splitlines()
        if line.startswith('deleting ')
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_sync.py::test_find_deletions_returns_deleted_paths tests/test_sync.py::test_find_deletions_adds_dry_run_flag tests/test_sync.py::test_find_deletions_does_not_duplicate_dry_run tests/test_sync.py::test_find_deletions_returns_empty_when_nothing_deleted -v
```

Expected: all 4 PASS.

- [ ] **Step 5: Run full sync suite to check no regressions**

```bash
pytest tests/test_sync.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add lib/vibedom/cli.py tests/test_sync.py
git commit -m "feat: add _find_deletions helper for rsync deletion preview"
```

---

### Task 4: Wire deletion preview and `--force` into `pull` and `push`

**Files:**
- Modify: `lib/vibedom/cli.py` (`pull` and `push` commands)
- Modify: `tests/test_sync.py` (integration tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sync.py`:

```python
def test_pull_delete_shows_preview_and_aborts_on_no(sync_env):
    """pull --delete should show deletion preview and abort if user says no."""
    runner = CliRunner()

    with patch('vibedom.cli.ContainerRegistry') as mock_registry_cls:
        mock_registry = MagicMock()
        mock_registry.find.return_value = sync_env['state']
        mock_registry_cls.return_value = mock_registry

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('vibedom.cli._find_deletions', return_value=['.env.secrets']) as mock_fd:
                result = runner.invoke(
                    main, ['pull', 'myapp', '--delete', '--yes'],
                    input='n\n', catch_exceptions=False
                )

    assert result.exit_code == 0
    assert '.env.secrets' in result.output
    rsync_calls = [c for c in mock_run.call_args_list if 'rsync' in str(c)]
    assert not rsync_calls, "rsync should NOT run when user declines deletion preview"


def test_pull_delete_proceeds_on_yes(sync_env):
    """pull --delete should proceed after user confirms deletion preview."""
    runner = CliRunner()

    with patch('vibedom.cli.ContainerRegistry') as mock_registry_cls:
        mock_registry = MagicMock()
        mock_registry.find.return_value = sync_env['state']
        mock_registry_cls.return_value = mock_registry

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('vibedom.cli._find_deletions', return_value=['.env.secrets']):
                result = runner.invoke(
                    main, ['pull', 'myapp', '--delete', '--yes'],
                    input='y\n', catch_exceptions=False
                )

    assert result.exit_code == 0
    rsync_calls = [c for c in mock_run.call_args_list if 'rsync' in str(c)]
    assert rsync_calls, "rsync should run after user confirms"


def test_pull_delete_force_skips_preview(sync_env):
    """pull --delete --force should skip deletion preview entirely."""
    runner = CliRunner()

    with patch('vibedom.cli.ContainerRegistry') as mock_registry_cls:
        mock_registry = MagicMock()
        mock_registry.find.return_value = sync_env['state']
        mock_registry_cls.return_value = mock_registry

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('vibedom.cli._find_deletions') as mock_fd:
                result = runner.invoke(
                    main, ['pull', 'myapp', '--delete', '--force'], catch_exceptions=False
                )

    assert result.exit_code == 0
    mock_fd.assert_not_called()
    rsync_calls = [c for c in mock_run.call_args_list if 'rsync' in str(c)]
    assert rsync_calls, "rsync should run when --force is used"


def test_pull_delete_dry_run_skips_preview(sync_env):
    """pull --delete --dry-run should skip deletion preview (dry-run output covers it)."""
    runner = CliRunner()

    with patch('vibedom.cli.ContainerRegistry') as mock_registry_cls:
        mock_registry = MagicMock()
        mock_registry.find.return_value = sync_env['state']
        mock_registry_cls.return_value = mock_registry

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('vibedom.cli._find_deletions') as mock_fd:
                result = runner.invoke(
                    main, ['pull', 'myapp', '--delete', '--dry-run'], catch_exceptions=False
                )

    mock_fd.assert_not_called()


def test_pull_delete_no_preview_when_nothing_deleted(sync_env):
    """pull --delete should not prompt if _find_deletions returns empty list."""
    runner = CliRunner()

    with patch('vibedom.cli.ContainerRegistry') as mock_registry_cls:
        mock_registry = MagicMock()
        mock_registry.find.return_value = sync_env['state']
        mock_registry_cls.return_value = mock_registry

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('vibedom.cli._find_deletions', return_value=[]):
                result = runner.invoke(
                    main, ['pull', 'myapp', '--delete', '--yes'], catch_exceptions=False
                )

    assert result.exit_code == 0
    assert 'Proceed?' not in result.output


def test_push_delete_shows_preview_and_aborts_on_no(sync_env):
    """push --delete should show deletion preview and abort if user says no."""
    runner = CliRunner()

    with patch('vibedom.cli.ContainerRegistry') as mock_registry_cls:
        mock_registry = MagicMock()
        mock_registry.find.return_value = sync_env['state']
        mock_registry_cls.return_value = mock_registry

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('vibedom.cli._find_deletions', return_value=['.env.secrets']):
                result = runner.invoke(
                    main, ['push', 'myapp', '--delete', '--yes'],
                    input='n\n', catch_exceptions=False
                )

    assert result.exit_code == 0
    assert '.env.secrets' in result.output
    rsync_calls = [c for c in mock_run.call_args_list if 'rsync' in str(c)]
    assert not rsync_calls


def test_push_delete_force_skips_preview(sync_env):
    """push --delete --force should skip deletion preview and full-tree prompt."""
    runner = CliRunner()

    with patch('vibedom.cli.ContainerRegistry') as mock_registry_cls:
        mock_registry = MagicMock()
        mock_registry.find.return_value = sync_env['state']
        mock_registry_cls.return_value = mock_registry

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('vibedom.cli._find_deletions') as mock_fd:
                result = runner.invoke(
                    main, ['push', 'myapp', '--delete', '--force'], catch_exceptions=False
                )

    assert result.exit_code == 0
    mock_fd.assert_not_called()


def test_force_skips_full_tree_confirmation(sync_env):
    """--force should skip the full-tree sync confirmation prompt."""
    runner = CliRunner()

    with patch('vibedom.cli.ContainerRegistry') as mock_registry_cls:
        mock_registry = MagicMock()
        mock_registry.find.return_value = sync_env['state']
        mock_registry_cls.return_value = mock_registry

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            # No --yes, no input — would hang if it prompted
            result = runner.invoke(
                main, ['push', 'myapp', '--force'], catch_exceptions=False
            )

    assert result.exit_code == 0
    rsync_calls = [c for c in mock_run.call_args_list if 'rsync' in str(c)]
    assert rsync_calls
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_sync.py::test_pull_delete_shows_preview_and_aborts_on_no tests/test_sync.py::test_pull_delete_force_skips_preview tests/test_sync.py::test_push_delete_shows_preview_and_aborts_on_no tests/test_sync.py::test_force_skips_full_tree_confirmation -v
```

Expected: errors — `--force` option not recognised yet.

- [ ] **Step 3: Add `--force` option and update `pull`**

In `lib/vibedom/cli.py`, update the `pull` command decorator and signature:

```python
@main.command()
@click.argument('workspace')
@click.argument('paths', nargs=-1)
@click.option('--delete', is_flag=True, help='Also remove files in host that are absent in container')
@click.option('--dry-run', '-n', is_flag=True, help='Show what would be synced without doing it')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation for full-tree sync')
@click.option('--force', '-f', is_flag=True, help='Skip all confirmations')
def pull(workspace, paths, delete, dry_run, yes, force):
```

Replace the full-tree confirmation block (currently `if not paths and not dry_run and not yes:`):

```python
    if not paths and not dry_run and not yes and not force:
        if not click.confirm(
            f"Sync all files from container repo to {workspace_path.name}?",
            default=False,
        ):
            click.echo("Aborted")
            return
```

After the `cmd = _build_rsync_cmd(...)` call, add the deletion preview block immediately before the `if dry_run:` echo:

```python
    if delete and not force and not dry_run:
        deletions = _find_deletions(cmd)
        if deletions:
            click.echo("These files will be deleted from the host:")
            for f in deletions:
                click.echo(f"  {f}")
            if not click.confirm("\nProceed?", default=False):
                click.echo("Aborted")
                return
```

- [ ] **Step 4: Add `--force` option and update `push`**

In `lib/vibedom/cli.py`, update the `push` command decorator and signature:

```python
@main.command()
@click.argument('workspace')
@click.argument('paths', nargs=-1)
@click.option('--delete', is_flag=True, help='Also remove files in container that are absent on host')
@click.option('--dry-run', '-n', is_flag=True, help='Show what would be synced without doing it')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation for full-tree sync')
@click.option('--force', '-f', is_flag=True, help='Skip all confirmations')
def push(workspace, paths, delete, dry_run, yes, force):
```

Replace the full-tree confirmation block:

```python
    if not paths and not dry_run and not yes and not force:
        if not click.confirm(
            f"Sync all files from {workspace_path.name} to container repo?",
            default=False,
        ):
            click.echo("Aborted")
            return
```

After the `cmd = _build_rsync_cmd(...)` call, add:

```python
    if delete and not force and not dry_run:
        deletions = _find_deletions(cmd)
        if deletions:
            click.echo("These files will be deleted from the container:")
            for f in deletions:
                click.echo(f"  {f}")
            if not click.confirm("\nProceed?", default=False):
                click.echo("Aborted")
                return
```

- [ ] **Step 5: Run all new tests to verify they pass**

```bash
pytest tests/test_sync.py::test_pull_delete_shows_preview_and_aborts_on_no tests/test_sync.py::test_pull_delete_proceeds_on_yes tests/test_sync.py::test_pull_delete_force_skips_preview tests/test_sync.py::test_pull_delete_dry_run_skips_preview tests/test_sync.py::test_pull_delete_no_preview_when_nothing_deleted tests/test_sync.py::test_push_delete_shows_preview_and_aborts_on_no tests/test_sync.py::test_push_delete_force_skips_preview tests/test_sync.py::test_force_skips_full_tree_confirmation -v
```

Expected: all 8 PASS.

- [ ] **Step 6: Run full sync suite and full test suite**

```bash
pytest tests/test_sync.py -v && pytest tests/ -v --tb=short -q
```

Expected: all tests pass (core logic 100%).

- [ ] **Step 7: Commit**

```bash
git add lib/vibedom/cli.py tests/test_sync.py
git commit -m "feat: add deletion preview and --force flag to push/pull"
```
