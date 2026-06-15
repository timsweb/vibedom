import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / 'vm'))

try:
    from mitmproxy import http
except ImportError:
    from unittest.mock import MagicMock

    class MockResponse:
        """Mock Response for testing when mitmproxy not installed."""
        @staticmethod
        def make(status_code, body, headers):
            return Mock(status_code=status_code, content=body, headers=headers)

    class MockHTTPFlow:
        """Mock HTTPFlow for testing when mitmproxy not installed."""
        request = None
        response = None

    http = MagicMock()
    http.Response = MockResponse
    http.HTTPFlow = MockHTTPFlow


@patch('pathlib.Path.mkdir')
def test_request_headers_pass_through(mock_mkdir):
    """Should allow Authorization header through (for API calls)."""
    from mitmproxy_addon import VibedomProxy

    proxy = VibedomProxy()

    flow = MagicMock()
    flow.request.host = "api.anthropic.com"
    flow.request.host_header = "api.anthropic.com"
    flow.request.content = None
    flow.request.pretty_url = "https://api.anthropic.com/v1/messages"
    flow.request.url = "https://api.anthropic.com/v1/messages"
    flow.request.headers = {
        "Authorization": "Bearer sk-ant-api123",
        "Content-Type": "application/json"
    }

    proxy.request(flow)

    # Authorization header should still be present
    assert flow.request.headers.get("Authorization") == "Bearer sk-ant-api123"


@patch('pathlib.Path.mkdir')
def test_response_body_not_scrubbed(mock_mkdir):
    """Should not scrub response bodies (not needed for our threat model)."""
    from mitmproxy_addon import VibedomProxy

    proxy = VibedomProxy()

    flow = Mock(spec=http.HTTPFlow)
    flow.response = Mock()
    flow.response.content = b'{"api_key": "AKIAIOSFODNN7EXAMPLE"}'
    flow.response.headers = {"Content-Type": "application/json"}

    # response() method should not exist - responses pass through unmodified
    assert not hasattr(proxy, 'response')

    # Response content should remain unchanged (no scrubbing)
    assert flow.response.content == b'{"api_key": "AKIAIOSFODNN7EXAMPLE"}'


def test_addon_reads_whitelist_from_env(tmp_path, monkeypatch):
    """VibedomProxy should read whitelist path from VIBEDOM_WHITELIST_PATH env var."""
    whitelist = tmp_path / 'domains.txt'
    whitelist.write_text('example.com\n')
    monkeypatch.setenv('VIBEDOM_WHITELIST_PATH', str(whitelist))
    monkeypatch.setenv('VIBEDOM_NETWORK_LOG_PATH', str(tmp_path / 'network.jsonl'))
    monkeypatch.setenv('VIBEDOM_GITLEAKS_CONFIG', str(tmp_path / 'gitleaks.toml'))

    from mitmproxy_addon import VibedomProxy
    proxy = VibedomProxy()
    assert 'example.com' in proxy.whitelist


def test_addon_reads_network_log_from_env(tmp_path, monkeypatch):
    """VibedomProxy should write network log to VIBEDOM_NETWORK_LOG_PATH."""
    log_path = tmp_path / 'network.jsonl'
    monkeypatch.setenv('VIBEDOM_NETWORK_LOG_PATH', str(log_path))
    monkeypatch.setenv('VIBEDOM_WHITELIST_PATH', str(tmp_path / 'domains.txt'))
    monkeypatch.setenv('VIBEDOM_GITLEAKS_CONFIG', str(tmp_path / 'gitleaks.toml'))

    from mitmproxy_addon import VibedomProxy
    proxy = VibedomProxy()
    assert proxy.network_log_path == log_path


def test_addon_reads_gitleaks_config_from_env(tmp_path, monkeypatch):
    """VibedomProxy should read gitleaks config from VIBEDOM_GITLEAKS_CONFIG env var."""
    monkeypatch.setenv('VIBEDOM_WHITELIST_PATH', str(tmp_path / 'domains.txt'))
    monkeypatch.setenv('VIBEDOM_NETWORK_LOG_PATH', str(tmp_path / 'network.jsonl'))
    gitleaks_config = tmp_path / 'gitleaks.toml'
    gitleaks_config.write_text('')  # empty but exists
    monkeypatch.setenv('VIBEDOM_GITLEAKS_CONFIG', str(gitleaks_config))

    from mitmproxy_addon import VibedomProxy
    proxy = VibedomProxy()
    # Just verify it instantiates without error when all env vars are set
    assert proxy.network_log_path == tmp_path / 'network.jsonl'


