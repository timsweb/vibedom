import subprocess
import tempfile
from pathlib import Path
import time
import shutil

def test_full_workflow():
    """Test complete git bundle workflow: init -> run -> stop."""
    # This is a manual integration test
    # Run with: pytest tests/test_integration.py -v -s

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / 'test-project'
        workspace.mkdir()

        # Create test git repository
        subprocess.run(['git', 'init'], cwd=workspace, check=True)
        subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=workspace, check=True)
        subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=workspace, check=True)

        # Create test files
        (workspace / 'README.md').write_text('# Test Project')
        (workspace / 'app.py').write_text('print("hello")')
        subprocess.run(['git', 'add', '.'], cwd=workspace, check=True)
        subprocess.run(['git', 'commit', '-m', 'Initial commit'], cwd=workspace, check=True)

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

            # Verify git repository exists in container
            result = subprocess.run([
                'docker', 'exec', container_name,
                'sh', '-c', 'cd /work/repo && git log --oneline'
            ], capture_output=True, text=True)
            assert result.returncode == 0
            assert 'Initial commit' in result.stdout

            # Make a commit in container
            subprocess.run([
                'docker', 'exec', container_name,
                'sh', '-c', 'cd /work/repo && echo "agent work" > agent.txt && git add . && git commit -m "Agent commit"'
            ], check=True)

            # Verify commit in container
            result = subprocess.run([
                'docker', 'exec', container_name,
                'sh', '-c', 'cd /work/repo && git log --oneline'
            ], capture_output=True, text=True)
            assert result.returncode == 0
            assert 'Agent commit' in result.stdout

            # Stop sandbox (creates bundle)
            result = subprocess.run([
                'vibedom', 'stop', str(workspace)
            ], input='n\n', text=True, capture_output=True)

            assert result.returncode == 0
            assert 'session complete!' in result.stdout.lower()

            # Extract bundle path from output
            bundle_path = None
            for line in result.stdout.split('\n'):
                if 'Bundle:' in line:
                    bundle_path = line.split('Bundle:')[1].strip()
                    break

            assert bundle_path is not None, "Bundle path not found in output"

            # Verify bundle exists
            bundle_file = Path(bundle_path)
            assert bundle_file.exists(), f"Bundle file not found: {bundle_path}"

            # Verify bundle is valid
            result = subprocess.run(['git', 'bundle', 'verify', bundle_path],
                                  capture_output=True, text=True)
            assert result.returncode == 0, f"Bundle verification failed: {result.stderr}"

        finally:
            # Cleanup on failure
            subprocess.run(['vibedom', 'stop', str(workspace)],
                          input='n\n', capture_output=True, text=True)
            # Remove test workspace
            if workspace.exists():
                shutil.rmtree(workspace, ignore_errors=True)

if __name__ == '__main__':
    test_full_workflow()
    print("✅ Integration test passed!")
