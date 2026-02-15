"""Lightweight DLP scrubber for secret and PII detection.

Loads secret patterns from gitleaks.toml (shared with pre-flight scanning)
and provides built-in PII patterns. Zero external dependencies.
"""

import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


# Maximum text size to scrub (skip large binary-decoded content)
MAX_SCRUB_SIZE = 512_000  # 512KB

# Chunking settings for large files
CHUNK_SIZE = 512_000  # 512KB chunks
OVERLAP = 2000  # 2KB overlap to catch secrets at boundaries


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
        self.warnings: list[str] = []

        if gitleaks_config:
            self._load_gitleaks_patterns(gitleaks_config)
        self._load_pii_patterns()

        if self.warnings:
            print(f"WARNING: DLP scrubber had {len(self.warnings)} issue(s):", file=sys.stderr)
            for warning in self.warnings:
                print(f"  - {warning}", file=sys.stderr)

    def _load_gitleaks_patterns(self, config_path: str) -> None:
        """Load secret patterns from gitleaks.toml."""
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
        if not text:
            return ScrubResult(text=text)

        # Process in chunks for large files
        if len(text) > MAX_SCRUB_SIZE:
            return self._scrub_large_text(text)

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

    def _scrub_large_text(self, text: str) -> ScrubResult:
        """Scrub large text by processing in chunks with overlap."""
        all_findings: list[Finding] = []
        offset = 0

        while offset < len(text):
            chunk = text[offset:offset + CHUNK_SIZE + OVERLAP]
            result = self._scrub_chunk(chunk, offset)
            all_findings.extend(result.findings)
            offset += CHUNK_SIZE

        # Deduplicate findings (secrets in overlapping chunks)
        unique_findings = self._deduplicate_findings(all_findings)

        if not unique_findings:
            return ScrubResult(text=text)

        # Sort findings by start position descending for replacement
        unique_findings.sort(key=lambda f: f.start, reverse=True)

        # Replace right-to-left to preserve positions
        scrubbed = text
        for finding in unique_findings:
            scrubbed = (
                scrubbed[:finding.start] +
                finding.placeholder +
                scrubbed[finding.end:]
            )

        # Reverse findings so they're in left-to-right order
        unique_findings.reverse()

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
                    start=start + offset,
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
