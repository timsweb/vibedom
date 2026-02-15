# Vibedom - Project Context for Claude

## Project Overview

**Vibedom** is a hardware-isolated sandbox environment for running AI coding agents (Claude Code, Cursor, etc.) safely on Apple Silicon Macs.

**Current Status**: Phase 1 complete (HTTP/HTTPS whitelisting, VM isolation, git bundle workflow, secret detection)

**Primary Goal**: Enable safe AI agent usage in enterprise environments with compliance requirements (SOC2, HIPAA, etc.)

## Architecture

### Core Components

1. **VM Isolation** (`lib/vibedom/vm.py`)
    - Docker-based PoC (will migrate to `apple/container` in production)
    - Read-only workspace mount at `/mnt/workspace`
    - Git repository at `/work/repo` (mounted from session)
    - Health check polling for VM readiness

2. **Network Control** (`vm/mitmproxy_addon.py`, `vm/startup.sh`)
   - mitmproxy in explicit proxy mode (HTTP_PROXY/HTTPS_PROXY environment variables)
   - Domain whitelist enforcement with subdomain support
   - Supports both HTTP and HTTPS traffic
   - DLP scrubber for secret and PII detection in HTTP traffic
   - Logs all requests to `network.jsonl`

3. **Secret Detection** (`lib/vibedom/gitleaks.py`)
   - Pre-flight Gitleaks scan before VM starts
   - Risk categorization (critical vs warnings)
   - Interactive review UI for findings

4. **Session Management** (`lib/vibedom/session.py`)
   - Structured logging (JSONL for network, text for events)
   - Session directories: `~/.vibedom/logs/session-YYYYMMDD-HHMMSS-microseconds/`
   - Tracks VM lifecycle, network requests, user decisions

5. **CLI** (`lib/vibedom/cli.py`)
   - `vibedom run <workspace>` - Start sandbox
   - `vibedom stop <workspace>` - Stop specific sandbox
   - `vibedom stop` - Stop all vibedom containers
   - `vibedom init` - First-time setup (SSH keys, whitelist)

### Key Design Decisions

**Git Bundle Workflow**: Git-native approach for agent changes (not diff-based)
- Rationale: Cleaner code review, better GitLab integration, preserves commit history
- Implementation: Container clones workspace, creates git bundle at session end
- Benefits: Users can review/merge using standard git operations

**Container Initialization**: Clone workspace or init fresh repo
- Git workspaces: Clone from host `.git`, checkout current branch
- Non-git workspaces: Initialize fresh repo with snapshot commit
- Implementation: Git clone/init in `vm/startup.sh`

**Explicit Proxy**: HTTP_PROXY/HTTPS_PROXY environment variables
- Rationale: Works with both HTTP and HTTPS
- Implementation: Environment variables set at container level, mitmproxy in regular mode
- Compatibility: 95%+ of modern tools respect proxy environment variables

**Deploy Keys**: Unique SSH key per machine
- Rationale: Avoid exposing personal credentials to VM
- Setup: `vibedom init` generates key, user adds to GitLab/GitHub

## Development Workflow

### Git Bundle Workflow

**Container Initialization:**
- Git workspaces: Cloned from host, checkout current branch
- Non-git workspaces: Fresh git init with snapshot commit
- Agent works in `/work/repo` (mounted to `~/.vibedom/sessions/session-xyz/repo`)

**During Session:**
- Agent commits normally to isolated repo
- User can fetch from live repo for mid-session testing
- `git remote add vibedom-live ~/.vibedom/sessions/session-xyz/repo`

**After Session:**
- Git bundle created at `~/.vibedom/sessions/session-xyz/repo.bundle`
- User adds bundle as remote, reviews commits
- User merges into feature branch (with or without squash)
- User pushes feature branch for GitLab MR

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

### Git Bundle Workflow

**Current Implementation:**
- Agent works on same branch as user's current branch
- Bundle contains all refs from session
- User decides to keep commits or squash during merge

**Phase 2 Enhancements:**
- Helper commands: `vibedom review`, `vibedom merge`
- Automatic session cleanup with retention policies
- GitLab integration for MR creation

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

### Docker Dependency

**Current**: Uses Docker for PoC

