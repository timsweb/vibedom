# DLP Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add real-time secret and PII scrubbing to outbound HTTP traffic, preventing AI agents from exfiltrating sensitive data while maintaining uninterrupted agent workflows.

**Architecture:** A lightweight Python scrubber that loads regex patterns from the existing `gitleaks.toml` (shared with pre-flight scanning) plus built-in PII patterns. Integrated into the mitmproxy addon to scrub request bodies, response bodies, and headers. No new dependencies — uses Python stdlib only (`re`, `tomllib`).

**Tech Stack:** Python `re` + `tomllib` (stdlib), mitmproxy addon API

**Why not Presidio:** Presidio requires spaCy + ML models (150-500MB, 2-5s startup) but doesn't detect API keys, tokens, or credentials — the highest-priority threats for code agent DLP. Our threat model is secret exfiltration from code repos, not generic PII. A custom regex scrubber covers 95%+ of real threats at zero dependency cost. See design doc for full analysis.

---

### Task 1: Expand Gitleaks Pattern Library

**Files:**
- Modify: `lib/vibedom/config/gitleaks.toml`

**Context:** This file is already used by the Gitleaks binary for pre-flight scanning. We're expanding it with more patterns. The same file will also be loaded by our Python scrubber at runtime — one config, two enforcement points.

**Step 1: Read the current config**

Read: `lib/vibedom/config/gitleaks.toml`
Understand: Current structure has 3 rules (generic-api-key, gitlab-token, database-password) plus an allowlist section.

**Step 2: Add high-value secret patterns from upstream Gitleaks**

Add these rules to `lib/vibedom/config/gitleaks.toml` (after existing rules):

```toml
[[rules]]
id = "aws-access-key"
description = "AWS Access Key ID"
regex = '''\b((?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16})\b'''
tags = ["aws", "key"]

[[rules]]
id = "stripe-api-key"
description = "Stripe API Key"
regex = '''\b((?:sk|rk)_(?:test|live|prod)_[a-zA-Z0-9]{10,99})\b'''
tags = ["stripe", "key"]

[[rules]]
id = "openai-api-key"
description = "OpenAI API Key"
regex = '''\b(sk-[a-zA-Z0-9]{20,})\b'''
tags = ["openai", "key"]

[[rules]]
id = "github-pat"
description = "GitHub Personal Access Token"
regex = '''ghp_[0-9a-zA-Z]{36}'''
tags = ["github", "token"]

[[rules]]
id = "github-fine-grained-pat"
description = "GitHub Fine-Grained Personal Access Token"
regex = '''github_pat_\w{82}'''
tags = ["github", "token"]

[[rules]]
id = "slack-bot-token"
description = "Slack Bot Token"
regex = '''xoxb-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*'''
tags = ["slack", "token"]

[[rules]]
id = "slack-webhook"
description = "Slack Webhook URL"
regex = '''hooks\.slack\.com/(?:services|workflows|triggers)/[A-Za-z0-9+/]{43,56}'''
tags = ["slack", "webhook"]

[[rules]]
id = "private-key"
description = "Private Key Header"
regex = '''-----BEGIN[ A-Z0-9_-]{0,100}PRIVATE KEY[ A-Z0-9_-]{0,100}-----'''
tags = ["key", "private"]

[[rules]]
id = "jwt-token"
description = "JSON Web Token"
regex = '''\b(ey[a-zA-Z0-9]{17,}\.ey[a-zA-Z0-9/_-]{17,}\.[a-zA-Z0-9/_-]{10,}={0,2})\b'''
tags = ["jwt", "token"]

[[rules]]
id = "generic-password"
description = "Generic Password Assignment"
regex = '''(?i)(password|passwd|pwd)['":\s]*[=:]\s*['"]?[^'"\s]{8,}['"]?'''
tags = ["password"]

[[rules]]
id = "connection-string"
description = "Database Connection String"
regex = '''(?i)(mongodb|postgres|mysql|redis|amqp):\/\/[^:]+:[^@]+@[^\s'"]+'''
tags = ["database", "connection"]

[[rules]]
id = "bearer-token"
description = "Bearer Token in Text"
regex = '''(?i)bearer\s+[a-zA-Z0-9_-]{20,}'''
tags = ["token", "auth"]
```

**Step 3: Verify existing Gitleaks tests still pass**

