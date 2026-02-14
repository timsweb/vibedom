# Git Bundle Workflow - Design Document

**Date**: 2026-02-14
**Status**: Approved
**Replaces**: Overlay filesystem diff workflow

## Problem Statement

The current overlay filesystem approach captures ALL file changes including `.git/` directory modifications. When AI agents work inside the sandbox (creating branches, commits, etc.), the diff becomes polluted with git metadata (objects, refs, logs, index), making code review impractical.

**Example of current issue:**
```bash
# Current get_diff() output includes:
diff -ur mnt/workspace/.git/objects/ab/cd1234... work/.git/objects/ab/cd1234...
diff -ur mnt/workspace/.git/refs/heads/feature work/.git/refs/heads/feature
# ... hundreds of git metadata files ...
```

## Solution: Git Bundle Workflow

Use git's native bundle format to export the agent's work as a portable git repository that can be added as a remote and reviewed using standard git commands.

## Architecture

### High-Level Flow

1. **Start Session**: Container clones workspace repo and checks out user's current branch
2. **Agent Works**: Makes commits on user's branch in isolated repo
3. **Mid-Session Testing**: User can fetch from live repo to test changes
4. **End Session**: Create git bundle for long-term archival
5. **Review**: User merges bundle into their feature branch
6. **Push for Review**: User pushes feature branch to GitLab for peer review/MR

### Components

**Container Git Repository:**
- Location: `/work/repo/` (inside container)
- Mounted to: `~/.vibedom/sessions/session-YYYYMMDD-HHMMSS-microseconds/repo/` (on host)
- Initialization:
  - Git workspace: Clone from host's `.git`, checkout current branch
  - Non-git workspace: Initialize fresh with snapshot

**Git Bundle:**
- Created at session end
- Location: `~/.vibedom/sessions/session-YYYYMMDD-HHMMSS-microseconds/repo.bundle`
- Contains all branches, commits, tags
- Used as git remote for review and merge

### Mounts

```bash
# VMManager.start() docker run:
-v {workspace}:/mnt/workspace:ro              # Read-only workspace
-v {config_dir}:/mnt/config:ro                # Config files
-v {session_dir}/repo:/work/repo              # Live git repo (read-write)
-v {session_dir}:/mnt/session                 # Bundle output location
```

## Technical Implementation

### Container Initialization (startup.sh)

```bash
#!/bin/bash

# Initialize git repo from workspace
if [ -d /mnt/workspace/.git ]; then
    echo "Cloning git repository from workspace..."
    git clone /mnt/workspace/.git /work/repo
    cd /work/repo

    # Checkout the same branch user is on
    CURRENT_BRANCH=$(git -C /mnt/workspace rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
    git checkout "$CURRENT_BRANCH" 2>/dev/null || git checkout -b "$CURRENT_BRANCH"

    echo "Working on branch: $CURRENT_BRANCH"
else
    echo "Non-git workspace, initializing fresh repository..."
    mkdir -p /work/repo
    rsync -a /mnt/workspace/ /work/repo/
    cd /work/repo
    git init
    git add .
    git commit -m "Initial snapshot from vibedom session"
fi

# Set git identity for agent commits
git config user.name "Vibedom Agent"
git config user.email "agent@vibedom.local"

# Continue with existing mitmproxy setup...
```

### Bundle Creation (session.py)

```python
class Session:
    def create_bundle(self) -> Optional[Path]:
        """Create git bundle from container's repository.

        Returns:
            Path to bundle file, or None if creation failed
        """
        bundle_path = self.session_dir / 'repo.bundle'

        try:
            self.log_event('Creating git bundle...', level='INFO')

            # Create bundle with all refs
            result = subprocess.run([
                'docker', 'exec', self.vm.container_name,
                'sh', '-c',
                'cd /work/repo && git bundle create /mnt/session/repo.bundle --all'
            ], capture_output=True, check=True)

            # Verify bundle is valid
            verify_result = subprocess.run([
                'git', 'bundle', 'verify', str(bundle_path)
            ], capture_output=True, check=False)

            if verify_result.returncode == 0:
                self.log_event(f'Bundle created: {bundle_path}', level='INFO')
                return bundle_path
            else:
                self.log_event(f'Bundle verification failed: {verify_result.stderr}', level='ERROR')
                return None

        except subprocess.CalledProcessError as e:
            self.log_event(f'Bundle creation failed: {e}', level='ERROR')
            self.log_event(f'Live repo still available at {self.session_dir / "repo"}', level='WARN')
            return None
```

### CLI Integration (cli.py)

