import tempfile
from pathlib import Path
import pytest
from vibedom.vm import VMManager

@pytest.fixture
def test_workspace():
    """Create a temporary workspace for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / 'workspace'
        workspace.mkdir()
        (workspace / 'test.txt').write_text('hello')
        yield workspace

@pytest.fixture
def test_config():
    """Create a temporary config directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)
        yield config_dir

def test_vm_start_stop(test_workspace, test_config):
    """Should start and stop VM successfully."""
    vm = VMManager(test_workspace, test_config)

    vm.start()

    # Check container is running
    result = vm.exec(['echo', 'test'])
    assert result.returncode == 0
    assert 'test' in result.stdout

    vm.stop()

def test_vm_overlay_filesystem(test_workspace, test_config):
    """Should have overlay filesystem mounted at /work."""
    vm = VMManager(test_workspace, test_config)

    vm.start()

    # Write to overlay
    vm.exec(['sh', '-c', 'echo "modified" > /work/test.txt'])

    # Check original is unchanged
    original = test_workspace / 'test.txt'
    assert original.read_text() == 'hello'

    # Check overlay has change
    result = vm.exec(['cat', '/work/test.txt'])
    assert 'modified' in result.stdout

    vm.stop()

def test_vm_get_diff(test_workspace, test_config):
    """Should generate diff between workspace and overlay."""
    vm = VMManager(test_workspace, test_config)

    vm.start()

    # Modify file in overlay
    vm.exec(['sh', '-c', 'echo "modified" > /work/test.txt'])

    diff = vm.get_diff()

    assert 'test.txt' in diff
    assert '+modified' in diff
    assert '-hello' in diff

    vm.stop()
