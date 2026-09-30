import json
import os
import signal
import subprocess
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from vibedom.cli import main
from vibedom.container_state import ContainerState


def test_up_with_mounts_passes_exactly_that_list(tmp_path):
    """up with a mounts: config passes normalized mounts to VMManager and marks the
    container; the up directory itself is not auto-mounted."""
    proj = tmp_path / 'agent'
    proj.mkdir()
    target = tmp_path / 'www'
    target.mkdir()
    (proj / 'vibedom.yml').write_text(f'mounts:\n  - {target}\n')

    home = tmp_path / 'home'
    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli.scan_workspace', return_value=[]):
            with patch('vibedom.cli.review_findings', return_value=True):
                with patch('vibedom.cli.VMManager') as mock_vm_cls:
                    mock_vm_cls._detect_runtime.return_value = ('docker', 'docker')
                    mock_vm = MagicMock()
                    mock_vm.is_running.return_value = False
                    mock_vm.exists.return_value = False
                    mock_vm._proxy = MagicMock(port=54321, pid=99999)
                    mock_vm_cls.return_value = mock_vm
                    result = runner.invoke(main, ['up', str(proj)], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    _, kwargs = mock_vm_cls.call_args
    mounts = kwargs['mounts']
    assert [(m.name, m.read_only) for m in mounts] == [('www', False)]

    state = ContainerState.load(home / '.vibedom' / 'containers' / 'agent')
    assert state.legacy is False


def test_up_live_mount_missing_dir_fails_fast(tmp_path):
    """up rejects a mounts: entry whose path is not a directory, before creating anything."""
    proj = tmp_path / 'agent'
    proj.mkdir()
    missing = tmp_path / 'does-not-exist'
    (proj / 'vibedom.yml').write_text(f'mounts:\n  - {missing}\n')

    home = tmp_path / 'home'
    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli.VMManager') as mock_vm_cls:
            mock_vm_cls._detect_runtime.return_value = ('docker', 'docker')
            result = runner.invoke(main, ['up', str(proj)], catch_exceptions=False)

    assert result.exit_code == 1
    assert 'not a directory' in result.output
    # Validation runs before the container is constructed
    mock_vm_cls.assert_not_called()


def test_up_already_running_says_files_are_bind_mounted(tmp_path):
    """The already-running branch must not print a misleading Repo: copy path for live containers."""
    proj = tmp_path / 'agent'
    proj.mkdir()
    home = tmp_path / 'home'
    cdir = home / '.vibedom' / 'containers' / 'agent'
    cdir.mkdir(parents=True)
    state = ContainerState.create(proj, 'docker')
    state.status = 'running'
    state.save(cdir)

    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli._ensure_proxy_running'):
            with patch('vibedom.cli.VMManager') as mock_vm_cls:
                mock_vm_cls._detect_runtime.return_value = ('docker', 'docker')
                mock_vm = MagicMock()
                mock_vm.is_running.return_value = True
                mock_vm_cls.return_value = mock_vm
                result = runner.invoke(main, ['up', str(proj)], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert 'bind-mounted' in result.output
    assert 'Repo:' not in result.output

def test_cli_help_lists_only_container_commands():
    result = CliRunner().invoke(main, ['--help'])
    assert result.exit_code == 0
    for cmd in ('init', 'up', 'down', 'destroy', 'status', 'list', 'shell',
                'reload-whitelist', 'proxy-restart'):
        assert cmd in result.output
    for gone in ('run', 'attach', 'review', 'merge', 'prune', 'housekeeping'):
        assert f'  {gone} ' not in result.output


def test_reload_whitelist_sends_sighup_to_running_containers(tmp_path):
    proj = tmp_path / 'agent'
    proj.mkdir()
    cdir = tmp_path / '.vibedom' / 'containers' / 'agent'
    cdir.mkdir(parents=True)
    state = ContainerState.create(proj, 'docker')
    state.mark_running(54321, 99999, cdir)

    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        with patch('os.kill') as mock_kill:
            result = CliRunner().invoke(main, ['reload-whitelist'])

    assert result.exit_code == 0, result.output
    mock_kill.assert_called_once_with(99999, signal.SIGHUP)


def test_reload_whitelist_no_running_containers(tmp_path):
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        result = CliRunner().invoke(main, ['reload-whitelist'])
    assert result.exit_code == 0
    assert 'No running containers' in result.output


def _make_container(tmp_path, name='myapp', status='running',
                    proxy_pid=99999, proxy_port=54321):
    """Create a container.json under ~/.vibedom/containers/<name>/ for tests."""
    from vibedom.container_state import ContainerState

    workspace = tmp_path / name
    workspace.mkdir(exist_ok=True)
    container_dir = tmp_path / '.vibedom' / 'containers' / name
    state = ContainerState(
        workspace=str(workspace),
        container_name=f'vibedom-{name}',
        runtime='docker',
        created_at='2026-06-15T00:00:00',
        status=status,
        proxy_port=proxy_port,
        proxy_pid=proxy_pid,
    )
    state.save(container_dir)
    return container_dir


def test_proxy_restart_persistent_container(tmp_path):
    """proxy-restart should restart the proxy for a persistent container by name."""
    container_dir = _make_container(tmp_path, name='myapp',
                                    proxy_pid=99999, proxy_port=54321)

    runner = CliRunner()
    mock_proxy = MagicMock()
    mock_proxy.pid = 88888
    mock_proxy.port = 54321

    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        with patch('vibedom.cli._live_container_status', return_value='running'):
            with patch('os.kill') as mock_kill:
                with patch('vibedom.cli.ProxyManager', return_value=mock_proxy):
                    result = runner.invoke(main, ['proxy-restart', 'myapp'])

    assert result.exit_code == 0, result.output
    mock_kill.assert_called_once_with(99999, signal.SIGTERM)
    mock_proxy.start.assert_called_once_with(port=54321)
    assert '88888' in result.output

    # New PID should be persisted to container.json
    state = json.loads((container_dir / 'container.json').read_text())
    assert state['proxy_pid'] == 88888


def test_proxy_restart_uses_live_status_not_persisted(tmp_path):
    """proxy-restart must trust the live runtime status, not a stale container.json.

    Regression: `vibedom list` reported the container running (live inspect)
    while proxy-restart refused it because the persisted status field still
    said 'stopped'. The live check is the source of truth, and the restart
    should reconcile the stale field back to 'running'.
    """
    container_dir = _make_container(tmp_path, name='waterstones-api',
                                    status='stopped',  # stale persisted value
                                    proxy_pid=99999, proxy_port=63337)

    runner = CliRunner()
    mock_proxy = MagicMock()
    mock_proxy.pid = 88888
    mock_proxy.port = 63337

    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        with patch('vibedom.cli._live_container_status', return_value='running'):
            with patch('os.kill'):
                with patch('vibedom.cli.ProxyManager', return_value=mock_proxy):
                    result = runner.invoke(
                        main, ['proxy-restart', 'waterstones-api'])

    assert result.exit_code == 0, result.output
    mock_proxy.start.assert_called_once_with(port=63337)

    state = json.loads((container_dir / 'container.json').read_text())
    assert state['proxy_pid'] == 88888
    assert state['status'] == 'running'  # stale field reconciled


def test_proxy_restart_container_not_running(tmp_path):
    """proxy-restart should refuse a container the runtime reports as not running."""
    _make_container(tmp_path, name='myapp', status='running', proxy_pid=99999)

    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=tmp_path):
        with patch('vibedom.cli._live_container_status', return_value='exited'):
            with patch('vibedom.cli.ProxyManager') as mock_pm:
                result = runner.invoke(main, ['proxy-restart', 'myapp'])

    assert result.exit_code == 1
    assert 'not running' in result.output.lower()
    mock_pm.assert_not_called()


def test_live_container_status_apple_v14_status_object(tmp_path):
    """_live_container_status must return a string when apple/container 1.4+ nests state under status."""
    from vibedom.cli import _live_container_status
    c = ContainerState(
        workspace=str(tmp_path / 'myapp'), container_name='vibedom-myapp',
        runtime='apple', status='running', created_at='2026-09-16T00:00:00',
    )
    v14 = '[{"id": "vibedom-myapp", "configuration": {}, "status": {"state": "running", "networks": []}}]'
    legacy = '[{"configuration": {}, "status": "stopped", "networks": []}]'
    with patch('vibedom.cli.subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=v14)
        assert _live_container_status(c) == 'running'
        mock_run.return_value = MagicMock(returncode=0, stdout=legacy)
        assert _live_container_status(c) == 'stopped'
        mock_run.return_value = MagicMock(returncode=0, stdout='[]')
        assert _live_container_status(c) == 'gone'
        mock_run.return_value = MagicMock(returncode=1, stdout='')
        assert _live_container_status(c) == 'gone'


def _recreate_setup(tmp_path, *, yml: str = '') -> tuple:
    """Project dir + saved running ContainerState for an existing container."""
    proj = tmp_path / 'agent'
    proj.mkdir()
    if yml:
        (proj / 'vibedom.yml').write_text(yml)
    home = tmp_path / 'home'
    cdir = home / '.vibedom' / 'containers' / 'agent'
    cdir.mkdir(parents=True)
    state = ContainerState.create(proj, 'docker')
    state.mark_running(54321, 4242, cdir)
    return proj, home, cdir


def _invoke_recreate(proj, home, args, *, exists=True, setup_result=None):
    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli.scan_workspace', return_value=[]):
            with patch('vibedom.cli.review_findings', return_value=True):
                with patch('vibedom.cli.os.kill') as mock_kill:
                    with patch('vibedom.cli.VMManager') as mock_vm_cls:
                        mock_vm_cls._detect_runtime.return_value = ('docker', 'docker')
                        mock_vm = MagicMock()
                        mock_vm.is_running.return_value = exists
                        mock_vm.exists.return_value = exists
                        mock_vm._proxy = MagicMock(port=60000, pid=77777)
                        mock_vm.exec.return_value = setup_result or MagicMock(returncode=0)
                        mock_vm_cls.return_value = mock_vm
                        result = runner.invoke(
                            main, ['up', str(proj), *args], catch_exceptions=False
                        )
    return result, mock_vm_cls, mock_vm, mock_kill


def test_up_recreate_removes_container_and_starts_fresh(tmp_path):
    """--recreate on a live container: kill old proxy, remove container, create anew,
    without prompting (nothing is lost for live mounts)."""
    target = tmp_path / 'www'
    target.mkdir()
    proj, home, cdir = _recreate_setup(tmp_path, yml=f'mounts:\n  - {target}\n')

    result, mock_vm_cls, mock_vm, mock_kill = _invoke_recreate(proj, home, ['--recreate'])

    assert result.exit_code == 0, result.output
    mock_kill.assert_called_once_with(4242, signal.SIGTERM)
    mock_vm.stop.assert_called_once()
    mock_vm.start.assert_called_once()
    mock_vm.restart.assert_not_called()
    state = ContainerState.load(cdir)
    assert state.status == 'running'
    assert state.proxy_port == 60000


def test_up_recreate_reruns_setup_commands(tmp_path):
    proj, home, _ = _recreate_setup(
        tmp_path, yml='setup:\n  - echo one\n  - echo two\n'
    )
    result, _, mock_vm, _ = _invoke_recreate(proj, home, ['--recreate'])

    assert result.exit_code == 0, result.output
    cmds = [c.args[0] for c in mock_vm.exec.call_args_list]
    assert cmds == [['sh', '-c', 'echo one'], ['sh', '-c', 'echo two']]


def test_up_recreate_rebuilds_base_image_when_no_base_image_configured(tmp_path):
    proj, home, _ = _recreate_setup(tmp_path)
    result, mock_vm_cls, _, _ = _invoke_recreate(proj, home, ['--recreate'])

    assert result.exit_code == 0, result.output
    mock_vm_cls.build_image.assert_called_once_with('docker')


def test_up_recreate_skips_base_image_rebuild_when_project_layer_used(tmp_path):
    """With base_image: the project layer rebuilds on create anyway (COPY startup.sh)."""
    proj, home, _ = _recreate_setup(tmp_path, yml='base_image: php:8.3\n')
    result, mock_vm_cls, _, _ = _invoke_recreate(proj, home, ['--recreate'])

    assert result.exit_code == 0, result.output
    mock_vm_cls.build_image.assert_not_called()


def test_up_recreate_without_existing_container_is_plain_create(tmp_path):
    proj = tmp_path / 'agent'
    proj.mkdir()
    home = tmp_path / 'home'
    result, _, mock_vm, mock_kill = _invoke_recreate(proj, home, ['--recreate'], exists=False)

    assert result.exit_code == 0, result.output
    mock_kill.assert_not_called()
    mock_vm.stop.assert_not_called()
    mock_vm.start.assert_called_once()


def test_up_recreates_missing_container_and_reruns_setup(tmp_path):
    """Container gone from the runtime but state intact: setup must run again, since
    anything it installed into the container filesystem is gone."""
    proj, home, _ = _recreate_setup(tmp_path, yml='setup:\n  - echo one\n')
    result, _, mock_vm, _ = _invoke_recreate(proj, home, [], exists=False)

    assert result.exit_code == 0, result.output
    assert 'Recreating' in result.output
    assert [c.args[0] for c in mock_vm.exec.call_args_list] == [['sh', '-c', 'echo one']]


def _up_first_run(proj, home, args=()):
    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli.scan_workspace', return_value=[]) as mock_scan:
            with patch('vibedom.cli.review_findings', return_value=True):
                with patch('vibedom.cli.VMManager') as mock_vm_cls:
                    mock_vm_cls._detect_runtime.return_value = ('docker', 'docker')
                    mock_vm = MagicMock()
                    mock_vm.is_running.return_value = False
                    mock_vm.exists.return_value = False
                    mock_vm._proxy = MagicMock(port=54321, pid=99999)
                    mock_vm_cls.return_value = mock_vm
                    result = runner.invoke(main, ['up', str(proj), *args], catch_exceptions=False)
    return result, mock_vm_cls, mock_scan


def test_up_without_yml_mounts_the_workspace_itself(tmp_path):
    proj = tmp_path / 'myapp'
    proj.mkdir()
    result, mock_vm_cls, mock_scan = _up_first_run(proj, tmp_path / 'home')

    assert result.exit_code == 0, result.output
    mounts = mock_vm_cls.call_args.kwargs['mounts']
    assert [(m.host_path, m.name, m.read_only) for m in mounts] == [(proj.resolve(), 'myapp', False)]
    mock_scan.assert_called_once_with(proj.resolve())
    assert '/work/myapp' in result.output


def test_up_yml_without_mounts_uses_default_mount(tmp_path):
    proj = tmp_path / 'myapp'
    proj.mkdir()
    (proj / 'vibedom.yml').write_text('setup:\n  - echo hi\n')
    result, mock_vm_cls, _ = _up_first_run(proj, tmp_path / 'home')

    assert result.exit_code == 0, result.output
    mounts = mock_vm_cls.call_args.kwargs['mounts']
    assert [m.name for m in mounts] == ['myapp']


def test_up_with_mounts_does_not_auto_mount_workspace(tmp_path):
    proj = tmp_path / 'agent'
    proj.mkdir()
    (tmp_path / 'www').mkdir()
    (proj / 'vibedom.yml').write_text(f'mounts:\n  - {tmp_path / "www"}\n')
    result, mock_vm_cls, _ = _up_first_run(proj, tmp_path / 'home')

    assert result.exit_code == 0, result.output
    assert [m.name for m in mock_vm_cls.call_args.kwargs['mounts']] == ['www']


def _legacy_setup(tmp_path):
    proj = tmp_path / 'old'
    proj.mkdir()
    home = tmp_path / 'home'
    cdir = home / '.vibedom' / 'containers' / 'old'
    cdir.mkdir(parents=True)
    (cdir / 'container.json').write_text(json.dumps({
        'workspace': str(proj), 'container_name': 'vibedom-old', 'runtime': 'docker',
        'created_at': '2026-01-01T00:00:00', 'repo_dir': str(cdir / 'repo'),
        'status': 'stopped', 'live': False,
    }))
    return proj, home, cdir


def test_up_refuses_legacy_container(tmp_path):
    proj, home, cdir = _legacy_setup(tmp_path)
    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli.VMManager') as mock_vm_cls:
            mock_vm_cls._detect_runtime.return_value = ('docker', 'docker')
            result = runner.invoke(main, ['up', str(proj)])

    assert result.exit_code == 1
    assert 'copy+sync' in result.output
    assert str(cdir / 'repo') in result.output
    assert 'vibedom destroy old' in result.output
    mock_vm_cls.return_value.start.assert_not_called()


def test_up_recreate_refuses_legacy_container(tmp_path):
    proj, home, _ = _legacy_setup(tmp_path)
    runner = CliRunner()
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli.VMManager') as mock_vm_cls:
            mock_vm_cls._detect_runtime.return_value = ('docker', 'docker')
            result = runner.invoke(main, ['up', str(proj), '--recreate'])

    assert result.exit_code == 1
    assert 'vibedom destroy old' in result.output
    mock_vm_cls.return_value.stop.assert_not_called()


def test_up_recreate_has_no_yes_flag(tmp_path):
    proj = tmp_path / 'myapp'
    proj.mkdir()
    result = CliRunner().invoke(main, ['up', str(proj), '--recreate', '--yes'])
    assert result.exit_code == 2
    assert 'No such option' in result.output


def test_up_has_no_pull_or_push():
    result = CliRunner().invoke(main, ['pull', 'x'])
    assert result.exit_code == 2
    result = CliRunner().invoke(main, ['push', 'x'])
    assert result.exit_code == 2


def test_status_marks_legacy_container_and_lists_others(tmp_path):
    home = tmp_path / 'home'
    old, _, _ = _legacy_setup(tmp_path)          # writes home/.vibedom/containers/old
    new = tmp_path / 'new'
    new.mkdir()
    cdir = home / '.vibedom' / 'containers' / 'new'
    cdir.mkdir(parents=True)
    ContainerState.create(new, 'docker').save(cdir)

    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli._live_container_status', return_value='stopped'):
            result = CliRunner().invoke(main, ['status'])

    assert result.exit_code == 0, result.output
    lines = {l.split()[0]: l for l in result.output.splitlines() if l.startswith(('old', 'new'))}
    assert 'legacy' in lines['old'] and 'vibedom destroy' in lines['old']
    assert 'legacy' not in lines['new']


def _shell_setup(tmp_path, yml=''):
    proj = tmp_path / 'myapp'
    proj.mkdir()
    if yml:
        (proj / 'vibedom.yml').write_text(yml)
    home = tmp_path / 'home'
    cdir = home / '.vibedom' / 'containers' / 'myapp'
    cdir.mkdir(parents=True)
    state = ContainerState.create(proj, 'docker')
    state.mark_running(54321, 4242, cdir)
    return proj, home


def _invoke_shell(home):
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli._ensure_proxy_running'):
            with patch('vibedom.cli.subprocess.run') as mock_run:
                result = CliRunner().invoke(main, ['shell', 'myapp'], catch_exceptions=False)
    return result, mock_run


def test_shell_single_mount_opens_in_that_mount(tmp_path):
    _, home = _shell_setup(tmp_path)
    result, mock_run = _invoke_shell(home)
    assert result.exit_code == 0, result.output
    cmd = mock_run.call_args.args[0]
    assert cmd[cmd.index('-w') + 1] == '/work/myapp'


def test_shell_multiple_mounts_opens_in_work(tmp_path):
    (tmp_path / 'a').mkdir()
    (tmp_path / 'b').mkdir()
    _, home = _shell_setup(tmp_path, f'mounts:\n  - {tmp_path / "a"}\n  - {tmp_path / "b"}\n')
    result, mock_run = _invoke_shell(home)
    assert result.exit_code == 0, result.output
    cmd = mock_run.call_args.args[0]
    assert cmd[cmd.index('-w') + 1] == '/work'


def test_shell_workdir_follows_current_config(tmp_path):
    """Editing vibedom.yml after creation changes the shell cwd without crashing."""
    proj, home = _shell_setup(tmp_path)
    (tmp_path / 'lib').mkdir()
    (proj / 'vibedom.yml').write_text(f'mounts:\n  - .\n  - {tmp_path / "lib"}\n')
    result, mock_run = _invoke_shell(home)
    assert result.exit_code == 0, result.output
    assert mock_run.call_args.args[0][mock_run.call_args.args[0].index('-w') + 1] == '/work'


def test_shell_refuses_legacy_container(tmp_path):
    _, home, _ = _legacy_setup(tmp_path)
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli.subprocess.run') as mock_run:
            result = CliRunner().invoke(main, ['shell', 'old'])
    assert result.exit_code == 1
    assert 'vibedom destroy old' in result.output
    mock_run.assert_not_called()


# --- review fixes: down/destroy must not need a mount list; shell tolerates bad yml ---

def _running_container(tmp_path, name='myapp'):
    proj = tmp_path / name
    proj.mkdir(exist_ok=True)
    home = tmp_path / 'home'
    cdir = home / '.vibedom' / 'containers' / name
    cdir.mkdir(parents=True, exist_ok=True)
    state = ContainerState.create(proj, 'docker')
    state.mark_running(54321, 4242, cdir)
    return proj, home, cdir


def test_down_stops_container(tmp_path):
    """down constructs a real VMManager (no mock) and must not trip the mounts check."""
    _, home, cdir = _running_container(tmp_path)
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli.os.kill'):
            with patch('vibedom.vm.subprocess.run') as mock_run:
                with patch('shutil.which', return_value='/usr/local/bin/docker'):
                    result = CliRunner().invoke(main, ['down', 'myapp'])

    assert result.exit_code == 0, result.output
    assert any('stop' in c.args[0] for c in mock_run.call_args_list)
    assert ContainerState.load(cdir).status == 'stopped'


def test_destroy_removes_container_and_state(tmp_path):
    _, home, cdir = _running_container(tmp_path)
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli.os.kill'):
            with patch('vibedom.vm.subprocess.run') as mock_run:
                with patch('shutil.which', return_value='/usr/local/bin/docker'):
                    result = CliRunner().invoke(main, ['destroy', 'myapp', '--force'])

    assert result.exit_code == 0, result.output
    assert any('rm' in c.args[0] for c in mock_run.call_args_list)
    assert not cdir.exists()


def test_destroy_works_for_legacy_container(tmp_path):
    """The rescue instructions tell legacy users to run destroy — it must work."""
    _, home, cdir = _legacy_setup(tmp_path)
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli.os.kill'):
            with patch('vibedom.vm.subprocess.run'):
                with patch('shutil.which', return_value='/usr/local/bin/docker'):
                    result = CliRunner().invoke(main, ['destroy', 'old', '--force'])

    assert result.exit_code == 0, result.output
    assert not cdir.exists()


def test_destroy_prompt_says_mounted_dirs_are_untouched(tmp_path):
    _, home, _ = _running_container(tmp_path)
    with patch('vibedom.cli.Path.home', return_value=home):
        result = CliRunner().invoke(main, ['destroy', 'myapp'], input='n\n')

    assert result.exit_code == 0, result.output
    assert 'repo data' not in result.output
    assert 'not touched' in result.output
    assert 'Aborted' in result.output


def test_shell_falls_back_to_work_when_yml_is_invalid(tmp_path):
    proj, home = _shell_setup(tmp_path, 'mountz:\n  - .\n')
    result, mock_run = _invoke_shell(home)
    assert result.exit_code == 0, result.output
    assert 'vibedom.yml' in result.output
    cmd = mock_run.call_args.args[0]
    assert cmd[cmd.index('-w') + 1] == '/work'


def test_list_is_an_alias_of_status(tmp_path):
    _, home, _ = _running_container(tmp_path)
    with patch('vibedom.cli.Path.home', return_value=home):
        with patch('vibedom.cli._live_container_status', return_value='running'):
            status = CliRunner().invoke(main, ['status'])
            listed = CliRunner().invoke(main, ['list'])

    assert status.exit_code == 0, status.output
    assert listed.exit_code == 0, listed.output
    assert listed.output == status.output
    assert 'vibedom-myapp' in listed.output
