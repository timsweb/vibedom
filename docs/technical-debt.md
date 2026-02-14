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

## Phase 1 Architectural Limitation: HTTPS Support

**Status:** Deferred to Phase 2
**Created:** 2026-02-13
**Priority:** High (for production use)

### Issue: HTTPS Whitelisting Not Supported

**Current Behavior:**
- HTTP requests: ✅ Successfully proxied and whitelisted through mitmproxy
- HTTPS requests: ❌ Timeout during TLS handshake

**Root Cause:**
Transparent proxy mode (iptables NAT redirect) is fundamentally incompatible with HTTPS in Docker containerized environments:

1. **Mitmproxy runs in transparent mode**: `--mode transparent` with iptables redirecting ports 80/443 → 8080
2. **TLS interception fails**: Original destination information lost during NAT translation
3. **Docker network isolation**: Container network namespace prevents proper bidirectional routing for TLS handshake
4. **Certificate validation issues**: Even with CA cert trusted, handshake cannot complete

**Technical Details:**
```bash
# Current setup (startup.sh)
iptables -t nat -A OUTPUT -p tcp --dport 80 -j REDIRECT --to-port 8080   # ✅ Works
iptables -t nat -A OUTPUT -p tcp --dport 443 -j REDIRECT --to-port 8080  # ❌ Hangs

# Symptom: TLS Client Hello sent, no Server Hello received
curl -v https://pypi.org/simple/  # Timeout after 5 minutes
```

**Attempted Fixes:**
- ✅ Installed mitmproxy CA certificate in system trust store (`update-ca-certificates`)
- ✅ Set environment variables (REQUESTS_CA_BUNDLE, SSL_CERT_FILE, CURL_CA_BUNDLE)
- ❌ Still times out - issue is routing, not trust

**Recommended Solution for Phase 2:**

**Option A: Explicit Proxy Mode** (Recommended)
- Switch from transparent mode to explicit proxy
- Set HTTP_PROXY/HTTPS_PROXY environment variables
- Applications configure proxy through env vars (not iptables redirect)
- Pros: Clean architecture, widely supported by tools (curl, requests, npm, git)
- Cons: Applications must respect proxy env vars (most do)

**Implementation:**
```bash
# In startup.sh, replace iptables with:
export HTTP_PROXY=http://127.0.0.1:8080
export HTTPS_PROXY=http://127.0.0.1:8080
export NO_PROXY=localhost,127.0.0.1

# Update mitmproxy mode:
mitmdump --mode regular --listen-port 8080 -s /mnt/config/mitmproxy_addon.py
```

**Option B: Advanced Transparent Mode** (Not Recommended)
- Deep-dive into iptables TPROXY mode with policy routing
- Requires kernel modules, complex routing tables
- Fragile and difficult to debug
- Pros: True transparency (no application changes)
- Cons: High complexity, maintenance burden

**Impact:**
- Phase 1: HTTP-only whitelisting acceptable for PoC and local development
- Production: HTTPS support required for most real-world workflows (npm, pip, git over HTTPS)

**Estimated Effort:**
- Option A (explicit proxy): 2-3 hours (modify startup.sh, test with various tools)
- Option B (advanced transparent): 8-16 hours (research, implement, debug, fragile)

