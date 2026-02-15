# DLP Scrubber Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix critical bugs in DLP scrubbing (Go regex failures, file size limit, silent failures) and adjust scrubbing to not break API tools while still preventing secret exfiltration.

**Architecture:**
- Remove request header scrubbing (Authorization, Cookie, etc. pass through for legitimate API calls)
- Keep request body scrubbing (main exfiltration vector for large secrets)
- Add request URL scrubbing (catches query param exfiltration like `?api_key=xxx`)
- Validate gitleaks.toml patterns load correctly (warn on Python/Go regex incompatibilities)
- Chunk large files instead of skipping (512KB → 16KB chunks)
- Add proper warnings for silent failures

**Tech Stack:** Python 3.12, pytest, mitmproxy addon API

---

## Summary of Changes

**Before:**
- Scrubbed request headers → API calls to Anthropic/Context7 broken
- Scrubbed request bodies → Good (main exfiltration vector)
- No URL scrubbing → Missed query param exfiltration
- Files >512KB skipped entirely → Easy bypass
- Invalid regex patterns silently dropped → No secrets scrubbed
- Missing config warnings → No indication of broken state

**After:**
- Request headers pass through → API calls work
- Request bodies scrubbed → Main exfiltration caught
- URLs scrubbed → Query param exfiltration caught
- Large files chunked → No size bypass
- Regex errors logged → Pattern failures visible
- Config errors warned → Broken state detected

---

### Task 1: Add Pattern Validation and Warning System

**Files:**
- Modify: `vm/dlp_scrubber.py:60-84`
- Test: `tests/test_dlp_scrubber.py`

**Context:** Current code silently skips invalid regex patterns with no indication. User won't know if patterns failed to load.

**Step 1: Add warning support to DLPScrubber class**

Modify `vm/dlp_scrubber.py` to add warning tracking:

```python
import sys
from dataclasses import dataclass, field

@dataclass
class ScrubResult:
    text: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def was_scrubbed(self) -> bool:
        return len(self.findings) > 0


class DLPScrubber:
    def __init__(self, gitleaks_config: str | None = None):
        self.secret_patterns: list[Pattern] = []
        self.pii_patterns: list[Pattern] = []
        self.warnings: list[str] = []

        if gitleaks_config:
            self._load_gitleaks_patterns(gitleaks_config)
        self._load_pii_patterns()

        # Warn if patterns failed to load
        if self.warnings:
            print(f"WARNING: DLP scrubber had {len(self.warnings)} issue(s):", file=sys.stderr)
            for warning in self.warnings:
                print(f"  - {warning}", file=sys.stderr)
```

**Step 2: Track regex compilation errors**

Modify `_load_gitleaks_patterns` method:

```python
def _load_gitleaks_patterns(self, config_path: str) -> None:
    path = Path(config_path)
    if not path.exists():
        self.warnings.append(f"Config file not found: {config_path}")
        return

    try:
        with open(path, 'rb') as f:
            config = tomllib.load(f)
    except Exception as e:
        self.warnings.append(f"Failed to load config: {e}")
        return

    rules = config.get('rules', [])
    if not rules:
        self.warnings.append("No rules found in config file")
        return

    for rule in rules:
        rule_id = rule.get('id', 'unknown')
        try:
            compiled = re.compile(rule['regex'])
        except re.error as e:
            self.warnings.append(f"Rule '{rule_id}': Invalid regex - {e}")
            continue
        except KeyError:
            self.warnings.append(f"Rule '{rule_id}': Missing 'regex' field")
            continue

        placeholder_name = rule_id.upper().replace('-', '_')
        self.secret_patterns.append(Pattern(
            id=rule_id,
            description=rule.get('description', ''),
            regex=compiled,
            category='SECRET',
            placeholder=f'[REDACTED_{placeholder_name}]',
        ))

    if len(self.secret_patterns) == 0 and len(rules) > 0:
        self.warnings.append("All patterns failed to compile - no secrets will be scrubbed!")
```

**Step 3: Write test for warning system**

Add to `tests/test_dlp_scrubber.py`:

