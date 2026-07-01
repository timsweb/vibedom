"""Behavioral tests for the git-identity defaulting in startup.sh.

The agent identity must be a *default* applied only when the user hasn't set
one — never an override. Regression: an unconditional `git config` block ran on
every container start and reset the user's name/email back to "Vibedom Agent".

These tests extract the real `ensure_git_identity` shell function from
startup.sh and execute it (via /bin/sh) against throwaway git repos, so we test
the shipped code, not a copy of it.
"""

import re
import subprocess
from pathlib import Path

import pytest

STARTUP_SH = (
    Path(__file__).resolve().parent.parent
    / 'lib' / 'vibedom' / 'container' / 'startup.sh'
)


def _extract_function(name: str) -> str:
    """Pull a POSIX-sh function definition out of startup.sh by name."""
    text = STARTUP_SH.read_text()
    match = re.search(rf'^{name}\(\) \{{.*?^\}}', text, re.DOTALL | re.MULTILINE)
    assert match, f"{name}() not found in startup.sh"
    return match.group(0)


def _run_identity_fn(repo: Path) -> None:
    """Run the extracted ensure_git_identity() with `repo` as the cwd."""
    script = _extract_function('ensure_git_identity') + '\nensure_git_identity\n'
    # Isolate from the host's global/system git config so "unset" is truly unset.
    env = {
        # Isolate from the host's config: HOME (the throwaway repo) backs the
        # global config, so `git config --global` (what ensure_git_identity now
        # writes) lands in $HOME/.gitconfig. Point the system config at a
        # nonexistent path, not /dev/null — this git version errors with
        # "bad config line 1 in file /dev/null" when a config path is /dev/null.
        'GIT_CONFIG_SYSTEM': str(repo / 'nonexistent-system-config'),
        'PATH': '/usr/bin:/bin:/usr/local/bin',
        'HOME': str(repo),
    }
    subprocess.run(['sh', '-c', script], cwd=repo, env=env, check=True)


def _git(repo: Path, *args: str) -> str:
    env = {
        # Isolate from the host's config: HOME (the throwaway repo) backs the
        # global config, so `git config --global` (what ensure_git_identity now
        # writes) lands in $HOME/.gitconfig. Point the system config at a
        # nonexistent path, not /dev/null — this git version errors with
        # "bad config line 1 in file /dev/null" when a config path is /dev/null.
        'GIT_CONFIG_SYSTEM': str(repo / 'nonexistent-system-config'),
        'PATH': '/usr/bin:/bin:/usr/local/bin',
        'HOME': str(repo),
    }
    return subprocess.run(
        ['git', *args], cwd=repo, env=env, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, 'init')
    return tmp_path


def test_sets_default_identity_when_unset(repo):
    """With no identity configured, the agent default is applied."""
    _run_identity_fn(repo)
    assert _git(repo, 'config', 'user.name') == 'Vibedom Agent'
    assert _git(repo, 'config', 'user.email') != ''


def test_preserves_user_name(repo):
    """A user-configured name must NOT be clobbered (the reported bug)."""
    _git(repo, 'config', 'user.name', 'Ada Lovelace')
    _git(repo, 'config', 'user.email', '[REDACTED_EMAIL]')

    _run_identity_fn(repo)

    assert _git(repo, 'config', 'user.name') == 'Ada Lovelace'
    assert _git(repo, 'config', 'user.email') == '[REDACTED_EMAIL]'


def test_idempotent_across_restarts(repo):
    """Running it repeatedly (simulating restarts) never overrides a user value."""
    _git(repo, 'config', 'user.name', 'Grace Hopper')
    for _ in range(3):
        _run_identity_fn(repo)
    assert _git(repo, 'config', 'user.name') == 'Grace Hopper'
