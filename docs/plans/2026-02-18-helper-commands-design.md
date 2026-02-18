# Helper Commands for Git Bundle Workflow - Design

**Date:** 2026-02-18
**Status:** Approved

## Goal

Add helper commands to streamline the git bundle workflow after vibedom sessions end. Replace manual multi-step git commands with simple, single-command workflows for reviewing and merging agent changes.

## Current Workflow (Manual)

After `vibedom stop`, users must manually:

```bash
# Review changes
git remote add vibedom-xyz ~/.vibedom/logs/session-xyz/repo.bundle
git fetch vibedom-xyz
git log vibedom-xyz/feature-branch
git diff feature-branch..vibedom-xyz/feature-branch

# Merge changes
git merge --squash vibedom-xyz/feature-branch
git commit -m "Apply changes from vibedom session"
git remote remove vibedom-xyz

# Or inspect container
docker exec -it vibedom-workspace sh
cd /work/repo
```

**Problems:**
- Too many manual steps
- Easy to forget remote cleanup
- Need to remember bundle path and session ID
- Container exec syntax is verbose

## Proposed Solution

Three new top-level CLI commands:

### 1. `vibedom review <workspace> [--branch <name>] [--runtime <type>]`

**Purpose:** Review agent changes without modifying workspace

**Behavior:**
1. Find most recent stopped session for workspace
2. Verify session is stopped (container not running)
3. Verify bundle exists at `session_dir/repo.bundle`
4. Get current branch (or use `--branch` argument)
5. Check if remote `vibedom-{session-id}` exists, add if not
6. Fetch bundle: `git fetch vibedom-{session-id}`
7. Display:
   - Session info (timestamp, bundle path)
   - Commit log: `git log --oneline {branch}..vibedom-{session-id}/{branch}`
   - Full diff: `git diff {branch}..vibedom-{session-id}/{branch}`
8. Show hint: "To merge: vibedom merge {workspace}"

**Options:**
- `--branch <name>`: Review specific branch from bundle (default: current workspace branch)
- `--runtime <auto|docker|apple>`: Specify container runtime (default: auto-detect)

**Example:**
```bash
vibedom review ~/projects/myapp
# Shows commits and diff from most recent session

vibedom review ~/projects/myapp --branch experimental
# Reviews 'experimental' branch from bundle
```

### 2. `vibedom merge <workspace> [--branch <name>] [--merge] [--runtime <type>]`

**Purpose:** Merge agent changes into current workspace branch

**Behavior:**
1. Find most recent stopped session
2. Verify session is stopped, bundle exists
3. Check for uncommitted changes: `git status --porcelain`
   - If dirty: abort with error
4. Get current branch (or use `--branch` argument)
5. Check/add remote `vibedom-{session-id}` (reuse if exists from `review`)
6. Fetch bundle
7. Perform merge:
   - **Default (squash)**: `git merge --squash vibedom-{session-id}/{branch}`, create commit
   - **With `--merge`**: `git merge vibedom-{session-id}/{branch}` (keep full history)
8. Clean up: `git remote remove vibedom-{session-id}`
9. Display success message

**Options:**
- `--branch <name>`: Merge specific branch from bundle (default: current workspace branch)
- `--merge`: Keep full commit history instead of squashing (default: squash)
- `--runtime <auto|docker|apple>`: Specify container runtime (default: auto-detect)

**Example:**
```bash
vibedom merge ~/projects/myapp
# Squash merge (default) - creates single commit

vibedom merge ~/projects/myapp --merge
# Keep full commit history

vibedom merge ~/projects/myapp --branch experimental
# Merge 'experimental' branch from bundle
```

### 3. `vibedom shell <workspace> [--runtime <type>]`

**Purpose:** Quick access to container shell in agent's working directory

**Behavior:**
1. Resolve workspace path
2. Detect runtime (respect `--runtime` flag, default auto-detect)
3. Execute: `{runtime_cmd} exec -it -w /work/repo vibedom-{workspace.name} bash`
4. User gets interactive bash shell in `/work/repo`

