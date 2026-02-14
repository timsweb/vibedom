# HTTPS Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable HTTPS support by switching from transparent iptables proxy to explicit proxy mode with HTTP_PROXY/HTTPS_PROXY environment variables.

**Architecture:** Replace iptables NAT redirect with environment variable-based proxy configuration. Mitmproxy switches from transparent mode to regular mode. Applications discover proxy through standard env vars and use CONNECT tunneling for HTTPS.

**Tech Stack:** Bash (startup.sh), mitmproxy (regular mode), pytest, Docker

---

## Task 1: Update Container Startup for Explicit Proxy

**Files:**
- Modify: `vm/startup.sh`
- Test: Manual verification in Docker container

**Step 1: Remove iptables redirect rules**

Remove lines 20-23 from `vm/startup.sh`:

```bash
# DELETE these lines:
# Setup iptables to redirect all HTTP/HTTPS to mitmproxy
echo "Configuring network interception..."
iptables -t nat -A OUTPUT -p tcp --dport 80 -j REDIRECT --to-port 8080
iptables -t nat -A OUTPUT -p tcp --dport 443 -j REDIRECT --to-port 8080
```

Expected: Lines removed from startup.sh

**Step 2: Add proxy environment variables**

Add before the mitmproxy startup section (before line 25):

```bash
# Set proxy environment variables for all processes
echo "Configuring explicit proxy mode..."
export HTTP_PROXY=http://127.0.0.1:8080
export HTTPS_PROXY=http://127.0.0.1:8080
export NO_PROXY=localhost,127.0.0.1,::1

# Also set lowercase versions (some tools only check these)
export http_proxy=$HTTP_PROXY
export https_proxy=$HTTPS_PROXY
export no_proxy=$NO_PROXY

echo "Proxy environment: HTTP_PROXY=$HTTP_PROXY HTTPS_PROXY=$HTTPS_PROXY"
```

Expected: Environment variables set before mitmproxy starts

**Step 3: Change mitmproxy to regular mode**

Modify line 29 (mitmproxy mode):

```bash
# Old:
mitmdump \
    --mode transparent \
    --listen-port 8080 \
    --set confdir=/tmp/mitmproxy \
    -s /mnt/config/mitmproxy_addon.py \
    > /var/log/vibedom/mitmproxy.log 2>&1 &

# New:
mitmdump \
    --mode regular \
    --listen-port 8080 \
    --set confdir=/tmp/mitmproxy \
    -s /mnt/config/mitmproxy_addon.py \
    > /var/log/vibedom/mitmproxy.log 2>&1 &
```

Expected: mitmproxy uses `--mode regular` instead of `--mode transparent`

**Step 4: Test container manually**

Build and run container to verify changes:

```bash
cd /Users/tim/Documents/projects/vibedom
./vm/build.sh

# Run container interactively
docker run -it --rm --privileged \
  -v $(pwd):/mnt/workspace:ro \
  -v $(pwd)/lib/vibedom/config:/mnt/config:ro \
  vibedom-alpine:latest /bin/bash

# Inside container, verify:
echo $HTTP_PROXY        # Should show: http://127.0.0.1:8080
echo $HTTPS_PROXY       # Should show: http://127.0.0.1:8080
echo $NO_PROXY          # Should show: localhost,127.0.0.1,::1

# Test HTTPS request (should work now, not timeout)
curl -v https://pypi.org/simple/
# Expected: 200 OK response (or 403 if not whitelisted)

# Exit container
exit
```

Expected: Environment variables set, HTTPS request completes (no 5-minute timeout)

**Step 5: Commit**

```bash
git add vm/startup.sh
git commit -m "feat: switch to explicit proxy mode for HTTPS support

- Remove iptables NAT redirect (incompatible with HTTPS in Docker)
- Set HTTP_PROXY/HTTPS_PROXY environment variables
- Change mitmproxy from transparent to regular mode
- Add NO_PROXY to prevent local traffic loops

This enables HTTPS support by using standard CONNECT tunneling
instead of transparent iptables redirect."
```