@patch('pathlib.Path.mkdir')
def test_log_request_includes_timestamp(mock_mkdir, tmp_path, monkeypatch):
    """log_request should include an ISO timestamp in each network log entry."""
    log_path = tmp_path / 'network.jsonl'
    monkeypatch.setenv('VIBEDOM_NETWORK_LOG_PATH', str(log_path))
    monkeypatch.setenv('VIBEDOM_WHITELIST_PATH', str(tmp_path / 'domains.txt'))
    monkeypatch.setenv('VIBEDOM_GITLEAKS_CONFIG', str(tmp_path / 'gitleaks.toml'))

    from mitmproxy_addon import VibedomProxy
    import json as json_mod

    proxy = VibedomProxy()

    flow = MagicMock()
    flow.request.method = 'GET'
    flow.request.pretty_url = 'https://api.anthropic.com/v1/messages'
    flow.request.host_header = 'api.anthropic.com'
    flow.request.host = 'api.anthropic.com'

    proxy.log_request(flow, allowed=True)

    entry = json_mod.loads(log_path.read_text().strip())
    assert 'timestamp' in entry
    assert 'T' in entry['timestamp']  # ISO format contains 'T' separator


@patch('pathlib.Path.mkdir')
def test_missing_whitelist_prints_warning(mock_mkdir, tmp_path, monkeypatch, capsys):
    """load_whitelist should warn to stderr when whitelist file is missing."""
    monkeypatch.setenv('VIBEDOM_WHITELIST_PATH', str(tmp_path / 'nonexistent.txt'))
    monkeypatch.setenv('VIBEDOM_NETWORK_LOG_PATH', str(tmp_path / 'network.jsonl'))
    monkeypatch.setenv('VIBEDOM_GITLEAKS_CONFIG', str(tmp_path / 'gitleaks.toml'))

    from mitmproxy_addon import VibedomProxy
    proxy = VibedomProxy()

    assert proxy.whitelist == set()
    captured = capsys.readouterr()
    assert 'WARNING' in captured.err
    assert 'blocking all traffic' in captured.err


@patch('pathlib.Path.mkdir')
def test_json_request_body_stays_valid_after_scrub(mock_mkdir):
    """A JSON body with a bare numeric field must stay valid JSON after scrubbing.

    Regression for 400 Bad Request: numeric PII patterns matching a bare
    (unquoted) JSON number used to insert a [REDACTED_*] token in value
    position, corrupting the request.
    """
    import json
    from mitmproxy_addon import VibedomProxy

    proxy = VibedomProxy()

    phone = "8" + "00" + "555" + "1234"        # matches phone_us
    card = "4" + "111" + "1111" + "11111111"   # matches credit_card
    email = "alice" + chr(64) + "acme.io"  # non-exempt domain
    body = (
        '{"model":"x","messages":[{"role":"assistant","content":'
        '[{"type":"tool_use","input":{"since_ts":' + phone
        + ',"card_id":' + card + ',"author":"' + email + '"}}]}]}'
    )
    raw = body.encode('utf-8')

    flow = MagicMock()
    flow.request.host = "api.anthropic.com"
    flow.request.host_header = "api.anthropic.com"
    flow.request.content = raw
    flow.request.pretty_url = "https://api.anthropic.com/v1/messages"
    flow.request.url = "https://api.anthropic.com/v1/messages"
    flow.request.headers = {"Content-Type": "application/json"}

    proxy.request(flow)

    # Body must remain valid JSON
    scrubbed = json.loads(flow.request.content.decode('utf-8'))
    inp = scrubbed["messages"][0]["content"][0]["input"]
    # Bare numbers preserved; string email redacted
    assert inp["since_ts"] == int(phone)
    assert inp["card_id"] == int(card)
    assert inp["author"] == "[REDACTED_EMAIL]"


@patch('pathlib.Path.mkdir')
def test_non_json_body_falls_back_to_raw_scrub(mock_mkdir):
    """Non-JSON (e.g. form-encoded) bodies still get raw-text scrubbing."""
    from mitmproxy_addon import VibedomProxy

    proxy = VibedomProxy()
    email = "bob" + chr(64) + "acme.io"  # non-exempt domain
    raw = ("contact=" + email).encode('utf-8')

    flow = MagicMock()
    flow.request.host = "api.anthropic.com"
    flow.request.host_header = "api.anthropic.com"
    flow.request.content = raw
    flow.request.pretty_url = "https://api.anthropic.com/submit"
    flow.request.url = "https://api.anthropic.com/submit"
    flow.request.headers = {"Content-Type": "application/x-www-form-urlencoded"}

    proxy.request(flow)

    out = flow.request.content.decode('utf-8')
    assert email not in out
    assert "[REDACTED_EMAIL]" in out
