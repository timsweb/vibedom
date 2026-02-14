"""Git workflow integration tests."""

import pytest
import subprocess
import shutil
from pathlib import Path
from vibedom.vm import VMManager
from vibedom.session import Session

@pytest.fixture
def git_workspace(tmp_path):
    """Create a test workspace with git repo."""
    workspace = tmp_path / 'workspace'
    workspace.mkdir()

    # Initialize git repo
    subprocess.run(['git', 'init'], cwd=workspace, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=workspace, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=workspace, check=True)

    # Create initial commit
    (workspace / 'README.md').write_text('# Test Project')
    subprocess.run(['git', 'add', '.'], cwd=workspace, check=True)
    subprocess.run(['git', 'commit', '-m', 'Initial commit'], cwd=workspace, check=True)

    # Create feature branch
    subprocess.run(['git', 'checkout', '-b', 'feature/test'], cwd=workspace, check=True)
    (workspace / 'feature.txt').write_text('Feature work')
    subprocess.run(['git', 'add', '.'], cwd=workspace, check=True)
    subprocess.run(['git', 'commit', '-m', 'Add feature'], cwd=workspace, check=True)

    yield workspace
    shutil.rmtree(workspace, ignore_errors=True)

@pytest.fixture
def config_dir(tmp_path):
    """Create test config directory."""
    config = tmp_path / 'config'
    config.mkdir()

    # Copy mitmproxy addon
    import vibedom
    addon_src = Path(vibedom.__file__).parent.parent.parent / 'vm' / 'mitmproxy_addon.py'
    shutil.copy(addon_src, config / 'mitmproxy_addon.py')

    # Create whitelist
    (config / 'trusted_domains.txt').write_text('pypi.org\n')

    yield config
    shutil.rmtree(config, ignore_errors=True)

def test_git_workspace_cloned_with_branch(git_workspace, config_dir, tmp_path):
    """Container clones workspace and checks out current branch."""
    logs_dir = tmp_path / 'logs'
    session = Session(git_workspace, logs_dir)
    vm = VMManager(git_workspace, config_dir, session_dir=session.session_dir)

    try:
        vm.start()

        # Verify git repo exists in container
        result = vm.exec(['sh', '-c', 'test -d /work/repo/.git && echo exists'])
        assert 'exists' in result.stdout

        # Verify correct branch checked out
        result = vm.exec(['sh', '-c', 'cd /work/repo && git branch --show-current'])
        assert result.stdout.strip() == 'feature/test'

        # Verify commits present
        result = vm.exec(['sh', '-c', 'cd /work/repo && git log --oneline'])
        assert 'Add feature' in result.stdout
        assert 'Initial commit' in result.stdout

    finally:
        vm.stop()
        shutil.rmtree(session.session_dir, ignore_errors=True)

def test_bundle_created_and_valid(git_workspace, config_dir, tmp_path):
    """Bundle is created and can be verified."""
    logs_dir = tmp_path / 'logs'
    session = Session(git_workspace, logs_dir)
    vm = VMManager(git_workspace, config_dir, session_dir=session.session_dir)

    try:
        vm.start()

        # Agent makes a commit
        vm.exec(['sh', '-c', '''
            cd /work/repo &&
            echo "Agent work" > agent.txt &&
            git add . &&
            git commit -m "Agent commit"
        '''])

        # Create bundle
        bundle_path = session.create_bundle()
        assert bundle_path is not None
        assert bundle_path.exists()

        # Verify bundle
        result = subprocess.run(
            ['git', 'bundle', 'verify', str(bundle_path)],
            capture_output=True, text=True
        )
        assert result.returncode == 0

        # Bundle should contain all refs
        result = subprocess.run(
            ['git', 'bundle', 'list-heads', str(bundle_path)],
            capture_output=True, text=True
        )
        assert 'feature/test' in result.stdout

    finally:
        vm.stop()
        shutil.rmtree(session.session_dir, ignore_errors=True)

