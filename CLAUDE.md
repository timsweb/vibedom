# Vibedom - Project Context for Claude

## Project Overview

**Vibedom** is a hardware-isolated sandbox environment for running AI coding agents (Claude Code, Cursor, etc.) safely on Apple Silicon Macs.

**Current Status**: Phase 1 complete. Phase 2 DLP complete (real-time scrubbing, audit logging). Single live-mount container model (ephemeral sessions and copy+sync removed 2026-09-30).

**Primary Goal**: Enable safe AI agent usage in enterprise environments with compliance requirements (SOC2, HIPAA, etc.)

## Architecture

### Core Components

1. **VM Isolation** (`lib/vibedom/vm.py`)
    - Supports both apple/container (preferred) and Docker (fallback)
    - Project directories bind-mounted live at `/work/<name>` (one per `Mount`; `mounts` is required)
    - `~/.vibedom` read-only at `/mnt/config`; shared Claude config volume at `/root/.claude`
    - Claude Code CLI pre-installed with persistent config volume
    - Health check polling for VM readiness
    - `exists()` / `is_running()` / `pause()` / `restart()` for persistent container lifecycle

2. **Container State** (`lib/vibedom/container_state.py`)
   - `ContainerState` dataclass persisted as `~/.vibedom/containers/{name}/container.json`
   - Tracks workspace, runtime, proxy PID/port, status (running/stopped)
   - `load()` marks a pre-live-mount `container.json` (no `live: true`) as `legacy`; `up`/`shell`/`--recreate` refuse it, `status` flags it
   - `ContainerRegistry` for discovering/looking up containers by workspace name or path

3. **Network Control** (`lib/vibedom/proxy.py`, `lib/vibedom/container/mitmproxy_addon.py`)
   - ProxyManager starts mitmproxy as a **host process** (not inside the container)
   - One process per container on an OS-assigned port (no hardcoded ports)
   - Port and PID stored in `container.json` for whitelist reload
   - Proxy auto-restarts on `vibedom up`/`vibedom shell` if PID is dead
   - Container receives `HTTP_PROXY=http://host.docker.internal:<port>` and CA cert via `/mnt/config/mitmproxy/`
   - Domain whitelist enforcement with subdomain support
   - DLP scrubber for secret and PII detection in outbound HTTP traffic
   - Logs all requests to `network.jsonl`

4. **Secret Detection** (`lib/vibedom/gitleaks.py`)
   - Pre-flight Gitleaks scan before VM starts
   - Risk categorization (critical vs warnings)
   - Interactive review UI for findings

5. **CLI** (`lib/vibedom/cli.py`)
   - `init`, `up`, `down`, `destroy`, `status`, `shell`, `reload-whitelist`, `proxy-restart`

### Key Design Decisions

**Single model: persistent, live-mounted**
- `vibedom up <dir>` creates one long-lived container per project; `down`/`up` stop and restart it with the filesystem preserved
- Default mount: with no `mounts:` in `vibedom.yml`, `<dir>` is mounted rw at `/work/<basename>`. A `mounts:` list is the complete list (the `up` dir is not auto-mounted; add `- .`). Scalar or `{path, as, ro}` entries; one container can span several projects, all sharing one `base_image`
- No copy, no sync: the agent edits real files; git is the safety net. Network/DLP and per-mount secret scanning are unchanged
- Legacy containers (created by the removed copy+sync model) are refused with rescue instructions and must be destroyed and recreated
- `sync_exclude:` in `vibedom.yml` is obsolete: warns and is ignored

**Idempotent startup**: `startup.sh` only `cd`s to `/work`; nothing to clone
- SSH agent liveness check (`ssh-add -l`) on restart: reuses a live agent, replaces a stale socket left by `container stop`/`start`

**Explicit Proxy**: HTTP_PROXY/HTTPS_PROXY environment variables
- Rationale: Works with both HTTP and HTTPS
- Implementation: Environment variables set at container level, mitmproxy in regular mode
- Proxy port is baked into the container env at creation — restart must use same port
- Proxy auto-restart on `vibedom up` / `vibedom shell` if PID is dead

**Deploy Keys**: Unique SSH key per machine
- Rationale: Avoid exposing personal credentials to VM
- Setup: `vibedom init` generates key, user adds to GitLab/GitHub

## Development Workflow

### Persistent Container Workflow (Primary)

**Setup (once per project):**
- Optional `vibedom.yml` with `base_image`, `network`, `host_aliases`, `setup` commands, `memory`, `env`, `mounts`
- `vibedom up ~/projects/myapp` — creates container with `~/projects/myapp` at `/work/myapp`, runs setup commands

**Iterative development:**
```
vibedom shell myapp          # open shell in /work/myapp, run agent inside
# the agent edits your real files; review with git on the host, commit, repeat
```

