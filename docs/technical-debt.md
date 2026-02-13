# Technical Debt - Vibedom Sandbox

This document tracks improvements deferred for future implementation.

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
