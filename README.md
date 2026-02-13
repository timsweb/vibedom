# Vibedom - Secure AI Agent Sandbox

A hardware-isolated sandbox environment for running AI coding agents (Claude Code, OpenCode) safely on Apple Silicon Macs.

## Features

- **VM-level isolation**: Uses Apple's Virtualization.framework (not Docker namespaces)
- **Overlay filesystem**: Agent modifications are reviewed before applying to your code
- **Network whitelisting**: HTTP traffic control with domain whitelist (HTTPS in Phase 2)
- **Secret detection**: Pre-flight Gitleaks scan catches hardcoded credentials
- **Audit logging**: Complete network and session logs for compliance

## Status

🚧 **Phase 1 (Current)**: Core sandbox with basic network control
- ✅ VM isolation with overlay FS
- ✅ mitmproxy with whitelist enforcement
- ✅ Gitleaks pre-flight scanning
- ✅ Session logging

🔜 **Phase 2 (Next)**: HTTPS support and DLP
- ⏳ HTTPS whitelisting (explicit proxy mode)
- ⏳ Presidio integration
- ⏳ Context-aware scrubbing
- ⏳ High-severity alerting

## Requirements

- macOS 13+ on Apple Silicon (M1/M2/M3)
- Xcode Command Line Tools
- Python 3.11+
- Docker Desktop (for PoC; will migrate to apple/container)
- Homebrew

## Quick Start

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install
pip install -e .

# Initialize (first time)
vibedom init
# Follow prompts to add SSH key to GitLab

# Run agent in sandbox
vibedom run ~/projects/myapp

# Stop sandbox
vibedom stop ~/projects/myapp
```

## How It Works

1. **Pre-flight scan**: Gitleaks checks for hardcoded secrets
2. **VM boot**: Alpine Linux VM starts with workspace mounted read-only
3. **Overlay FS**: Agent works in `/work` (overlay), host files unchanged
4. **Network filter**: mitmproxy enforces whitelist, logs HTTP requests
5. **Review changes**: At session end, diff is shown for approval

**Note**: Phase 1 supports HTTP whitelisting only. HTTPS support is planned for Phase 2. See [docs/TESTING.md](docs/TESTING.md#https-support) for details.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full architecture details.

## Configuration

Edit `~/.vibedom/trusted_domains.txt` to add your internal domains:

```
# Add your internal services
gitlab.company.internal
composer.company.internal
```

## Logs

Session logs are saved to `~/.vibedom/logs/session-YYYYMMDD-HHMMSS/`:

- `session.log` - Human-readable timeline
- `network.jsonl` - All network requests (structured)
- `gitleaks_report.json` - Pre-flight scan results

## Security Model

- **VM isolation**: Agent cannot escape to host via kernel exploits
- **Read-only workspace**: Original files protected from malicious writes
- **Forced proxy**: All traffic routed through mitmproxy (no bypass)
- **Deploy keys**: Unique SSH key per machine (not personal credentials)

## Development

```bash
# Activate virtual environment
source .venv/bin/activate

# Run tests
pytest tests/ -v

# Build VM image
./vm/build.sh

# Integration test
python tests/test_integration.py
```

## License

MIT
