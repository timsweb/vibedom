"""startup.sh must run under any POSIX /bin/sh, not just busybox ash.

On Debian/Ubuntu base images /bin/sh is dash, which is stricter than busybox:
it rejects `trap ... SIGTERM` ("bad trap"), and under `set -e` that kills the
script before the container signals readiness.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

STARTUP_SH = (
    Path(__file__).resolve().parent.parent
    / 'lib' / 'vibedom' / 'container' / 'startup.sh'
)

DASH = shutil.which('dash')
needs_dash = pytest.mark.skipif(DASH is None, reason='dash not installed')


def _trap_lines() -> list[str]:
    lines = [line.strip() for line in STARTUP_SH.read_text().splitlines()]
    return [line for line in lines if re.match(r'^trap\s', line)]


def test_startup_installs_a_signal_trap():
    assert _trap_lines(), 'startup.sh should trap TERM to persist Claude config'


@needs_dash
def test_startup_parses_under_dash():
    result = subprocess.run([DASH, '-n', str(STARTUP_SH)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@needs_dash
@pytest.mark.parametrize('trap_line', _trap_lines())
def test_traps_install_under_dash_errexit(trap_line):
    result = subprocess.run(
        [DASH, '-ec', f'{trap_line}\necho installed'],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert 'installed' in result.stdout
