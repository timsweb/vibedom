import subprocess
import shutil
from pathlib import Path
from vibedom.session import Session

def test_session_creation(tmp_path):
    """Should create session directory with unique ID."""
    workspace = tmp_path / 'test'
    workspace.mkdir()
    logs_dir = tmp_path / 'logs'

    session = Session.start(workspace, 'docker', logs_dir)

    assert session.session_dir.exists()
    assert session.session_dir.parent == logs_dir
    assert 'session-' in session.session_dir.name

def test_session_log_network_request(tmp_path):
    """Should log network requests to network.jsonl."""
    workspace = tmp_path / 'test'
    workspace.mkdir()
    session = Session.start(workspace, 'docker', tmp_path / 'logs')

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

def test_session_log_event(tmp_path):
    """Should log events to session.log."""
    workspace = tmp_path / 'test'
    workspace.mkdir()
    session = Session.start(workspace, 'docker', tmp_path / 'logs')

    session.log_event('VM started')
    session.log_event('Pre-flight scan complete', level='INFO')

    log_file = session.session_dir / 'session.log'
    assert log_file.exists()

    content = log_file.read_text()
    assert 'VM started' in content
    assert 'Pre-flight scan complete' in content

def test_session_finalize(tmp_path):
    """Should log session end or finalization event."""
    workspace = tmp_path / 'test'
    workspace.mkdir()
    session = Session.start(workspace, 'docker', tmp_path / 'logs')
    session.finalize()

    log_file = session.session_dir / 'session.log'
    content = log_file.read_text()
    # finalize now calls create_bundle which logs events
    assert 'Session' in content

def test_create_bundle_success(tmp_path):
    """Bundle created successfully from container repo."""
    workspace = tmp_path / 'test-workspace-bundle'
    logs_dir = tmp_path / 'test-logs-bundle'

    # Create test workspace with git repo
    workspace.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'init'], cwd=workspace, check=True)
    (workspace / 'test.txt').write_text('test')
    subprocess.run(['git', 'add', '.'], cwd=workspace, check=True)
    subprocess.run(['git', 'commit', '-m', 'Initial'], cwd=workspace, check=True)

    session = Session.start(workspace, 'docker', logs_dir)

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


def test_create_bundle_failure(tmp_path):
    """Bundle creation failure logged, returns None."""
    workspace = tmp_path / 'test-workspace-bundle-fail'
    logs_dir = tmp_path / 'test-logs-bundle-fail'

    workspace.mkdir(parents=True, exist_ok=True)
    session = Session.start(workspace, 'docker', logs_dir)

    # No repo directory exists - bundle creation should fail gracefully
    bundle_path = session.create_bundle()

    assert bundle_path is None

    # Check error logged
    log_content = (session.session_log).read_text()
    assert 'Bundle creation failed' in log_content or 'ERROR' in log_content


def test_session_start_creates_state_json(tmp_path):
    """Session.start() should write state.json."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    session = Session.start(workspace, 'docker', tmp_path / 'logs')
    assert (session.session_dir / 'state.json').exists()
    assert session.state.status == 'running'
    assert session.state.runtime == 'docker'

def test_session_start_creates_session_log(tmp_path):
    """Session.start() should create session.log with initial entry."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    session = Session.start(workspace, 'docker', tmp_path / 'logs')
    assert session.session_log.exists()

def test_session_load_from_existing_dir(tmp_path):
    """Session.load() should restore session from state.json."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    session = Session.start(workspace, 'docker', tmp_path / 'logs')
    session_dir = session.session_dir
    loaded = Session.load(session_dir)
    assert loaded.state.session_id == session.state.session_id
    assert loaded.state.workspace == session.state.workspace

def test_session_is_container_running_docker(tmp_path):
    """is_container_running uses state.runtime, no parameter."""
    from unittest.mock import patch, MagicMock
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    session = Session.start(workspace, 'docker', tmp_path / 'logs')
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout='vibedom-myapp\n')
        assert session.is_container_running() is True
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == 'docker'

def test_session_is_container_running_apple(tmp_path):
    """is_container_running uses 'container' command for apple runtime."""
    from unittest.mock import patch, MagicMock
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    session = Session.start(workspace, 'apple', tmp_path / 'logs')
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout='vibedom-myapp\n')
        session.is_container_running()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == 'container'

def test_session_not_running_for_complete_status(tmp_path):
    """is_container_running returns False without subprocess for non-running sessions."""
    from unittest.mock import patch
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    session = Session.start(workspace, 'docker', tmp_path / 'logs')
    session.state.status = 'complete'
    with patch('subprocess.run') as mock_run:
        assert session.is_container_running() is False
        mock_run.assert_not_called()

def test_session_age_str(tmp_path):
    """age_str should return human-readable age."""
    session = Session.start(tmp_path / 'myapp', 'docker', tmp_path / 'logs')
    # Just started — should be seconds old
    assert 's ago' in session.age_str or 'm ago' in session.age_str

def test_session_display_name(tmp_path):
    """display_name includes session_id and status."""
    workspace = tmp_path / 'myapp'
    workspace.mkdir()
    session = Session.start(workspace, 'docker', tmp_path / 'logs')
    name = session.display_name
    assert session.state.session_id in name
    assert 'running' in name
