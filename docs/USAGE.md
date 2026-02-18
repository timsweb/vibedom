# Usage Guide

## First-Time Setup

1. Set up virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install vibedom:
   ```bash
   pip install -e .
   ```

3. Initialize:
   ```bash
   vibedom init
   ```

4. Add the displayed SSH public key to your GitLab account:
   - GitLab → Settings → SSH Keys
   - Paste the key shown by `vibedom init`

5. Edit `~/.vibedom/trusted_domains.txt` to add your internal domains

## Container Runtime

Vibedom auto-detects your container runtime:

- **apple/container** (preferred) — hardware-isolated VMs via Virtualization.framework. Requires macOS 26+ and Apple Silicon. Install from [github.com/apple/container](https://github.com/apple/container).
- **Docker** (fallback) — namespace-based containers. Works on any platform.

Before first use with apple/container, start the system service:
```bash
container system start
```

## Running a Sandbox

```bash
vibedom run ~/projects/myapp
```

This will:
1. Scan workspace for secrets (Gitleaks)
2. Show findings for review
3. Start VM with workspace mounted as read-only
4. Clone/create git repository in isolated session
5. Launch mitmproxy

The sandbox is now running.

## Using Claude Code

Claude Code CLI is pre-installed in the container image and your settings/authentication persist across sessions via a shared Docker volume.

**First time setup (per container runtime):**

1. Exec into the container:
   ```bash
   docker exec -it vibedom-myapp sh
   # or with apple/container:
   container exec -it vibedom-myapp sh
   ```

2. Authenticate Claude:
   ```bash
   cd /work/repo
   claude
   ```

3. Follow the OAuth flow to authenticate. Your authentication and settings will persist across all vibedom containers.

**Subsequent sessions:**

Claude will already be authenticated - just exec in and run:
```bash
docker exec -it vibedom-myapp sh -c "cd /work/repo && claude"
# or
container exec -it vibedom-myapp sh -c "cd /work/repo && claude"
```

**Note:** The first Claude Code installation generates OAuth credentials that persist in the `vibedom-claude-config` Docker volume, shared across all workspaces.

## Other Operations

You can also:

- Inspect the git repository:
  ```bash
  docker exec -it vibedom-myapp sh -c "cd /work/repo && git log --oneline"
  ```

- Monitor network requests:
  ```bash
  tail -f ~/.vibedom/logs/session-*/network.jsonl
  ```

## Working with Git Bundles

### Starting a Session

When you start a vibedom session, the container clones your workspace repository and checks out your current branch:

```bash
# On your feature branch
git checkout feature/add-authentication
vibedom run ~/projects/myapp
```

The agent will work on the same branch (`feature/add-authentication`) inside an isolated git repository.

### Testing Changes Mid-Session

You can fetch from the live repository to test changes while the session is still running:

```bash
# Add live repo as remote (once per session)
git remote add vibedom-live ~/.vibedom/sessions/session-20260214-123456/repo

# Fetch latest commits anytime
git fetch vibedom-live

# Create test branch
git checkout -b test-changes vibedom-live/feature/add-authentication

# Test the changes
npm test
npm run dev

# Session continues...
```

### Reviewing and Merging Changes

After stopping the session, a git bundle is created:

```bash
vibedom stop ~/projects/myapp
# Creates bundle at ~/.vibedom/sessions/session-xyz/repo.bundle
```

**Add bundle as remote and review:**

```bash
git remote add vibedom-xyz ~/.vibedom/sessions/session-xyz/repo.bundle
git fetch vibedom-xyz

# Review commits
git log vibedom-xyz/feature/add-authentication
git log --oneline vibedom-xyz/feature/add-authentication ^feature/add-authentication

# Review changes
git diff feature/add-authentication..vibedom-xyz/feature/add-authentication
```

**Merge (keep commit history):**

```bash
git checkout feature/add-authentication
git merge vibedom-xyz/feature/add-authentication
```

**Merge (squash commits):**

```bash
git checkout feature/add-authentication
git merge --squash vibedom-xyz/feature/add-authentication
git commit -m "Implement authentication system

Agent implemented:
- User login/logout endpoints
- JWT token generation
- Password hashing
"
```

**Push for peer review:**

```bash
git push origin feature/add-authentication
# Create Merge Request in GitLab
```

**Cleanup:**

```bash
git remote remove vibedom-xyz
```

### Helper Commands

**Quick review of changes:**
```bash
vibedom review ~/projects/myapp
# Shows commit log and diff from most recent session
```

**Merge changes into workspace:**
```bash
vibedom merge ~/projects/myapp
# Squash merge (single commit) - default

vibedom merge ~/projects/myapp --merge
# Keep full commit history

vibedom merge ~/projects/myapp --branch experimental
# Merge specific branch from bundle
```

**Shell access to container:**
```bash
vibedom shell ~/projects/myapp
# Opens bash in /work/repo directory
```

**Full workflow:**
```bash
# 1. Start session
vibedom run ~/projects/myapp

# 2. Work in container
vibedom shell ~/projects/myapp
# (make changes, exit shell)

# 3. Stop and create bundle
vibedom stop ~/projects/myapp

# 4. Review changes
vibedom review ~/projects/myapp

# 5. Merge into workspace
vibedom merge ~/projects/myapp
```

### Session Management

**List sessions:**

```bash
ls ~/.vibedom/logs/
```

**Clean up old sessions:**

```bash
rm -rf ~/.vibedom/logs/session-20260214-123456
```

### Session Cleanup

Vibedom provides automated session cleanup commands to help manage disk space.

**Prune old sessions:**

Remove all session directories that don't have running containers:

```bash
# Preview what will be deleted
vibedom prune --dry-run

# Delete all non-running sessions (interactive)
vibedom prune

# Delete without prompting
vibedom prune --force
```

**Clean up old sessions by age:**

Remove sessions older than N days:

```bash
# Delete sessions older than 7 days (default)
vibedom housekeeping --dry-run
vibedom housekeeping

# Delete sessions older than 30 days
vibedom housekeeping --days 30 --dry-run
vibedom housekeeping --days 30 --force
```

Both commands skip sessions with running containers to avoid data loss.

### Troubleshooting

**Bundle creation failed:**

If bundle creation fails, the live repo is still available:

```bash
git remote add vibedom-live ~/.vibedom/sessions/session-xyz/repo
git fetch vibedom-live
# Manually create bundle:
cd ~/.vibedom/sessions/session-xyz/repo
git bundle create ../repo.bundle --all
```

**Non-git workspace:**

If your workspace isn't a git repository, vibedom will initialize a fresh repo with an initial snapshot commit.

## Stopping a Sandbox

```bash
vibedom stop ~/projects/myapp
```

This will:
1. Create a git bundle from the session repository
2. Display instructions for reviewing and merging changes
3. Stop and remove the container
4. Finalize session logs

The bundle contains all commits made by the agent and can be reviewed and merged into your workspace.

## Network Whitelisting

The sandbox enforces domain whitelisting for both HTTP and HTTPS traffic.

### Adding Domains

Edit `~/.vibedom/trusted_domains.txt`:

```
pypi.org
npmjs.com
github.com
gitlab.com
```

### Reloading Whitelist

After editing the whitelist, you can reload it without restarting the container:

```bash
vibedom reload-whitelist ~/projects/myapp
```

The command auto-detects your container runtime, or you can specify it explicitly:

```bash
vibedom reload-whitelist ~/projects/myapp --runtime docker
vibedom reload-whitelist ~/projects/myapp --runtime apple
```

This sends a SIGHUP signal to mitmproxy, triggering it to reload the whitelist from `/mnt/config/trusted_domains.txt`.

### Testing Network Access

```bash
# Inside sandbox
curl https://pypi.org/simple/    # ✅ Whitelisted, succeeds
curl https://example.com/         # ❌ Not whitelisted, blocked
```

### How It Works

Vibedom uses mitmproxy in explicit proxy mode with HTTP_PROXY/HTTPS_PROXY environment variables. Most modern tools (curl, pip, npm, git) respect these variables automatically.

**Supported tools:**
- curl, wget, httpie
- pip (Python packages)
- npm, yarn (Node.js packages)
- git (over HTTPS)
- cargo (Rust packages)
- Go tools (go get)
- Most language HTTP clients (requests, axios, etc.)

**Tools that may need configuration:**
- Docker client: Set HTTP_PROXY in daemon config
- Java applications: May need -Dhttp.proxyHost/-Dhttp.proxyPort
- Custom binaries: Check tool documentation for proxy support

## Data Loss Prevention (DLP)

Vibedom scrubs secrets from outbound HTTP traffic to prevent prompt injection attacks from exfiltrating workspace secrets.

**Protected Against:**
- Agent reading secrets from `.env`, config files, etc. and POSTing them to external endpoints
- Agent exfiltrating secrets via URL query parameters (e.g., `?api_key=xxx`)

**Not Affected:**
- Legitimate API calls (Authorization headers pass through)
- API responses (not a threat vector for our model)

**Logging:**
All scrubbing events are logged to `~/.vibedom/logs/session-*/network.jsonl` with pattern ID and original value (truncated).

## Troubleshooting

### "Domain not whitelisted"

Add the domain to `~/.vibedom/trusted_domains.txt`:

```bash
echo "new-domain.com" >> ~/.vibedom/trusted_domains.txt
```

Then reload the whitelist:

```bash
vibedom reload-whitelist ~/projects/myapp
```

### "Gitleaks found secrets"

Review the findings:
- **LOW_RISK** (local dev): Safe to continue
- **MEDIUM_RISK**: Will be scrubbed by DLP (Phase 2)
- **HIGH_RISK**: Fix before continuing

### VM won't start

Check Docker:
```bash
docker ps -a | grep vibedom
docker logs vibedom-<name>
```

Rebuild VM image:
```bash
./vm/build.sh
```

### Git repository not initialized

If the container fails to initialize the git repository, check:
1. Is the workspace a git repository?
2. Is the `.git` directory accessible?
3. Check container logs for specific errors

```bash
docker logs vibedom-<name>
```

## Advanced

### Attach to running VM

```bash
docker exec -it vibedom-<workspace-name> sh
```

### Inspect logs

```bash
ls ~/.vibedom/logs/session-*/
cat ~/.vibedom/logs/session-*/session.log
```

### Clean up old sessions

```bash
rm -rf ~/.vibedom/logs/session-*
```
