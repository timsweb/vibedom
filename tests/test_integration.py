import subprocess
import tempfile
from pathlib import Path
import time

def test_full_workflow():
    """Test complete workflow: init -> run -> stop."""
    # This is a manual integration test
    # Run with: pytest tests/test_integration.py -v -s

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / 'test-project'
        workspace.mkdir()

        # Create test files
        (workspace / 'README.md').write_text('# Test Project')
        (workspace / 'app.py').write_text('print("hello")')

        container_name = f'vibedom-{workspace.name}'

        try:
            # Run sandbox
            result = subprocess.run([
                'vibedom', 'run', str(workspace)
            ], input='c\n', text=True, capture_output=True)

            assert result.returncode == 0
            assert 'Sandbox running' in result.stdout

            # Wait a bit
            time.sleep(2)

            # Verify container is running
            result = subprocess.run([
                'docker', 'ps', '--filter', f'name={container_name}', '--format', '{{.Names}}'
            ], capture_output=True, text=True)

            assert container_name in result.stdout

            # Verify file mounting
            result = subprocess.run([
                'docker', 'exec', container_name, 'cat', '/work/app.py'
            ], capture_output=True, text=True)
            assert result.returncode == 0
            assert 'print("hello")' in result.stdout

            # Make a change
            subprocess.run([
                'docker', 'exec', container_name,
                'sh', '-c', 'echo "modified" > /work/app.py'
            ], check=True)

            # Stop sandbox
            result = subprocess.run([
                'vibedom', 'stop', str(workspace)
            ], input='n\n', text=True, capture_output=True)

            assert result.returncode == 0
            assert 'stopped' in result.stdout.lower()

        finally:
            # Cleanup on failure
            subprocess.run(['vibedom', 'stop', str(workspace)],
                          input='n\n', capture_output=True, text=True)

if __name__ == '__main__':
    test_full_workflow()
    print("✅ Integration test passed!")