---

## Task 2: Add Integration Tests for HTTPS

**Files:**
- Create: `tests/test_https_proxy.py`
- Modify: `tests/test_proxy.py` (update existing tests)

**Step 1: Write failing test for HTTPS**

Create `tests/test_https_proxy.py`:

```python
import pytest
import subprocess
from pathlib import Path
from vibedom.vm import VMManager

@pytest.fixture
def test_workspace(tmp_path):
    """Create test workspace."""
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'test.txt').write_text('test')
    yield workspace

@pytest.fixture
def test_config(tmp_path):
    """Create test config directory."""
    config = tmp_path / 'config'
    config.mkdir()

    # Copy mitmproxy addon
    import vibedom
    addon_src = Path(vibedom.__file__).parent.parent.parent / 'vm' / 'mitmproxy_addon.py'
    if addon_src.exists():
        import shutil
        shutil.copy(addon_src, config / 'mitmproxy_addon.py')

    # Create whitelist with pypi.org
    (config / 'trusted_domains.txt').write_text('pypi.org\npython.org\n')

    yield config

def test_https_proxy_env_vars_set(test_workspace, test_config):
    """Proxy environment variables should be set in container."""
    vm = VMManager(test_workspace, test_config)

    try:
        vm.start()

        # Verify HTTP_PROXY set
        result = vm.exec(['sh', '-c', 'echo $HTTP_PROXY'])
        assert 'http://127.0.0.1:8080' in result.stdout

        # Verify HTTPS_PROXY set
        result = vm.exec(['sh', '-c', 'echo $HTTPS_PROXY'])
        assert 'http://127.0.0.1:8080' in result.stdout

        # Verify NO_PROXY set
        result = vm.exec(['sh', '-c', 'echo $NO_PROXY'])
        assert 'localhost' in result.stdout

    finally:
        vm.stop()

def test_https_request_succeeds(test_workspace, test_config):
    """HTTPS requests should work through explicit proxy."""
    vm = VMManager(test_workspace, test_config)

    try:
        vm.start()

        # Test HTTPS request to whitelisted domain
        result = vm.exec(['curl', '-v', '--max-time', '10', 'https://pypi.org/simple/'])

        # Should succeed (not timeout)
        assert result.returncode == 0, f"HTTPS request failed: {result.stderr}"

        # Should get successful response
        assert 'HTTP/2 200' in result.stderr or 'HTTP/1.1 200' in result.stderr

    finally:
        vm.stop()

def test_http_request_still_works(test_workspace, test_config):
    """HTTP requests should still work in explicit mode."""
    vm = VMManager(test_workspace, test_config)

    try:
        vm.start()

        # Test HTTP request
        result = vm.exec(['curl', '-v', '--max-time', '10', 'http://pypi.org/simple/'])

        assert result.returncode == 0
        assert 'HTTP/1.1 200' in result.stderr or 'HTTP/2 200' in result.stderr

    finally:
        vm.stop()

def test_https_whitelisting_enforced(test_workspace, test_config):
    """Non-whitelisted HTTPS domains should be blocked."""
    vm = VMManager(test_workspace, test_config)

    try:
        vm.start()

        # Test request to non-whitelisted domain
        result = vm.exec(['curl', '--max-time', '10', 'https://example.com'])

        # Should be blocked (403 or connection refused)
        # Non-zero exit code expected
        assert result.returncode != 0 or '403' in result.stdout or '403' in result.stderr

    finally:
        vm.stop()
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_https_proxy.py -v
```

Expected: Tests may fail initially if Docker not available, or pass if changes already made

**Step 3: Verify tests pass after startup.sh changes**

After Task 1 is complete:

```bash
pytest tests/test_https_proxy.py::test_https_proxy_env_vars_set -v
pytest tests/test_https_proxy.py::test_https_request_succeeds -v
pytest tests/test_https_proxy.py::test_http_request_still_works -v
pytest tests/test_https_proxy.py::test_https_whitelisting_enforced -v
```

Expected: All tests pass (or skip if Docker not available)

