"""Domain whitelist management for network filtering."""

import shutil
from pathlib import Path
from typing import Set

# Path to default whitelist template
DEFAULT_WHITELIST = Path(__file__).parent / 'config' / 'default_whitelist.txt'

def load_whitelist(whitelist_path: Path) -> Set[str]:
    """Load whitelist from file.

    Args:
        whitelist_path: Path to whitelist file

    Returns:
        Set of allowed domains
    """
    if not whitelist_path.exists():
        return set()

    domains = set()
    with open(whitelist_path) as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if line and not line.startswith('#'):
                domains.add(line.lower())

    return domains

def is_domain_allowed(domain: str, whitelist: Set[str]) -> bool:
    """Check if a domain is allowed.

    Supports exact match or subdomain match.

    Args:
        domain: Domain to check (e.g., 'api.github.com')
        whitelist: Set of allowed domains

    Returns:
        True if allowed, False otherwise
    """
    domain = domain.lower()

    # Exact match
    if domain in whitelist:
        return True

    # Check if any whitelisted domain is a parent
    # e.g., 'api.github.com' matches if 'github.com' is whitelisted
    parts = domain.split('.')
    for i in range(len(parts)):
        parent = '.'.join(parts[i:])
        if parent in whitelist:
            return True

    return False

def create_default_whitelist(config_dir: Path) -> Path:
    """Create default whitelist file in config directory.

    Args:
        config_dir: Directory to create whitelist in

    Returns:
        Path to created whitelist file
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    whitelist_path = config_dir / 'trusted_domains.txt'

    if not whitelist_path.exists():
        shutil.copy(DEFAULT_WHITELIST, whitelist_path)

    return whitelist_path
