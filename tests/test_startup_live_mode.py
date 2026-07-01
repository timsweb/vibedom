"""Behavioral tests for live-mount detection in startup.sh.

In live-mount mode (VIBEDOM_LIVE set) the real project dirs are bind-mounted
under $WORK_DIR, so init_repo must NOT clone or git-init anything — it just
cd's into $WORK_DIR. We extract the real init_repo function and run it.
"""

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


def _run_init_repo(cwd: Path, env_overrides: dict) -> subprocess.CompletedProcess:
    script = _extract_function('init_repo') + '\ninit_repo\npwd\n'
    env = {
        'PATH': '/usr/bin:/bin:/usr/local/bin',
        'HOME': str(cwd),
        'GIT_CONFIG_GLOBAL': '/dev/null',
        'GIT_CONFIG_SYSTEM': '/dev/null',
    }
    env.update(env_overrides)
    return subprocess.run(
        ['sh', '-c', script], cwd=str(cwd), env=env,
        capture_output=True, text=True,
    )


def test_live_mode_skips_clone_and_cds_to_work(tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    result = _run_init_repo(tmp_path, {
        'VIBEDOM_LIVE': '1',
        'WORK_DIR': str(work),
        'REPO_DIR': str(tmp_path / 'repo'),
        'WORKSPACE_DIR': str(tmp_path / 'ws'),
    })
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == str(work)
    assert not (tmp_path / 'repo').exists()


def test_existing_repo_still_skips_clone(tmp_path):
    repo = tmp_path / 'repo'
    (repo / '.git').mkdir(parents=True)
    result = _run_init_repo(tmp_path, {
        'WORK_DIR': str(tmp_path / 'work'),
        'REPO_DIR': str(repo),
        'WORKSPACE_DIR': str(tmp_path / 'ws'),
    })
    assert result.returncode == 0, result.stderr
    assert 'skipping clone' in result.stdout
    assert result.stdout.strip().splitlines()[-1] == str(repo)