**Options:**
- `--runtime <auto|docker|apple>`: Specify container runtime (default: auto-detect)

**Example:**
```bash
vibedom shell ~/projects/myapp
# Drops into bash at /work/repo inside container
```

## Architecture

### CLI Structure

All three commands are top-level commands in `lib/vibedom/cli.py`:

```python
@main.command('review')
@click.argument('workspace', type=click.Path(exists=True))
@click.option('--branch', help='Branch to review from bundle')
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple']), default='auto')
def review(workspace, branch, runtime):
    """Review changes from most recent session."""
    ...

@main.command('merge')
@click.argument('workspace', type=click.Path(exists=True))
@click.option('--branch', help='Branch to merge from bundle')
@click.option('--merge', is_flag=True, help='Keep full commit history (default: squash)')
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple']), default='auto')
def merge(workspace, branch, merge, runtime):
    """Merge changes from most recent session."""
    ...

@main.command('shell')
@click.argument('workspace', type=click.Path(exists=True))
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple']), default='auto')
def shell(workspace, runtime):
    """Open shell in container's working directory."""
    ...
```

### Shared Infrastructure

**Session Finding:**
Reuse logic from `stop` command:
```python
def find_latest_session(workspace_path: Path, logs_dir: Path) -> Optional[Session]:
    """Find most recent session for workspace."""
    for session_dir in sorted(logs_dir.glob('session-*'), reverse=True):
        session_log = session_dir / 'session.log'
        if session_log.exists():
            log_content = session_log.read_text()
            if str(workspace_path) in log_content:
                return session_dir
    return None
```

**Runtime Detection:**
Use `VMManager._detect_runtime()` for consistent runtime handling across all commands.

**Git Operations:**
All git operations via `subprocess.run()` with proper error handling.

### Remote Naming Convention

Remote name: `vibedom-{session-timestamp}`

Example: `vibedom-20260218-143052-123456`

**Benefits:**
- Unique per session
- Same remote used by both `review` and `merge`
- Cleaned up after `merge` completes
- Easy to identify in `git remote -v`

## Error Handling

### Common Errors

| Error | Message | Action |
|-------|---------|--------|
| Workspace not a directory | "Error: {workspace} is not a directory" | Exit |
| Not a git repository | "Error: {workspace} is not a git repository" | Exit |
| Runtime not available | "Error: {runtime} not found. Install it or use --runtime" | Exit |

### `review` Specific

| Error | Message | Action |
|-------|---------|--------|
| No session found | "No session found for {workspace}. Run 'vibedom run {workspace}' first." | Exit |
| Session still running | "Session still active. Stop it first: vibedom stop {workspace}" | Exit |
| Bundle missing | "Bundle not found at {path}. Session may have failed." | Exit |
| Branch not in bundle | "Branch '{branch}' not found in bundle. Available: {list}" | Exit |

### `merge` Specific

| Error | Message | Action |
|-------|---------|--------|
| Uncommitted changes | "Cannot merge: uncommitted changes. Commit or stash first." | Exit |
| Not on a branch | "Cannot merge: HEAD is detached. Check out a branch first." | Exit |
| Merge conflicts | (Let git handle naturally) | User resolves manually |

### `shell` Specific

| Error | Message | Action |
|-------|---------|--------|
| Container not running | "Container not running. Start it: vibedom run {workspace}" | Exit |

## Data Flow

### `review` Flow

```
User runs: vibedom review ~/projects/myapp
    ↓
Find latest session for workspace
    ↓
Verify session stopped (no container running)
    ↓
Verify bundle exists
    ↓
Get current branch (or use --branch)
    ↓
Check if remote vibedom-{session-id} exists
    ↓
Add remote if needed: git remote add vibedom-xyz {bundle_path}
    ↓
Fetch: git fetch vibedom-xyz
    ↓
Show commits: git log --oneline branch..vibedom-xyz/branch
    ↓
Show diff: git diff branch..vibedom-xyz/branch
    ↓
Display hint to run vibedom merge
```

### `merge` Flow