def test_live_repo_accessible_during_session(git_workspace, config_dir, tmp_path):
    """Live repo can be accessed from host during session."""
    logs_dir = tmp_path / 'logs'
    session = Session(git_workspace, logs_dir)
    vm = VMManager(git_workspace, config_dir, session_dir=session.session_dir)

    try:
        vm.start()

        # Verify live repo exists
        live_repo = session.session_dir / 'repo'
        assert live_repo.exists()
        assert (live_repo / '.git').exists()

        # Agent makes commit
        vm.exec(['sh', '-c', '''
            cd /work/repo &&
            echo "Live test" > live.txt &&
            git add . &&
            git commit -m "Live commit"
        '''])

        # Fetch from live repo (from a different location)
        test_clone = tmp_path / 'test-clone'
        subprocess.run(['git', 'clone', str(git_workspace), str(test_clone)], check=True)
        subprocess.run(['git', 'remote', 'add', 'vibedom-live', str(live_repo)], cwd=test_clone, check=True)
        subprocess.run(['git', 'fetch', 'vibedom-live'], cwd=test_clone, check=True)

        # Verify commit visible
        result = subprocess.run(
            ['git', 'log', '--oneline', 'vibedom-live/feature/test'],
            cwd=test_clone, capture_output=True, text=True
        )
        assert 'Live commit' in result.stdout

    finally:
        vm.stop()
        shutil.rmtree(session.session_dir, ignore_errors=True)
        shutil.rmtree(test_clone, ignore_errors=True)

def test_merge_workflow_from_bundle(git_workspace, config_dir, tmp_path):
    """Bundle can be added as remote and merged."""
    logs_dir = tmp_path / 'logs'
    session = Session(git_workspace, logs_dir)
    vm = VMManager(git_workspace, config_dir, session_dir=session.session_dir)

    try:
        vm.start()

        # Agent makes commits
        vm.exec(['sh', '-c', '''
            cd /work/repo &&
            echo "Feature A" > feature_a.txt &&
            git add . &&
            git commit -m "Add feature A" &&
            echo "Feature B" > feature_b.txt &&
            git add . &&
            git commit -m "Add feature B"
        '''])

        # Create bundle
        bundle_path = session.create_bundle()
        vm.stop()

        # User merges from bundle
        subprocess.run(['git', 'remote', 'add', 'vibedom-test', str(bundle_path)], cwd=git_workspace, check=True)
        subprocess.run(['git', 'fetch', 'vibedom-test'], cwd=git_workspace, check=True)
        subprocess.run(['git', 'merge', 'vibedom-test/feature/test'], cwd=git_workspace, check=True)

        # Verify files exist
        assert (git_workspace / 'feature_a.txt').exists()
        assert (git_workspace / 'feature_b.txt').exists()

        # Verify commit history
        result = subprocess.run(
            ['git', 'log', '--oneline'],
            cwd=git_workspace, capture_output=True, text=True
        )
        assert 'Add feature A' in result.stdout
        assert 'Add feature B' in result.stdout

    finally:
        shutil.rmtree(session.session_dir, ignore_errors=True)

def test_non_git_workspace_initialized(tmp_path, config_dir):
    """Non-git workspace gets initialized as fresh repo."""
    workspace = tmp_path / 'non-git-workspace'
    workspace.mkdir()
    (workspace / 'file.txt').write_text('content')

    logs_dir = tmp_path / 'logs'
    session = Session(workspace, logs_dir)
    vm = VMManager(workspace, config_dir, session_dir=session.session_dir)

    try:
        vm.start()

        # Verify git repo initialized
        result = vm.exec(['sh', '-c', 'cd /work/repo && git status'])
        assert result.returncode == 0

        # Verify initial commit exists
        result = vm.exec(['sh', '-c', 'cd /work/repo && git log --oneline'])
        assert 'Initial snapshot' in result.stdout

        # Verify file copied
        result = vm.exec(['sh', '-c', 'test -f /work/repo/file.txt && echo exists'])
        assert 'exists' in result.stdout

    finally:
        vm.stop()
        shutil.rmtree(session.session_dir, ignore_errors=True)
        shutil.rmtree(workspace, ignore_errors=True)