```python
def test_warns_on_invalid_regex():
    """Should warn when config has invalid regex."""
    from dlp_scrubber import DLPScrubber
    import tempfile

    with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
        f.write('''
[[rules]]
id = "bad-regex"
description = "Bad regex"
regex = '''[invalid('''
''')
        f.flush()

        import sys
        from io import StringIO

        old_stderr = sys.stderr
        sys.stderr = StringIO()

        scrubber = DLPScrubber(gitleaks_config=f.name)

        warning_output = sys.stderr.getvalue()
        sys.stderr = old_stderr

        assert len(scrubber.warnings) == 1
        assert "bad-regex" in scrubber.warnings[0]
        assert "WARNING" in warning_output
```

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && PYTHONPATH=vm pytest tests/test_dlp_scrubber.py::test_warns_on_invalid_regex -v`
Expected: PASS

**Step 5: Commit**

```bash
git add vm/dlp_scrubber.py tests/test_dlp_scrubber.py
git commit -m "feat: add pattern validation and warnings for DLP scrubber"
```

---

### Task 2: Fix File Size Limit by Chunking

**Files:**
- Modify: `vm/dlp_scrubber.py:109-166`

**Context:** Files >512KB are skipped entirely. Agent can pad any secret to 513KB to bypass all scrubbing.

**Step 1: Write test for large file chunking**

Add to `tests/test_dlp_scrubber.py`:

```python
def test_scrubs_large_file_in_chunks():
    """Should scrub large files by processing in chunks."""
    from dlp_scrubber import DLPScrubber, MAX_SCRUB_SIZE

    scrubber = make_scrubber()

    # Create text with secret in middle of 1MB string
    prefix = 'A' * 500_000  # 500KB before
    secret = 'AKIAIOSFODNN7EXAMPLE'
    suffix = 'A' * 500_000  # 500KB after
    large_text = prefix + secret + secret

    result = scrubber.scrub(large_text)

    # Should scrub secret even though file >512KB
    assert secret not in result.text
    assert '[REDACTED_AWS_ACCESS_KEY]' in result.text
    assert result.was_scrubbed
```

**Step 2: Implement chunking logic**

Modify `scrub` method in `vm/dlp_scrubber.py`:

```python
CHUNK_SIZE = 512_000  # 512KB chunks with overlap
OVERLAP = 2000  # Overlap to catch secrets at chunk boundaries

def scrub(self, text: str) -> ScrubResult:
    if not text:
        return ScrubResult(text=text)

    # Process in chunks for large files
    if len(text) > MAX_SCRUB_SIZE:
        return self._scrub_large_text(text)

    # Original logic for small files...
    # [keep existing lines 119-166]
```

**Step 3: Add _scrub_large_text method**

Add new method after `scrub`:

```python
def _scrub_large_text(self, text: str) -> ScrubResult:
    """Scrub large text by processing in chunks with overlap."""
    scrubbed = text
    all_findings: list[Finding] = []
    offset = 0

    while offset < len(text):
        chunk = text[offset:offset + CHUNK_SIZE + OVERLAP]
        result = self._scrub_chunk(chunk, offset)
        all_findings.extend(result.findings)

        if result.was_scrubbed:
            # Replace in scrubbed text
            for finding in result.findings:
                scrubbed = (
                    scrubbed[:finding.start] +
                    finding.placeholder +
                    scrubbed[finding.end:]
                )

        offset += CHUNK_SIZE

    # Deduplicate findings (secrets in overlapping chunks)
    unique_findings = self._deduplicate_findings(all_findings)
    return ScrubResult(text=scrubbed, findings=unique_findings)


def _scrub_chunk(self, chunk: str, offset: int) -> ScrubResult:
    """Scrub a single chunk and return findings with absolute positions."""
    all_matches: list[tuple[int, int, Finding, Pattern]] = []

    for pattern in self.secret_patterns + self.pii_patterns:
        for match in pattern.regex.finditer(chunk):
            if match.lastindex:
                start, end = match.start(1), match.end(1)
                matched_text = match.group(1)
            else:
                start, end = match.start(), match.end()
                matched_text = match.group()

            finding = Finding(
                pattern_id=pattern.id,
                category=pattern.category,
                matched_text=matched_text,
                start=start + offset,  # Absolute position
                end=end + offset,
                placeholder=pattern.placeholder,
            )
            all_matches.append((start + offset, end + offset, finding, pattern))

    if not all_matches:
        return ScrubResult(text=chunk)

    # Sort, filter overlaps, replace (same logic as original scrub)
    all_matches.sort(key=lambda m: m[0], reverse=True)

    filtered: list[tuple[int, int, Finding, Pattern]] = []
    min_start = len(chunk) + offset
    for start, end, finding, pattern in all_matches:
        if end <= min_start:
            filtered.append((start, end, finding, pattern))
            min_start = start

    chunk_scrubbed = chunk
    findings = []
    for start, end, finding, pattern in filtered:
        chunk_scrubbed = chunk_scrubbed[:start - offset] + pattern.placeholder + chunk_scrubbed[end - offset:]
        findings.append(finding)

    findings.reverse()
    return ScrubResult(text=chunk_scrubbed, findings=findings)


