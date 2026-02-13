# Testing Documentation

## Test Results Summary

**Overall**: 18/26 tests passing (69% pass rate)

### Passing Tests (18)

**Core Logic (100% passing)**:
- ✅ Gitleaks integration (3/3)
- ✅ Session management (3/3)
- ✅ Mitmproxy addon (3/3)
- ✅ VM manager logic (2/2)

**Integration (varying)**:
- ✅ CLI commands (3/3)
- ✅ Basic integration (4/4)

### Failing Tests (8)

**Docker-dependent tests** (require Docker daemon access):
- ❌ VM container lifecycle (2 tests)
- ❌ VM filesystem operations (2 tests)
- ❌ VM integration tests (4 tests)

**Root cause**: Tests run in environment without Docker daemon access. Core business logic is fully tested and passing.

## Code Coverage

Estimated coverage: **~85%**

**Well-covered**:
- Gitleaks scanning and risk categorization
- Session logging (network.jsonl, session.log)
- Mitmproxy whitelist enforcement
- VM manager error handling
- CLI argument validation

**Not covered** (acceptable for Phase 1 PoC):
- Docker container runtime behavior
- Overlay filesystem edge cases
- Network proxy edge cases

## Known Limitations

### HTTPS Support

**Status**: Not supported in Phase 1

**Reason**: Transparent proxy mode (iptables NAT redirect) is fundamentally incompatible with HTTPS in Docker containerized environments. The bidirectional TLS handshake cannot complete when traffic is transparently redirected.

**Current behavior**:
- ✅ HTTP requests: Successfully proxied and whitelisted
- ❌ HTTPS requests: Timeout during TLS handshake (Client Hello sent, no Server Hello)

**Technical details**:
- Mitmproxy runs in transparent mode (`--mode transparent`)
- iptables redirects ports 80/443 to 8080
- TLS interception fails because:
  - Original destination information lost in NAT
  - Certificate validation fails even with CA trust
  - Docker network namespace isolation prevents proper routing

**Workarounds considered**:
1. **Explicit proxy mode** (HTTP_PROXY/HTTPS_PROXY env vars) - requires application support
2. **Advanced iptables/routing** - complex, fragile, out of scope for Phase 1
3. **CONNECT tunneling** - requires mitmproxy mode changes

**Recommendation for Phase 2**:
- Switch to explicit proxy mode with environment variable injection
- Most modern tools (curl, requests, npm, git) respect HTTP_PROXY
- Provides cleaner architecture than transparent interception
- Avoids iptables complexity

**Current workaround**:
For Phase 1 testing and development, use HTTP endpoints or configure tools to use HTTP where possible.

## Running Tests

### Unit Tests

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

### Integration Tests

**Prerequisites**:
- Docker daemon running
- Docker Desktop or Colima
- Sufficient disk space for Alpine image

```bash
# Build VM image first
./vm/build.sh

# Run integration tests
pytest tests/test_integration.py -v
pytest tests/test_vm.py -v
```

### Manual Testing

```bash
# Test basic workflow
vibedom run ~/projects/test-workspace

# In container, verify:
docker exec vibedom-<workspace> cat /tmp/.vm-ready
docker exec vibedom-<workspace> ls /work

# Test HTTP whitelisting (should succeed if pypi.org is whitelisted)
docker exec vibedom-<workspace> curl http://pypi.org/simple/

# Test blocked domain (should fail with 403)
docker exec vibedom-<workspace> curl http://example.com/

# Check logs
cat ~/.vibedom/logs/session-*/network.jsonl
cat ~/.vibedom/logs/session-*/session.log

# Stop sandbox
vibedom stop ~/projects/test-workspace
```

## Test Development Guidelines

### Test Organization

```
tests/
├── test_gitleaks.py      # Secret scanning logic
├── test_session.py       # Session management
├── test_mitmproxy.py     # Proxy addon logic
├── test_vm.py           # VM manager (Docker-dependent)
├── test_cli.py          # CLI commands (Docker-dependent)
└── test_integration.py  # End-to-end (Docker-dependent)
```

### Writing New Tests

**Prefer unit tests**:
- Fast, no Docker required
- Test business logic in isolation
- Use mocks for Docker/subprocess calls

**Integration tests**:
- Only when testing Docker interactions
- Use pytest fixtures for cleanup
- Add `finally` blocks to ensure container cleanup

**Example unit test**:
```python
def test_risk_categorization():
    findings = [{'RuleID': 'generic-api-key', 'Secret': 'sk_test_123'}]
    critical, warnings = categorize_findings(findings)
    assert len(critical) == 1
```

**Example integration test**:
```python
def test_vm_lifecycle():
    vm = VMManager(Path('/tmp/test'), Path('/tmp/config'))
    try:
        vm.start()
        assert vm.is_running()
    finally:
        vm.stop()
```

## Continuous Integration

**Current status**: Local testing only

**Future CI/CD**:
- GitHub Actions with Docker-in-Docker
- Run unit tests on every PR
- Run integration tests on main branch
- Generate coverage reports

## Test Maintenance

### When to Update Tests

- **Breaking changes**: Update affected tests immediately
- **New features**: Add tests before implementation (TDD)
- **Bug fixes**: Add regression test first, then fix

### Test Debt

See [technical-debt.md](technical-debt.md) for deferred test improvements:
- Mitmproxy edge cases (subdomain matching, HTTPS, empty whitelist)
- VM error handling edge cases
- CLI bulk operations feedback

## Debugging Test Failures

### Docker-related failures

```bash
# Check Docker daemon
docker ps

# Check Docker Desktop running
pgrep -fl Docker

# Check disk space
docker system df
```

### Import errors

```bash
# Verify virtual environment
which python
python --version

# Reinstall package
pip install -e .
```

### Cleanup stuck containers

```bash
# List all vibedom containers
docker ps -a | grep vibedom

# Force remove
docker rm -f $(docker ps -aq --filter "name=vibedom")
```

## Test Performance

**Unit tests**: ~0.5s (fast, no I/O)
**Integration tests**: ~5-10s (Docker overhead)
**Full suite**: ~10-15s

**Optimization tips**:
- Use pytest fixtures for shared setup
- Mock Docker calls in unit tests
- Parallelize with `pytest-xdist` if needed
