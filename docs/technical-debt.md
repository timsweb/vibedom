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

## Task 7: Mitmproxy Integration - Deferred Improvements

**Status:** Deferred to Phase 2 or later
**Created:** 2026-02-13
**Priority:** Medium

### 1. File I/O Error Handling (Medium Priority)

**Issue:** `log_request()` in mitmproxy addon opens file without error handling. Could crash proxy on disk full or permission errors.

**Location:** `lib/vibedom/container/mitmproxy_addon.py` lines 63-73

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

**Location:** `lib/vibedom/container/mitmproxy_addon.py` lines 63-73

**Current Behavior:** File opened/closed for each request

**Recommendation:** Use buffered logging or keep file handle open

**Impact:** Performance improvement under high traffic load.

**Estimated Effort:** 15 minutes

**Note:** Acceptable for Phase 1 PoC with low traffic.

---

### 3. Missing Whitelist Warning (Medium Priority)

**Issue:** When whitelist file doesn't exist, addon silently returns empty set and blocks ALL traffic. No warning logged.

**Location:** `lib/vibedom/container/mitmproxy_addon.py` lines 16-20

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

**Location:** `lib/vibedom/container/mitmproxy_addon.py` lines 65-70

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

## Host Proxy - Deferred Improvements

**Status:** Deferred
**Created:** 2026-02-20
**Priority:** Medium

### 1. `vibedom init` Does Not Rebuild Stale Image (Medium Priority)

**Issue:** `vibedom init` skips the image build if `vibedom-alpine:latest` already exists. After a vibedom upgrade that changes `startup.sh` or the Dockerfile, users must manually rebuild the image or the old startup logic keeps running.

**Current Behavior:**
```python
if VMManager.image_exists(runtime_cmd):
    click.echo("✓ VM image already up to date")
else:
    VMManager.build_image(rt)
```

**Recommendation:** Add a `vibedom build` command (or `vibedom init --force`) that always rebuilds the image. Document in upgrade notes that a rebuild is required after updates.

**Workaround:** `docker rmi vibedom-alpine:latest && vibedom init`

**Estimated Effort:** 30 minutes

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