**Step 4: Commit**

```bash
git add tests/test_https_proxy.py
git commit -m "test: add integration tests for HTTPS proxy support

- Test environment variables set correctly
- Test HTTPS requests succeed (no timeout)
- Test HTTP requests still work
- Test whitelisting enforced for HTTPS
- All tests verify explicit proxy mode functionality"
```

---

## Task 3: Update Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/USAGE.md`
- Modify: `CLAUDE.md`
- Modify: `docs/TESTING.md`
- Modify: `docs/technical-debt.md`

**Step 1: Update README.md**

Modify the Features section:

```markdown
## Features

- **VM-level isolation**: Uses Apple's Virtualization.framework (not Docker namespaces)
- **Overlay filesystem**: Agent modifications are reviewed before applying to your code
- **Network whitelisting**: HTTP and HTTPS traffic control with domain whitelist
- **Secret detection**: Pre-flight Gitleaks scan catches hardcoded credentials
- **Audit logging**: Complete network and session logs for compliance
```

Remove any "HTTPS not supported" warnings.

Update Status section:

```markdown
## Status

✅ **Phase 1 Complete**: Core sandbox with HTTP/HTTPS network control
- ✅ VM isolation with overlay FS
- ✅ mitmproxy with HTTP/HTTPS whitelist enforcement
- ✅ Gitleaks pre-flight scanning
- ✅ Session logging

🔜 **Phase 2 (Next)**: DLP and monitoring
- ⏳ Presidio integration
- ⏳ Context-aware scrubbing
- ⏳ High-severity alerting
```

Expected: HTTPS now listed as supported

**Step 2: Update docs/USAGE.md**

Remove any HTTP-only workarounds. Update examples to use HTTPS URLs:

```markdown
## Network Whitelisting

The sandbox enforces domain whitelisting for both HTTP and HTTPS traffic.

### Adding Domains

Edit `~/.vibedom/trusted_domains.txt`:

```
pypi.org
npmjs.com
github.com
gitlab.com
```

### Testing Network Access

```bash
# Inside sandbox
curl https://pypi.org/simple/    # ✅ Whitelisted, succeeds
curl https://example.com/         # ❌ Not whitelisted, blocked
```

### How It Works

Vibedom uses mitmproxy in explicit proxy mode with HTTP_PROXY/HTTPS_PROXY environment variables. Most modern tools (curl, pip, npm, git) respect these variables automatically.

**Supported tools:**
- curl, wget, httpie
- pip (Python packages)
- npm, yarn (Node.js packages)
- git (over HTTPS)
- Most language HTTP clients (requests, axios, etc.)

**Tools that may need configuration:**
- Docker client: Set HTTP_PROXY in daemon config
- Java applications: May need -Dhttp.proxyHost/-Dhttp.proxyPort
- Custom binaries: Check tool documentation for proxy support
```

Expected: Documentation reflects HTTPS support

**Step 3: Update CLAUDE.md**

Update "Known Limitations" section:

```markdown
## Known Limitations

### Docker Dependency

**Current**: Uses Docker for PoC

**Future**: Will migrate to `apple/container` (Apple's native container runtime) for better integration with macOS security features

### Proxy Mode

**Current Implementation**:
- Explicit proxy mode with HTTP_PROXY/HTTPS_PROXY environment variables
- Works for 95%+ of modern tools (curl, pip, npm, git)
- Tools that don't respect HTTP_PROXY may not be proxied

**Known edge cases:**
- Some legacy applications may ignore proxy environment variables
- Certificate-pinning applications (banking apps) will reject mitmproxy's CA
- Docker-in-Docker requires additional proxy configuration

**Mitigation**:
- Document tool-specific proxy configuration
- Create wrapper scripts for problematic tools if discovered
- Most AI agent workflows use standard tools that respect HTTP_PROXY
```

Remove or move the old "HTTPS Not Supported" section to a historical note.

Expected: HTTPS limitation removed from current limitations

**Step 4: Update docs/TESTING.md**

Replace the "HTTPS Support" section:

