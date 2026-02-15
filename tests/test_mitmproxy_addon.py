import sys
from pathlib import Path
from unittest.mock import Mock, patch

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

    flow = Mock(spec=http.HTTPFlow)
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