**Between tasks:**
- `vibedom down myapp` — stops container, environment preserved
- `vibedom up myapp` — restarts, no re-clone, proxy auto-restarts
- `vibedom up myapp --recreate` — removes and recreates the container from the current `vibedom.yml` (new mounts/env/image); no prompt, setup re-runs

### Git Worktrees

**Preferred location**: `.worktrees/` (hidden, project-local)

New features should be developed in isolated worktrees:
```bash
git worktree add .worktrees/feature-name -b feature-name
cd .worktrees/feature-name
```

### Test-Driven Development

All features follow TDD:
1. Write failing test
2. Run test to verify it fails
3. Implement minimal code to pass
4. Run test to verify it passes
5. Commit

**Test organization**:
- `tests/test_*.py` - Unit tests (no Docker required)
- Core logic: 100% passing
- Docker-dependent tests: May fail in sandboxed environments

### Code Quality Standards

- **DRY**: Extract constants, avoid magic numbers
- **YAGNI**: No speculative features
- **Error handling**: Contextual messages, proper exception chaining
- **Type hints**: Use throughout (except CLI functions use Click decorators)
- **Docstrings**: Include usage examples for public APIs

### Technical Debt Tracking

**Document deferred improvements in**: `docs/technical-debt.md`

**Current high-priority items**:
- File I/O error handling in network logging
- Input validation for log methods

## Known Limitations

### Legacy Containers

Containers created before the live-mount-only change (copy+sync) cannot be started. `up`/`shell` print rescue instructions: pull anything from `~/.vibedom/containers/<name>/repo/`, then `vibedom destroy <name>` and `vibedom up <dir>`. See `docs/USAGE.md` → Upgrading.

### Proxy Mode

**Current Implementation**:
- Explicit proxy mode with HTTP_PROXY/HTTPS_PROXY environment variables
- Works for 95%+ of modern tools (curl, pip, npm, git)
- Tools that don't respect HTTP_PROXY may not be proxied

**Known edge cases**:
- Some legacy applications may ignore proxy environment variables
- Certificate-pinning applications (banking apps) will reject mitmproxy's CA
- Docker-in-Docker requires additional proxy configuration

**Mitigation**:
- Document tool-specific proxy configuration
- Create wrapper scripts for problematic tools if discovered
- Most AI agent workflows use standard tools that respect HTTP_PROXY

### Container Runtime

**Current**: Supports both apple/container (preferred) and Docker (fallback). Runtime is auto-detected at startup.

**Claude Code Persistence**: Uses a shared Docker volume (`vibedom-claude-config`) to persist authentication and settings across all workspaces.

**Future**: Enhancements to apple/container integration as the platform matures.

## Testing

### Running Tests

```bash
# Activate virtual environment
source .venv/bin/activate

# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_gitleaks.py -v

# Run with coverage
pytest tests/ --cov=lib/vibedom --cov-report=html
```

### Test Results (Phase 1)

- **Core logic**: 18/18 passing (100%)
- **Docker-dependent**: May fail without Docker daemon access
- **Coverage**: ~85%

### Manual Testing

```bash
# Build VM image
vibedom init  # builds image on first run

# Container workflow
vibedom up ~/projects/test-workspace
vibedom status
vibedom shell test-workspace              # lands in /work/test-workspace
vibedom down test-workspace
vibedom up ~/projects/test-workspace      # should restart without re-running setup
vibedom up test-workspace --recreate      # removes + recreates, setup re-runs
vibedom destroy test-workspace --force

# Verify inside container
docker exec vibedom-<workspace> cat /tmp/.vm-ready
docker exec vibedom-<workspace> ls /work

# Test HTTP/HTTPS whitelisting
docker exec vibedom-<workspace> curl https://pypi.org/simple/

# Check logs
cat ~/.vibedom/containers/test-workspace/network.jsonl
```

## Project Structure

```
vibedom/
├── lib/vibedom/              # Core Python package
│   ├── cli.py               # Click CLI commands
│   ├── vm.py                # VM lifecycle management
│   ├── container_state.py   # Container state (ContainerState incl. legacy detection, ContainerRegistry)
│   ├── project_config.py    # vibedom.yml parsing
│   ├── gitleaks.py          # Secret scanning
│   ├── review_ui.py         # Interactive review
│   ├── ssh_keys.py          # Deploy key management
│   ├── whitelist.py         # Domain whitelist logic
│   ├── proxy.py             # Host-side mitmproxy management
│   ├── config/              # Default configs (gitleaks.toml, trusted_domains.txt)
│   └── container/           # Container image files (Dockerfile.*, startup.sh, mitmproxy_addon.py)
├── tests/                   # Test suite
├── docs/                    # Documentation
│   ├── ARCHITECTURE.md      # System architecture
│   ├── USAGE.md             # User guide
│   ├── TESTING.md           # Test documentation
│   └── technical-debt.md    # Deferred improvements
└── pyproject.toml           # Package configuration
```