**Future**: Will migrate to `apple/container` (Apple's native container runtime) for better integration with macOS security features

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
./vm/build.sh

# Test basic workflow
vibedom run ~/projects/test-workspace

# Verify inside container
docker exec vibedom-<workspace> cat /tmp/.vm-ready
docker exec vibedom-<workspace> ls /work

# Test HTTP/HTTPS whitelisting
docker exec vibedom-<workspace> curl https://pypi.org/simple/

# Check logs
cat ~/.vibedom/logs/session-*/network.jsonl

# Stop
vibedom stop ~/projects/test-workspace
```

## Project Structure

```
vibedom/
├── lib/vibedom/          # Core Python package
│   ├── cli.py           # Click CLI commands
│   ├── vm.py            # VM lifecycle management
│   ├── session.py       # Session logging
│   ├── gitleaks.py      # Secret scanning
│   ├── review_ui.py     # Interactive review
│   ├── ssh_keys.py      # Deploy key management
│   ├── whitelist.py     # Domain whitelist logic
│   └── config/          # Default configs
├── vm/                   # VM image and runtime
│   ├── Dockerfile.alpine # Alpine-based image
│   ├── startup.sh       # Container entrypoint
│   ├── mitmproxy_addon.py # Proxy addon
│   └── build.sh         # Image build script
├── tests/               # Test suite
├── docs/                # Documentation
│   ├── ARCHITECTURE.md  # System architecture
│   ├── USAGE.md         # User guide
│   ├── TESTING.md       # Test documentation
│   └── technical-debt.md # Deferred improvements
└── pyproject.toml       # Package configuration
```

## Common Commands

### Development

```bash
# Install in development mode
pip install -e .

# Run tests
pytest tests/ -v

# Build VM image
./vm/build.sh

# Check code style
ruff check lib/ tests/
```

### Usage

```bash
# First-time setup
vibedom init

# Run sandbox
vibedom run ~/projects/myapp

# Stop sandbox
vibedom stop ~/projects/myapp

# Stop all
vibedom stop

# View logs
ls ~/.vibedom/logs/
cat ~/.vibedom/logs/session-*/session.log
```

### Debugging

```bash
# Check container status
docker ps -a | grep vibedom

# View container logs
docker logs vibedom-<workspace>

# Exec into container
docker exec -it vibedom-<workspace> /bin/bash

# Check mitmproxy logs
docker exec vibedom-<workspace> cat /var/log/vibedom/mitmproxy.log

# Check network logs
docker exec vibedom-<workspace> cat /var/log/vibedom/network.jsonl
```

## Future Roadmap

### Phase 2: DLP and Monitoring

- **DLP scrubbing**: Real-time secret and PII scrubbing in HTTP traffic
- **Shared patterns**: gitleaks.toml serves pre-flight scan + runtime DLP
- **Audit logging**: Scrubbed findings logged to network.jsonl
- Context-aware scrubbing
- High-severity alerting

### Phase 3: Production Hardening

- **apple/container migration**: Replace Docker with native macOS containers
- **Log rotation**: Implement size limits and rotation policies
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
- [ ] No `--privileged` additions without security review

### Pull Requests

- Keep PRs focused (one feature/fix per PR)
- Update documentation for user-facing changes
- Add tests for new functionality
- Run full test suite before submitting

## Security Considerations

### Current Security Model

- **VM isolation**: Agent cannot escape to host via kernel exploits
- **Read-only workspace**: Original files protected from malicious writes
- **Forced proxy**: All traffic routed through mitmproxy (no bypass)
- **Deploy keys**: Unique SSH key per machine (not personal credentials)

### Known Security Limitations (Phase 1)

- **Privileged mode**: Required for git operations (reduces container isolation)
- **No egress DLP**: Sensitive data could leak via HTTP/HTTPS requests
- **Docker dependency**: Relies on Docker daemon security
- **Proxy bypass**: Tools that don't respect HTTP_PROXY can bypass whitelist (~5%)

### Future Security Enhancements (Phase 2+)

- Explicit capabilities instead of `--privileged` mode
- Real-time DLP with Presidio
- Migration to apple/container for better macOS integration
- Kernel-level network filtering as fallback for non-proxy-aware tools

## Support and Documentation

- **Architecture**: See `docs/ARCHITECTURE.md`
- **User Guide**: See `docs/USAGE.md`
- **Testing**: See `docs/TESTING.md`
- **Technical Debt**: See `docs/technical-debt.md`
- **Design Docs**: See `docs/plans/` for historical context

## Contact

For questions or issues, refer to project documentation or create an issue in the repository.

---

**Last Updated**: 2026-02-14 (git bundle workflow implemented)
**Status**: HTTP/HTTPS whitelisting working, git bundle workflow complete, Phase 1 complete
**Next Milestone**: Phase 2 - DLP integration and monitoring
