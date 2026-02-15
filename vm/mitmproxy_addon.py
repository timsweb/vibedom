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