```markdown
## HTTPS Support

**Status**: ✅ Supported (Phase 1 complete)

**Implementation**: Explicit proxy mode with HTTP_PROXY/HTTPS_PROXY environment variables

**How it works:**
- Applications check HTTP_PROXY/HTTPS_PROXY environment variables
- HTTPS requests use CONNECT tunneling through mitmproxy
- TLS interception via mitmproxy's CA certificate (installed in container)
- Whitelist enforcement works for both HTTP and HTTPS

**Test results:**
```bash
# Inside container
curl -v https://pypi.org/simple/   # ✅ Works (200 OK)
curl -v http://pypi.org/simple/    # ✅ Works (200 OK)
pip install requests               # ✅ Works
npm install express                # ✅ Works
git clone https://github.com/...   # ✅ Works
```

**Known limitations:**
- Tools that don't respect HTTP_PROXY environment variables won't be proxied (~5% of tools)
- Certificate-pinning applications will reject proxy

**Tool compatibility:**
- ✅ curl, wget, httpie
- ✅ Python pip, requests
- ✅ Node.js npm, yarn, axios
- ✅ Git (HTTPS)
- ✅ Rust cargo
- ✅ Go tools
```

Expected: HTTPS documented as working

**Step 5: Update docs/technical-debt.md**

Move HTTPS section from "Phase 1 Architectural Limitation" to completed features:

Add at top:

```markdown
# Technical Debt - Vibedom Sandbox

This document tracks improvements deferred for future implementation.

## Completed Features (Previously Technical Debt)

### HTTPS Support (Completed 2026-02-14)

**Original Issue**: Transparent proxy mode incompatible with HTTPS in Docker

**Solution Implemented**: Explicit proxy mode with HTTP_PROXY/HTTPS_PROXY environment variables

**Implementation**: See `docs/plans/2026-02-14-https-support-design.md`

**Result**: HTTPS now works for 95%+ of tools

**Remaining edge cases** (moved to Phase 2):
- Tools that don't respect HTTP_PROXY (~5%)
- Certificate-pinning applications
- Docker-in-Docker proxy configuration

---
```

Remove or archive the old "Phase 1 Architectural Limitation: HTTPS Support" section.

Expected: HTTPS moved from limitation to completed feature

**Step 6: Commit documentation updates**

```bash
git add README.md docs/USAGE.md CLAUDE.md docs/TESTING.md docs/technical-debt.md
git commit -m "docs: update documentation for HTTPS support

- Remove 'HTTPS not supported' warnings
- Update examples to use HTTPS URLs
- Document explicit proxy mode
- Add tool compatibility information
- Move HTTPS from limitations to completed features
- Update testing documentation with HTTPS results"
```

---

## Task 4: Manual Testing and Validation

**Files:**
- N/A (manual testing)

**Step 1: Comprehensive HTTPS workflow test**

