import tempfile
import subprocess
from pathlib import Path
import pytest
import shutil
from unittest.mock import patch, MagicMock
from vibedom.vm import VMManager
from vibedom.session import Session

@pytest.fixture
def test_workspace():
    """Create a temporary workspace for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / 'workspace'
        workspace.mkdir()
        (workspace / 'test.txt').write_text('hello')
        yield workspace

@pytest.fixture
def test_config():
    """Create a temporary config directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)
        yield config_dir

def test_vm_start_stop(test_workspace, test_config):
    """Should start and stop VM successfully."""
    vm = VMManager(test_workspace, test_config)

    vm.start()

    # Check container is running
    result = vm.exec(['echo', 'test'])
    assert result.returncode == 0
    assert 'test' in result.stdout

    vm.stop()

def test_vm_git_repo_initialized(test_workspace, test_config):
    """VM should initialize git repo from workspace."""
    import subprocess
    from vibedom.session import Session

    # Create test git workspace
    (test_workspace / 'test.txt').write_text('test content')
    subprocess.run(['git', 'init'], cwd=test_workspace, check=True)
    subprocess.run(['git', 'add', '.'], cwd=test_workspace, check=True)
    subprocess.run(['git', 'commit', '-m', 'Initial'], cwd=test_workspace, check=True)

    session = Session(test_workspace, Path('/tmp/vibedom-test-logs'))
    vm = VMManager(test_workspace, test_config, session_dir=session.session_dir)

    try:
        vm.start()

        # Verify git repo initialized in container
        result = vm.exec(['sh', '-c', 'cd /work/repo && git log --oneline'])
        assert 'Initial' in result.stdout

    finally:
        vm.stop()
        shutil.rmtree(session.session_dir, ignore_errors=True)

def test_vm_mounts_session_repo(test_workspace, test_config):
    """VM should mount session repo directory."""
    session = Session(test_workspace, Path('/tmp/vibedom-test-logs'))

    vm = VMManager(test_workspace, test_config, session_dir=session.session_dir)

    try:
        vm.start()

        # Verify repo directory exists in session
        repo_dir = session.session_dir / 'repo'
        assert repo_dir.exists(), "Repo directory should exist in session dir"

        # Verify .git exists in mounted repo
        git_dir = repo_dir / '.git'
        assert git_dir.exists(), "Git directory should exist in mounted repo"

    finally:
        vm.stop()
        shutil.rmtree(session.session_dir, ignore_errors=True)


def test_detect_runtime_prefers_apple(test_workspace, test_config):
    """Should prefer apple/container when available."""
    with patch('shutil.which') as mock_which:
        mock_which.side_effect = lambda cmd: '/usr/local/bin/container' if cmd == 'container' else None
        vm = VMManager(test_workspace, test_config)
        assert vm.runtime == 'apple'
        assert vm.runtime_cmd == 'container'


def test_detect_runtime_falls_back_to_docker(test_workspace, test_config):
    """Should fall back to Docker when apple/container not available."""
    with patch('shutil.which') as mock_which:
        mock_which.side_effect = lambda cmd: '/usr/local/bin/docker' if cmd == 'docker' else None
        vm = VMManager(test_workspace, test_config)
        assert vm.runtime == 'docker'
        assert vm.runtime_cmd == 'docker'


def test_detect_runtime_raises_when_neither(test_workspace, test_config):
    """Should raise RuntimeError when no runtime found."""
    with patch('shutil.which', return_value=None):
        with pytest.raises(RuntimeError, match="No container runtime found"):
            VMManager(test_workspace, test_config)


def test_explicit_runtime_docker(test_workspace, test_config):
    """Should use Docker when explicitly specified."""
    with patch('shutil.which') as mock_which:
        mock_which.return_value = '/usr/local/bin/docker'
        vm = VMManager(test_workspace, test_config, runtime='docker')
        assert vm.runtime == 'docker'
        assert vm.runtime_cmd == 'docker'


