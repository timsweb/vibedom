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

One persistent, live-mounted container per project (`vibedom up/down/destroy`):
- Named `vibedom-{workspace-name}`; state at `~/.vibedom/containers/{name}/container.json`
- Project directories are bind-mounted live under `/work` (see VM Configuration). Nothing is copied or cloned, so stop/restart/reboot preserve the container filesystem and the host files are always current.
- `vibedom up` distinguishes: already running (no-op), stopped/rebooted (restart), gone but state file exists (recreate, setup re-run), `--recreate` (remove and recreate from the current `vibedom.yml`, setup re-run), first run (secret scan, create, setup)
- `setup:` commands from `vibedom.yml` run on every create, never on restart
- `vibedom status` queries the runtime live, not disk state; apple/container `inspect` has no `--format` flag, so vibedom parses the JSON directly
- **Legacy detection**: a `container.json` without `live: true` was written by the removed copy+sync model. `ContainerState.load()` marks it `legacy`; `up`, `shell` and `--recreate` refuse it with rescue instructions and `status` flags it. `destroy` is the cleanup path.

#### VM Configuration
- Alpine Linux base image (or project image via `base_image:` in `vibedom.yml`, with the vibedom layer built on top by `Dockerfile.layer`)
- Bind mounts: `~/.vibedom` read-only at `/mnt/config`, the shared Claude config volume at `/root/.claude`, and one `/work/<name>` per project mount
- Explicit proxy via `HTTP_PROXY`/`HTTPS_PROXY` environment variables
- `startup.sh` sets git identity, starts the SSH agent with the deploy key (replacing a stale socket after `container stop`/`start`), configures the CA bundle, restores Claude config, and `cd`s to `/work`

##### Mounts (`mounts:` in `vibedom.yml`)
- Default (no `mounts:`): the directory passed to `vibedom up` is mounted read-write at `/work/<basename>`. The CLI computes this in `_resolve_mounts()`.
- Explicit `mounts:` is the complete list; the `up` directory is not auto-mounted. Entry forms: scalar `- <path>` (→ `/work/<basename>`, rw) or mapping `- {path:, as:, ro:}`; `.`/relative resolve against the `vibedom.yml` dir. Parsed into `Mount(host_path, name, read_only)` by `project_config.py`.
- `VMManager.start()` requires a non-empty mount list and emits one `-v` per mount; `down`/`destroy` construct it without mounts just to stop/remove.
- One container can span multiple projects (each at `/work/<name>`), all sharing the same `base_image`. Git is the safety net for edits; network/DLP and pre-flight secret scanning (run per mount) are unchanged.
- Mounts are fixed at container creation; `vibedom up --recreate` applies changes.

### Network Layer
- mitmproxy in explicit proxy mode (`HTTP_PROXY`/`HTTPS_PROXY`)
- One host-side proxy process per container, on an OS-assigned port
- Port and PID stored in `container.json` for whitelist reload and health checks
- Custom addon for whitelist enforcement and DLP scrubbing
- Structured logging to `network.jsonl`
- Proxy auto-restarts on `vibedom up`/`vibedom shell` if PID is dead

### Security Layer
- Gitleaks pre-flight scanning (secrets in workspace files)
- DLP runtime scrubbing (secrets and PII in HTTP traffic)
- SSH deploy keys (not personal keys)
- Container audit logs (`network.jsonl`)
- Live mounts: the agent edits real files; `ro:` mounts for reference code; git is the safety net

## Storage Layout

```
~/.vibedom/
  keys/
    id_ed25519_vibedom          # SSH deploy key
  trusted_domains.txt           # network whitelist
  gitleaks.toml                 # DLP patterns (shared with pre-flight scanner)
  mitmproxy/                    # CA cert and mitmproxy state
  claude-config/                # Claude Code config (apple/container; Docker uses a named volume)

  containers/                   # one directory per container
    {workspace-name}/
      container.json            # ContainerState: workspace, runtime, proxy PID/port, status
      network.jsonl             # proxy request log
      mitmproxy.log             # proxy process log
```

Project files live only in the user's own directories, bind-mounted into the container.

## Data Flow

```
vibedom up ~/project
  ↓
Legacy container.json (pre-live-mount)? → refuse with rescue instructions
  ↓
Already running? → check proxy health, print status, exit
  ↓
Stopped or rebooted (vm.exists)? → restart container + proxy on same port
  ↓
--recreate? → kill proxy, remove container, (rebuild base image if no base_image:)
  ↓
Gone but state file exists? → recreate container + proxy on new port
  ↓
First run? → Gitleaks scan of every mount → user reviews findings
  ↓
container run: -v <host>:/work/<name>[:ro] per mount, proxy env, CA bundle
  → port saved to container.json
  → run setup: commands from vibedom.yml (every create)
  ↓
vibedom shell: exec bash in /work/<name> (one mount) or /work (several)
Agent: edits real files under /work, network filtered and DLP-scrubbed
  ↓
vibedom down: container stopped (filesystem preserved), proxy killed
vibedom destroy: container removed, ~/.vibedom/containers/{name}/ deleted; mounts untouched
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
