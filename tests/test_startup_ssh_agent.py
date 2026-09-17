"""Behavioral tests for SSH agent startup in startup.sh.

Regression: after `container stop` / `container start`, the old
/tmp/ssh-agent.sock file survived in the container filesystem but the agent
process behind it was gone. startup.sh only checked for the socket's
existence, took the "already running" branch, and never started a new agent —
so git over SSH failed until someone manually restarted the agent and re-added
the key.

These tests extract the real `start_ssh_agent` function from startup.sh and
run it against a throwaway key and socket path.
"""

import re
import socket
import subprocess
from pathlib import Path

import pytest

STARTUP_SH = (
    Path(__file__).resolve().parent.parent
    / 'lib' / 'vibedom' / 'container' / 'startup.sh'
)


def _extract_function(name: str) -> str:
    text = STARTUP_SH.read_text()
    match = re.search(rf'^{name}\(\) \{{.*?^\}}', text, re.DOTALL | re.MULTILINE)
    assert match, f"{name}() not found in startup.sh"
    return match.group(0)


@pytest.fixture
def agent_env(tmp_path):
    key = tmp_path / 'id_ed25519_vibedom'
    subprocess.run(
        ['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)],
        check=True,
    )
    env = {
        'PATH': '/usr/bin:/bin:/usr/local/bin',
        'HOME': str(tmp_path),
        'SSH_KEY_FILE': str(key),
        'SSH_AGENT_SOCK': str(tmp_path / 'agent.sock'),
        'SSH_AGENT_PROFILE': str(tmp_path / 'ssh-agent.sh'),
    }
    yield env
    subprocess.run(['pkill', '-f', f"ssh-agent -a {env['SSH_AGENT_SOCK']}"], check=False)


def _run_start_ssh_agent(env: dict) -> subprocess.CompletedProcess:
    script = _extract_function('start_ssh_agent') + '\nstart_ssh_agent\n'
    return subprocess.run(
        ['sh', '-c', script], env=env, capture_output=True, text=True,
    )


def _agent_keys(env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['ssh-add', '-l'],
        env={**env, 'SSH_AUTH_SOCK': env['SSH_AGENT_SOCK']},
        capture_output=True, text=True,
    )


def _make_stale_socket(path: str) -> None:
    """Leave a socket file on disk with no process listening — what a
    stopped container's /tmp looks like after `container start`."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(path)
    s.close()
    assert Path(path).is_socket()


def test_fresh_start_loads_key(agent_env):
    result = _run_start_ssh_agent(agent_env)
    assert result.returncode == 0, result.stderr
    keys = _agent_keys(agent_env)
    assert keys.returncode == 0, keys.stderr
    assert 'ED25519' in keys.stdout
    assert Path(agent_env['SSH_AGENT_PROFILE']).read_text().strip() == (
        f"export SSH_AUTH_SOCK={agent_env['SSH_AGENT_SOCK']}"
    )


def test_stale_socket_is_replaced_by_live_agent(agent_env):
    _make_stale_socket(agent_env['SSH_AGENT_SOCK'])
    assert _agent_keys(agent_env).returncode != 0  # nothing listening

    result = _run_start_ssh_agent(agent_env)
    assert result.returncode == 0, result.stderr
    keys = _agent_keys(agent_env)
    assert keys.returncode == 0, keys.stderr
    assert 'ED25519' in keys.stdout


def test_live_agent_is_reused(agent_env):
    _run_start_ssh_agent(agent_env)
    first = _agent_keys(agent_env).stdout

    result = _run_start_ssh_agent(agent_env)
    assert result.returncode == 0, result.stderr
    assert 'already running' in result.stdout
    assert _agent_keys(agent_env).stdout == first


def test_no_key_file_is_a_noop(agent_env, tmp_path):
    agent_env['SSH_KEY_FILE'] = str(tmp_path / 'missing')
    result = _run_start_ssh_agent(agent_env)
    assert result.returncode == 0, result.stderr
    assert not Path(agent_env['SSH_AGENT_SOCK']).exists()
