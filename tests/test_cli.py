import subprocess
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from vibedom.cli import main

def test_cli_shows_help():
    """CLI should show help message when invoked with --help"""
    result = subprocess.run(
        ['vibedom', '--help'],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert 'vibedom' in result.stdout.lower()
    assert 'init' in result.stdout
    assert 'run' in result.stdout


def test_reload_whitelist_sends_sighup(tmp_path):
    """reload-whitelist should send SIGHUP to mitmdump in container."""
    workspace = tmp_path / 'test-workspace'
    workspace.mkdir()

    with patch('vibedom.cli.VMManager._detect_runtime', return_value=('docker', 'docker')):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr='')

            runner = CliRunner()
            result = runner.invoke(main, ['reload-whitelist', str(workspace)])

            # Should call docker exec ... pkill -HUP mitmdump
            assert mock_run.called
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == 'docker'
            assert 'exec' in cmd
            assert 'pkill' in cmd
            assert '-HUP' in cmd
            assert 'mitmdump' in cmd
            assert result.exit_code == 0


def test_reload_whitelist_fails_if_container_not_running(tmp_path):
    """reload-whitelist should fail gracefully if container not running."""
    workspace = tmp_path / 'test-workspace'
    workspace.mkdir()

    with patch('vibedom.cli.VMManager._detect_runtime', return_value=('docker', 'docker')):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr='Error: No such container')

            runner = CliRunner()
            result = runner.invoke(main, ['reload-whitelist', str(workspace)])

            assert result.exit_code == 1
            assert 'Failed to reload' in result.output


def test_find_latest_session_success(tmp_path):
    """find_latest_session should return most recent session for workspace."""
    from vibedom.cli import find_latest_session

    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    logs_dir = tmp_path / 'logs'
    logs_dir.mkdir()

    # Create two sessions
    session1 = logs_dir / 'session-20260218-100000-000000'
    session1.mkdir()
    (session1 / 'session.log').write_text(f'Session started for workspace: {workspace}')

    session2 = logs_dir / 'session-20260218-110000-000000'
    session2.mkdir()
    (session2 / 'session.log').write_text(f'Session started for workspace: {workspace}')

    result = find_latest_session(workspace, logs_dir)
    assert result == session2  # Most recent


def test_find_latest_session_not_found(tmp_path):
    """find_latest_session should return None if no session found."""
    from vibedom.cli import find_latest_session

    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    logs_dir = tmp_path / 'logs'
    logs_dir.mkdir()

    result = find_latest_session(workspace, logs_dir)
    assert result is None


def test_review_command_success(tmp_path):
    """review command should add remote, fetch, show commits and diff."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    # Create fake session
    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260218-120000-000000'
    session_dir.mkdir(parents=True)
    (session_dir / 'session.log').write_text(f'Session started for workspace: {workspace}')
    (session_dir / 'repo.bundle').write_text('fake bundle')

    runner = CliRunner()

    with patch('vibedom.cli.Path.home') as mock_home:
        mock_home.return_value = tmp_path

        with patch('vibedom.cli.VMManager._detect_runtime', return_value=('docker', 'docker')):
            with patch('subprocess.run') as mock_run:
                # Mock git commands and container check
                mock_run.side_effect = [
                    MagicMock(returncode=0),  # git rev-parse --git-dir (is git repo)
                    MagicMock(returncode=0, stdout=''),  # docker ps (not running)
                    MagicMock(returncode=0, stdout='main\n'),  # git rev-parse --abbrev-ref HEAD
                    MagicMock(returncode=1),  # git remote get-url (doesn't exist)
                    MagicMock(returncode=0),  # git remote add
                    MagicMock(returncode=0),  # git fetch
                    MagicMock(returncode=0, stdout='abc123 commit message\n'),  # git log
                    MagicMock(returncode=0, stdout='diff content\n'),  # git diff
                ]

                result = runner.invoke(main, ['review', str(workspace)])

                assert result.exit_code == 0
                assert 'session-20260218-120000-000000' in result.output

                # Verify git commands were called
                calls = [' '.join(call[0][0]) for call in mock_run.call_args_list]
                assert any('remote add' in call for call in calls)
                assert any('fetch' in call for call in calls)
                assert any('log' in call for call in calls)
                assert any('diff' in call for call in calls)


def test_review_no_session_found(tmp_path):
    """review should error if no session found."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    logs_dir = tmp_path / 'logs'
    logs_dir.mkdir()

    runner = CliRunner()

    with patch('vibedom.cli.Path.home') as mock_home:
        mock_home.return_value = tmp_path

        with patch('subprocess.run') as mock_run:
            # Mock git check to pass
            mock_run.return_value = MagicMock(returncode=0)

            result = runner.invoke(main, ['review', str(workspace)])

            assert result.exit_code == 1
            assert 'No session found' in result.output