def _deduplicate_findings(self, findings: list[Finding]) -> list[Finding]:
    """Remove duplicate findings from overlapping chunks."""
    seen = set()
    unique = []
    for f in findings:
        key = (f.pattern_id, f.start, f.end)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique
```

**Step 4: Run tests to verify chunking works**

Run: `source .venv/bin/activate && PYTHONPATH=vm pytest tests/test_dlp_scrubber.py::test_scrubs_large_file_in_chunks -v`
Expected: PASS

Also run: `PYTHONPATH=vm pytest tests/test_dlp_scrubber.py -v` to verify existing tests still pass
Expected: All 23 tests pass

**Step 5: Commit**

```bash
git add vm/dlp_scrubber.py tests/test_dlp_scrubber.py
git commit -m "feat: scrub large files in chunks instead of skipping"
```

---

### Task 3: Remove Request Header Scrubbing

**Files:**
- Modify: `vm/mitmproxy_addon.py:89-107, 166-195`

**Context:** Scrubbing `Authorization` headers breaks API calls to Anthropic, Context7, etc. Headers should pass through.

**Step 1: Remove header scrubbing from request() method**

Modify `request` method in `vm/mitmproxy_addon.py`:

```python
def request(self, flow: http.HTTPFlow) -> None:
    """Intercept, scrub, and filter requests."""
    domain = flow.request.host_header or flow.request.host

    scrubbed_findings = []

    # Scrub request body before forwarding
    if flow.request.content:
        content_type = flow.request.headers.get('Content-Type', '')
        scrubbed_content, findings = self._scrub_body(
            flow.request.content, content_type
        )
        if findings:
            flow.request.content = scrubbed_content
            scrubbed_findings.extend(findings)

    # Scrub URL query parameters
    url_scrubbed, url_findings = self._scrub_url(flow.request.pretty_url)
    if url_scrubbed != flow.request.pretty_url:
        flow.request.url = url_scrubbed
        scrubbed_findings.extend(url_findings)

    # Log request (with scrubbing info)
    self.log_request(flow, allowed=self.is_allowed(domain),
                   scrubbed=scrubbed_findings)

    # Block if not whitelisted
    if not self.is_allowed(domain):
        flow.response = http.Response.make(
            403,
            b"Domain not whitelisted by vibedom",
            {"Content-Type": "text/plain"}
        )
```

**Step 2: Remove _scrub_headers method entirely**

Delete lines 89-107 in `vm/mitmproxy_addon.py` (the `_scrub_headers` method)

**Step 3: Write test for request header passthrough**

Create `tests/test_mitmproxy_addon.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'vm'))

from mitmproxy import http
from unittest.mock import Mock
from mitmproxy_addon import VibedomProxy


def test_request_headers_pass_through():
    """Should allow Authorization header through (for API calls)."""
    proxy = VibedomProxy()

    flow = Mock(spec=http.HTTPFlow)
    flow.request.host = "api.anthropic.com"
    flow.request.host_header = "api.anthropic.com"
    flow.request.content = None
    flow.request.pretty_url = "https://api.anthropic.com/v1/messages"
    flow.request.url = "https://api.anthropic.com/v1/messages"
    flow.request.headers = {
        "Authorization": "Bearer sk-ant-api123",
        "Content-Type": "application/json"
    }

    proxy.request(flow)

    # Authorization header should still be present
    assert flow.request.headers.get("Authorization") == "Bearer sk-ant-api123"