def test_explicit_runtime_apple(test_workspace, test_config):
    """Should use apple/container when explicitly specified."""
    with patch('shutil.which') as mock_which:
        mock_which.return_value = '/usr/local/bin/container'
        vm = VMManager(test_workspace, test_config, runtime='apple')
        assert vm.runtime == 'apple'
        assert vm.runtime_cmd == 'container'


def test_explicit_runtime_raises_if_not_available(test_workspace, test_config):
    """Should raise RuntimeError when explicit runtime not found."""
    with patch('shutil.which', return_value=None):
        with pytest.raises(RuntimeError, match="Docker runtime requested but not found"):
            VMManager(test_workspace, test_config, runtime='docker')


def test_start_uses_apple_runtime(test_workspace, test_config):
    """start() should use 'container' command when runtime is apple."""
    with patch('shutil.which') as mock_which:
        mock_which.side_effect = lambda cmd: '/usr/local/bin/container' if cmd == 'container' else None
        vm = VMManager(test_workspace, test_config)

    with patch('subprocess.run') as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        try:
            vm.start()
        except RuntimeError:
            pass

        calls = mock_run.call_args_list
        run_call = next(c for c in calls if 'run' in c[0][0])
        assert run_call[0][0][0] == 'container'
        assert '--detach' in run_call[0][0]
        assert '--privileged' not in run_call[0][0]


def test_start_uses_docker_runtime(test_workspace, test_config):
    """start() should use 'docker' command when runtime is docker."""
    with patch('shutil.which') as mock_which:
        mock_which.side_effect = lambda cmd: '/usr/local/bin/docker' if cmd == 'docker' else None
        vm = VMManager(test_workspace, test_config)

    with patch('subprocess.run') as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        try:
            vm.start()
        except RuntimeError:
            pass

        calls = mock_run.call_args_list
        run_call = next(c for c in calls if 'run' in c[0][0])
        assert run_call[0][0][0] == 'docker'
        assert '-d' in run_call[0][0]
        assert '--privileged' not in run_call[0][0]


def test_stop_uses_apple_commands(test_workspace, test_config):
    """stop() should use 'container stop' + 'container delete' for apple runtime."""
    with patch('shutil.which') as mock_which:
        mock_which.side_effect = lambda cmd: '/usr/local/bin/container' if cmd == 'container' else None
        vm = VMManager(test_workspace, test_config)

    with patch('subprocess.run') as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        vm.stop()

        calls = [c[0][0] for c in mock_run.call_args_list]
        assert calls[0][:2] == ['container', 'stop']
        assert calls[1][:2] == ['container', 'delete']


def test_stop_uses_docker_command(test_workspace, test_config):
    """stop() should use 'docker rm -f' for docker runtime."""
    with patch('shutil.which') as mock_which:
        mock_which.side_effect = lambda cmd: '/usr/local/bin/docker' if cmd == 'docker' else None
        vm = VMManager(test_workspace, test_config)

    with patch('subprocess.run') as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        vm.stop()

        calls = [c[0][0] for c in mock_run.call_args_list]
        assert calls[0] == ['docker', 'rm', '-f', vm.container_name]


def test_exec_uses_detected_runtime(test_workspace, test_config):
    """exec() should use detected runtime command."""
    with patch('shutil.which') as mock_which:
        mock_which.side_effect = lambda cmd: '/usr/local/bin/container' if cmd == 'container' else None
        vm = VMManager(test_workspace, test_config)

    with patch('subprocess.run') as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='hello', stderr=''
        )
        vm.exec(['echo', 'hello'])

        call_args = mock_run.call_args[0][0]
        assert call_args[:2] == ['container', 'exec']


