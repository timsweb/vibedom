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

## Git Bundle Workflow - Phase 2 Enhancements

**Status:** Phase 1 complete, enhancements deferred
**Created:** 2026-02-14
**Priority:** Medium

### 1. Helper Commands (Medium Priority)

**Current:** Users run manual git commands for review/merge

**Proposed:**
```bash
vibedom review <workspace>      # Auto-add remote, show log/diff
vibedom merge <workspace>       # Merge and cleanup
vibedom merge <workspace> --squash
vibedom sessions list           # Show all bundles
vibedom sessions clean --older-than 30d
```

**Estimated Effort:** 4-6 hours

### 2. Session Recovery (Low Priority)

**Issue:** If bundle creation fails, user must manually create bundle

**Proposed:**
```bash
vibedom recover <session-id>    # Retry bundle creation from live repo
```

**Estimated Effort:** 1-2 hours

### 3. Automatic Cleanup (Medium Priority)

**Issue:** Session directories accumulate indefinitely

**Proposed:**
- Configurable retention policy (default 30 days)
- `~/.vibedom/config.toml`: `session_retention_days = 30`
- Automatic cleanup on vibedom start

**Estimated Effort:** 2-3 hours

### 4. GitLab Integration (High Priority for Production)

**Issue:** Manual push and MR creation

**Proposed:**
```bash
vibedom push <workspace>        # Push branch, create MR
```

Uses GitLab API to create MR with:
- Session metadata (bundle link)
- Agent commit summary
- Links to session logs

**Estimated Effort:** 6-8 hours

### 5. Disk Space Checks (Low Priority)

**Issue:** Bundle creation can fail due to disk space

**Proposed:**
- Check available space before bundle creation
- Warn if < 1GB available
- Offer to cleanup old sessions

**Estimated Effort:** 1 hour

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

## Session Cleanup - Deferred Improvements

**Status:** Deferred
**Created:** 2026-02-18
**Priority:** Low

### 1. Missing Test Coverage for prune/housekeeping (Low Priority)

**Issue:** Two code paths have no automated test coverage:
- `vibedom prune --force` and `vibedom housekeeping --force`: the force path deletes without prompting and is the most consequential code path, but has no test.
- `vibedom prune` when `~/.vibedom/logs` does not exist: expected output is "No sessions to delete" but this is not verified by any test.

**Location:** `tests/test_prune.py`

**Recommendation:** Add tests:
```python
def test_prune_force_deletes_without_prompting(...):
    # verify sessions deleted without click.confirm call

def test_prune_no_logs_directory(runner):
    result = runner.invoke(main, ['prune'])
    assert result.exit_code == 0
    assert 'No sessions to delete' in result.output
```

**Estimated Effort:** 20 minutes

---

### 2. Missing click.secho Warnings for Skipped Sessions (Low Priority)

**Issue:** The original design spec required `click.secho()` warnings when sessions are skipped due to invalid directory names, malformed timestamps, or future-dated timestamps. The implementation silently skips these cases instead.

**Location:** `lib/vibedom/session.py` - `find_all_sessions()` and `_filter_by_age()`

**Current Behavior:** Sessions with bad names or malformed timestamps are silently skipped.

**Recommendation:**
```python
timestamp = SessionCleanup._parse_timestamp(session_dir.name)
if timestamp is None:
    click.secho(f"Warning: skipping {session_dir.name} (unrecognised name format)", fg='yellow', err=True)
    continue
```

**Impact:** Improves debuggability when session directories have unexpected names (e.g. manually created or corrupted).

**Estimated Effort:** 15 minutes

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
