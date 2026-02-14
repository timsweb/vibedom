import tempfile
import subprocess
import shutil
from pathlib import Path
from vibedom.session import Session

def test_session_creation():
    """Should create session directory with unique ID."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logs_dir = Path(tmpdir)
        workspace = Path('/tmp/test')

        session = Session(workspace, logs_dir)

        assert session.session_dir.exists()
        assert session.session_dir.parent == logs_dir
        assert 'session-' in session.session_dir.name

def test_session_log_network_request():
    """Should log network requests to network.jsonl."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session = Session(Path('/tmp/test'), Path(tmpdir))

        session.log_network_request(
            method='GET',
            url='https://api.anthropic.com/v1/messages',
            allowed=True
        )

        log_file = session.session_dir / 'network.jsonl'
        assert log_file.exists()

        import json
        with open(log_file) as f:
            entry = json.loads(f.readline())
            assert entry['method'] == 'GET'
            assert entry['url'] == 'https://api.anthropic.com/v1/messages'
            assert entry['allowed'] is True

def test_session_log_event():
    """Should log events to session.log."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session = Session(Path('/tmp/test'), Path(tmpdir))

        session.log_event('VM started')
        session.log_event('Pre-flight scan complete', level='INFO')

        log_file = session.session_dir / 'session.log'
        assert log_file.exists()

        content = log_file.read_text()
        assert 'VM started' in content
        assert 'Pre-flight scan complete' in content

def test_session_finalize():
    """Should log session end event."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session = Session(Path('/tmp/test'), Path(tmpdir))
        session.finalize()

        log_file = session.session_dir / 'session.log'
        content = log_file.read_text()
        assert 'Session ended' in content

def test_create_bundle_success():
    """Bundle created successfully from container repo."""
    workspace = Path('/tmp/test-workspace-bundle')
    logs_dir = Path('/tmp/test-logs-bundle')

    try:
        # Create test workspace with git repo
        workspace.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init'], cwd=workspace, check=True)
        (workspace / 'test.txt').write_text('test')
        subprocess.run(['git', 'add', '.'], cwd=workspace, check=True)
        subprocess.run(['git', 'commit', '-m', 'Initial'], cwd=workspace, check=True)

        session = Session(workspace, logs_dir)

        # Simulate container repo with commits
        repo_dir = session.session_dir / 'repo'
        repo_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', str(workspace / '.git'), str(repo_dir)], check=True)

        # Make a commit in the "container" repo
        (repo_dir / 'feature.txt').write_text('new feature')
        subprocess.run(['git', 'add', '.'], cwd=repo_dir, check=True)
        subprocess.run(['git', 'commit', '-m', 'Add feature'], cwd=repo_dir, check=True)

        # Create bundle
        bundle_path = session.create_bundle()

        assert bundle_path is not None
        assert bundle_path.exists()
        assert bundle_path.name == 'repo.bundle'

        # Verify bundle is valid
        result = subprocess.run(
            ['git', 'bundle', 'verify', str(bundle_path)],
            capture_output=True
        )
        assert result.returncode == 0

    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(logs_dir, ignore_errors=True)

def test_create_bundle_failure():
    """Bundle creation failure logged, returns None."""
    workspace = Path('/tmp/test-workspace-bundle-fail')
    logs_dir = Path('/tmp/test-logs-bundle-fail')

    try:
        workspace.mkdir(parents=True, exist_ok=True)
        session = Session(workspace, logs_dir)

        # No repo directory exists - bundle creation should fail gracefully
        bundle_path = session.create_bundle()

        assert bundle_path is None

        # Check error logged
        log_content = (session.session_log).read_text()
        assert 'Bundle creation failed' in log_content or 'ERROR' in log_content

    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(logs_dir, ignore_errors=True)