```python
@main.command()
def stop(workspace: str) -> None:
    """Stop sandbox and create git bundle."""
    workspace_path = Path(workspace).resolve()
    vm = VMManager(workspace_path, config_dir)
    session = Session.find_active_session(workspace_path)

    if session:
        # Create bundle before stopping
        bundle_path = session.create_bundle()

        # Stop VM
        vm.stop()

        # Show user how to review
        if bundle_path:
            # Get current branch name from workspace
            current_branch = subprocess.run(
                ['git', '-C', str(workspace_path), 'rev-parse', '--abbrev-ref', 'HEAD'],
                capture_output=True, text=True
            ).stdout.strip()

            click.echo(f"\n✅ Session complete!")
            click.echo(f"📦 Bundle: {bundle_path}")
            click.echo(f"\nTo review changes:")
            click.echo(f"  git remote add vibedom-xyz {bundle_path}")
            click.echo(f"  git fetch vibedom-xyz")
            click.echo(f"  git log vibedom-xyz/{current_branch}")
            click.echo(f"  git diff {current_branch}..vibedom-xyz/{current_branch}")
            click.echo(f"\nTo merge into your feature branch (keep commits):")
            click.echo(f"  git merge vibedom-xyz/{current_branch}")
            click.echo(f"\nTo merge (squash):")
            click.echo(f"  git merge --squash vibedom-xyz/{current_branch}")
            click.echo(f"  git commit -m 'Apply changes from vibedom session'")
            click.echo(f"\nPush for peer review:")
            click.echo(f"  git push origin {current_branch}")
            click.echo(f"\nCleanup:")
            click.echo(f"  git remote remove vibedom-xyz")
        else:
            click.echo(f"⚠️  Bundle creation failed")
            click.echo(f"📁 Live repo: {session.session_dir / 'repo'}")
```

## User Workflow

### Typical Development Flow

```bash
# User working on feature branch
git checkout -b feature/add-authentication
# ... make some changes, commit ...

# Start vibedom session (agent continues on feature/add-authentication)
vibedom run ~/projects/myapp

# Agent works, makes commits...
# User can test mid-session (see below)

# Stop session
vibedom stop ~/projects/myapp
```

### During Session (Testing Changes)

```bash
# Add live repo as remote (once per session)
git remote add vibedom-live ~/.vibedom/sessions/session-20260214-123456/repo

# Fetch latest agent commits anytime
git fetch vibedom-live

# Create test branch to try changes
git checkout -b test-vibedom vibedom-live/feature/add-authentication

# Run tests, inspect code, etc.
npm test
git log
git diff feature/add-authentication

# Session continues, agent keeps working...
# Fetch again later to see new commits
git fetch vibedom-live
```

### After Session (Review and Merge)

```bash
# Add bundle as remote
git remote add vibedom-session ~/.vibedom/sessions/session-20260214-123456/repo.bundle

# Fetch all refs from bundle
git fetch vibedom-session

# Review what agent did
git log vibedom-session/feature/add-authentication
git log --oneline vibedom-session/feature/add-authentication ^feature/add-authentication
git diff feature/add-authentication..vibedom-session/feature/add-authentication

# Option 1: Merge and keep commit history
git checkout feature/add-authentication
git merge vibedom-session/feature/add-authentication
# Creates merge commit, preserves agent's commits

# Option 2: Merge and squash commits
git checkout feature/add-authentication
git merge --squash vibedom-session/feature/add-authentication
git commit -m "Implement authentication system

Agent implemented:
- User login/logout endpoints
- JWT token generation
- Password hashing with bcrypt
- Session management

Co-Authored-By: Vibedom Agent <agent@vibedom.local>"

# Push for peer review in GitLab
git push origin feature/add-authentication
# Create Merge Request in GitLab UI

# Cleanup
git remote remove vibedom-session
```

### Session Cleanup

```bash
# Manual cleanup (delete old sessions)
rm -rf ~/.vibedom/sessions/session-20260214-123456

# Future enhancement: automatic cleanup
vibedom sessions clean --older-than 30d
```

## Edge Cases and Error Handling

### 1. Non-Git Workspace

If workspace lacks `.git/`, initialize fresh repo:
- `git init` in `/work/repo`
- Copy workspace files
- Create initial commit
- Agent works from clean slate

User gets bundle with agent's commits (no prior history).

### 2. Bundle Creation Failure

If bundle creation fails:
- Log error to session log
- Preserve live repo at `~/.vibedom/sessions/session-xyz/repo/`
- User can still add live repo as remote
- Optional: Add `vibedom recover <session-id>` command to retry bundle creation

### 3. Detached HEAD State

If user's workspace is in detached HEAD:
- Clone still works (clones all refs)
- Agent works on detached HEAD
- User can create branch from bundle commits after review

### 4. Container Crash Mid-Session

Live repo persists at `~/.vibedom/sessions/session-xyz/repo/`:
- User can add as remote and fetch
- Final bundle won't be created
- Future enhancement: `vibedom recover` to create bundle from crashed session