def test_review_fails_if_session_running(tmp_path):
    """review should error if container is still running."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    # Create fake session
    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260218-120000-000000'
    session_dir.mkdir(parents=True)
    (session_dir / 'session.log').write_text(f'Session started for workspace: {workspace}')
    (session_dir / 'repo.bundle').write_text('fake bundle')

    runner = CliRunner()

    with patch('vibedom.cli.Path.home') as mock_home:
        mock_home.return_value = tmp_path

        with patch('vibedom.cli.Path.cwd') as mock_cwd:
            mock_cwd.return_value = workspace

            with patch('vibedom.cli.VMManager._detect_runtime', return_value=('docker', 'docker')):
                with patch('subprocess.run') as mock_run:
                    # Mock git repo check, then container ps shows running
                    mock_run.side_effect = [
                        MagicMock(returncode=0),  # git rev-parse (is git repo)
                        MagicMock(returncode=0, stdout='vibedom-myapp\n'),  # docker ps (running)
                    ]

                    result = runner.invoke(main, ['review', str(workspace)])

                    assert result.exit_code == 1
                    assert 'still running' in result.output


def test_review_fails_if_bundle_missing(tmp_path):
    """review should error if bundle file is missing."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    # Create session without bundle
    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260218-120000-000000'
    session_dir.mkdir(parents=True)
    (session_dir / 'session.log').write_text(f'Session started for workspace: {workspace}')
    # No bundle created

    runner = CliRunner()

    with patch('vibedom.cli.Path.home') as mock_home:
        mock_home.return_value = tmp_path

        with patch('vibedom.cli.VMManager._detect_runtime', return_value=('docker', 'docker')):
            with patch('subprocess.run') as mock_run:
                # Mock git repo check and container not running
                mock_run.side_effect = [
                    MagicMock(returncode=0),  # git rev-parse (is git repo)
                    MagicMock(returncode=0, stdout=''),  # docker ps (not running)
                ]

                result = runner.invoke(main, ['review', str(workspace)])

                assert result.exit_code == 1
                assert 'Bundle not found' in result.output


def test_review_fails_if_not_git_repo(tmp_path):
    """review should error if workspace is not a git repository."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    runner = CliRunner()

    with patch('subprocess.run') as mock_run:
        # Mock git check to fail
        mock_run.side_effect = subprocess.CalledProcessError(128, 'git rev-parse')

        result = runner.invoke(main, ['review', str(workspace)])

        assert result.exit_code == 1
        assert 'not a git repository' in result.output


def test_review_fails_on_git_remote_add_error(tmp_path):
    """review should error gracefully if git remote add fails."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    # Create fake session
    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260218-120000-000000'
    session_dir.mkdir(parents=True)
    (session_dir / 'session.log').write_text(f'Session started for workspace: {workspace}')
    (session_dir / 'repo.bundle').write_text('fake bundle')

    runner = CliRunner()

    with patch('vibedom.cli.Path.home') as mock_home:
        mock_home.return_value = tmp_path

        with patch('vibedom.cli.VMManager._detect_runtime', return_value=('docker', 'docker')):
            with patch('subprocess.run') as mock_run:
                # Mock git commands
                mock_run.side_effect = [
                    MagicMock(returncode=0),  # git rev-parse --git-dir (is git repo)
                    MagicMock(returncode=0, stdout=''),  # docker ps (not running)
                    MagicMock(returncode=0, stdout='main\n'),  # git rev-parse --abbrev-ref HEAD
                    MagicMock(returncode=1),  # git remote get-url (doesn't exist)
                    subprocess.CalledProcessError(128, 'git remote add'),  # git remote add fails
                ]

                result = runner.invoke(main, ['review', str(workspace)])

                assert result.exit_code == 1
                assert 'Failed to add git remote' in result.output


