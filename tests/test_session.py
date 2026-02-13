import tempfile
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