```

**Step 4: Run test to verify headers pass through**

Run: `source .venv/bin/activate && PYTHONPATH=vm pytest tests/test_mitmproxy_addon.py::test_request_headers_pass_through -v`
Expected: PASS

**Step 5: Commit**

```bash
git add vm/mitmproxy_addon.py tests/test_mitmproxy_addon.py
git commit -m "feat: remove request header scrubbing to allow API calls"
```

---

### Task 4: Add URL Query Parameter Scrubbing

**Files:**
- Modify: `vm/mitmproxy_addon.py` (add new method)
- Test: `tests/test_mitmproxy_addon.py`

**Context:** Agent can exfiltrate secrets via URL query params like `?api_key=xxx&password=yyy`

**Step 1: Add _scrub_url method**

Add to `vm/mitmproxy_addon.py` after `_scrub_body`:

```python
def _scrub_url(self, url: str) -> tuple[str, list]:
    """Scrub secrets from URL query parameters.

    Returns:
        Tuple of (possibly-scrubbed url, list of findings)
    """
    # Parse URL
    from urllib.parse import urlparse, parse_qs, urlunparse, urlencode

    try:
        parsed = urlparse(url)
    except Exception:
        return url, []

    if not parsed.query:
        return url, []

    # Scrub query parameters
    params = parse_qs(parsed.query)
    all_findings = []

    for param_name, param_values in params.items():
        for i, value in enumerate(params[param_name]):
            result = self.scrubber.scrub(value)
            if result.was_scrubbed:
                params[param_name][i] = result.text
                all_findings.extend(result.findings)

    if not all_findings:
        return url, []

    # Reconstruct URL
    new_query = urlencode(params, doseq=True)
    scrubbed_url = urlunparse(parsed._replace(query=new_query))

    return scrubbed_url, all_findings
```

**Step 2: Update request() to call _scrub_url**

Already done in Task 3 Step 1.

**Step 3: Write test for URL scrubbing**

Add to `tests/test_mitmproxy_addon.py`:

```python
def test_scrubs_secret_in_query_params():
    """Should scrub secrets from URL query parameters."""
    proxy = VibedomProxy()

    flow = Mock(spec=http.HTTPFlow)
    flow.request.host = "api.evil.com"
    flow.request.host_header = "api.evil.com"
    flow.request.content = None
    flow.request.pretty_url = "https://api.evil.com/collect?api_key=AKIAIOSFODNN7EXAMPLE&email=admin@corp.com"
    flow.request.url = "https://api.evil.com/collect?api_key=AKIAIOSFODNN7EXAMPLE&email=admin@corp.com"
    flow.request.headers = {}

    proxy.request(flow)

    # URL should be scrubbed
    assert "AKIAIOSFODNN7EXAMPLE" not in flow.request.url
    assert "admin@corp.com" not in flow.request.url
    assert "[REDACTED_AWS_ACCESS_KEY]" in flow.request.url
    assert "[REDACTED_EMAIL]" in flow.request.url


def test_does_not_scrub_clean_url():
    """Should not modify URLs without secrets."""
    proxy = VibedomProxy()

    flow = Mock(spec=http.HTTPFlow)
    flow.request.host = "api.github.com"
    flow.request.host_header = "api.github.com"
    flow.request.content = None
    flow.request.pretty_url = "https://api.github.com/repos?page=2&per_page=100"
    flow.request.url = "https://api.github.com/repos?page=2&per_page=100"
    flow.request.headers = {}

    proxy.request(flow)

    # URL should be unchanged
    assert flow.request.url == "https://api.github.com/repos?page=2&per_page=100"