def test_merge_command_squash(tmp_path):
    """merge command should squash by default."""
    from vibedom.cli import main

    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    # Create fake session (needs to be in .vibedom/logs like the review command expects)
    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260218-130000-000000'
    session_dir.mkdir(parents=True)
    (session_dir / 'session.log').write_text(f'Session started for workspace: {workspace}')
    (session_dir / 'repo.bundle').write_text('fake bundle')

    runner = CliRunner()

    with patch('vibedom.cli.Path.home') as mock_home:
        mock_home.return_value = tmp_path

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0),  # git rev-parse --git-dir (is git repo)
                MagicMock(returncode=0, stdout=''),  # git status --porcelain (clean)
                MagicMock(returncode=0, stdout='main\n'),  # git rev-parse --abbrev-ref HEAD (branch)
                MagicMock(returncode=1),  # git remote get-url (doesn't exist)
                MagicMock(returncode=0),  # git remote add
                MagicMock(returncode=0),  # git fetch
                MagicMock(returncode=0),  # git merge --squash
                MagicMock(returncode=0),  # git commit
                MagicMock(returncode=0),  # git remote remove
            ]

            result = runner.invoke(main, ['merge', str(workspace)])

            assert result.exit_code == 0
            # Verify squash merge was called
            merge_calls = [call for call in mock_run.call_args_list
                          if 'merge' in ' '.join(call[0][0])]
            assert any('--squash' in ' '.join(call[0][0]) for call in merge_calls)


def test_merge_command_keep_history(tmp_path):
    """merge command with --merge flag should keep full history."""
    from vibedom.cli import main

    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    # Create fake session (needs to be in .vibedom/logs like the review command expects)
    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260218-130000-000000'
    session_dir.mkdir(parents=True)
    (session_dir / 'session.log').write_text(f'Session started for workspace: {workspace}')
    (session_dir / 'repo.bundle').write_text('fake bundle')

    runner = CliRunner()

    with patch('vibedom.cli.Path.home') as mock_home:
        mock_home.return_value = tmp_path

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0),  # git rev-parse --git-dir (is git repo)
                MagicMock(returncode=0, stdout=''),  # git status --porcelain (clean)
                MagicMock(returncode=0, stdout='main\n'),  # git rev-parse --abbrev-ref HEAD (branch)
                MagicMock(returncode=1),  # git remote get-url (doesn't exist)
                MagicMock(returncode=0),  # git remote add
                MagicMock(returncode=0),  # git fetch
                MagicMock(returncode=0),  # git merge (no squash)
                MagicMock(returncode=0),  # git remote remove
            ]

            result = runner.invoke(main, ['merge', str(workspace), '--merge'])

            assert result.exit_code == 0
            # Verify regular merge (no --squash)
            merge_calls = [call for call in mock_run.call_args_list
                          if 'merge' in ' '.join(call[0][0])]
            assert not any('--squash' in ' '.join(call[0][0]) for call in merge_calls)


def test_merge_fails_with_uncommitted_changes(tmp_path):
    """merge should abort if workspace has uncommitted changes."""
    from vibedom.cli import main

    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    # Create fake session (needs to be in .vibedom/logs like the review command expects)
    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260218-130000-000000'
    session_dir.mkdir(parents=True)
    (session_dir / 'session.log').write_text(f'Session started for workspace: {workspace}')
    (session_dir / 'repo.bundle').write_text('fake bundle')

    runner = CliRunner()

    with patch('vibedom.cli.Path.home') as mock_home:
        mock_home.return_value = tmp_path

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0),  # git rev-parse --git-dir (is git repo)
                MagicMock(returncode=0, stdout=' M file.txt\n'),  # git status returns dirty state
            ]

            result = runner.invoke(main, ['merge', str(workspace)])

            assert result.exit_code == 1
            assert 'uncommitted changes' in result.output


def test_attach_execs_into_running_session(tmp_path):
    """attach should exec into the running session's container."""
    import json
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260219-100000-000000'
    session_dir.mkdir(parents=True)
    (session_dir / 'state.json').write_text(json.dumps({
        'session_id': 'myapp-happy-turing',
        'workspace': str(workspace),
        'runtime': 'docker',
        'container_name': 'vibedom-myapp',
        'status': 'running',
        'started_at': '2026-02-19T10:00:00',
        'ended_at': None,
        'bundle_path': None,
    }))

    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(main, ['attach', 'myapp-happy-turing'])

    assert result.exit_code == 0
    cmd = mock_run.call_args[0][0]
    assert 'exec' in cmd
    assert '-it' in cmd
    assert '/work/repo' in cmd
    assert 'vibedom-myapp' in cmd
    assert 'bash' in cmd