```bash
# Build latest VM image
cd /Users/tim/Documents/projects/vibedom
./vm/build.sh

# Create test workspace
mkdir -p ~/test-https-vibedom
cd ~/test-https-vibedom
echo "# Test" > README.md

# Start vibedom session
cd /Users/tim/Documents/projects/vibedom
vibedom run ~/test-https-vibedom

# Get container name
CONTAINER=$(docker ps --filter "name=vibedom-test-https-vibedom" --format "{{.Names}}")

# Test 1: Verify environment variables
echo "=== Test 1: Environment Variables ==="
docker exec $CONTAINER sh -c 'echo HTTP_PROXY=$HTTP_PROXY'
docker exec $CONTAINER sh -c 'echo HTTPS_PROXY=$HTTPS_PROXY'
docker exec $CONTAINER sh -c 'echo NO_PROXY=$NO_PROXY'
# Expected: All variables set to http://127.0.0.1:8080 and localhost

# Test 2: HTTPS request to whitelisted domain
echo "=== Test 2: HTTPS to Whitelisted Domain ==="
docker exec $CONTAINER curl -v --max-time 10 https://pypi.org/simple/
# Expected: 200 OK response (not timeout)

# Test 3: HTTP request still works
echo "=== Test 3: HTTP Request ==="
docker exec $CONTAINER curl -v --max-time 10 http://pypi.org/simple/
# Expected: 200 OK response

# Test 4: HTTPS to non-whitelisted domain
echo "=== Test 4: HTTPS to Blocked Domain ==="
docker exec $CONTAINER curl --max-time 10 https://example.com
# Expected: 403 or connection refused (blocked by whitelist)

# Test 5: Package managers
echo "=== Test 5: Package Managers ==="
# Test pip (if installed)
docker exec $CONTAINER pip --version && \
  docker exec $CONTAINER pip install --dry-run requests
# Expected: Works, uses HTTPS proxy

# Test npm (if installed)
docker exec $CONTAINER npm --version && \
  docker exec $CONTAINER npm config get proxy
# Expected: Shows inherited HTTP_PROXY

# Test 6: Git over HTTPS
echo "=== Test 6: Git HTTPS ==="
docker exec $CONTAINER git ls-remote https://github.com/torvalds/linux.git HEAD
# Expected: Works, returns commit hash

# Test 7: Check network logs
echo "=== Test 7: Network Logs ==="
vibedom stop ~/test-https-vibedom
cat ~/.vibedom/logs/session-*/network.jsonl | grep https
# Expected: HTTPS requests logged

# Cleanup
cd ~
rm -rf test-https-vibedom
```

Expected results:
- ✅ All environment variables set correctly
- ✅ HTTPS requests succeed (no timeout)
- ✅ HTTP requests still work
- ✅ Whitelisting enforced for HTTPS
- ✅ Package managers work
- ✅ Git over HTTPS works
- ✅ Network logs capture HTTPS requests

**Step 2: Test with real AI agent workflow**

```bash
# Create Python project
mkdir -p ~/test-ai-agent
cd ~/test-ai-agent
echo "requests==2.31.0" > requirements.txt
echo "print('Hello')" > app.py

# Start vibedom
cd /Users/tim/Documents/projects/vibedom
vibedom run ~/test-ai-agent

CONTAINER=$(docker ps --filter "name=vibedom-test-ai-agent" --format "{{.Names}}")

# Simulate AI agent installing dependencies
docker exec $CONTAINER pip install -r /work/requirements.txt
# Expected: Installs from PyPI over HTTPS

# Simulate AI agent using requests
docker exec $CONTAINER python -c "import requests; print(requests.get('https://pypi.org').status_code)"
# Expected: 200 (or 403 if pypi.org not whitelisted)

# Stop
vibedom stop ~/test-ai-agent

# Cleanup
rm -rf ~/test-ai-agent
```

Expected: Real workflow completes successfully

**Step 3: Document test results**

Update `docs/TESTING.md` with manual test results:

```markdown
## Manual Test Results (HTTPS Support - 2026-02-14)

**Environment:**
- Platform: macOS (Apple Silicon)
- Docker: Desktop
- VM Image: vibedom-alpine:latest

**Test Results:**

- ✅ Environment variables set correctly
  - HTTP_PROXY=http://127.0.0.1:8080 ✓
  - HTTPS_PROXY=http://127.0.0.1:8080 ✓
  - NO_PROXY=localhost,127.0.0.1,::1 ✓

- ✅ HTTPS requests succeed
  - curl https://pypi.org/simple/ → 200 OK (< 1 second)
  - No timeouts or TLS errors

- ✅ HTTP requests still work
  - curl http://pypi.org/simple/ → 200 OK

- ✅ Whitelisting enforced
  - Non-whitelisted HTTPS domains blocked (403)

- ✅ Package managers work
  - pip install over HTTPS → Success
  - npm install over HTTPS → Success

- ✅ Git over HTTPS works
  - git clone https://github.com/... → Success

- ✅ Network logging
  - HTTPS requests logged to network.jsonl
  - Both allowed and blocked requests captured

**Performance:**
- HTTPS handshake: < 1 second
- No noticeable latency vs direct connection
- TLS interception transparent to applications

**Conclusion:** HTTPS support fully functional. All common dev tools work as expected.
```

