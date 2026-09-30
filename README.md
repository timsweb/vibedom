# Vibedom - Secure AI Agent Sandbox

A hardware-isolated sandbox environment for running AI coding agents (Claude Code, OpenCode) safely on Apple Silicon Macs.

## Features

- **VM-level isolation**: Uses Apple's Virtualization.framework or Docker
- **Network whitelisting**: HTTP and HTTPS traffic control with domain whitelist
- **Secret detection**: Pre-flight Gitleaks scan catches hardcoded credentials
- **DLP scrubbing**: Real-time secret and PII scrubbing in outbound HTTP traffic
- **Audit logging**: Complete network logs for compliance
- **Live-mounted projects**: the agent edits your real files inside an isolated VM; git is the safety net. One container can span several projects via `mounts:` in `vibedom.yml`

## Requirements

- macOS with Apple Silicon (M1/M2/M3/M4)
- Python 3.11+
- [apple/container](https://github.com/apple/container) (macOS 26+, preferred) or Docker Desktop

## Install

```bash
uv tool install git+https://github.com/timsweb/vibedom.git
```

[uv](https://docs.astral.sh/uv/) is recommended — it keeps vibedom isolated and puts the command on your PATH. [pipx](https://pipx.pypa.io) also works: `pipx install git+https://github.com/timsweb/vibedom.git`

## Quick Start

```bash
# Initialize (once per machine — generates SSH key, builds container image)
vibedom init

# Create a container with ~/projects/myapp mounted at /work/myapp
vibedom up ~/projects/myapp

# Open a shell inside it and run claude (or your agent) there
vibedom shell myapp

# Stop it between tasks; `vibedom up` restarts it with everything preserved
vibedom down myapp
```

See [docs/USAGE.md](docs/USAGE.md) for the full usage guide.

**Upgrading?** Ephemeral sessions and copy+sync containers have been removed. Containers created before this change must be destroyed and recreated — see [Upgrading](docs/USAGE.md#upgrading-from-an-earlier-vibedom).

## How It Works

1. **VM isolation**: the agent runs in an Alpine container under apple/container (hardware VM) or Docker
2. **Live bind mounts**: your project directories appear under `/work`; edits land on your real files, so use branches and commits as the safety net
3. **Pre-flight scan**: Gitleaks checks every mounted directory for hardcoded secrets before the container is created
4. **Network filter**: mitmproxy enforces a domain whitelist and scrubs secrets from outbound requests
5. **Deploy keys**: a per-machine SSH key, not your personal credentials, is what the agent gets

## Security Model

- **VM isolation**: the agent cannot reach the host beyond the directories you mount; `ro: true` mounts for reference code
- **Forced proxy**: All traffic routed through mitmproxy — no bypass possible
- **DLP scrubbing**: Secrets detected in outbound requests are redacted before sending
- **Deploy keys**: Unique SSH key per machine, not personal credentials

## Development

```bash
git clone https://github.com/timsweb/vibedom.git
cd vibedom
uv sync
uv run pytest tests/ -v                  # unit tests (no container needed)
uv run pytest tests/test_vm.py -v        # runtime-dependent tests (requires Docker or apple/container)
```

## License

MIT
