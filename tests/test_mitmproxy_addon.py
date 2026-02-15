import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / 'vm'))


class MockRequest:
    """Mock HTTP request object."""
    def __init__(self):
        self.host: str = ""
        self.host_header: str = ""
        self.content: bytes | None = None
        self.pretty_url: str = ""
        self.url: str = ""
        self.headers: dict = {}
        self.method: str = "GET"


class MockHTTPFlow:
    """Mock HTTP flow object."""
    def __init__(self):
        self.request = MockRequest()
        self.response = None


@patch('pathlib.Path.mkdir')
def test_request_headers_pass_through(mock_mkdir):
    """Should allow Authorization header through (for API calls)."""
    from mitmproxy_addon import VibedomProxy

    proxy = VibedomProxy()

    flow = MockHTTPFlow()
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
