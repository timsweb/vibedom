"""Parse vibedom.yml project configuration."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

KNOWN_FIELDS = {
    'base_image', 'network', 'host_aliases', 'setup',
    'sync_exclude', 'memory', 'env', 'mounts',
}


@dataclass(frozen=True)
class Mount:
    """A normalized bind mount: host_path -> /work/<name>, optionally read-only."""
    host_path: Path
    name: str
    read_only: bool = False


def _parse_mounts(raw, base_dir: Path) -> Optional[list['Mount']]:
    """Normalize the raw `mounts:` value into a list of Mount, or None if absent.

    Scalar entries mount read-write at /work/<basename>. Mapping entries take
    `path` (required), optional `as` (subdir name), and optional `ro` (bool).
    Relative paths (including '.') resolve against base_dir (the vibedom.yml dir).
    """
    if raw is None:
        return None

    mounts = []
    seen = set()
    for entry in raw:
        if isinstance(entry, str):
            host, name, read_only = entry, None, False
        elif isinstance(entry, dict):
            if 'path' not in entry:
                raise ValueError(f"mounts entry missing 'path': {entry!r}")
            host = entry['path']
            name = entry.get('as')
            read_only = bool(entry.get('ro', False))
        else:
            raise ValueError(f"Invalid mounts entry: {entry!r}")

        host_path = Path(str(host)).expanduser()
        if not host_path.is_absolute():
            host_path = base_dir / host_path
        host_path = host_path.resolve()

        if name is None:
            name = host_path.name
        if name in seen:
            raise ValueError(
                f"Duplicate mount name '{name}' — use 'as:' to disambiguate"
            )
        seen.add(name)

        mounts.append(Mount(host_path=host_path, name=name, read_only=read_only))
    return mounts


@dataclass
class ProjectConfig:
    """Project-specific vibedom configuration from vibedom.yml."""
    base_image: Optional[str] = None
    network: Optional[str] = None
    host_aliases: Optional[dict] = None
    setup: Optional[list] = None
    sync_exclude: Optional[list] = None
    memory: Optional[str] = None
    env: Optional[dict] = None
    mounts: Optional[list[Mount]] = None

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
            host_aliases=data.get('host_aliases'),
            setup=data.get('setup'),
            sync_exclude=data.get('sync_exclude'),
            memory=data.get('memory'),
            env=data.get('env'),
            mounts=_parse_mounts(data.get('mounts'), workspace.resolve()),
        )
