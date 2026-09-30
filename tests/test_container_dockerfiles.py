"""Regression guards for the container Dockerfiles.

These are content assertions (no Docker required) protecting invariants that
have bitten us: notably that login shells keep /root/.local/bin on PATH after
/etc/profile resets it.
"""

import re
from pathlib import Path

import pytest

CONTAINER_DIR = Path(__file__).resolve().parent.parent / 'lib' / 'vibedom' / 'container'


@pytest.mark.parametrize('dockerfile', ['Dockerfile.alpine', 'Dockerfile.layer'])
def test_login_shells_keep_local_bin_on_path(dockerfile):
    """Both images must re-add /root/.local/bin via /etc/profile.d.

    `bash --login` (used by `vibedom shell` and `attach`) sources /etc/profile,
    which resets PATH and drops the `ENV PATH=/root/.local/bin:...` line — so
    `claude` vanishes from login shells unless a profile.d script puts it back.
    Dockerfile.alpine has always done this; Dockerfile.layer regressed by
    omitting it.
    """
    text = (CONTAINER_DIR / dockerfile).read_text()
    assert '/etc/profile.d/local-bin.sh' in text, (
        f"{dockerfile} must write /etc/profile.d/local-bin.sh so login shells "
        f"keep /root/.local/bin on PATH"
    )
    assert '/root/.local/bin' in text


LAYER = CONTAINER_DIR / 'Dockerfile.layer'


def _layer_lines(marker: str) -> str:
    """Return the Dockerfile.layer line containing ``marker`` (exactly one)."""
    lines = [line for line in LAYER.read_text().splitlines() if marker in line]
    assert len(lines) == 1, f"expected one line containing {marker!r}, got {lines}"
    return lines[0]


def test_layer_switches_to_root_before_installing():
    """Base images may set a non-root USER (node, many app images); package
    installs and the /root/... paths need root."""
    text = LAYER.read_text()
    assert re.search(r'^USER root$', text, re.MULTILINE)
    assert text.index('USER root') < text.index('apt-get')


def test_layer_detects_package_manager_explicitly():
    """`apt ... || apk ...` hides the real apt error behind 'apk: not found'."""
    text = LAYER.read_text()
    assert 'command -v apt-get' in text
    assert 'command -v apk' in text
    assert '2>/dev/null) ||' not in text


@pytest.mark.parametrize('package', ['openssh-client', 'ripgrep'])
def test_layer_apt_branch_installs(package):
    """startup.sh needs ssh-agent/ssh-add; USE_BUILTIN_RIPGREP=0 needs rg."""
    assert package in _layer_lines('apt-get install')


def test_layer_apk_branch_installs_openssh_client():
    """Same ssh-agent requirement on Alpine base images (e.g. php:*-alpine)."""
    assert 'openssh-client' in _layer_lines('apk add --no-cache git')


def test_layer_apt_is_noninteractive():
    assert 'DEBIAN_FRONTEND=noninteractive' in LAYER.read_text()
