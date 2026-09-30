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

Add the displayed public key to your GitLab account under **Settings → SSH Keys**. This lets the agent push and fetch your private repositories over SSH.

## Container Runtime

Vibedom auto-detects your container runtime:

- **apple/container** (preferred) — hardware-isolated VMs via Virtualization.framework. Requires macOS 26+ and Apple Silicon. Install from [github.com/apple/container](https://github.com/apple/container). Note: the `network:` field in `vibedom.yml` is not supported — see below for the host-port alternative.
- **Docker** (fallback) — install [Docker Desktop](https://www.docker.com/products/docker-desktop/).

To force a specific runtime:

```bash
vibedom up ~/projects/myapp --runtime docker
vibedom up ~/projects/myapp --runtime apple
```

## Upgrading from an earlier vibedom

Vibedom now has a single model: the project directory is bind-mounted live into
the container. Two earlier models have been removed:

- **Ephemeral sessions** — `vibedom run`, `stop`, `attach`, `review`, `merge`,
  `list`, `rm`, `prune`, `housekeeping` no longer exist.
- **Copy+sync containers** — `vibedom pull`/`push`, the `/work/repo` copy and
  the read-only `/mnt/workspace` mount no longer exist.

**If you have a container created before this change, you must destroy it and
recreate it.** `vibedom up`, `vibedom shell` and `vibedom status` will tell you
when a container is one of these ("legacy"). Steps:

1. Anything the agent changed lives in the host-side copy at
   `~/.vibedom/containers/<name>/repo/`. It is a normal git repo: commit and
   push from there, or copy files out.
2. `vibedom destroy <name>`
3. `vibedom up <dir>` — the container is recreated with `<dir>` mounted live.

Containers that already used `mounts:` keep working without any action.

Old `~/.vibedom/logs/session-*` directories are no longer used and can be
deleted. A `sync_exclude:` key in `vibedom.yml` is ignored with a warning.

---

## Workflow

A vibedom container is persistent: it stays alive across tasks, and the
container filesystem (installed packages, compiled assets) is preserved between
`down` and `up`. Your project files are never copied — they are bind-mounted
live from the host, so the agent edits your real files and git is your safety
net.

### Starting a Container

```bash
vibedom up ~/projects/myapp
```

- **First run**: scans every mount for secrets, builds the image, creates the container with `~/projects/myapp` mounted at `/work/myapp`, runs `setup:` commands
- **After `vibedom down`**: restarts the existing container (environment preserved)
- **After a reboot**: container is in a stopped state — `vibedom up` restarts it, same as after `vibedom down`
- **Container missing** (e.g. manually deleted): recreates it — no secret scan; setup commands re-run
- **`vibedom up myapp --recreate`**: removes the existing container and creates it again from the current `vibedom.yml`. Use this after changing `mounts:`, `env:`, `network:`, `memory:` or `base_image:`, or to pick up a new vibedom image. No prompt — your files are bind-mounted, not copied, so nothing is lost. Setup commands re-run.
- **Already running**: checks proxy health and prints status

### Project Setup (vibedom.yml)

Add `vibedom.yml` to your project root to configure the container:

```yaml
base_image: wapi-php-fpm:latest   # use your project's image instead of Alpine
network: wapi_shared_network      # join this docker network (for DB, Redis, etc.)
host_aliases:
  wapi-redis: host                # resolve this hostname to the host machine

env:                              # extra env vars injected into the container
  DB_PORT: 1234                   # e.g. point the app at a different DB port
  DB_HOST: host.docker.internal

setup:
  - composer install              # run once when the container is created
  - cp .env.example .env
  - php artisan key:generate

mounts:                           # optional: which host dirs to mount (see below)
  - .                             #   this project → /work/<project-name>
  - ~/projects/api                #   another project → /work/api
  - path: ~/projects/shared-libs  #   mapping form: rename and/or make read-only
    as: shared                    #   → /work/shared
    ro: true                      #   read-only mount
```

`setup:` commands run when the container is created (first `up`, `--recreate`, or recreation after the container went missing), not on restarts. Packages installed during setup persist in the container.

`env:` vars are baked into the container at creation time (like `network`/`memory`/`mounts`). Changing them in `vibedom.yml` takes effect after `vibedom up --recreate`, not on a plain `down`/`up` restart. Reserved vibedom vars (the proxy, CA-bundle, and SSH-agent variables) cannot be overridden — supplying one prints a warning and is ignored.

### Git identity

Your host git identity is lifted into the container automatically. On container creation, vibedom reads your **global** identity (`git config --global user.name` / `user.email`) and sets it as the container's global git identity, so agent commits are authored as you. Per-repo overrides on the host are intentionally not consulted — this mirrors your machine-wide identity. If the host has no global identity configured, commits fall back to the default `Vibedom Agent`. You can still override explicitly with `GIT_AUTHOR_*`/`GIT_COMMITTER_*` under `env:` or a `git config` command under `setup:`; both take precedence over the lifted identity.

> **apple/container:** The `network:` field is not supported. Expose services on the host and connect via `host.docker.internal`. Vibedom will warn and ignore the setting.

### Mounts

Every container has one or more **mounts**: host directories bind-mounted live at `/work/<name>`.

**Default** — with no `mounts:` in `vibedom.yml` (or no `vibedom.yml` at all), the directory you pass to `vibedom up` is mounted read-write at `/work/<basename>`:

```bash
vibedom up ~/projects/myapp     # ~/projects/myapp → /work/myapp
```

**Explicit** — a `mounts:` list replaces the default entirely. It is the complete list of what gets mounted; the directory you pass to `vibedom up` names the container but is **not** auto-mounted, so list it (`- .`) if you want it inside.

```yaml
mounts:
  - .                             # scalar: this project, live at /work/<project-name>
  - ~/projects/api                # scalar: → /work/api (name = basename)
  - path: ~/projects/legacy-src   # mapping: rename to avoid a name clash
    as: legacy                    #   → /work/legacy
  - path: ~/projects/shared-libs  # mapping: read-only reference material
    as: shared
    ro: true                      #   → /work/shared (read-only)
```

- **Scalar** (`- <path>`): bind-mounted read-write at `/work/<basename>`.
- **Mapping** (`- {path:, as:, ro:}`): `path` is required; `as` overrides the `/work/<name>` subdirectory (needed when two dirs share a basename); `ro: true` mounts read-only (good for shared libraries the agent should read but not modify).
- `~` and relative paths resolve against the directory containing `vibedom.yml`; `.` is that directory itself.
- Mounts are fixed when the container is created. After adding or changing entries, run `vibedom up myapp --recreate` to apply them.

**Multi-project example** — one "agent container" spanning a backend and frontend:

```yaml
# ~/projects/agent/vibedom.yml
base_image: my-php-fpm:latest
mounts:
  - ~/projects/api
  - ~/projects/frontend
```
```bash
vibedom up ~/projects/agent    # /work/api and /work/frontend are both live
vibedom shell agent            # opens /work; both projects are subdirectories
```

> **One container = one base image.** All mounted projects share the container's `base_image` (and therefore its language/PHP version). Group projects that need different PHP versions into separate containers, or use a base image that provides multiple versions.

### Working in the Container

```bash
vibedom shell myapp
# or auto-select if only one container running
vibedom shell
```

This opens a bash shell inside the container, where Claude Code is pre-installed and authenticated. With a single mount the shell opens in `/work/<name>`; with several it opens in `/work`, with each project as a subdirectory.

**Git is your safety net.** The agent edits your real files, and its commits land on your actual checked-out branch. Work on a branch, commit often, and treat it as "hand the project to the agent" rather than editing the same tree at the same time from the host.

**Secret scanning and network/DLP isolation are unchanged** — every mount (including `ro:` ones) is gitleaks-scanned before the container is first created, and all traffic still goes through the whitelisting/DLP proxy.

### Reaching Host Services

Databases and caches are best run on the host (Docker Desktop, Homebrew) and reached from inside the container:

- `HOST_IP` is set inside the container to the host's address.
- `host_aliases:` in `vibedom.yml` maps a hostname to the host (`host`) or a fixed IP, so app config can keep using names like `wapi-redis`.

Two caveats:

- Docker Desktop must publish the service port on all interfaces (`0.0.0.0:3306:3306`), not only `127.0.0.1`, or the container cannot reach it through the host gateway.
- Laravel Valet's dnsmasq and apple/container both want port 53. Stop Valet before `container system start` (see [Troubleshooting](#troubleshooting)).

### Checking Status

```bash
vibedom status          # all containers
vibedom status myapp    # specific project
```

Status is queried live from the container runtime — not from cached state on disk. After a reboot, a container that was running when you shut down will show as `stopped` rather than the stale `running` value stored on disk. Containers created before the live-mount-only change show as `legacy` with a reminder to destroy them.

### Stopping a Container

```bash
vibedom down myapp
# or auto-select
vibedom down
```

Stops the container and proxy. The filesystem is preserved — `vibedom up` restarts it without re-running setup.

### Destroying a Container

```bash
vibedom destroy myapp
```

Removes the container and vibedom's state for it (`~/.vibedom/containers/myapp/`). Your mounted directories are never touched. Asks for confirmation; use `--force` to skip.

To rebuild a container from a changed `vibedom.yml`, use `vibedom up myapp --recreate` instead.

---

## Using Claude Code

Claude Code is pre-installed in all container images. Authentication persists across containers via a shared volume.

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

All scrubbing events are logged to `~/.vibedom/containers/<name>/network.jsonl`.

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

### Container shows wrong status after reboot (apple/container)

apple/container containers survive reboots in a stopped state. Run `vibedom up <workspace>` as normal — it restarts the container without re-running setup. If networking seems broken inside the container after a reboot, you may need to run `container system dns create` on the host to restore DNS (a known apple/container issue).

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

### Laravel Valet and apple/container fight over port 53

Valet's dnsmasq binds port 53, which apple/container's DNS also needs; `apk add` and other lookups inside the container fail. Stop Valet, then restart the container system:

```bash
valet stop
container system stop && container system start
```

Run your database and cache in Docker Desktop instead and reach them via `host_aliases:` (see [Reaching Host Services](#reaching-host-services)).
