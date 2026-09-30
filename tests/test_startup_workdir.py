"""startup.sh init_repo: projects are bind-mounted under /work, so the only job
left is to cd there. No clone, no git init, no VIBEDOM_LIVE branch."""

import re
import subprocess
from pathlib import Path

STARTUP_SH = (
    Path(__file__).resolve().parent.parent
    / 'lib' / 'vibedom' / 'container' / 'startup.sh'
)


def _extract_function(name: str) -> str:
    text = STARTUP_SH.read_text()
    match = re.search(rf'^{name}\(\) \{{.*?^\}}', text, re.DOTALL | re.MULTILINE)
    assert match, f"{name}() not found in startup.sh"
    return match.group(0)


def test_init_repo_only_cds_to_work_dir(tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    script = _extract_function('init_repo') + '\ninit_repo\npwd\n'
    result = subprocess.run(
        ['sh', '-c', script], cwd=str(tmp_path),
        env={'PATH': '/usr/bin:/bin', 'WORK_DIR': str(work)},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == str(work)
    assert not (work / '.git').exists()


def test_startup_has_no_clone_or_live_flag():
    text = STARTUP_SH.read_text()
    for token in ('VIBEDOM_LIVE', 'git clone', 'REPO_DIR', 'WORKSPACE_DIR', 'rsync'):
        assert token not in text, f"{token} should be gone from startup.sh"


def test_alpine_image_does_not_install_rsync():
    dockerfile = STARTUP_SH.parent / 'Dockerfile.alpine'
    assert 'rsync' not in dockerfile.read_text()
