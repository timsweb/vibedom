import tempfile
from pathlib import Path
import time
import json
import pytest
from vibedom.vm import VMManager
from vibedom.whitelist import create_default_whitelist

@pytest.fixture
def vm_with_proxy():
    """Start VM with mitmproxy configured."""
    with tempfile.TemporaryDirectory() as workspace_dir:
        with tempfile.TemporaryDirectory() as config_dir:
            workspace = Path(workspace_dir)
            config = Path(config_dir)

            # Create whitelist
            create_default_whitelist(config)

            vm = VMManager(workspace, config)
            vm.start()

            # Give mitmproxy time to start
            time.sleep(2)

            yield vm

            vm.stop()

def test_mitmproxy_is_running(vm_with_proxy):
    """Should have mitmdump process running."""
    result = vm_with_proxy.exec(['ps', 'aux'])
    assert result.returncode == 0
    assert 'mitmdump' in result.stdout

def test_proxy_env_vars_configured(vm_with_proxy):
    """Should have proxy environment variables configured system-wide."""
    result = vm_with_proxy.exec(['sh', '-c', 'echo $HTTPS_PROXY'])
    assert result.returncode == 0
    assert 'http://127.0.0.1:8080' in result.stdout

def test_proxy_logs_whitelisted_requests(vm_with_proxy):
    """Should log whitelisted domain requests as allowed."""
    # Make request to whitelisted domain
    vm_with_proxy.exec(['curl', '-s', '-m', '5', 'http://github.com'])

    time.sleep(1)  # Let mitmproxy write log

    # Check log
    result = vm_with_proxy.exec(['cat', '/var/log/vibedom/network.jsonl'])
    assert result.returncode == 0
    assert 'github.com' in result.stdout

    # Parse last log entry
    lines = result.stdout.strip().split('\n')
    last_entry = json.loads(lines[-1])
    assert last_entry['host'] == 'github.com'
    assert last_entry['allowed'] is True

def test_proxy_detects_non_whitelisted_domains(vm_with_proxy):
    """Should detect and mark non-whitelisted domains as not allowed."""
    # Make request to non-whitelisted domain
    vm_with_proxy.exec(['curl', '-s', '-m', '5', 'http://example.org'])

    time.sleep(1)  # Let mitmproxy write log

    # Check log
    result = vm_with_proxy.exec(['cat', '/var/log/vibedom/network.jsonl'])
    assert result.returncode == 0

    # Find entry for example.org
    lines = result.stdout.strip().split('\n')
    for line in lines:
        entry = json.loads(line)
        if 'example.org' in entry['host']:
            assert entry['allowed'] is False
            return

    pytest.fail("No log entry found for example.org")
