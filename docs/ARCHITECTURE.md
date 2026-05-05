# Architecture

See [design document](plans/2026-02-13-ai-agent-sandbox-design.md) for full details.

## Components

### VM Layer

#### Container Runtime

Vibedom supports two container runtimes:

| | apple/container | Docker |
|---|---|---|
| **Isolation** | Hardware VM (Virtualization.framework) | Namespace-based |
| **macOS** | 26+ (Tahoe) | Any |
| **CPU** | Apple Silicon only | Any |
| **Security** | Full VM isolation per container | Shared kernel |
| **Status** | Preferred | Fallback |

Runtime is auto-detected at startup. apple/container is preferred when available.
Both runtimes use the same `Dockerfile.alpine` image (or a layered project image via `Dockerfile.layer`).

#### Container Lifecycle

Vibedom supports two container models:

**Persistent containers** (`vibedom up/down/destroy`):
- One long-lived container per project, named `vibedom-{workspace-name}`
- State stored at `~/.vibedom/containers/{name}/container.json`
- Repo bind-mounted from `~/.vibedom/containers/{name}/repo/` (survives stop/restart)
- `startup.sh` is idempotent — skips git clone if repo already exists
- One-time setup commands from `vibedom.yml` run on first creation only

**Ephemeral sessions** (`vibedom run/stop`):
- New container per task, destroyed on stop
- State stored at `~/.vibedom/logs/session-YYYYMMDD-HHMMSS/`
- Repo bind-mounted from session directory, captured as git bundle on stop
- Original workflow, retained for one-shot isolated tasks

#### VM Configuration
- Alpine Linux base image (or project image via `base_image:` in `vibedom.yml`)
- Read-only workspace mount at `/mnt/workspace`
- Agent workspace at `/work/repo` (bind-mounted from host — persists for persistent containers)
- Explicit proxy via `HTTP_PROXY`/`HTTPS_PROXY` environment variables

### Network Layer
- mitmproxy in explicit proxy mode (`HTTP_PROXY`/`HTTPS_PROXY`)
- One host-side proxy process per container, on an OS-assigned port
- Port and PID stored in `container.json` or `state.json` for whitelist reload and health checks
- Custom addon for whitelist enforcement and DLP scrubbing
- Structured logging to `network.jsonl`
- Proxy auto-restarts on `vibedom up`/`vibedom shell` if PID is dead

### Sync Layer
- Host-side rsync between `~/.vibedom/containers/{name}/repo/` and the workspace
- No docker exec needed — the repo dir is a bind mount visible on both sides
- `.gitignore` rules applied automatically via `--filter=':- .gitignore'`
- Extra excludes configurable via `sync_exclude:` in `vibedom.yml`
- Additive by default; `--delete` opt-in for destructive sync
- Path-specific sync supported: `vibedom pull myapp src/`

### Security Layer
- Gitleaks pre-flight scanning (secrets in workspace files)
- DLP runtime scrubbing (secrets and PII in HTTP traffic)
- SSH deploy keys (not personal keys)
- Session/container audit logs
- Path traversal protection in sync commands (absolute paths rejected, `../` containment enforced)

## Storage Layout

```
~/.vibedom/
  keys/
    id_ed25519_vibedom          # SSH deploy key
  config/
    trusted_domains.txt         # network whitelist
    gitleaks.toml               # DLP patterns (shared with pre-flight scanner)
    mitmproxy/                  # CA cert and mitmproxy state

  containers/                   # persistent container state
    {workspace-name}/
      container.json            # ContainerState: workspace, runtime, proxy PID/port, status
      repo/                     # bind-mounted to /work/repo in container
      network.jsonl             # proxy request log
      mitmproxy.log             # proxy process log

  logs/                         # ephemeral session state
    session-YYYYMMDD-HHMMSS/
      state.json                # SessionState: session ID, proxy info, bundle path
      session.log               # lifecycle events
      network.jsonl             # proxy request log
      repo/                     # bind-mounted to /work/repo (ephemeral sessions)
      repo.bundle               # git bundle created on stop
```

## Data Flow

### Persistent container

```
vibedom up ~/project
  ↓
Pre-flight (first run only): Gitleaks scan → user reviews findings
  ↓
Container start: mount workspace (read-only) + repo dir (persistent bind mount)
  ↓
Proxy start: mitmproxy on host, port saved to container.json
  ↓
Setup (first run only): run setup: commands from vibedom.yml
  ↓
Agent: works in /work/repo, network filtered and DLP-scrubbed
  ↓
vibedom pull myapp: rsync repo/ → workspace (specific paths or full tree)
vibedom push myapp: rsync workspace → repo/ (specific paths or full tree)
  ↓
vibedom down: container stopped (filesystem preserved), proxy killed
  ↓
vibedom up: container restarted, proxy restarted on same port
```

### Ephemeral session

```
vibedom run ~/project
  ↓
Pre-flight: Gitleaks scan → user reviews findings
  ↓
VM start: mount workspace (read-only) + clone repo into session dir
  ↓
Proxy start: mitmproxy on host
  ↓
Agent: commits to /work/repo, network filtered
  ↓
vibedom stop: git bundle created from session repo, container destroyed
  ↓
vibedom review / vibedom merge: inspect and apply changes
```

## DLP Runtime Scrubbing

**Threat Model:** Prevent prompt injection attacks from exfiltrating secrets found in workspace to external endpoints.

**What We Scrub:**
- Request bodies (main exfiltration vector for large secrets like API keys, connection strings)
- URL query parameters (catches `?api_key=xxx` exfiltration)

**What We Don't Scrub:**
- Request headers (needed for legitimate API calls to Anthropic, Context7, etc.)
- Response bodies (API data entering the VM is not a threat)

**Implementation:**
- Chunked processing for large files (no size bypass)
- Go/Python regex compatibility warnings
- Pattern validation on startup

## Future Enhancements

- Context-aware rules (internal vs external traffic)
- High-severity real-time alerting
- Metrics and dashboards