```

**Step 4: Run tests to verify URL scrubbing works**

Run: `source .venv/bin/activate && PYTHONPATH=vm pytest tests/test_mitmproxy_addon.py::test_scrubs_secret_in_query_params tests/test_mitmproxy_addon.py::test_does_not_scrub_clean_url -v`
Expected: PASS

**Step 5: Commit**

```bash
git add vm/mitmproxy_addon.py tests/test_mitmproxy_addon.py
git commit -m "feat: add URL query parameter scrubbing"
```

---

### Task 5: Remove Response Scrubbing

**Files:**
- Modify: `vm/mitmproxy_addon.py:141-164`

**Context:** Response scrubbing is not needed for current threat model (preventing outbound secret exfiltration).

**Step 1: Remove response() method entirely**

Delete lines 141-164 in `vm/mitmproxy_addon.py` (the `response` method)

**Step 2: Remove _log_scrub_event and _format_findings methods**

These are now unused after removing response scrubbing.

**Step 3: Write test for response passthrough**

Add to `tests/test_mitmproxy_addon.py`:

```python
def test_response_body_not_scrubbed():
    """Should not scrub response bodies (not needed for our threat model)."""
    proxy = VibedomProxy()

    flow = Mock(spec=http.HTTPFlow)
    flow.response = Mock()
    flow.response.content = b'{"api_key": "AKIAIOSFODNN7EXAMPLE"}'
    flow.response.headers = {"Content-Type": "application/json"}

    proxy.response(flow)

    # Response should not be modified
    assert flow.response.content == b'{"api_key": "AKIAIOSFODNN7EXAMPLE"}'
```

**Step 4: Run tests**

Run: `source .venv/bin/activate && PYTHONPATH=vm pytest tests/test_mitmproxy_addon.py -v`
Expected: All tests pass

**Step 5: Commit**

```bash
git add vm/mitmproxy_addon.py tests/test_mitmproxy_addon.py
git commit -m "refactor: remove response scrubbing (not needed for threat model)"
```

---

### Task 6: Update Documentation

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/USAGE.md`
- Modify: `docs/plans/2026-02-14-dlp-presidio-integration.md`

**Step 1: Update ARCHITECTURE.md**

Update DLP section to reflect new behavior:

```markdown
### DLP Runtime Scrubbing

**Threat Model:** Prevent prompt injection attacks from exfiltrating secrets found in workspace to external endpoints.

**What We Scrub:**
- Request bodies (main exfiltration vector for large secrets like API keys, connection strings)
- URL query parameters (catches `?api_key=xxx` exfiltration)

**What We Don't Scrub:**
- Request headers (needed for legitimate API calls to Anthropic, Context7, etc.)
- Response bodies (API data entering the VM is not a threat)

**Implementation:**
- Chunked processing for large files (no size bypass)
- Go/Python regex compatibility warnings
- Pattern validation on startup
```

**Step 2: Update USAGE.md**

Update DLP section:

```markdown
### DLP Scrubbing

Vibedom scrubs secrets from outbound HTTP traffic to prevent prompt injection attacks from exfiltrating workspace secrets.

**Protected Against:**
- Agent reading secrets from `.env`, config files, etc. and POSTing them to external endpoints
- Agent exfiltrating secrets via URL query parameters (e.g., `?api_key=xxx`)

**Not Affected:**
- Legitimate API calls (Authorization headers pass through)
- API responses (not a threat vector for our model)

**Logging:**
All scrubbing events are logged to `~/.vibedom/logs/session-*/network.jsonl` with pattern ID and original value (truncated).
```

**Step 3: Update design plan**

Mark plan as completed in `docs/plans/2026-02-14-dlp-presidio-integration.md`

**Step 4: Run tests to verify everything works**

Run: `source .venv/bin/activate && PYTHONPATH=vm pytest tests/test_dlp_scrubber.py tests/test_mitmproxy_addon.py -v`
Expected: All tests pass

**Step 5: Commit**

```bash
git add docs/
git commit -m "docs: update DLP scrubbing documentation"
```

---

## Final Verification

Run full test suite:

```bash
source .venv/bin/activate
PYTHONPATH=vm pytest tests/test_dlp_scrubber.py tests/test_mitmproxy_addon.py -v
```

Expected: All tests pass (25+ tests total)

Run existing test suite to ensure no regressions:

```bash
pytest tests/ -v
```

Expected: All existing tests still pass

---

## Summary of Changes

1. **Pattern validation**: Invalid regex patterns now warn instead of silently failing
2. **File chunking**: Large files (>512KB) processed in chunks instead of skipped
3. **Header passthrough**: Request headers no longer scrubbed (API calls work)
4. **URL scrubbing**: Query parameters now scrubbed (catches `?api_key=xxx`)
5. **Response removal**: Response scrubbing removed (not needed for threat model)
6. **Documentation updated**: Reflects new behavior and threat model

This maintains multi-layered defense (pre-flight Gitleaks → whitelist → runtime DLP) while keeping tools functional.
