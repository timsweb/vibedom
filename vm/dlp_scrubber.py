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

    def scrub(self, text: str) -> ScrubResult:
        """Scrub secrets and PII from text.

        Finds all matches, replaces right-to-left to preserve positions,
        and returns scrubbed text with audit trail of findings.
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

        # Remove overlapping matches (keep rightmost non-overlapping)
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
