"""Parse vibedom.yml project configuration."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

KNOWN_FIELDS = {'base_image', 'network'}


@dataclass
class ProjectConfig:
    """Project-specific vibedom configuration from vibedom.yml."""
    base_image: Optional[str] = None
    network: Optional[str] = None

    @classmethod
    def load(cls, workspace: Path) -> Optional['ProjectConfig']:
        """Load vibedom.yml from workspace root. Returns None if not present."""
        config_file = workspace / 'vibedom.yml'
        if not config_file.exists():
            return None

        with open(config_file, encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}

        unknown = set(data.keys()) - KNOWN_FIELDS
        if unknown:
            raise ValueError(f"Unknown vibedom.yml field(s): {', '.join(sorted(unknown))}")

        return cls(
            base_image=data.get('base_image'),
            network=data.get('network'),
        )
