"""Regression guards for the container Dockerfiles.

These are content assertions (no Docker required) protecting invariants that
have bitten us: notably that login shells keep /root/.local/bin on PATH after
/etc/profile resets it.
"""

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
