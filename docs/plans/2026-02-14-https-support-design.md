# HTTPS Support via Explicit Proxy Mode - Design Document

**Date**: 2026-02-14
**Status**: Approved
**Replaces**: Transparent proxy mode (HTTP-only)
**Priority**: Critical - system currently unusable for HTTPS traffic

## Problem Statement

The current transparent proxy implementation using iptables NAT redirect is fundamentally incompatible with HTTPS in Docker containerized environments. HTTPS requests timeout during TLS handshake because:

1. Original destination information is lost during NAT translation
2. Docker network namespace isolation prevents proper bidirectional routing for TLS
3. Mitmproxy cannot complete TLS interception in transparent mode

**Current behavior:**
- ✅ HTTP requests: Successfully proxied and whitelisted
- ❌ HTTPS requests: Timeout (Client Hello sent, no Server Hello)

**Impact**: System is unusable for real-world workflows since 95%+ of modern web traffic uses HTTPS (npm, pip, git, etc.).

## Solution: Explicit Proxy Mode

Replace transparent iptables-based proxy with explicit HTTP_PROXY/HTTPS_PROXY environment variables.

### Core Architecture

**Transparent Mode (Current - Broken):**
```
Application → OS network stack → iptables NAT redirect → mitmproxy
                                    ↑ Destination info lost, TLS breaks
```

**Explicit Mode (New - Working):**
```
Application checks HTTP_PROXY env var → sends CONNECT request → mitmproxy
                                                                  ↓
                                                    Establishes tunnel, TLS works
```

### How It Works

1. **Container Startup**: Set environment variables
   ```bash
   export HTTP_PROXY=http://127.0.0.1:8080
   export HTTPS_PROXY=http://127.0.0.1:8080
   export NO_PROXY=localhost,127.0.0.1,::1
   ```

2. **Mitmproxy Configuration**: Switch to regular mode
   ```bash
   mitmdump --mode regular --listen-port 8080 ...
   ```

3. **Application Behavior**:
   - **HTTP**: Sends `GET http://example.com/path` to proxy
   - **HTTPS**: Sends `CONNECT example.com:443`, then TLS handshake through tunnel

4. **TLS Interception**: Mitmproxy intercepts TLS using its CA cert (already installed and trusted)

5. **Whitelist Enforcement**: Mitmproxy addon filters requests as before (unchanged)

### Key Benefits

- ✅ **HTTPS works**: CONNECT tunneling preserves destination, TLS handshake completes
- ✅ **Standard protocol**: Well-tested, widely supported approach
- ✅ **Simple architecture**: No complex iptables rules or routing tables
- ✅ **Broad compatibility**: 95%+ of tools respect HTTP_PROXY

## Implementation Details

### Changes to vm/startup.sh

**Remove (lines 20-23):**
```bash
# DELETE - no longer needed
echo "Configuring network interception..."
iptables -t nat -A OUTPUT -p tcp --dport 80 -j REDIRECT --to-port 8080
iptables -t nat -A OUTPUT -p tcp --dport 443 -j REDIRECT --to-port 8080
```

**Add (before mitmproxy starts):**
```bash
# Set proxy environment variables for all processes
export HTTP_PROXY=http://127.0.0.1:8080
export HTTPS_PROXY=http://127.0.0.1:8080
export NO_PROXY=localhost,127.0.0.1,::1

# Also set lowercase versions (some tools only check these)
export http_proxy=$HTTP_PROXY
export https_proxy=$HTTPS_PROXY
export no_proxy=$NO_PROXY
```

**Modify (line 29):**
```bash
# CHANGE from transparent to regular mode
# Old:
mitmdump --mode transparent --listen-port 8080 ...

# New:
mitmdump --mode regular --listen-port 8080 ...
```

**Keep Unchanged:**
- CA certificate installation (still required for TLS interception)
- mitmproxy addon (`mitmproxy_addon.py` - whitelist logic unchanged)
- Network logging setup
- Overlay filesystem
- SSH agent configuration

### Environment Variables Explained

