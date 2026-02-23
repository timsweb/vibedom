# Usage Guide

## Installation

[pipx](https://pipx.pypa.io) is recommended — it installs vibedom in an isolated environment and puts the `vibedom` command on your PATH without affecting other Python projects:

```bash
pipx install git+https://github.com/timsweb/vibedom.git
```

**Updating:**

```bash
pipx install --force git+https://github.com/timsweb/vibedom.git
```

Or if you've already installed via pipx:

```bash
pipx reinstall vibedom
```

**Alternative (plain pip):**

```bash
pip install git+https://github.com/timsweb/vibedom.git
```

**For development:**

```bash
git clone https://github.com/timsweb/vibedom.git
cd vibedom
pip install -e .
```

## First-Time Setup

Run once per machine:

```bash
vibedom init
```

This will:
1. Generate an SSH deploy key at `~/.vibedom/keys/id_ed25519_vibedom`
2. Create a default network whitelist at `~/.vibedom/config/trusted_domains.txt`
3. Build the container image (requires Docker or apple/container)

Add the displayed public key to your GitLab account under **Settings → SSH Keys**. This lets the agent clone your private repositories.

## Container Runtime

Vibedom auto-detects your container runtime:

- **Docker** (default) — install [Docker Desktop](https://www.docker.com/products/docker-desktop/).
- **apple/container** (experimental) — hardware-isolated VMs via Virtualization.framework. Requires macOS 26+ and Apple Silicon. Install from [github.com/apple/container](https://github.com/apple/container). Note: the `network:` field in `vibedom.yml` is not supported — see below for the host-port alternative.

To force a specific runtime:

```bash
vibedom run ~/projects/myapp --runtime docker
vibedom run ~/projects/myapp --runtime apple
```

## Running a Session

```bash
vibedom run ~/projects/myapp
```

This will:
1. Scan the workspace for secrets (Gitleaks) and show findings for review
2. Start mitmproxy on the host as a dedicated proxy process
3. Start the container with the workspace mounted read-only
4. Clone your git repository into an isolated session

On startup, vibedom prints a **session ID** (e.g. `myapp-happy-turing`) — use this to refer to the session in subsequent commands.

## Project Integration (vibedom.yml)

For projects with existing Docker images and shared networks, add a `vibedom.yml` to your workspace root:

```yaml
base_image: wapi-php-fpm:latest   # use your project's image instead of Alpine
network: wapi_shared_network      # join this docker network (for DB, Redis, etc.)
```

`vibedom run` will detect this file and:
1. Build a thin vibedom layer on top of your `base_image`
2. Connect the container to `network` (so artisan, rails console, etc. can reach the database)

The read-only workspace mount, git clone to `/work/repo`, and git bundle workflow are unchanged — your original files remain protected.

> **apple/container:** The `network:` field is not supported. Instead, expose your services on the host (e.g. `mysql -h 0.0.0.0`) and connect from the container via `host.docker.internal:3306`. Vibedom will warn and ignore the `network:` setting if you run with `--runtime apple`.

## Working in the Session

### Attaching a Shell

```bash
vibedom attach
# Auto-selects if only one session running

vibedom attach myapp-happy-turing
# Specific session by ID or workspace name
```

This opens a shell at `/work/repo` inside the container, where Claude Code is pre-installed and authenticated.

### Using Claude Code

Claude Code is pre-installed in the container image. Authentication persists across sessions via a shared volume.

**First time:**
```bash
vibedom attach
cd /work/repo
claude   # follow OAuth flow
```

**Subsequent sessions:**
```bash
vibedom attach   # Claude is already authenticated
```

### Monitoring Network Activity

```bash
tail -f ~/.vibedom/logs/session-*/network.jsonl
```

## Stopping a Session

```bash
vibedom stop
# Auto-selects if only one session running

vibedom stop myapp-happy-turing
# Specific session
```

This creates a git bundle from the session repository, then stops and removes the container. After stopping, the output shows commands to review and merge the agent's changes.

## Reviewing and Merging Changes

### Review

```bash
vibedom review myapp-happy-turing
```

Shows the commit log and diff between your current branch and what the agent produced. Prints the remote name added for further manual git operations.

### Merge

```bash
# Squash into a single commit (default)
vibedom merge myapp-happy-turing

# Keep full commit history
vibedom merge myapp-happy-turing --merge

# Merge a specific branch from the bundle
vibedom merge myapp-happy-turing --branch experimental
```

After merging, push your branch for peer review:

```bash
git push origin feature/add-authentication
```

### Manual Git Access

If you prefer to work directly with git, the bundle is at:

```
~/.vibedom/logs/session-<id>/repo.bundle
```

```bash
git remote add vibedom-session ~/.vibedom/logs/session-xyz/repo.bundle
git fetch vibedom-session
git log vibedom-session/main
git diff main..vibedom-session/main
```

## Session Management

### List Sessions

```bash
vibedom list
```

Shows all sessions with their status, age, and workspace.

### Delete a Session

```bash
vibedom rm myapp-happy-turing
# Prompts for confirmation

vibedom rm myapp-happy-turing --force
# No prompt
```

Running sessions are refused — stop them first.

### Prune All Non-Running Sessions

```bash
vibedom prune --dry-run   # preview
vibedom prune             # interactive
vibedom prune --force     # no prompts
```

### Clean Up by Age

```bash
vibedom housekeeping --dry-run        # preview sessions older than 7 days
vibedom housekeeping                  # delete sessions older than 7 days
vibedom housekeeping --days 30        # older than 30 days
```

Both `prune` and `housekeeping` skip running sessions.

## Network Whitelisting

All outbound traffic is filtered through mitmproxy. Only domains in the whitelist are allowed.

### Editing the Whitelist

```bash
edit ~/.vibedom/config/trusted_domains.txt
```

One domain per line. Subdomains are included automatically:

```
pypi.org
npmjs.com
github.com
your-internal-gitlab.com
```

### Reloading Without Restart

After editing the whitelist, apply changes to all running containers:

```bash
vibedom reload-whitelist
```

### Testing Network Access

```bash
# Inside the container (vibedom attach)
curl https://pypi.org/simple/    # ✅ whitelisted
curl https://example.com/        # ❌ blocked
```

### How It Works

Vibedom sets `HTTP_PROXY`/`HTTPS_PROXY` environment variables in the container. Most modern tools respect these automatically: curl, pip, npm, yarn, git, cargo, go.

## Data Loss Prevention (DLP)

Vibedom scrubs secrets from outbound HTTP requests in real time, preventing agents from exfiltrating workspace secrets (API keys, tokens, etc. found in `.env` files or config).

All scrubbing events are logged to `~/.vibedom/logs/session-*/network.jsonl`.

## Troubleshooting

### Container won't start

Check runtime status:

```bash
# Docker
docker ps -a | grep vibedom
docker logs vibedom-myapp

# apple/container
container list
container logs vibedom-myapp
```

Rebuild the image:

```bash
vibedom init  # builds image on first run
```

### "Domain not whitelisted"

Add the domain and reload:

```bash
echo "new-domain.com" >> ~/.vibedom/config/trusted_domains.txt
vibedom reload-whitelist
```

### "Gitleaks found secrets"

Review each finding:
- **LOW_RISK**: Safe to continue (e.g. local dev placeholders)
- **MEDIUM_RISK**: Will be scrubbed by DLP at runtime
- **HIGH_RISK**: Fix before continuing

### Bundle creation failed

The live repo is still accessible at `~/.vibedom/logs/session-xyz/repo`. You can create the bundle manually:

```bash
cd ~/.vibedom/logs/session-xyz/repo
git bundle create ../repo.bundle --all
```