def test_attach_uses_container_cmd_for_apple(tmp_path):
    """attach should use 'container' command for apple runtime."""
    import json
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260219-100000-000000'
    session_dir.mkdir(parents=True)
    (session_dir / 'state.json').write_text(json.dumps({
        'session_id': 'myapp-happy-turing',
        'workspace': str(workspace),
        'runtime': 'apple',
        'container_name': 'vibedom-myapp',
        'status': 'running',
        'started_at': '2026-02-19T10:00:00',
        'ended_at': None,
        'bundle_path': None,
    }))

    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            runner.invoke(main, ['attach', 'myapp-happy-turing'])

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == 'container'


def test_attach_rejects_non_running_session(tmp_path):
    """attach should reject sessions that are not running."""
    import json
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260219-100000-000000'
    session_dir.mkdir(parents=True)
    (session_dir / 'state.json').write_text(json.dumps({
        'session_id': 'myapp-happy-turing',
        'workspace': str(workspace),
        'runtime': 'docker',
        'container_name': 'vibedom-myapp',
        'status': 'complete',  # not running
        'started_at': '2026-02-19T10:00:00',
        'ended_at': '2026-02-19T11:00:00',
        'bundle_path': None,
    }))

    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        result = runner.invoke(main, ['attach', 'myapp-happy-turing'])

    assert result.exit_code != 0
    assert 'not running' in result.output


def test_run_writes_state_json(tmp_path):
    """vibedom run should write state.json to the session directory."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        with patch('vibedom.cli.scan_workspace', return_value=[]):
            with patch('vibedom.cli.review_findings', return_value=True):
                with patch('vibedom.cli.VMManager') as mock_vm_cls:
                    mock_vm_cls._detect_runtime.return_value = ('docker', 'docker')
                    mock_vm = MagicMock()
                    mock_vm_cls.return_value = mock_vm

                    runner.invoke(main, ['run', str(workspace)])

    # Find the session directory
    session_dirs = list((tmp_path / '.vibedom' / 'logs').glob('session-*'))
    assert len(session_dirs) == 1, f"Expected 1 session dir, got: {session_dirs}"
    state_file = session_dirs[0] / 'state.json'
    assert state_file.exists(), "state.json not written"
    import json
    state = json.loads(state_file.read_text())
    assert state['status'] == 'running'
    assert state['workspace'] == str(workspace)
    assert state['runtime'] == 'docker'


def test_run_shows_session_id(tmp_path):
    """vibedom run should display the session ID in output."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        with patch('vibedom.cli.scan_workspace', return_value=[]):
            with patch('vibedom.cli.review_findings', return_value=True):
                with patch('vibedom.cli.VMManager') as mock_vm_cls:
                    mock_vm_cls._detect_runtime.return_value = ('docker', 'docker')
                    mock_vm_cls.return_value = MagicMock()

                    result = runner.invoke(main, ['run', str(workspace)])

    assert 'Session ID:' in result.output


def test_stop_uses_session_registry(tmp_path):
    """stop should find session via SessionRegistry, not log parsing."""
    import json
    workspace = tmp_path / 'myapp'
    workspace.mkdir()

    logs_dir = tmp_path / '.vibedom' / 'logs'
    session_dir = logs_dir / 'session-20260219-100000-000000'
    session_dir.mkdir(parents=True)
    state = {
        'session_id': 'myapp-happy-turing',
        'workspace': str(workspace),
        'runtime': 'docker',
        'container_name': 'vibedom-myapp',
        'status': 'running',
        'started_at': '2026-02-19T10:00:00',
        'ended_at': None,
        'bundle_path': None,
    }
    (session_dir / 'state.json').write_text(json.dumps(state))

    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        with patch('vibedom.cli.VMManager') as mock_vm_cls:
            mock_vm = MagicMock()
            mock_vm_cls.return_value = mock_vm
            with patch('vibedom.session.Session.create_bundle', return_value=None):
                result = runner.invoke(main, ['stop', 'myapp-happy-turing'])

    assert result.exit_code == 0