### 5. Disk Space (Phase 2 Enhancement)

Future: Check available space before bundle creation:
```python
def has_sufficient_space(path: Path, required_mb: int) -> bool:
    stat = os.statvfs(path)
    available_mb = (stat.f_bavail * stat.f_frsize) / (1024 * 1024)
    return available_mb > required_mb
```

For now: Bundle creation fails with disk full error, live repo still accessible.

### 6. Multiple Concurrent Sessions

Each session gets unique ID (timestamp + microseconds):
- No directory conflicts
- No git ref conflicts
- Independent remotes

## Testing Strategy

### Unit Tests

**test_session.py:**
```python
def test_bundle_path_generation():
    """Bundle path follows naming convention."""
    session = Session(workspace, logs_dir)
    bundle_path = session.session_dir / 'repo.bundle'
    assert str(bundle_path).endswith('repo.bundle')

def test_session_log_bundle_creation():
    """Bundle creation events logged."""
    # Mock bundle creation
    # Verify log entries created
```

### Integration Tests

**test_git_workflow.py:**
```python
def test_git_workspace_cloned_with_branch():
    """Git workspace cloned and correct branch checked out."""
    workspace = create_test_git_repo(branch='feature/test')
    vm = VMManager(workspace, config)
    vm.start()

    # Verify correct branch checked out
    result = vm.exec(['sh', '-c', 'cd /work/repo && git branch --show-current'])
    assert result.stdout.strip() == 'feature/test'

def test_non_git_workspace_initialized():
    """Non-git workspace initialized as git repo."""
    workspace = create_test_directory()  # No .git
    vm = VMManager(workspace, config)
    vm.start()

    result = vm.exec(['sh', '-c', 'cd /work/repo && git status'])
    assert result.returncode == 0

def test_bundle_creation_and_validity():
    """Bundle created and verified."""
    vm = VMManager(workspace, config)
    session = Session(workspace, logs_dir)
    vm.start()

    # Make commits
    vm.exec(['sh', '-c',
        'cd /work/repo && echo "test" > test.txt && '
        'git add . && git commit -m "Test commit"'])

    bundle_path = session.create_bundle()
    assert bundle_path.exists()

    # Verify bundle
    result = subprocess.run(
        ['git', 'bundle', 'verify', str(bundle_path)],
        capture_output=True
    )
    assert result.returncode == 0

def test_live_repo_accessible():
    """Live repo mounted and accessible from host."""
    vm = VMManager(workspace, config)
    session = Session(workspace, logs_dir)
    vm.start()

    live_repo = session.session_dir / 'repo'
    assert live_repo.exists()
    assert (live_repo / '.git').exists()

    # Can add as remote
    subprocess.run(['git', 'remote', 'add', 'test', str(live_repo)], check=True)
    subprocess.run(['git', 'fetch', 'test'], check=True)

def test_mid_session_fetch():
    """Can fetch from live repo during session."""
    vm = VMManager(workspace, config)
    session = Session(workspace, logs_dir)
    vm.start()

    # Add as remote
    live_repo = session.session_dir / 'repo'
    subprocess.run(['git', 'remote', 'add', 'live', str(live_repo)])

    # Make commit in container
    vm.exec(['sh', '-c',
        'cd /work/repo && echo "v1" > file.txt && '
        'git add . && git commit -m "Version 1"'])

    # Fetch and verify
    subprocess.run(['git', 'fetch', 'live'], check=True)
    result = subprocess.run(
        ['git', 'log', '--oneline', 'live/feature/test'],
        capture_output=True, text=True
    )
    assert 'Version 1' in result.stdout

def test_merge_workflow():
    """Bundle can be merged into feature branch."""
    workspace = create_test_git_repo(branch='feature/test')
    vm = VMManager(workspace, config)
    session = Session(workspace, logs_dir)
    vm.start()

    # Agent makes commit
    vm.exec(['sh', '-c',
        'cd /work/repo && echo "feature" > feature.txt && '
        'git add . && git commit -m "Add feature"'])

    # Create bundle
    bundle_path = session.create_bundle()
    vm.stop()

    # Merge from bundle
    os.chdir(workspace)
    subprocess.run(['git', 'remote', 'add', 'vibedom', str(bundle_path)])
    subprocess.run(['git', 'fetch', 'vibedom'])
    result = subprocess.run(['git', 'merge', 'vibedom/feature/test'], check=True)

    # Verify file exists
    assert (workspace / 'feature.txt').exists()
```

### Manual Testing Checklist

- [ ] Start session on feature branch → verify agent works on same branch
- [ ] Start session with non-git workspace → verify init successful
- [ ] Make commits in container → fetch from live repo → verify commits visible
- [ ] Continue session, make more commits → fetch again → verify new commits
- [ ] Stop session → verify bundle created
- [ ] Add bundle as remote → fetch → verify all commits present
- [ ] Merge from bundle (keep commits) → verify history preserved
- [ ] Merge from bundle (squash) → verify single commit created
- [ ] Push feature branch to GitLab → create MR → verify workflow complete
- [ ] Cleanup remote → verify no errors

