"""Mock mitmproxy module for testing."""

class HTTPResponse:
    """Mock HTTP response."""
    @staticmethod
    def make(status_code, body, headers):
        """Create a mock HTTP response."""
        return MockResponse(status_code, body, headers)


class MockResponse:
    """Mock response object."""
    def __init__(self, status_code, body, headers):
        self.status_code = status_code
        self.content = body
        self.headers = headers


class HTTPFlow:
    """Mock HTTP flow."""
    pass


class http:
    """Mock http module."""
    Response = HTTPResponse
    HTTPFlow = HTTPFlow
