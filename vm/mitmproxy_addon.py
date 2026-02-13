"""Mitmproxy addon for enforcing whitelist and logging."""

import json
from pathlib import Path
from mitmproxy import http

class VibedomProxy:
    """Mitmproxy addon for vibedom sandbox."""

    def __init__(self):
        self.whitelist = self.load_whitelist()
        self.network_log_path = Path('/var/log/vibedom/network.jsonl')
        self.network_log_path.parent.mkdir(parents=True, exist_ok=True)

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

        # Exact match
        if domain in self.whitelist:
            return True

        # Parent domain match
        parts = domain.split('.')
        for i in range(len(parts)):
            parent = '.'.join(parts[i:])
            if parent in self.whitelist:
                return True

        return False

    def request(self, flow: http.HTTPFlow) -> None:
        """Intercept and filter requests."""
        # Use Host header if available (more reliable than flow.request.host which may be IP)
        domain = flow.request.host_header or flow.request.host

        # Log request
        self.log_request(flow, allowed=self.is_allowed(domain))

        # Block if not whitelisted
        if not self.is_allowed(domain):
            flow.response = http.Response.make(
                403,
                b"Domain not whitelisted by vibedom",
                {"Content-Type": "text/plain"}
            )

    def log_request(self, flow: http.HTTPFlow, allowed: bool) -> None:
        """Log network request."""
        entry = {
            'method': flow.request.method,
            'url': flow.request.pretty_url,
            'host': flow.request.host_header or flow.request.host,
            'allowed': allowed
        }

        with open(self.network_log_path, 'a') as f:
            f.write(json.dumps(entry) + '\n')

addons = [VibedomProxy()]