## Migration from Phase 1

**Changes Required:**

1. **vm/startup.sh**: Replace overlay FS setup with git clone/init, checkout current branch
2. **lib/vibedom/vm.py**:
   - Update mounts to include session repo volume
   - Remove `get_diff()` method (no longer needed)
   - Pass current branch to container
3. **lib/vibedom/session.py**: Add `create_bundle()` method
4. **lib/vibedom/cli.py**: Update `stop` command to create bundle and show branch-aware instructions
5. **tests/**: Add git workflow integration tests
6. **docs/**: Update USAGE.md with git bundle workflow

**Backwards Compatibility:**

Not applicable - this is a fundamental workflow change. Phase 1 used overlay FS for testing only, no production usage to migrate.

## Future Enhancements

### Phase 2 Candidates

1. **Helper Commands**:
   - `vibedom review <workspace>` - Auto-add remote, show log/diff
   - `vibedom merge <workspace> [--squash]` - Merge and cleanup
   - `vibedom sessions list` - Show all session bundles
   - `vibedom sessions clean --older-than 30d` - Automatic cleanup

2. **Session Recovery**:
   - `vibedom recover <session-id>` - Create bundle from crashed session

3. **Disk Space Management**:
   - Check available space before bundle creation
   - Automatic cleanup of old sessions (configurable retention)
   - Bundle compression options

4. **Multi-Branch Support**:
   - Agent creates feature branches within session
   - Bundle includes all branches
   - User can cherry-pick specific branches

5. **GitLab Integration**:
   - `vibedom push <workspace>` - Push feature branch and create MR automatically
   - Link session to MR in GitLab (metadata)

## Design Decisions and Trade-offs

### Why Git Bundles?

**Considered alternatives:**
1. **Overlay FS with .git excluded** - Still creates disconnected diff, no git history
2. **Direct branch in host .git** - Less isolation, agent touches host .git
3. **Patch files** - Loses commit history and metadata

**Bundle advantages:**
- Git-native format
- Preserves full history
- Works as remote (no import needed)
- Portable and archivable
- Standard git tools work

### Why Live Repo + Bundle?

**Alternative: Bundle only (no live repo)** would require:
- Waiting until session end to review
- No mid-session testing
- Less flexible workflow

**Live repo + bundle** gives:
- Mid-session testing (fetch from live repo)
- Long-term archival (bundle)
- Flexibility to iterate

**Trade-off:** Slight duplication (live repo + bundle), but provides better UX and cleanup path.

### Why Clone vs Fresh Init?

**Clone from host .git:**
- Agent sees existing branches/history
- Can work on user's current branch
- More context for decisions
- Matches user's workflow (feature branches)

**Fresh init:**
- Simpler, no dependencies on host .git
- Cleaner for non-git workspaces

**Decision:** Support both - clone if .git exists (checkout current branch), init otherwise. Gives flexibility without complexity.

### Why Current Branch (Not New Branch)?

**Alternative: Agent creates new branch** (e.g., `vibedom/session-xyz`)
- More explicit separation
- User merges branch-to-branch

**Current branch approach:**
- Simpler - agent continues user's work
- Natural workflow - user merges bundle into same branch
- Fewer branches to manage

**Decision:** Clone current branch. User's workflow is already branch-based (feature branches for MRs), agent extends that work. If user wants isolation, they can create a new branch before starting vibedom.

## Success Criteria

- [ ] Agent works on user's current branch (or main if detached)
- [ ] User can fetch from live repo mid-session to test changes
- [ ] Bundle created successfully at session end
- [ ] Bundle contains all commits and branches
- [ ] User can merge bundle into their feature branch (with or without squash)
- [ ] No .git pollution in diffs
- [ ] Works with both git and non-git workspaces
- [ ] Supports standard GitLab workflow (feature branch → MR)
- [ ] Error handling preserves user's ability to access changes

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Bundle creation fails | High - user loses work | Preserve live repo, add recovery command |
| Disk space exhaustion | Medium - bundle fails | Check space first (Phase 2), live repo remains accessible |
| Detached HEAD state | Low - workflow unclear | Clone works, user creates branch from bundle |
| Container crash mid-session | Medium - no bundle | Live repo persists, can be recovered |
| Multiple concurrent sessions | Low - conflicts | Unique session IDs prevent conflicts |
| Agent commits break build | Medium - broken feature branch | User reviews before merging, can cherry-pick or discard |

---

**Approved by**: User
**Next Steps**: Create implementation plan using writing-plans skill
