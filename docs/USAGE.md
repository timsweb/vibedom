# Usage Guide

## Installation

[uv](https://docs.astral.sh/uv/) is recommended — it installs vibedom in an isolated environment and puts the `vibedom` command on your PATH without affecting other Python projects:

```bash
uv tool install git+https://github.com/timsweb/vibedom.git
```

**Updating:**

```bash
uv tool upgrade vibedom
```

**Alternative (pipx):**

```bash
pipx install git+https://github.com/timsweb/vibedom.git
pipx upgrade vibedom  # to update
```

**For development:**

```bash
git clone https://github.com/timsweb/vibedom.git
cd vibedom
uv sync
uv run pytest tests/ -v
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
vibedom up ~/projects/myapp --runtime docker
vibedom up ~/projects/myapp --runtime apple
```

## Two Workflows

Vibedom supports two ways of working. Choose based on how you use the tool:

| | **Persistent containers** | **Ephemeral sessions** |
|---|---|---|
| **Command** | `vibedom up` | `vibedom run` |
| **Container lifetime** | Survives across tasks | Destroyed on stop |
| **Environment setup** | Once (composer install, etc.) | Every run |
| **Code sync** | `vibedom push` / `vibedom pull` | Git bundle at stop |
| **Best for** | Iterative development | Isolated one-shot tasks |

---

## Persistent Container Workflow (Recommended)

Persistent containers stay alive across multiple tasks. The container filesystem (installed packages, `.env` files, compiled assets) is preserved between sessions. You sync code explicitly when you want it.

### Starting a Container

```bash
vibedom up ~/projects/myapp
```

- **First run**: scans for secrets, builds image, clones repo into container
- **After `vibedom down`**: restarts the existing container (no re-clone, environment preserved)
- **Already running**: checks proxy health and prints status

### Project Setup (vibedom.yml)

Add `vibedom.yml` to your workspace root to configure the container:

```yaml
base_image: wapi-php-fpm:latest   # use your project's image instead of Alpine
network: wapi_shared_network      # join this docker network (for DB, Redis, etc.)
host_aliases:
  wapi-redis: host                # resolve this hostname to the host machine

setup:
  - composer install              # run once on first 'vibedom up'
  - cp .env.example .env
  - php artisan key:generate

sync_exclude:                     # extra excludes on top of .gitignore
  - storage/logs/
  - bootstrap/cache/
```

`setup:` commands run once when the container is first created, not on subsequent restarts. Packages installed during setup persist in the container.

> **apple/container:** The `network:` field is not supported. Expose services on the host and connect via `host.docker.internal`. Vibedom will warn and ignore the setting.

### Syncing Code

Changes made by the agent inside the container don't automatically appear on the host, and vice versa. Use explicit sync commands:

```bash
# Pull agent's changes → your workspace
vibedom pull myapp

# Pull only specific paths
vibedom pull myapp src/ app/Http/

# Push your local edits → container
vibedom push myapp

# Push only specific paths
vibedom push myapp src/Controllers/

# Preview before syncing
vibedom pull myapp --dry-run
vibedom push myapp --dry-run
```

**What gets excluded automatically:**
- Everything in `.gitignore` (vendor/, node_modules/, .env, build artifacts, etc.)
- `.git/` itself
- Additional patterns from `sync_exclude:` in `vibedom.yml`

**Safety defaults:**
- Sync is additive by default — files are copied/overwritten but nothing is deleted
- Full-tree syncs (no path args) ask for confirmation before running
- Use `--delete` to also remove files absent from the source (destructive)
- Use `--yes` to skip the confirmation prompt in scripts

### Opening a Shell

```bash
vibedom shell myapp
# or auto-select if only one container running
vibedom shell
```

This opens a bash shell at `/work/repo` inside the container, where Claude Code is pre-installed and authenticated.

### Checking Status

```bash
vibedom status          # all containers
vibedom status myapp    # specific project
```

Output shows container name, status (running/stopped), and proxy health.

### Stopping a Container

```bash
vibedom down myapp
# or auto-select
vibedom down
```

Stops the container and proxy. The filesystem is preserved — `vibedom up` restarts it without re-cloning or re-running setup.

### Destroying a Container

```bash
vibedom destroy myapp
```

Removes the container and deletes its repo data entirely. Asks for confirmation. Use `--force` to skip.

---

## Ephemeral Session Workflow

Each `vibedom run` creates a fresh isolated session. The container is destroyed on stop and changes are extracted as a git bundle for review.

### Running a Session

```bash
vibedom run ~/projects/myapp
```

This will:
1. Scan the workspace for secrets (Gitleaks) and show findings for review
2. Start mitmproxy on the host as a dedicated proxy process
3. Start the container with the workspace mounted read-only
4. Clone your git repository into an isolated session

On startup, vibedom prints a **session ID** (e.g. `myapp-happy-turing`) — use this to refer to the session in subsequent commands.

### Attaching a Shell

```bash
vibedom attach
# Auto-selects if only one session running

vibedom attach myapp-happy-turing
# Specific session by ID or workspace name
```

### Stopping a Session

```bash
vibedom stop
vibedom stop myapp-happy-turing
```

Creates a git bundle from the session repository, then stops and removes the container.

### Reviewing and Merging Changes

```bash
# Review what changed
vibedom review myapp-happy-turing

# Merge as a single squash commit (default)
vibedom merge myapp-happy-turing

# Keep full commit history
vibedom merge myapp-happy-turing --merge
```

After merging, push your branch for peer review:

```bash
git push origin feature/add-authentication
```

### Manual Git Access

The bundle is at `~/.vibedom/logs/session-<id>/repo.bundle`:

```bash
git remote add vibedom-session ~/.vibedom/logs/session-xyz/repo.bundle
git fetch vibedom-session
git log vibedom-session/main
git diff main..vibedom-session/main
```

### Session Management

```bash
vibedom list                          # all sessions
vibedom rm myapp-happy-turing         # delete a session (prompts)
vibedom rm myapp-happy-turing --force # no prompt
vibedom prune --dry-run               # preview non-running sessions
vibedom prune                         # delete all non-running sessions
vibedom housekeeping --days 30        # delete sessions older than 30 days
```

---

## Using Claude Code

Claude Code is pre-installed in all container images. Authentication persists across containers and sessions via a shared volume.

**First time:**
```bash
vibedom shell myapp
# inside the container:
claude   # follow OAuth flow
```

**Subsequently** Claude is already authenticated in all containers.

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

```bash
vibedom reload-whitelist
```

### Testing Network Access

```bash
# Inside the container (vibedom shell myapp)
curl https://pypi.org/simple/    # ✅ whitelisted
curl https://example.com/        # ❌ blocked
```

## Data Loss Prevention (DLP)

Vibedom scrubs secrets from outbound HTTP requests in real time, preventing agents from exfiltrating workspace secrets (API keys, tokens, etc. found in `.env` files or config).

All scrubbing events are logged to `~/.vibedom/containers/<name>/network.jsonl` (persistent) or `~/.vibedom/logs/session-*/network.jsonl` (ephemeral).

## Troubleshooting

### Container won't start

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
vibedom init
```

### Proxy died after terminal close

The proxy is a host process that stops when the terminal closes. On next `vibedom up` or `vibedom shell`, the proxy is automatically restarted.

To restart manually:

```bash
vibedom proxy-restart myapp
```

### "Domain not whitelisted"

```bash
echo "new-domain.com" >> ~/.vibedom/config/trusted_domains.txt
vibedom reload-whitelist
```

### "Gitleaks found secrets"

Review each finding:
- **LOW_RISK**: Safe to continue (e.g. local dev placeholders)
- **MEDIUM_RISK**: Will be scrubbed by DLP at runtime
- **HIGH_RISK**: Fix before continuing

### Bundle creation failed (ephemeral sessions)

The live repo is still accessible at `~/.vibedom/logs/session-xyz/repo`. Create the bundle manually:

```bash
cd ~/.vibedom/logs/session-xyz/repo
git bundle create ../repo.bundle --all
```