Run: `pytest tests/test_gitleaks.py -v`
Expected: All tests PASS (we only added rules, didn't change existing ones)

**Step 4: Commit**

```bash
git add lib/vibedom/config/gitleaks.toml
git commit -m "feat: expand gitleaks patterns for runtime DLP

Add 13 new secret detection patterns from upstream Gitleaks:
- AWS, Stripe, OpenAI, GitHub, Slack tokens
- Private keys, JWTs, bearer tokens
- Database connection strings, generic passwords

These patterns serve double duty: pre-flight scanning (Gitleaks binary)
and runtime HTTP scrubbing (Python DLP scrubber)."
```

---

### Task 2: Create DLP Scrubber Engine — Pattern Loading

**Files:**
- Create: `vm/dlp_scrubber.py`
- Create: `tests/test_dlp_scrubber.py`

**Context:** The scrubber is a standalone Python module with zero external dependencies. It loads secret patterns from `gitleaks.toml` and has built-in PII patterns. It runs inside the container as a module imported by the mitmproxy addon.

**Step 1: Write failing test for TOML pattern loading**

Create `tests/test_dlp_scrubber.py`:

```python
import tempfile
from pathlib import Path


def test_load_gitleaks_patterns():
    """Should load and compile regex patterns from gitleaks.toml."""
    from dlp_scrubber import DLPScrubber

    config_path = Path(__file__).parent.parent / 'lib' / 'vibedom' / 'config' / 'gitleaks.toml'
    scrubber = DLPScrubber(gitleaks_config=str(config_path))

    # Should have loaded secret patterns from TOML
    assert len(scrubber.secret_patterns) > 0

    # Each pattern should have required fields
    for p in scrubber.secret_patterns:
        assert p.id, "Pattern must have an ID"
        assert p.regex, "Pattern must have a compiled regex"
        assert p.placeholder, "Pattern must have a placeholder"


def test_load_from_missing_config():
    """Should work with no gitleaks config (PII patterns only)."""
    from dlp_scrubber import DLPScrubber

    scrubber = DLPScrubber(gitleaks_config=None)

    assert len(scrubber.secret_patterns) == 0
    assert len(scrubber.pii_patterns) > 0


def test_load_from_empty_config():
    """Should handle empty/minimal TOML config."""
    from dlp_scrubber import DLPScrubber

    with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
        f.write('title = "Empty"\n')
        f.flush()

        scrubber = DLPScrubber(gitleaks_config=f.name)
        assert len(scrubber.secret_patterns) == 0
```

**Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=vm pytest tests/test_dlp_scrubber.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dlp_scrubber'`

**Step 3: Implement pattern loading**

Create `vm/dlp_scrubber.py`:

```python
"""Lightweight DLP scrubber for secret and PII detection.

Loads secret patterns from gitleaks.toml (shared with pre-flight scanning)
and provides built-in PII patterns. Zero external dependencies.
"""

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


# Maximum text size to scrub (skip large binary-decoded content)
MAX_SCRUB_SIZE = 512_000  # 512KB


@dataclass
class Pattern:
    """A compiled detection pattern."""
    id: str
    description: str
    regex: re.Pattern
    category: str  # 'SECRET' or 'PII'
    placeholder: str


@dataclass
class Finding:
    """A detected secret or PII instance."""
    pattern_id: str
    category: str
    matched_text: str
    start: int
    end: int
    placeholder: str


@dataclass
class ScrubResult:
    """Result of scrubbing text."""
    text: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def was_scrubbed(self) -> bool:
        return len(self.findings) > 0


class DLPScrubber:
    """Scrubs secrets and PII from text using regex patterns."""

    def __init__(self, gitleaks_config: str | None = None):
        self.secret_patterns: list[Pattern] = []
        self.pii_patterns: list[Pattern] = []

        if gitleaks_config:
            self._load_gitleaks_patterns(gitleaks_config)
        self._load_pii_patterns()

    def _load_gitleaks_patterns(self, config_path: str) -> None:
        """Load secret patterns from gitleaks.toml."""
        path = Path(config_path)
        if not path.exists():
            return

        with open(path, 'rb') as f:
            config = tomllib.load(f)

        for rule in config.get('rules', []):
            rule_id = rule.get('id', 'unknown')
            try:
                compiled = re.compile(rule['regex'])
            except (re.error, KeyError):
                continue  # Skip invalid patterns

            placeholder_name = rule_id.upper().replace('-', '_')
            self.secret_patterns.append(Pattern(
                id=rule_id,
                description=rule.get('description', ''),
                regex=compiled,
                category='SECRET',
                placeholder=f'[REDACTED_{placeholder_name}]',
            ))

    def _load_pii_patterns(self) -> None:
        """Load built-in PII detection patterns."""
        pii_defs = [
            ('email', 'Email Address',
             r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'),
            ('credit_card', 'Credit Card Number',
             r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b'),
            ('us_ssn', 'US Social Security Number',
             r'\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b'),
            ('phone_us', 'US Phone Number',
             r'\b(?:\+?1[-.\s]?)?(?:\(?[2-9]\d{2}\)?[-.\s]?)[2-9]\d{2}[-.\s]?\d{4}\b'),
            ('ipv4_private', 'Private IPv4 Address',
             r'\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b'),
        ]

        for pattern_id, description, regex_str in pii_defs:
            self.pii_patterns.append(Pattern(
                id=pattern_id,
                description=description,
                regex=re.compile(regex_str),
                category='PII',
                placeholder=f'[REDACTED_{pattern_id.upper()}]',
            ))
```

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=vm pytest tests/test_dlp_scrubber.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add vm/dlp_scrubber.py tests/test_dlp_scrubber.py
git commit -m "feat: create DLP scrubber engine with pattern loading

- Loads secret patterns from gitleaks.toml (shared with pre-flight scan)
- Built-in PII patterns (email, credit card, SSN, phone, private IP)
- Zero external dependencies (Python stdlib only)
- Compiles patterns at startup for fast matching"
```

---

### Task 3: Implement Scrub Function

**Files:**
- Modify: `vm/dlp_scrubber.py`
- Modify: `tests/test_dlp_scrubber.py`

**Context:** The core `scrub()` method finds all pattern matches, replaces them right-to-left (to preserve character positions), and returns the scrubbed text plus a list of findings for audit logging.

**Step 1: Write failing tests for scrubbing**

Add to `tests/test_dlp_scrubber.py`:

```python
def make_scrubber():
    """Create scrubber with gitleaks patterns loaded."""
    from dlp_scrubber import DLPScrubber

    config_path = Path(__file__).parent.parent / 'lib' / 'vibedom' / 'config' / 'gitleaks.toml'
    return DLPScrubber(gitleaks_config=str(config_path))


def test_scrub_aws_key():
    """Should scrub AWS access key."""
    scrubber = make_scrubber()
    text = "aws_key = AKIAIOSFODNN7EXAMPLE"
    result = scrubber.scrub(text)

    assert "AKIAIOSFODNN7EXAMPLE" not in result.text
    assert result.was_scrubbed
    assert any(f.pattern_id == 'aws-access-key' for f in result.findings)


def test_scrub_stripe_key():
    """Should scrub Stripe API key."""
    scrubber = make_scrubber()
    text = '{"key": "sk_test_4eC39HqLyjWDarjtT1zdp7dc"}'
    result = scrubber.scrub(text)

    assert "sk_test_4eC39HqLyjWDarjtT1zdp7dc" not in result.text
    assert result.was_scrubbed


def test_scrub_email():
    """Should scrub email addresses."""
    scrubber = make_scrubber()
    text = "Contact: admin@company.com for help"
    result = scrubber.scrub(text)

    assert "admin@company.com" not in result.text
    assert "[REDACTED_EMAIL]" in result.text
    assert any(f.category == 'PII' for f in result.findings)


def test_scrub_private_key():
    """Should scrub private key headers."""
    scrubber = make_scrubber()
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow..."
    result = scrubber.scrub(text)

    assert "-----BEGIN RSA PRIVATE KEY-----" not in result.text
    assert result.was_scrubbed


def test_scrub_multiple_findings():
    """Should scrub multiple secrets in one text."""
    scrubber = make_scrubber()
    text = 'email=admin@corp.com&api_key=sk_live_abc123def456xyz789012345'
    result = scrubber.scrub(text)

    assert "admin@corp.com" not in result.text
    assert "sk_live_abc123def456xyz789012345" not in result.text
    assert len(result.findings) >= 2


def test_scrub_clean_text():
    """Should pass through clean text unchanged."""
    scrubber = make_scrubber()
    text = "Hello world, this is normal code: x = 42"
    result = scrubber.scrub(text)

    assert result.text == text
    assert not result.was_scrubbed
    assert len(result.findings) == 0


def test_scrub_preserves_json_structure():
    """Should preserve JSON structure after scrubbing."""
    import json
    scrubber = make_scrubber()

    original = json.dumps({
        "user": "admin@company.com",
        "message": "hello world",
        "count": 42
    })
    result = scrubber.scrub(original)

    parsed = json.loads(result.text)
    assert parsed["message"] == "hello world"
    assert parsed["count"] == 42
    assert "admin@company.com" not in parsed["user"]


def test_scrub_skips_oversized_text():
    """Should skip scrubbing for text exceeding size limit."""
    from dlp_scrubber import DLPScrubber, MAX_SCRUB_SIZE

    scrubber = make_scrubber()
    # Create text larger than MAX_SCRUB_SIZE
    text = "admin@company.com " * (MAX_SCRUB_SIZE // 10)
    result = scrubber.scrub(text)

    # Should return text unchanged (too large to scrub)
    assert result.text == text
    assert not result.was_scrubbed
```

**Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=vm pytest tests/test_dlp_scrubber.py::test_scrub_aws_key -v`
Expected: FAIL — `AttributeError: 'DLPScrubber' object has no attribute 'scrub'`

**Step 3: Implement the scrub method**

Add to `DLPScrubber` class in `vm/dlp_scrubber.py`:

```python
    def scrub(self, text: str) -> ScrubResult:
        """Scrub secrets and PII from text.

        Finds all matches, replaces right-to-left to preserve positions,
        and returns scrubbed text with audit trail of findings.

        Args:
            text: Text to scrub

        Returns:
            ScrubResult with scrubbed text and list of findings
        """
        if len(text) > MAX_SCRUB_SIZE:
            return ScrubResult(text=text)

        # Collect all matches across all patterns
        all_matches: list[tuple[int, int, Finding, Pattern]] = []

        for pattern in self.secret_patterns + self.pii_patterns:
            for match in pattern.regex.finditer(text):
                # Use first capturing group if present, else full match
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
                    start=start,
                    end=end,
                    placeholder=pattern.placeholder,
                )
                all_matches.append((start, end, finding, pattern))

        if not all_matches:
            return ScrubResult(text=text)

        # Sort by start position descending (replace right-to-left)
        all_matches.sort(key=lambda m: m[0], reverse=True)

        # Remove overlapping matches (keep longest / leftmost)
        filtered: list[tuple[int, int, Finding, Pattern]] = []
        min_start = len(text)
        for start, end, finding, pattern in all_matches:
            if end <= min_start:
                filtered.append((start, end, finding, pattern))
                min_start = start

        # Replace right-to-left
        scrubbed = text
        findings = []
        for start, end, finding, pattern in filtered:
            scrubbed = scrubbed[:start] + pattern.placeholder + scrubbed[end:]
            findings.append(finding)

        # Reverse findings so they're in left-to-right order
        findings.reverse()

        return ScrubResult(text=scrubbed, findings=findings)
```

**Step 4: Run all tests to verify they pass**

Run: `PYTHONPATH=vm pytest tests/test_dlp_scrubber.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add vm/dlp_scrubber.py tests/test_dlp_scrubber.py
git commit -m "feat: implement scrub function with right-to-left replacement

- Finds all secret and PII matches across all patterns
- Replaces right-to-left to preserve character positions
- Handles overlapping matches (keeps longest)
- Skips oversized text (>512KB) for performance
- Returns audit trail of all findings
- Preserves JSON structure after scrubbing"
```

---

### Task 4: Integrate Scrubber into Mitmproxy Addon — Request Bodies

**Files:**
- Modify: `vm/mitmproxy_addon.py`
- Modify: `lib/vibedom/vm.py`

**Context:** The mitmproxy addon needs to import the scrubber, initialize it at startup, and scrub outbound request bodies. Only text-based content is scrubbed (skip binary). The scrubber module and gitleaks.toml must be copied to the config directory so they're available inside the container.

**Step 1: Update vm.py to copy scrubber and gitleaks config**

Read: `lib/vibedom/vm.py` — find the `shutil.copy` line for `mitmproxy_addon.py` (around line 31-33).

Add after the existing addon copy:

```python
        # Copy DLP scrubber module to config dir
        scrubber_src = Path(__file__).parent.parent.parent / 'vm' / 'dlp_scrubber.py'
        scrubber_dst = self.config_dir / 'dlp_scrubber.py'
        shutil.copy(scrubber_src, scrubber_dst)

        # Copy gitleaks config for runtime DLP patterns
        gitleaks_src = Path(__file__).parent / 'config' / 'gitleaks.toml'
        gitleaks_dst = self.config_dir / 'gitleaks.toml'
        shutil.copy(gitleaks_src, gitleaks_dst)
```

**Step 2: Modify mitmproxy addon to import and use scrubber**

Modify `vm/mitmproxy_addon.py`:

```python
"""Mitmproxy addon for enforcing whitelist and DLP scrubbing."""

import json
import sys
from pathlib import Path
from mitmproxy import http

# Import DLP scrubber (copied alongside this file to /mnt/config/)
sys.path.insert(0, str(Path(__file__).parent))
from dlp_scrubber import DLPScrubber

# Content types safe to scrub (text-based)
SCRUBBABLE_CONTENT_TYPES = (
    'text/',
    'application/json',
    'application/x-www-form-urlencoded',
    'application/xml',
    'application/javascript',
)


class VibedomProxy:
    """Mitmproxy addon for vibedom sandbox."""

    def __init__(self):
        self.whitelist = self.load_whitelist()
        self.network_log_path = Path('/var/log/vibedom/network.jsonl')
        self.network_log_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize DLP scrubber
        gitleaks_config = Path(__file__).parent / 'gitleaks.toml'
        config_path = str(gitleaks_config) if gitleaks_config.exists() else None
        self.scrubber = DLPScrubber(gitleaks_config=config_path)

    def load_whitelist(self) -> set:
        """Load whitelist from mounted config."""
        whitelist_path = Path('/mnt/config/trusted_domains.txt')
        if not whitelist_path.exists():
            return set()

        domains = set()
        with open(whitelist_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    domains.add(line.lower())
        return domains

    def is_allowed(self, domain: str) -> bool:
        """Check if domain is whitelisted."""
        domain = domain.lower()

        if domain in self.whitelist:
            return True

        parts = domain.split('.')
        for i in range(len(parts)):
            parent = '.'.join(parts[i:])
            if parent in self.whitelist:
                return True

        return False

    def _is_scrubbable(self, content_type: str | None) -> bool:
        """Check if content type is text-based and safe to scrub."""
        if not content_type:
            return False
        return any(content_type.startswith(ct) for ct in SCRUBBABLE_CONTENT_TYPES)

    def _scrub_body(self, content: bytes, content_type: str | None) -> tuple[bytes, list]:
        """Scrub request/response body if text-based.

        Returns:
            Tuple of (possibly-scrubbed content, list of findings)
        """
        if not content or not self._is_scrubbable(content_type):
            return content, []

        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            return content, []

        result = self.scrubber.scrub(text)
        if result.was_scrubbed:
            return result.text.encode('utf-8'), result.findings
        return content, []

    def request(self, flow: http.HTTPFlow) -> None:
        """Intercept, scrub, and filter requests."""
        domain = flow.request.host_header or flow.request.host

        # Scrub request body before forwarding
        scrubbed_findings = []
        if flow.request.content:
            content_type = flow.request.headers.get('Content-Type', '')
            scrubbed_content, findings = self._scrub_body(
                flow.request.content, content_type
            )
            if findings:
                flow.request.content = scrubbed_content
                scrubbed_findings = findings

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

    def log_request(self, flow: http.HTTPFlow, allowed: bool,
                    scrubbed: list | None = None) -> None:
        """Log network request with optional scrubbing details."""
        entry = {
            'method': flow.request.method,
            'url': flow.request.pretty_url,
            'host': flow.request.host_header or flow.request.host,
            'allowed': allowed,
        }

        if scrubbed:
            entry['scrubbed'] = [
                {
                    'pattern': f.pattern_id,
                    'category': f.category,
                    'original': f.matched_text,
                    'replaced_with': f.placeholder,
                }
                for f in scrubbed
            ]

        try:
            with open(self.network_log_path, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except OSError as e:
            print(f"Warning: Failed to log request: {e}", file=sys.stderr)


addons = [VibedomProxy()]
```

**Step 3: Run existing proxy tests to check for regressions**

Run: `pytest tests/test_proxy.py tests/test_whitelist.py -v`
Expected: PASS (no regressions — whitelist logic unchanged)

**Step 4: Commit**

```bash
git add vm/mitmproxy_addon.py lib/vibedom/vm.py
git commit -m "feat: integrate DLP scrubber into mitmproxy addon

- Scrub outbound request bodies for secrets and PII
- Only scrub text-based content (skip binary via Content-Type check)
- Log scrubbed findings to network.jsonl audit trail
- Copy scrubber module and gitleaks.toml to container config
- Requests are scrubbed, not blocked (agent flow continues)"
```

---

### Task 5: Add Response and Header Scrubbing

**Files:**
- Modify: `vm/mitmproxy_addon.py`
- Modify: `tests/test_dlp_scrubber.py`

**Context:** Scrubbing only requests is incomplete. An agent can learn secrets from API responses and exfiltrate them later. Headers (Authorization, Cookie) also carry sensitive data. This task adds both.

**Step 1: Write failing test for header scrubbing**

Add to `tests/test_dlp_scrubber.py`:

```python
def test_scrub_authorization_header():
    """Should scrub bearer tokens in headers."""
    scrubber = make_scrubber()
    text = "Bearer sk_test_4eC39HqLyjWDarjtT1zdp7dc"
    result = scrubber.scrub(text)

    assert "sk_test_4eC39HqLyjWDarjtT1zdp7dc" not in result.text
    assert result.was_scrubbed


def test_scrub_jwt_token():
    """Should scrub JWT tokens."""
    scrubber = make_scrubber()
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    text = f"Authorization: Bearer {jwt}"
    result = scrubber.scrub(text)

    assert jwt not in result.text
    assert result.was_scrubbed
```

**Step 2: Run test to verify it passes (JWT pattern already added in Task 1)**

Run: `PYTHONPATH=vm pytest tests/test_dlp_scrubber.py::test_scrub_jwt_token -v`
Expected: PASS (jwt-token pattern already in gitleaks.toml)

**Step 3: Add response hook and header scrubbing to addon**

Add to `VibedomProxy` class in `vm/mitmproxy_addon.py`:

```python
    def _scrub_headers(self, headers) -> list:
        """Scrub sensitive values from headers.

        Only scrubs header values, not names. Only checks headers
        likely to contain secrets.
        """
        sensitive_headers = {
            'authorization', 'cookie', 'set-cookie',
            'x-api-key', 'x-auth-token', 'proxy-authorization',
        }

        all_findings = []
        for name in list(headers.keys()):
            if name.lower() in sensitive_headers:
                result = self.scrubber.scrub(headers[name])
                if result.was_scrubbed:
                    headers[name] = result.text
                    all_findings.extend(result.findings)
        return all_findings

    def response(self, flow: http.HTTPFlow) -> None:
        """Scrub secrets from response bodies."""
        if not flow.response or not flow.response.content:
            return

        content_type = flow.response.headers.get('Content-Type', '')
        scrubbed_content, findings = self._scrub_body(
            flow.response.content, content_type
        )
        if findings:
            flow.response.content = scrubbed_content
```

Update the existing `request()` method to also scrub headers. Add before the body scrubbing:

```python
        # Scrub sensitive headers
        header_findings = self._scrub_headers(flow.request.headers)
        scrubbed_findings.extend(header_findings)
```

**Step 4: Run all tests**

Run: `PYTHONPATH=vm pytest tests/test_dlp_scrubber.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add vm/mitmproxy_addon.py tests/test_dlp_scrubber.py
git commit -m "feat: add response body and header scrubbing

- Scrub response bodies to prevent agent learning secrets from APIs
- Scrub sensitive headers (Authorization, Cookie, X-Api-Key, etc.)
- Only scrub header values, not header names
- Response scrubbing uses same content-type check as requests"
```

---

### Task 6: Add Edge Case Tests

**Files:**
- Modify: `tests/test_dlp_scrubber.py`

**Context:** Verify the scrubber handles edge cases correctly: binary content, Unicode, overlapping patterns, connection strings, and the full range of secret types.

**Step 1: Write edge case tests**

Add to `tests/test_dlp_scrubber.py`:

```python
def test_scrub_connection_string():
    """Should scrub database connection strings."""
    scrubber = make_scrubber()
    text = 'DATABASE_URL=postgres://admin:s3cret@db.internal.com:5432/mydb'
    result = scrubber.scrub(text)

    assert "admin:s3cret@db.internal.com" not in result.text
    assert result.was_scrubbed


def test_scrub_github_token():
    """Should scrub GitHub personal access tokens."""
    scrubber = make_scrubber()
    text = "GITHUB_TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"
    result = scrubber.scrub(text)

    assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in result.text
    assert result.was_scrubbed


def test_scrub_credit_card():
    """Should scrub credit card numbers."""
    scrubber = make_scrubber()
    text = "Card: 4111111111111111"
    result = scrubber.scrub(text)

    assert "4111111111111111" not in result.text
    assert "[REDACTED_CREDIT_CARD]" in result.text


def test_scrub_us_ssn():
    """Should scrub US Social Security numbers."""
    scrubber = make_scrubber()
    text = "SSN: 123-45-6789"
    result = scrubber.scrub(text)

    assert "123-45-6789" not in result.text
    assert "[REDACTED_US_SSN]" in result.text


def test_scrub_openai_key():
    """Should scrub OpenAI API keys."""
    scrubber = make_scrubber()
    text = "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwx"
    result = scrubber.scrub(text)

    assert "sk-proj-abcdefghijklmnopqrstuvwx" not in result.text
    assert result.was_scrubbed


def test_no_scrub_binary_like_text():
    """Scrubber should handle non-UTF-8 gracefully via caller."""
    # The addon checks Content-Type before calling scrub().
    # The scrubber itself only receives decoded text.
    # This test verifies scrub() handles unusual but valid text.
    scrubber = make_scrubber()
    text = "PK\x03\x04 binary-ish but decoded"
    result = scrubber.scrub(text)
    # Should not crash
    assert result.text is not None


def test_scrub_form_data():
    """Should scrub URL-encoded form data."""
    scrubber = make_scrubber()
    text = "username=admin&password=SuperSecret123!&email=admin@corp.com"
    result = scrubber.scrub(text)

    assert "admin@corp.com" not in result.text
    assert result.was_scrubbed


def test_scrub_private_ip():
    """Should scrub private IP addresses."""
    scrubber = make_scrubber()
    text = "server=192.168.1.100 port=5432"
    result = scrubber.scrub(text)

    assert "192.168.1.100" not in result.text
    assert "[REDACTED_IPV4_PRIVATE]" in result.text


def test_no_false_positive_version_numbers():
    """Version numbers should NOT be detected as IPs."""
    scrubber = make_scrubber()
    # Only private IPs are matched (10.x, 172.16-31.x, 192.168.x)
    text = "version 3.11.4 released"
    result = scrubber.scrub(text)

    assert result.text == text
    assert not result.was_scrubbed
```

**Step 2: Run all tests**

Run: `PYTHONPATH=vm pytest tests/test_dlp_scrubber.py -v`
Expected: All tests PASS. If any fail, adjust patterns in `gitleaks.toml` or `_load_pii_patterns()` to fix detection or false positives.

**Step 3: Commit**

```bash
git add tests/test_dlp_scrubber.py
git commit -m "test: add comprehensive edge case tests for DLP scrubber

- Connection strings, GitHub tokens, OpenAI keys
- Credit cards, SSNs, private IPs
- Form data scrubbing
- False positive avoidance (version numbers vs IPs)
- Binary-like text handling"
```

---

### Task 7: Update Documentation

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/USAGE.md`
- Modify: `CLAUDE.md`

**Step 1: Update ARCHITECTURE.md**

Replace the "Future: Phase 2" section and update the Network Layer and Security Layer descriptions:

Update Network Layer:
```markdown
### Network Layer
- mitmproxy in explicit proxy mode (HTTP_PROXY/HTTPS_PROXY)
- Custom addon for whitelist enforcement and DLP scrubbing
- Structured logging to network.jsonl (includes scrubbing audit trail)
```

Update Security Layer:
```markdown
### Security Layer
- Gitleaks pre-flight scanning (secrets in workspace files)
- DLP runtime scrubbing (secrets and PII in HTTP traffic)
- SSH deploy keys (not personal keys)
- Session audit logs
```

Replace "Future: Phase 2" with:
```markdown
## DLP (Data Loss Prevention)

Real-time scrubbing of secrets and PII from HTTP traffic.

### Two Enforcement Points

```
Pre-flight (before VM):    Gitleaks binary → scans workspace files
Runtime (inside VM):       DLP scrubber → scrubs HTTP traffic
                           ↑ Same gitleaks.toml patterns
```

### What Gets Scrubbed

**Secrets** (patterns from `lib/vibedom/config/gitleaks.toml`):
- API keys (AWS, Stripe, OpenAI, GitHub, GitLab, Slack)
- Database connection strings and passwords
- Private keys, JWTs, bearer tokens

**PII** (built-in patterns):
- Email addresses, credit card numbers
- US Social Security numbers, phone numbers
- Private IP addresses

### How It Works

1. Agent makes HTTP request with body containing secrets
2. Mitmproxy addon scrubs request body, response body, and sensitive headers
3. Secrets replaced with `[REDACTED_PATTERN_NAME]` placeholders
4. Request forwarded with scrubbed content (agent flow uninterrupted)
5. All scrubbed findings logged to `network.jsonl` for audit

### Design Decisions

- **Scrub, don't block**: Agent workflow continues uninterrupted
- **No Presidio**: Custom regex is lighter (0 deps vs 150-500MB) and catches API keys which Presidio cannot
- **Shared patterns**: gitleaks.toml serves both pre-flight and runtime detection
- **Content-type aware**: Only scrubs text content (skips binary)
- **Size-limited**: Skips bodies >512KB for performance

## Future Enhancements

- Context-aware rules (internal vs external traffic)
- High-severity real-time alerting
- Metrics and dashboards
```

**Step 2: Add DLP section to USAGE.md**

Add after the Network Whitelisting section:

```markdown
## Data Loss Prevention (DLP)

Vibedom automatically scrubs secrets and PII from HTTP traffic to prevent data exfiltration.

### What Gets Scrubbed

| Category | Examples | Replaced With |
|----------|----------|---------------|
| AWS Keys | `AKIAIOSFODNN7EXAMPLE` | `[REDACTED_AWS_ACCESS_KEY]` |
| API Keys | `sk_test_...`, `sk-proj-...` | `[REDACTED_STRIPE_API_KEY]` etc. |
| Tokens | `ghp_...`, `glpat-...` | `[REDACTED_GITHUB_PAT]` etc. |
| Passwords | `password=secret123` | `[REDACTED_GENERIC_PASSWORD]` |
| Private Keys | `-----BEGIN RSA PRIVATE KEY-----` | `[REDACTED_PRIVATE_KEY]` |
| Emails | `user@company.com` | `[REDACTED_EMAIL]` |
| Credit Cards | `4111111111111111` | `[REDACTED_CREDIT_CARD]` |

### How It Works

- Requests are **scrubbed, not blocked** — the agent continues working normally
- Only text-based content is scrubbed (JSON, form data, plain text)
- Binary content (images, archives) passes through unchanged
- All scrubbed items are logged for audit

### Viewing Scrubbed Activity

```bash
# View all requests where scrubbing occurred
cat ~/.vibedom/logs/session-*/network.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    entry = json.loads(line)
    if 'scrubbed' in entry:
        print(json.dumps(entry, indent=2))
"
```

### Adding Custom Secret Patterns

Edit `lib/vibedom/config/gitleaks.toml` to add patterns. The same file is used for both pre-flight scanning (Gitleaks) and runtime scrubbing (DLP):

```toml
[[rules]]
id = "my-internal-token"
description = "Internal Service Token"
regex = '''myco_token_[a-zA-Z0-9]{32}'''
tags = ["internal", "token"]
```
```

**Step 3: Update CLAUDE.md**

Find the "Phase 2" roadmap section and update it since DLP is now implemented:

```markdown
### Phase 2: DLP and Monitoring (Current)

- **DLP scrubbing**: Real-time secret and PII scrubbing in HTTP traffic
- **Shared patterns**: gitleaks.toml serves pre-flight scan + runtime DLP
- **Audit logging**: Scrubbed findings logged to network.jsonl
```

Add to the Architecture / Network Control section:
```markdown
- DLP scrubber for secret and PII detection in HTTP traffic
```

**Step 4: Commit**

```bash
git add docs/ARCHITECTURE.md docs/USAGE.md CLAUDE.md
git commit -m "docs: add DLP architecture and usage documentation

- Document two-enforcement-point design (pre-flight + runtime)
- Add scrubbing table with examples and placeholders
- Explain how to add custom patterns via gitleaks.toml
- Document audit log viewing
- Update Phase 2 roadmap status"
```

---

### Task 8: Manual Testing and Validation

**Files:**
- N/A (manual testing)
- Modify: `docs/TESTING.md` (document results)

**Step 1: Build VM image**

```bash
cd /Users/tim/Documents/projects/vibedom
./vm/build.sh
```

Expected: Image builds successfully

**Step 2: Run comprehensive DLP tests**

```bash
# Create test workspace
mkdir -p ~/test-dlp-vibedom
echo "print('hello')" > ~/test-dlp-vibedom/app.py

# Start vibedom
vibedom run ~/test-dlp-vibedom

CONTAINER=$(docker ps --filter "name=vibedom-test-dlp" --format "{{.Names}}")

# Test 1: Secret scrubbing (Stripe key in POST body)
echo "=== Test 1: Secret Scrubbing ==="
docker exec $CONTAINER curl -s -X POST https://httpbin.org/post \
  -d 'key=sk_test_4eC39HqLyjWDarjtT1zdp7dc'
# Expected: httpbin echoes back scrubbed content (REDACTED placeholder)

# Test 2: Email scrubbing
echo "=== Test 2: Email Scrubbing ==="
docker exec $CONTAINER curl -s -X POST https://httpbin.org/post \
  -H 'Content-Type: application/json' \
  -d '{"email":"secret@company.com","msg":"hello"}'
# Expected: email replaced with [REDACTED_EMAIL]

# Test 3: Clean content passes through
echo "=== Test 3: Clean Content ==="
docker exec $CONTAINER curl -s -X POST https://httpbin.org/post \
  -d 'message=hello+world'
# Expected: Content unchanged

# Test 4: Binary content not scrubbed
echo "=== Test 4: Binary Skipped ==="
docker exec $CONTAINER curl -s -X POST https://httpbin.org/post \
  -H 'Content-Type: application/octet-stream' \
  -d 'key=sk_test_4eC39HqLyjWDarjtT1zdp7dc'
# Expected: Content unchanged (binary content type)

# Test 5: Check audit logs
echo "=== Test 5: Audit Logs ==="
docker exec $CONTAINER cat /var/log/vibedom/network.jsonl
# Expected: Entries with "scrubbed" field showing what was detected

# Cleanup
vibedom stop ~/test-dlp-vibedom
rm -rf ~/test-dlp-vibedom
```

**Step 3: Document results in TESTING.md**

Add a "DLP Scrubbing" section to `docs/TESTING.md` with actual test results.

**Step 4: Commit**

```bash
git add docs/TESTING.md
git commit -m "test: validate DLP scrubbing end-to-end

Manual testing confirms:
- Secret patterns detected and scrubbed (API keys, tokens)
- PII patterns detected and scrubbed (emails)
- Clean content passes through unchanged
- Binary content skipped (Content-Type check works)
- Audit logs capture scrubbed findings
- Agent workflow not interrupted (requests succeed)"
```

---

## Summary

**Implementation effort:** 3-4 hours (8 tasks)

**Tasks breakdown:**
1. Expand gitleaks.toml secret patterns (15 min)
2. Create scrubber engine — pattern loading (30 min)
3. Implement scrub function (45 min)
4. Integrate into mitmproxy addon — request bodies (30 min)
5. Add response and header scrubbing (30 min)
6. Edge case tests (20 min)
7. Documentation (20 min)
8. Manual testing and validation (30 min)

**Key design decisions:**
- **No Presidio**: Custom regex scrubber — zero deps, catches API keys (Presidio can't), smaller container
- **Shared patterns**: `gitleaks.toml` serves pre-flight scan (Gitleaks binary) AND runtime scrubbing (Python DLP)
- **Scrub, don't block**: Agent workflow continues uninterrupted
- **Content-type aware**: Only scrubs text content, skips binary
- **Size-limited**: Skips bodies >512KB for performance
- **Three scrub points**: Request bodies, response bodies, sensitive headers
- **Audit trail**: All scrubbed findings logged to `network.jsonl`

**What gets detected:**
- ✅ API keys (AWS, Stripe, OpenAI, GitHub, GitLab, Slack) — from gitleaks.toml
- ✅ Database credentials (connection strings, passwords) — from gitleaks.toml
- ✅ Private keys, JWTs, bearer tokens — from gitleaks.toml
- ✅ Email, credit card, SSN, phone, private IP — built-in PII patterns
- ❌ Person names, organizations (would need NER/ML — accept this gap)

**Dependencies added:** None (Python stdlib `re` + `tomllib`)
**Container size impact:** ~0 bytes (just two small .py files + expanded .toml)