**HTTP_PROXY / HTTPS_PROXY:**
- Standard environment variables checked by most HTTP clients
- Both point to same port (8080) - mitmproxy distinguishes by request type
- Format: `http://127.0.0.1:8080` (yes, "http://" even for HTTPS_PROXY)

**NO_PROXY:**
- Bypass proxy for local connections
- Prevents loops (proxy shouldn't proxy itself)
- Common values: `localhost,127.0.0.1,::1,.local`

**Lowercase versions:**
- Some tools (Go, Java) only check lowercase `http_proxy`
- Set both to ensure maximum compatibility

### Mitmproxy Mode Comparison

| Feature | Transparent Mode | Regular (Explicit) Mode |
|---------|------------------|-------------------------|
| HTTP support | ✅ Works | ✅ Works |
| HTTPS support | ❌ Broken in Docker | ✅ Works |
| Requires iptables | Yes | No |
| Requires app support | No | Yes (HTTP_PROXY) |
| Configuration complexity | High | Low |
| Docker compatibility | Poor | Excellent |
| Maintenance | Complex | Simple |

## Tool Compatibility

### Expected to Work (95%+ coverage)

**Web clients:**
- curl, wget, httpie - Respect HTTP_PROXY by default

**Package managers:**
- pip (Python) - Checks HTTP_PROXY
- npm, yarn (Node.js) - Use HTTP_PROXY
- cargo (Rust) - Checks HTTP_PROXY
- go get (Go) - Checks HTTP_PROXY/http_proxy
- apt, apt-get - Proxy-aware

**Version control:**
- git - Respects http.proxy config and HTTP_PROXY
- svn, hg - Support proxy configuration

**Languages/frameworks:**
- Python requests library - Checks HTTP_PROXY
- Node.js http/https modules - Use HTTP_PROXY
- Java HttpClient - Checks http.proxyHost (may need explicit config)
- Ruby Net::HTTP - Checks HTTP_PROXY

### Edge Cases & Mitigation

**1. Tools that ignore HTTP_PROXY:**
- **Occurrence**: Rare (~5% of tools)
- **Examples**: Custom binaries, some legacy applications
- **Mitigation**:
  - Create wrapper scripts if discovered
  - Use tool-specific proxy config
  - Document in USAGE.md

**2. Certificate pinning:**
- **Occurrence**: Security-sensitive apps (banking, enterprise)
- **Issue**: Reject mitmproxy's CA cert by design
- **Mitigation**: Accept limitation or add to whitelist with bypass

**3. Tools needing explicit config:**
- **Example**: Git may need `git config --global http.proxy http://127.0.0.1:8080`
- **Mitigation**: Set in startup.sh or document in USAGE.md

**4. Docker-in-Docker:**
- **Issue**: Docker client inside container needs special config
- **Mitigation**: Set `HTTP_PROXY` in Docker daemon config

## Testing Strategy

### Unit Tests

**Test environment variable setting:**
```python
def test_proxy_env_vars_set():
    """Proxy environment variables set correctly."""
    vm.start()

    result = vm.exec(['sh', '-c', 'echo $HTTPS_PROXY'])
    assert 'http://127.0.0.1:8080' in result.stdout

    result = vm.exec(['sh', '-c', 'echo $NO_PROXY'])
    assert 'localhost' in result.stdout
```

### Integration Tests

**test_https_proxy.py:**
```python
def test_https_request_succeeds():
    """HTTPS requests work through explicit proxy."""
    vm.start()

    # Test HTTPS request to whitelisted domain
    result = vm.exec(['curl', '-v', 'https://pypi.org/simple/'])
    assert result.returncode == 0
    assert 'HTTP/2 200' in result.stderr or 'HTTP/1.1 200' in result.stderr

def test_http_request_succeeds():
    """HTTP requests still work."""
    vm.start()

    result = vm.exec(['curl', '-v', 'http://pypi.org/simple/'])
    assert result.returncode == 0

def test_whitelisting_enforced():
    """Non-whitelisted HTTPS domains blocked."""
    vm.start()

    result = vm.exec(['curl', 'https://blocked-domain.com'])
    assert result.returncode != 0 or '403' in result.stdout

def test_common_tools_work():
    """Common dev tools respect proxy."""
    vm.start()

    # Test pip
    result = vm.exec(['pip', 'install', '--dry-run', 'requests'])
    assert result.returncode == 0

    # Test npm (if available)
    result = vm.exec(['npm', 'config', 'get', 'proxy'])
    # Should show inherited HTTP_PROXY

    # Test git
    result = vm.exec(['git', 'ls-remote', 'https://github.com/torvalds/linux.git', 'HEAD'])
    assert result.returncode == 0
```

### Manual Testing

**Test script:**
```bash
# Start sandbox
vibedom run ~/test-workspace

# Exec into container
docker exec -it vibedom-test-workspace /bin/bash

# Inside container - test HTTPS
curl -v https://pypi.org/simple/          # Should succeed with 200
curl -v https://www.npmjs.com/            # Should succeed with 200
curl -v https://github.com/               # Should succeed with 200

# Test package managers
pip install requests                       # Should work
npm install express                        # Should work

# Test git over HTTPS
git clone https://github.com/user/repo.git # Should work

# Test whitelisting (assuming example.com not whitelisted)
curl https://example.com                   # Should get 403

# Verify logs
cat /var/log/vibedom/network.jsonl         # Should show HTTPS requests logged
```

**Expected results:**
- All HTTPS requests to whitelisted domains succeed
- Non-whitelisted domains return 403
- Network logs capture all requests
- No timeouts or TLS errors

## Migration & Rollback

### Migration Path

**Phase 1 → Phase 2 transition:**

1. **Update code**: Modify `vm/startup.sh` as specified above
2. **Rebuild image**: `./vm/build.sh`
3. **No user action required**: Existing workflows work, HTTPS now enabled

**User impact:**
- ✅ Transparent - no CLI changes, no config changes
- ✅ HTTPS now works (previously timed out)
- ✅ HTTP continues to work as before

### Backward Compatibility

**What stays the same:**
- CLI commands (`vibedom run/stop/init`)
- Configuration files (whitelist format)
- Network logging format (network.jsonl)
- Session management
- Whitelist enforcement logic

**What improves:**
- HTTPS requests now succeed (previously failed)

**Breaking changes:**
- None (purely additive functionality)

### Rollback Plan

If issues discovered after deployment:

**Step 1: Revert commit**
```bash
git revert <commit-hash>
```

**Step 2: Rebuild VM image**
```bash
./vm/build.sh
```

**Step 3: Document issues**
- Add to technical-debt.md
- Communicate limitation to users

**Step 4: System reverts to Phase 1**
- HTTP-only mode restored
- Known limitation, but stable

**Risk of rollback:**
- Low - no data corruption possible
- Network configuration only
- Users aware of HTTP-only limitation

## Documentation Updates

### Files to Update

**README.md:**
- ~~Remove "HTTPS not supported" warning~~
- Add "✅ HTTPS whitelisting" to features

**docs/USAGE.md:**
- ~~Remove workaround section for HTTPS~~
- Update examples to use HTTPS URLs
- Add troubleshooting for tools that don't respect HTTP_PROXY

**CLAUDE.md:**
- Update "Known Limitations" section
- Move HTTPS from limitation to completed feature
- Document explicit proxy approach

**docs/TESTING.md:**
- ~~Remove HTTPS timeout documentation~~
- Add HTTPS test results
- Update manual testing guide with HTTPS examples

**docs/technical-debt.md:**
- ~~Remove "Phase 1 Architectural Limitation: HTTPS Support" section~~
- Move to "Completed" section with implementation date

### New Documentation

**docs/TROUBLESHOOTING.md** (if needed):
```markdown
## HTTPS not working for specific tool

Some tools may not respect HTTP_PROXY environment variable.

**Diagnosis:**
```bash
# Check if tool respects HTTP_PROXY
TOOL_NAME --proxy http://127.0.0.1:8080 ...
```

**Solutions:**
1. Check tool documentation for proxy configuration
2. Set tool-specific proxy settings
3. Create wrapper script
4. Report issue for investigation
```

## Success Criteria

**Functional:**
- [ ] HTTPS requests to whitelisted domains succeed (no timeout)
- [ ] HTTP requests continue to work
- [ ] Whitelist enforcement works for HTTPS
- [ ] Common tools (curl, pip, npm, git) work with HTTPS
- [ ] Network logs capture HTTPS requests
- [ ] CA certificate properly installed and trusted

**Testing:**
- [ ] All integration tests pass
- [ ] Manual testing validates HTTPS workflow
- [ ] No regressions in HTTP functionality
- [ ] Whitelisting works for both HTTP and HTTPS

**Documentation:**
- [ ] All docs updated to reflect HTTPS support
- [ ] HTTPS limitation removed from known issues
- [ ] Troubleshooting guide for edge cases

**Performance:**
- [ ] No significant latency increase
- [ ] HTTPS handshake completes in < 1 second

## Security Considerations

**Unchanged:**
- VM isolation (agent cannot escape to host)
- Read-only workspace (original files protected)
- Whitelist enforcement (only approved domains accessible)
- Deploy keys (unique per machine)

**Improved:**
- ✅ HTTPS traffic now visible to proxy (can enforce whitelist)
- ✅ TLS interception working (can inspect encrypted traffic for DLP)

**New considerations:**
- Certificate trust: Mitmproxy CA must be trusted (already implemented)
- Certificate pinning: Some apps will reject proxy (accept limitation)

**Phase 2+ enhancements:**
- Real-time DLP with Presidio (inspect HTTPS traffic)
- Certificate validation policy (strict vs permissive)

## Alternative Approaches Considered

### Option A: Explicit Proxy Mode (Chosen)

**Pros:**
- Simple, standard approach
- Works with HTTPS
- 95%+ tool coverage
- Easy to maintain

**Cons:**
- Requires HTTP_PROXY support
- Not "transparent"

**Verdict**: ✅ **Selected** - best balance of simplicity and functionality

### Option B: Advanced Transparent Mode with TPROXY

**Approach:**
- Use iptables TPROXY instead of NAT REDIRECT
- Configure policy routing
- Complex kernel module requirements

**Pros:**
- True transparency
- No app configuration needed

**Cons:**
- Very complex (8-16 hours implementation)
- Fragile, hard to debug
- Requires privileged container features
- May still not work in Docker

**Verdict**: ❌ Rejected - complexity not justified

### Option C: Hybrid Mode (Explicit + Transparent Fallback)

**Approach:**
- Use explicit proxy as primary
- Keep iptables redirect as fallback

**Pros:**
- Best coverage

**Cons:**
- Transparent mode still broken for HTTPS (no benefit)
- More complex
- Potential conflicts

**Verdict**: ❌ Rejected - transparent fallback doesn't help with HTTPS

## Implementation Timeline

**Estimated effort:** 2-3 hours

**Task breakdown:**
1. Update startup.sh (30 min)
2. Add integration tests (1 hour)
3. Manual testing (30 min)
4. Documentation updates (30 min)
5. Build and deploy (15 min)

**Dependencies:**
- None (independent change)

**Risks:**
- Low - standard proxy approach
- Easy rollback if issues found

## Future Enhancements

### Phase 2+

**DLP Integration:**
- Inspect HTTPS traffic for sensitive data (now possible with working TLS interception)
- Real-time scrubbing with Presidio

**Advanced Proxy Features:**
- Request/response caching
- Bandwidth throttling
- Request/response modification hooks

**Tool Wrappers:**
- Auto-detect tools that don't respect HTTP_PROXY
- Generate wrapper scripts automatically
- Maintain compatibility database

**Monitoring:**
- Metrics on proxy usage
- Tool compatibility reports
- Performance analytics

---

**Approved by**: User
**Next Steps**: Create implementation plan using writing-plans skill
