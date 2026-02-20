def test_mitmdump_available():
    """mitmdump must be available on PATH when vibedom is installed."""
    import shutil
    assert shutil.which('mitmdump') is not None, \
        "mitmdump not found — add mitmproxy to pyproject.toml dependencies"


import socket
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
from vibedom.proxy import ProxyManager


def test_find_free_port_returns_usable_port():
    """OS-assigned port should be bindable."""
    from vibedom.proxy import _find_free_port
    port = _find_free_port()
    assert isinstance(port, int)
    assert 1024 < port < 65535


def test_proxy_manager_start_returns_port(tmp_path):
    """start() should launch mitmdump and return the port."""
    session_dir = tmp_path / 'session'
    session_dir.mkdir()
    config_dir = tmp_path / 'config'
    config_dir.mkdir()

    manager = ProxyManager(session_dir=session_dir, config_dir=config_dir)

    with patch('subprocess.Popen') as mock_popen, \
         patch('vibedom.proxy._find_free_port', return_value=18765):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        with patch('vibedom.proxy._wait_for_proxy', return_value=True):
            port = manager.start()

    assert port == 18765
    assert mock_popen.called
    cmd = mock_popen.call_args[0][0]
    assert 'mitmdump' in cmd[0]
    assert '--listen-port' in cmd
    assert str(port) in cmd


def test_proxy_manager_stop_terminates_process(tmp_path):
    """stop() should terminate the mitmdump process."""
    session_dir = tmp_path / 'session'
    session_dir.mkdir()
    config_dir = tmp_path / 'config'
    config_dir.mkdir()

    manager = ProxyManager(session_dir=session_dir, config_dir=config_dir)

    with patch('subprocess.Popen') as mock_popen, \
         patch('vibedom.proxy._find_free_port', return_value=18765):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        with patch('vibedom.proxy._wait_for_proxy', return_value=True):
            manager.start()

        manager.stop()
        assert mock_proc.terminate.called


def test_proxy_manager_reload_sends_sighup(tmp_path):
    """reload() should send SIGHUP to the mitmdump process."""
    import signal as signal_module
    session_dir = tmp_path / 'session'
    session_dir.mkdir()
    config_dir = tmp_path / 'config'
    config_dir.mkdir()

    manager = ProxyManager(session_dir=session_dir, config_dir=config_dir)

    with patch('subprocess.Popen') as mock_popen, \
         patch('vibedom.proxy._find_free_port', return_value=18765):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        with patch('vibedom.proxy._wait_for_proxy', return_value=True):
            manager.start()

        manager.reload()
        mock_proc.send_signal.assert_called_once_with(signal_module.SIGHUP)


def test_proxy_manager_passes_paths_as_env(tmp_path):
    """mitmdump should receive config paths via environment variables."""
    session_dir = tmp_path / 'session'
    session_dir.mkdir()
    config_dir = tmp_path / 'config'
    config_dir.mkdir()

    manager = ProxyManager(session_dir=session_dir, config_dir=config_dir)

    with patch('subprocess.Popen') as mock_popen, \
         patch('vibedom.proxy._find_free_port', return_value=18765):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        with patch('vibedom.proxy._wait_for_proxy', return_value=True):
            manager.start()

    env = mock_popen.call_args[1]['env']
    assert 'VIBEDOM_WHITELIST_PATH' in env
    assert 'VIBEDOM_NETWORK_LOG_PATH' in env
    assert 'VIBEDOM_GITLEAKS_CONFIG' in env


def test_ca_cert_path_returns_none_before_start(tmp_path):
    """ca_cert_path should return None when cert doesn't exist yet."""
    manager = ProxyManager(session_dir=tmp_path / 'session', config_dir=tmp_path / 'config')
    assert manager.ca_cert_path is None


def test_ca_cert_path_returns_path_when_cert_exists(tmp_path):
    """ca_cert_path should return path when cert file exists."""
    config_dir = tmp_path / 'config'
    mitmproxy_dir = config_dir / 'mitmproxy'
    mitmproxy_dir.mkdir(parents=True)
    cert = mitmproxy_dir / 'mitmproxy-ca-cert.pem'
    cert.write_text('fake cert')

    manager = ProxyManager(session_dir=tmp_path / 'session', config_dir=config_dir)
    assert manager.ca_cert_path == cert