## Common Commands

### Development

```bash
# Install in development mode
pip install -e .

# Run tests
pytest tests/ -v

# Build VM image
vibedom init  # builds image on first run

# Check code style
ruff check lib/ tests/
```

### Usage

```bash
# First-time setup
vibedom init

# --- Container workflow ---
vibedom up ~/projects/myapp          # create (or restart) container; ~/projects/myapp -> /work/myapp
vibedom up myapp --recreate          # rebuild container from changed vibedom.yml (files untouched)
vibedom shell myapp                  # open shell inside container
vibedom status                       # show all container states (flags legacy ones)
vibedom down myapp                   # stop (preserves filesystem)
vibedom destroy myapp                # remove container + vibedom state (mounts untouched)

# --- Shared ---
vibedom reload-whitelist             # hot-reload domain whitelist
vibedom proxy-restart myapp          # restart the host proxy on the same port
```

### Debugging

```bash
# Check container status
docker ps -a | grep vibedom
vibedom status

# View container logs
docker logs vibedom-<workspace>

# Open shell in container
vibedom shell myapp

# Check proxy health
cat ~/.vibedom/containers/myapp/container.json   # shows proxy_pid / proxy_port

# Check network logs
cat ~/.vibedom/containers/myapp/network.jsonl
```

## Future Roadmap

### Phase 2: DLP and Monitoring ✅ (Complete)

- ✅ **DLP scrubbing**: Real-time secret and PII scrubbing in HTTP traffic
- ✅ **Shared patterns**: gitleaks.toml serves pre-flight scan + runtime DLP
- ✅ **Audit logging**: Scrubbed findings logged to network.jsonl

### Phase 2b: Persistent Containers ✅ (Complete)

- ✅ **Persistent containers**: `vibedom up/down/destroy` — container survives across tasks
- ✅ **Setup scripts**: `setup:` in `vibedom.yml`, run on every create
- ✅ **Proxy auto-restart**: proxy health checked and restarted on `up`/`shell`
- ✅ **Live mounts only** (2026-09-30): copy+sync (`push`/`pull`) and ephemeral sessions removed; `mounts:` or the default mount is the single model

### Phase 3: Production Hardening

- **High-severity alerting**: Real-time notifications for critical DLP findings
- **Log rotation**: Implement size limits and rotation policies
- **Container cleanup**: Automatic cleanup with retention policies
- **Multi-tenant support**: Workspace isolation for multiple users

## Contributing Guidelines

### Commit Messages

Follow conventional commits:
```
feat: add new feature
fix: bug fix
docs: documentation changes
test: test additions/changes
refactor: code refactoring
chore: maintenance tasks
```

Include co-authorship:
```
Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

### Code Review Checklist

- [ ] Tests pass (core logic 100%)
- [ ] No hardcoded secrets or credentials
- [ ] Error handling with contextual messages
- [ ] Type hints on public functions
- [ ] Docstrings for non-trivial functions
- [ ] Technical debt documented if deferred

### Pull Requests

- Keep PRs focused (one feature/fix per PR)
- Update documentation for user-facing changes
- Add tests for new functionality
- Run full test suite before submitting

## Security Considerations

### Current Security Model

- **VM isolation**: Agent cannot escape to host via kernel exploits
- **Live mounts**: the agent edits real files under `/work`; `ro: true` mounts for reference code; git is the safety net (the network/DLP layer is what protects secrets)
- **Forced proxy**: All traffic routed through mitmproxy (no bypass)
- **Deploy keys**: Unique SSH key per machine (not personal credentials)
- **DLP scrubbing**: Real-time secret/PII detection and scrubbing in HTTP traffic
- **Pre-flight scanning**: Gitleaks scan before VM starts

### Known Security Limitations

- **Proxy bypass**: Tools that don't respect HTTP_PROXY can bypass whitelist (~5%)
- **HTTPS response scrubbing**: Currently only scrubs requests, not responses (by design - not a threat vector for prompt injection)

### Future Security Enhancements

- Kernel-level network filtering as fallback for non-proxy-aware tools
- High-severity alerting for critical DLP findings

## Support and Documentation

- **Architecture**: See `docs/ARCHITECTURE.md`
- **User Guide**: See `docs/USAGE.md`
- **Testing**: See `docs/TESTING.md`
- **Technical Debt**: See `docs/technical-debt.md`
- **Design Docs**: See `docs/plans/` for historical context

## Contact

For questions or issues, refer to project documentation or create an issue in the repository.

---

**Last Updated**: 2026-09-30 (single live-mount model; ephemeral sessions and copy+sync removed)
**Status**: Phase 1 complete, Phase 2 DLP complete, Phase 2b persistent containers complete
**Next Milestone**: High-severity alerting OR Phase 3 production hardening