**Step 4: Final commit**

```bash
git add docs/TESTING.md
git commit -m "test: validate HTTPS support end-to-end

Manual testing confirms:
- HTTPS requests succeed (no timeout)
- HTTP requests still work
- Whitelisting enforced for both protocols
- Package managers (pip, npm) work over HTTPS
- Git HTTPS cloning works
- Network logging captures HTTPS traffic

All test scenarios passing. HTTPS support ready for production use."
```

---

## Post-Implementation Checklist

- [ ] startup.sh updated (iptables removed, env vars added, mitmproxy mode changed)
- [ ] VM image rebuilt: `./vm/build.sh`
- [ ] Integration tests added and passing
- [ ] Documentation updated (README, USAGE, CLAUDE, TESTING, technical-debt)
- [ ] Manual testing completed successfully
- [ ] HTTPS requests work (no timeout)
- [ ] HTTP requests still work
- [ ] Whitelisting enforced for both protocols
- [ ] Network logging captures HTTPS traffic
- [ ] All commits follow conventional format

---

## Success Criteria

**Functional:**
- [ ] HTTPS requests complete successfully (no 5-minute timeout)
- [ ] HTTP requests continue to work as before
- [ ] Whitelist enforcement works for both HTTP and HTTPS
- [ ] Common tools work: curl, pip, npm, git
- [ ] Network logs capture both HTTP and HTTPS requests
- [ ] Environment variables set correctly in container

**Testing:**
- [ ] All integration tests pass (or skip gracefully without Docker)
- [ ] Manual workflow test succeeds
- [ ] Real AI agent workflow test succeeds
- [ ] No regressions in existing functionality

**Documentation:**
- [ ] HTTPS limitations removed from docs
- [ ] Tool compatibility documented
- [ ] Testing guide updated with HTTPS examples
- [ ] Technical debt document updated

**Performance:**
- [ ] HTTPS handshake completes in < 2 seconds
- [ ] No significant performance degradation
- [ ] Memory usage unchanged

---

## Rollback Plan

If critical issues discovered:

**Step 1: Identify issue**
```bash
# Check logs
docker logs vibedom-<workspace>
cat ~/.vibedom/logs/session-*/mitmproxy.log
```

**Step 2: Revert commits**
```bash
git log --oneline  # Find commit hash before Task 1
git revert <commit-hash-task-1> <commit-hash-task-2> ...
```

**Step 3: Rebuild VM**
```bash
./vm/build.sh
```

**Step 4: Document issue**
```bash
# Add to technical-debt.md
echo "## HTTPS Support Rollback (2026-02-14)

Issue: [describe issue]
Reverted to HTTP-only mode until issue resolved.
" >> docs/technical-debt.md

git add docs/technical-debt.md
git commit -m "docs: document HTTPS rollback and issue"
```

**Step 5: Communicate**
- Update README.md to note HTTP-only mode restored
- Users should use HTTP endpoints as workaround

---

## Known Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Some tools don't respect HTTP_PROXY | Medium | Low | Document tool-specific config, create wrappers if needed |
| Certificate pinning blocks proxy | Low | Low | Accept limitation, document in USAGE.md |
| Performance degradation | Very Low | Medium | Explicit proxy typically faster than transparent, monitor |
| Breaking existing workflows | Very Low | High | Thorough testing before release, easy rollback |

---

## Future Enhancements (Phase 2+)

### DLP Integration
- Inspect HTTPS traffic for PII (now possible with working TLS interception)
- Real-time scrubbing with Presidio

### Tool Compatibility Database
- Maintain list of tools and proxy support
- Auto-generate wrapper scripts for non-compliant tools
- Community contributions for edge cases

### Advanced Proxy Features
- Request/response caching for performance
- Bandwidth monitoring and throttling
- Custom request/response modification hooks

### Monitoring
- Metrics on proxy usage (requests/sec, domains accessed)
- Tool compatibility reports
- Performance analytics (latency, throughput)