**Workaround for Phase 1:**
- Use HTTP endpoints where possible (e.g., http://pypi.org instead of https://pypi.org)
- Configure tools to use HTTP mirrors
- Document limitation clearly in user-facing docs

**References:**
- See [docs/TESTING.md#https-support](TESTING.md#https-support) for technical details
- Mitmproxy docs on transparent mode limitations with Docker

---

## Task 6: Session Management - Deferred Improvements

**Status:** Deferred to Phase 2 or later
**Created:** 2026-02-13
**Priority:** Low to Medium

### 1. File Buffering Optimization (Medium Priority)

**Issue:** Log file writes may be buffered, potentially losing recent entries on crash.

**Current Behavior:**
```python
with open(self.network_log, 'a') as f:
    f.write(json.dumps(entry) + '\n')
```

**Recommendation:**
```python
with open(self.network_log, 'a', buffering=1) as f:  # Line buffering
    f.write(json.dumps(entry) + '\n')
```

**Impact:** Reduces risk of log loss on process crash, but adds minor performance overhead.

**Estimated Effort:** 5 minutes

---

### 2. Input Validation (Low Priority)

**Issue:** No validation on method, url, level parameters. Malformed inputs could corrupt logs.

**Current Behavior:** Accepts any string values without validation.

**Recommendation:**
```python
def log_event(self, message: str, level: str = 'INFO') -> None:
    if level not in ('INFO', 'WARN', 'ERROR', 'DEBUG'):
        level = 'INFO'
    # ... rest of method
```

**Impact:** Improves log consistency and prevents accidental corruption.

**Estimated Effort:** 10 minutes

---

### 3. Inconsistent Import Patterns (Low Priority)

**Issue:** `import json` appears inside test function instead of module level.

**Location:** `tests/test_session.py` line 31

**Current:**
```python
def test_session_log_network_request():
    # ...
    import json
    with open(log_file) as f:
        entry = json.loads(f.readline())
```

**Recommendation:** Move to module-level imports for consistency with other test files.

**Impact:** Minor - improves code style consistency.

**Estimated Effort:** 1 minute

---

### 4. Class Docstring Usage Example (Low Priority)

**Issue:** Session class docstring lacks usage example, unlike some other modules.

**Recommendation:**
```python
class Session:
    """Manages a sandbox session with logging.

    Example:
        session = Session(workspace, logs_dir)
        session.log_event('VM started')
        session.log_network_request('GET', 'https://api.github.com', True)
        session.finalize()
    """
```

**Impact:** Improves developer experience and documentation.

**Estimated Effort:** 5 minutes

---

### 5. Session Directory Creation Validation (Low Priority)

**Issue:** `mkdir(parents=True, exist_ok=True)` doesn't verify directory was actually created.

**Recommendation:**
```python
self.session_dir.mkdir(parents=True, exist_ok=True)
if not self.session_dir.exists():
    raise RuntimeError(f"Failed to create session directory: {self.session_dir}")
```

**Impact:** Very rare edge case - only helps with exotic filesystem issues.

**Estimated Effort:** 2 minutes

---

## Task 7: Mitmproxy Integration - Deferred Improvements

**Status:** Deferred to Phase 2 or later
**Created:** 2026-02-13
**Priority:** Medium

### 1. File I/O Error Handling (Medium Priority)

**Issue:** `log_request()` in mitmproxy addon opens file without error handling. Could crash proxy on disk full or permission errors.

**Location:** `vm/mitmproxy_addon.py` lines 63-73

**Current Behavior:**
```python
def log_request(self, flow: http.HTTPFlow, allowed: bool) -> None:
    entry = {...}
    with open(self.network_log_path, 'a') as f:
        f.write(json.dumps(entry) + '\n')
```

**Recommendation:**
```python
def log_request(self, flow: http.HTTPFlow, allowed: bool) -> None:
    entry = {...}
    try:
        with open(self.network_log_path, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    except (IOError, OSError) as e:
        import sys
        print(f"Warning: Failed to log request: {e}", file=sys.stderr)
```

**Impact:** Prevents proxy crashes on I/O errors.

**Estimated Effort:** 5 minutes

---

### 2. File Handle Efficiency (Medium Priority)

**Issue:** Opening and closing file for every request is inefficient under high traffic.

**Location:** `vm/mitmproxy_addon.py` lines 63-73

**Current Behavior:** File opened/closed for each request

**Recommendation:** Use buffered logging or keep file handle open

**Impact:** Performance improvement under high traffic load.

**Estimated Effort:** 15 minutes

**Note:** Acceptable for Phase 1 PoC with low traffic.

---

### 3. Missing Whitelist Warning (Medium Priority)

**Issue:** When whitelist file doesn't exist, addon silently returns empty set and blocks ALL traffic. No warning logged.

**Location:** `vm/mitmproxy_addon.py` lines 16-20

**Recommendation:**
```python
if not whitelist_path.exists():
    import sys
    print(f"WARNING: Whitelist file not found at {whitelist_path}, blocking all traffic",
          file=sys.stderr)
    return set()
```

**Impact:** Improves debugging experience when whitelist is misconfigured.

**Estimated Effort:** 3 minutes

---

### 4. Add Timestamps to Network Logs (Low Priority)

**Issue:** Network log entries lack timestamps, making debugging harder.

**Location:** `vm/mitmproxy_addon.py` lines 65-70

**Recommendation:**
```python
import datetime
entry = {
    'timestamp': datetime.datetime.utcnow().isoformat(),
    'method': flow.request.method,
    'url': flow.request.pretty_url,
    'host': flow.request.host_header or flow.request.host,
    'allowed': allowed
}
```

**Impact:** Better log analysis and debugging.

**Estimated Effort:** 3 minutes

---

### 5. Expand Test Coverage (Low Priority)

**Issue:** Missing tests for edge cases.

**Missing Test Cases:**
- Subdomain matching (e.g., `api.github.com` when `github.com` is whitelisted)
- HTTPS requests (only HTTP tested)
- Empty whitelist scenario
- Port stripping behavior

**Impact:** Reduced confidence in edge case handling.

**Estimated Effort:** 20 minutes

---

## Task 8: Run Command Integration - Deferred Improvements

**Status:** Deferred to Phase 2 or later
**Created:** 2026-02-13
**Priority:** Low

### 1. Hardcoded Magic Number (Low Priority)

**Issue:** Diff preview limit hardcoded as 2000.

**Location:** `lib/vibedom/cli.py` line 143

**Current:**
```python
click.echo(diff[:2000])  # Show first 2000 chars
```

**Recommendation:**
```python
DIFF_PREVIEW_LIMIT = 2000
# ... later:
click.echo(diff[:DIFF_PREVIEW_LIMIT])
```

**Impact:** Minor code readability improvement.

**Estimated Effort:** 2 minutes

---

### 2. Inconsistent Container Status Messages (Low Priority)

**Issue:** "Stop all" path doesn't show individual container success confirmations.

**Location:** `lib/vibedom/cli.py` lines 113-144

**Recommendation:** Add per-container success/failure indicators for better UX.

**Impact:** Improved user feedback during bulk operations.

**Estimated Effort:** 5 minutes

---

### 3. Missing Type Hints (Low Priority)

**Issue:** CLI functions lack type hints despite codebase using them elsewhere.

**Location:** `lib/vibedom/cli.py` run() and stop() functions

**Recommendation:**
```python
def run(workspace: str) -> None:
def stop(workspace: Optional[str]) -> None:
```

**Impact:** Better IDE support and type checking.

**Estimated Effort:** 3 minutes

---

### 4. Incomplete Docstrings (Low Priority)

**Issue:** Stop command docstring doesn't mention "stop all" behavior.

**Location:** `lib/vibedom/cli.py` line 106

**Recommendation:**
```python
"""Stop running sandbox session.

If workspace is provided, stops that specific sandbox.
If omitted, stops all vibedom containers.
"""
```

**Impact:** Better documentation and CLI help output.

**Estimated Effort:** 2 minutes

---

## Future Considerations

### Log Rotation
- **Issue:** Log files can grow unbounded
- **Status:** Acceptable for MVP, consider for production
- **Recommendation:** Implement log rotation or size limits

### Log File Permissions
- **Issue:** Inherit from parent directory
- **Status:** Acceptable for local dev sandbox
- **Recommendation:** Set explicit permissions (0600) for production

---

## How to Use This Document

When planning future sprints:
1. Review items by priority
2. Group related improvements for batch implementation
3. Update status when addressed
4. Archive completed items to `docs/technical-debt-resolved.md`
