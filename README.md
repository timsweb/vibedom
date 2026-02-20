# Vibedom - Secure AI Agent Sandbox

A hardware-isolated sandbox environment for running AI coding agents (Claude Code, OpenCode) safely on Apple Silicon Macs.

## Features

- **VM-level isolation**: Uses Apple's Virtualization.framework or Docker
- **Network whitelisting**: HTTP and HTTPS traffic control with domain whitelist
- **Secret detection**: Pre-flight Gitleaks scan catches hardcoded credentials
- **DLP scrubbing**: Real-time secret and PII scrubbing in outbound HTTP traffic
- **Audit logging**: Complete network and session logs for compliance
- **Git bundle workflow**: Agent changes are reviewed and merged using standard git operations

## Requirements

- macOS with Apple Silicon (M1/M2/M3/M4)
- Python 3.11+
- [apple/container](https://github.com/apple/container) (macOS 26+, preferred) or Docker Desktop

## Install

```bash
pip install git+https://github.com/timsweb/vibedom.git
```

## Quick Start

```bash
# Initialize (once per machine — generates SSH key, builds container image)
vibedom init

# Run agent in sandbox
vibedom run ~/projects/myapp

# Attach a shell to the running container
vibedom attach

# Stop session and create git bundle
vibedom stop

# Review agent's changes
vibedom review myapp-happy-turing

# Merge into your workspace
vibedom merge myapp-happy-turing
```

See [docs/USAGE.md](docs/USAGE.md) for the full usage guide.

## How It Works

1. **Pre-flight scan**: Gitleaks checks for hardcoded secrets before starting
2. **Container boot**: Alpine Linux container starts with workspace mounted read-only
3. **Isolated git repo**: Agent commits to a cloned repo inside the session
4. **Network filter**: mitmproxy enforces domain whitelist, scrubs secrets from outbound requests
5. **Git bundle**: On stop, changes are bundled for review and merge using standard git

## Security Model

- **Container isolation**: Agent cannot modify host files (read-only workspace mount)
- **Forced proxy**: All traffic routed through mitmproxy — no bypass possible
- **DLP scrubbing**: Secrets detected in outbound requests are redacted before sending
- **Deploy keys**: Unique SSH key per machine, not personal credentials

## Development

```bash
git clone https://github.com/timsweb/vibedom.git
cd vibedom
pip install -e .
pytest tests/ -v
```

## License

MIT