def test_start_mounts_claude_api_key(test_workspace, test_config, tmp_path):
    """start() should mount ~/.claude/api_key if it exists."""
    # Create fake Claude config directory
    fake_claude_home = tmp_path / '.claude'
    fake_claude_home.mkdir()
    (fake_claude_home / 'api_key').write_text('fake-key')

    session_dir = tmp_path / 'session'
    session_dir.mkdir()

    with patch('vibedom.vm.Path.home', return_value=tmp_path):
        with patch('shutil.which', return_value='/usr/bin/docker'):
            vm = VMManager(test_workspace, test_config, session_dir)

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('shutil.copy'):
                try:
                    vm.start()
                except RuntimeError:
                    pass  # May fail on readiness check, that's ok

            # Find the 'run' call
            calls = mock_run.call_args_list
            run_call = next(c for c in calls if 'run' in c[0][0])
            cmd = run_call[0][0]

            # Check that api_key is mounted
            assert '-v' in cmd
            mount_idx = cmd.index('-v')
            while mount_idx < len(cmd):
                if f'{fake_claude_home}/api_key:/root/.claude/api_key:ro' in cmd[mount_idx + 1]:
                    break
                mount_idx = cmd.index('-v', mount_idx + 1)
            else:
                pytest.fail("api_key mount not found in command")


def test_start_mounts_claude_settings(test_workspace, test_config, tmp_path):
    """start() should mount ~/.claude/settings.json if it exists."""
    fake_claude_home = tmp_path / '.claude'
    fake_claude_home.mkdir()
    (fake_claude_home / 'settings.json').write_text('{}')

    session_dir = tmp_path / 'session'
    session_dir.mkdir()

    with patch('vibedom.vm.Path.home', return_value=tmp_path):
        with patch('shutil.which', return_value='/usr/bin/docker'):
            vm = VMManager(test_workspace, test_config, session_dir)

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('shutil.copy'):
                try:
                    vm.start()
                except RuntimeError:
                    pass

            calls = mock_run.call_args_list
            run_call = next(c for c in calls if 'run' in c[0][0])
            cmd = run_call[0][0]

            # Check that settings.json is mounted
            mount_found = any(
                f'{fake_claude_home}/settings.json:/root/.claude/settings.json:ro' in str(arg)
                for arg in cmd
            )
            assert mount_found, "settings.json mount not found"


def test_start_mounts_claude_skills(test_workspace, test_config, tmp_path):
    """start() should mount ~/.claude/skills directory if it exists."""
    fake_claude_home = tmp_path / '.claude'
    fake_claude_home.mkdir()
    skills_dir = fake_claude_home / 'skills'
    skills_dir.mkdir()

    session_dir = tmp_path / 'session'
    session_dir.mkdir()

    with patch('vibedom.vm.Path.home', return_value=tmp_path):
        with patch('shutil.which', return_value='/usr/bin/docker'):
            vm = VMManager(test_workspace, test_config, session_dir)

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('shutil.copy'):
                try:
                    vm.start()
                except RuntimeError:
                    pass

            calls = mock_run.call_args_list
            run_call = next(c for c in calls if 'run' in c[0][0])
            cmd = run_call[0][0]

            # Check that skills directory is mounted
            mount_found = any(
                f'{skills_dir}:/root/.claude/skills:ro' in str(arg)
                for arg in cmd
            )
            assert mount_found, "skills directory mount not found"


def test_start_skips_claude_mounts_if_not_exists(test_workspace, test_config, tmp_path):
    """start() should not fail if ~/.claude doesn't exist."""
    session_dir = tmp_path / 'session'
    session_dir.mkdir()

    # No .claude directory exists
    with patch('vibedom.vm.Path.home', return_value=tmp_path):
        with patch('shutil.which', return_value='/usr/bin/docker'):
            vm = VMManager(test_workspace, test_config, session_dir)

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch('shutil.copy'):
                try:
                    vm.start()
                except RuntimeError:
                    pass

            # Should still succeed, just without Claude mounts
            assert mock_run.called
