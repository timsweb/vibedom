import pytest
import shutil
from pathlib import Path
from vibedom.vm import VMManager

@pytest.fixture
def test_workspace(tmp_path):
    """Create test workspace."""
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'test.txt').write_text('test')
    yield workspace

@pytest.fixture
def test_config(tmp_path):
    """Create test config directory."""
    config = tmp_path / 'config'
    config.mkdir()

    # Copy mitmproxy addon
    import vibedom
    addon_src = Path(vibedom.__file__).parent.parent.parent / 'vm' / 'mitmproxy_addon.py'
    if addon_src.exists():
        shutil.copy(addon_src, config / 'mitmproxy_addon.py')

    # Create whitelist with pypi.org
    (config / 'trusted_domains.txt').write_text('pypi.org\npython.org\n')

    yield config

def test_https_proxy_env_vars_set(test_workspace, test_config):
    """Proxy environment variables should be set in container."""
    vm = VMManager(test_workspace, test_config)

    try:
        vm.start()

        # Verify HTTP_PROXY set
        result = vm.exec(['sh', '-c', 'echo $HTTP_PROXY'])
        assert 'http://127.0.0.1:8080' in result.stdout

        # Verify HTTPS_PROXY set
        result = vm.exec(['sh', '-c', 'echo $HTTPS_PROXY'])
        assert 'http://127.0.0.1:8080' in result.stdout

        # Verify NO_PROXY set
        result = vm.exec(['sh', '-c', 'echo $NO_PROXY'])
        assert 'localhost' in result.stdout

    finally:
        vm.stop()

def test_https_request_succeeds(test_workspace, test_config):
    """HTTPS requests should work through explicit proxy."""
    vm = VMManager(test_workspace, test_config)

    try:
        vm.start()

        # Test HTTPS request to whitelisted domain
        result = vm.exec(['curl', '-v', '--max-time', '10', 'https://pypi.org/simple/'])

        # Should succeed (not timeout)
        assert result.returncode == 0, f"HTTPS request failed: {result.stderr}"

        # Should get successful response
        assert 'HTTP/2 200' in result.stderr or 'HTTP/1.1 200' in result.stderr

    finally:
        vm.stop()

def test_http_request_still_works(test_workspace, test_config):
    """HTTP requests should still work in explicit mode."""
    vm = VMManager(test_workspace, test_config)

    try:
        vm.start()

        # Test HTTP request
        result = vm.exec(['curl', '-v', '--max-time', '10', 'http://pypi.org/simple/'])

        assert result.returncode == 0
        assert 'HTTP/1.1 200' in result.stderr or 'HTTP/2 200' in result.stderr

    finally:
        vm.stop()

def test_https_whitelisting_enforced(test_workspace, test_config):
    """Non-whitelisted HTTPS domains should be blocked."""
    vm = VMManager(test_workspace, test_config)

    try:
        vm.start()

        # Test request to non-whitelisted domain
        result = vm.exec(['curl', '--max-time', '10', 'https://example.com'])

        # Should be blocked by proxy (403)
        assert '403' in result.stdout or '403' in result.stderr, \
            f"Expected 403 from proxy, got: stdout={result.stdout}, stderr={result.stderr}"

    finally:
        vm.stop()