```
User runs: vibedom merge ~/projects/myapp
    ↓
Find latest session, verify stopped, bundle exists
    ↓
Check for uncommitted changes (git status --porcelain)
    ↓
If dirty: abort with error
    ↓
Get current branch (or use --branch)
    ↓
Check/add remote vibedom-{session-id}
    ↓
Fetch bundle
    ↓
Merge (squash by default, or full history with --merge)
    ↓
If squash: create commit with summary message
    ↓
Clean up: git remote remove vibedom-xyz
    ↓
Display success message
```

### `shell` Flow

```
User runs: vibedom shell ~/projects/myapp
    ↓
Detect runtime (docker or apple/container)
    ↓
Build exec command: {runtime} exec -it -w /work/repo vibedom-{workspace} bash
    ↓
Execute (user gets interactive shell)
    ↓
If container not running: show error with suggestion
```

## Testing Strategy

### Unit Tests (`tests/test_cli.py`)

**`test_review_command`**
- Mock session finding, bundle path
- Mock git commands (remote add, fetch, log, diff)
- Verify correct git commands called
- Test with/without `--branch` flag

**`test_merge_command_squash`**
- Mock session finding, clean git status
- Mock merge --squash, verify commit created
- Verify remote cleanup after success

**`test_merge_command_keep_history`**
- Test with `--merge` flag
- Verify regular merge (no --squash)

**`test_merge_fails_with_uncommitted_changes`**
- Mock git status returning dirty state
- Verify command aborts with error

**`test_shell_command`**
- Mock runtime detection
- Verify exec command built correctly
- Test with docker and apple/container runtimes

**`test_branch_not_found_in_bundle`**
- Mock bundle with specific branches
- Verify error message lists available branches

### Integration Tests (Manual)

1. Full workflow: `run → stop → review → merge`
2. Test with both docker and apple/container
3. Test squash vs keep-commits
4. Test `--branch` argument with multiple branches
5. Test error cases (dirty workspace, missing session)

## Implementation Notes

### Branch Detection

When no `--branch` specified:
```python
# Get current workspace branch
current_branch = subprocess.run(
    ['git', '-C', str(workspace_path), 'rev-parse', '--abbrev-ref', 'HEAD'],
    capture_output=True, text=True, check=True
).stdout.strip()
```

### Bundle Branch Listing

When branch not found, list available:
```python
# List branches in bundle
result = subprocess.run(
    ['git', 'bundle', 'list-heads', str(bundle_path)],
    capture_output=True, text=True, check=True
)
branches = [line.split()[-1] for line in result.stdout.splitlines()]
```

### Squash Commit Message

Default squash commit message:
```
Apply changes from vibedom session

Session: {session_timestamp}
Bundle: {bundle_path}
Branch: {branch}

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

## Benefits

**User Experience:**
- `vibedom review .` replaces 4 manual git commands
- `vibedom merge .` handles merge + cleanup automatically
- `vibedom shell .` beats typing full docker exec command
- Squash-by-default reduces noise in git history
- `--branch` provides flexibility for edge cases

**Developer Experience:**
- Follows existing CLI patterns (top-level commands, --runtime flag)
- Reuses existing infrastructure (VMManager, Session)
- Clear error messages guide users
- Comprehensive tests prevent regressions

**Future Extensions:**
- `vibedom review --all` - review all stopped sessions
- `vibedom cleanup` - remove old session bundles
- Integration with `gh pr create` for automatic PR creation

## Open Questions (Deferred)

1. **Branch auto-detection**: Should we detect which branch agent worked on if different from workspace?
   - **Decision**: Start with explicit `--branch` flag, refine after real-world usage

2. **Multiple sessions**: How to handle when multiple sessions exist for same workspace?
   - **Decision**: Use most recent, add `--session` flag later if needed

3. **Merge strategy customization**: Allow `--ff-only`, `--no-ff`, etc?
   - **Decision**: Start with squash/merge toggle, add more flags if requested

---

**Next Step:** Create implementation plan using `superpowers:writing-plans` skill.
