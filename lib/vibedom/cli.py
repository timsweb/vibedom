#!/usr/bin/env python3
"""vibedom CLI - Secure AI agent sandbox."""

import sys
import subprocess
import tempfile
import click
from pathlib import Path
from typing import Optional
from vibedom.ssh_keys import generate_deploy_key, get_public_key
from vibedom.gitleaks import scan_workspace
from vibedom.review_ui import review_findings
from vibedom.whitelist import create_default_whitelist
from vibedom.vm import VMManager
from vibedom.session import Session


def find_latest_session(workspace: Path, logs_dir: Path) -> Optional[Path]:
    """Find most recent session directory for a workspace.

    Args:
        workspace: Workspace path to search for
        logs_dir: Base logs directory (e.g., ~/.vibedom/logs)

    Returns:
        Path to session directory if found, None otherwise
    """
    if not logs_dir.exists():
        return None

    for session_dir in sorted(logs_dir.glob('session-*'), reverse=True):
        session_log = session_dir / 'session.log'
        if session_log.exists():
            log_content = session_log.read_text()
            if str(workspace.resolve()) in log_content:
                return session_dir
    return None

@click.group()
@click.version_option()
def main():
    """Secure AI agent sandbox for running Claude Code and OpenCode."""
    pass

@main.command()
def init():
    """Initialize vibedom (first-time setup)."""
    click.echo("🔧 Initializing vibedom...")

    # Create config directory
    config_dir = Path.home() / '.vibedom'
    keys_dir = config_dir / 'keys'
    keys_dir.mkdir(parents=True, exist_ok=True)

    # Generate deploy key
    key_path = keys_dir / 'id_ed25519_vibedom'
    if key_path.exists():
        click.echo(f"✓ Deploy key already exists at {key_path}")
    else:
        click.echo("Generating SSH deploy key...")
        generate_deploy_key(key_path)
        click.echo(f"✓ Deploy key created at {key_path}")

    # Show public key
    pubkey = get_public_key(key_path)
    click.echo("\n" + "="*60)
    click.echo("📋 Add this public key to your GitLab account:")
    click.echo("   Settings → SSH Keys")
    click.echo("="*60)
    click.echo(pubkey)
    click.echo("="*60 + "\n")

    # Create whitelist
    click.echo("Creating network whitelist...")
    whitelist_path = create_default_whitelist(config_dir)
    click.echo(f"✓ Whitelist created at {whitelist_path}")
    click.echo(f"  Edit this file to add your internal domains")

    click.echo("\n✅ Initialization complete!")

@main.command()
@click.argument('workspace', type=click.Path(exists=True))
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple'], case_sensitive=False),
              default='auto', help='Container runtime (auto-detect, docker, or apple)')
def run(workspace, runtime):
    """Run AI agent in sandboxed environment."""
    workspace_path = Path(workspace).resolve()
    if not workspace_path.is_dir():
        click.secho(f"❌ Error: {workspace_path} is not a directory", fg='red')
        sys.exit(1)
    
    # Initialize session
    logs_dir = Path.home() / '.vibedom' / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)

    session = Session(workspace_path, logs_dir)
    session.log_event('Starting sandbox...')

    try:
        # Scan for secrets
        click.echo("🔍 Scanning for secrets...")
        findings = scan_workspace(workspace_path)

        if not review_findings(findings):
            session.log_event('Cancelled by user', level='WARN')
            session.finalize()
            click.secho("❌ Cancelled", fg='yellow')
            sys.exit(1)

        # Start VM with session directory
        click.echo("🚀 Starting sandbox...")
        config_dir = Path.home() / '.vibedom'
        vm = VMManager(workspace_path, config_dir, session_dir=session.session_dir, runtime=runtime if runtime != 'auto' else None)
        vm.start()

        session.log_event('VM started successfully')

        click.echo(f"\n✅ Sandbox running!")
        click.echo(f"📁 Session: {session.session_dir}")
        click.echo(f"📦 Live repo: {session.session_dir / 'repo'}")
        click.echo(f"\n💡 To test changes mid-session:")
        click.echo(f"  git remote add vibedom-live {session.session_dir / 'repo'}")
        click.echo(f"  git fetch vibedom-live")
        click.echo(f"\n🛑 To stop:")
        click.echo(f"  vibedom stop {workspace_path}")

        # Don't finalize yet - session is still active

    except Exception as e:
        session.log_event(f'Error: {e}', level='ERROR')
        session.finalize()
        click.secho(f"❌ Error: {e}", fg='red')
        sys.exit(1)

@main.command()
@click.argument('workspace', type=click.Path(exists=True), required=False)
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple'], case_sensitive=False),
              default='auto', help='Container runtime (auto-detect, docker, or apple)')
def stop(workspace, runtime):
    """Stop sandbox and create git bundle.

    If workspace provided, stops that specific sandbox.
    If no workspace provided, stops all vibedom containers.
    """
    if workspace is None:
        # Stop all vibedom containers
        try:
            runtime, runtime_cmd = VMManager._detect_runtime(runtime if runtime != 'auto' else None)
        except RuntimeError as e:
            click.secho(f"❌ {e}", fg='red')
            sys.exit(1)

        try:
            if runtime == 'apple':
                result = subprocess.run(
                    ['container', 'list', '--all', '--format', '{{.Names}}'],
                    capture_output=True, text=True, check=True,
                )
            else:
                result = subprocess.run(
                    ['docker', 'ps', '-a', '--filter', 'name=vibedom-',
                     '--format', '{{.Names}}'],
                    capture_output=True, text=True, check=True,
                )

            containers = [
                name.strip() for name in result.stdout.split('\n')
                if name.strip() and name.strip().startswith('vibedom-')
            ]

            if not containers:
                click.echo("No vibedom containers running")
                return

            click.echo(f"Stopping {len(containers)} container(s)...")
            for name in containers:
                if runtime == 'apple':
                    subprocess.run(['container', 'stop', name], capture_output=True)
                    subprocess.run(['container', 'delete', '--force', name],
                                   capture_output=True)
                else:
                    subprocess.run(['docker', 'rm', '-f', name], capture_output=True)

            click.echo(f"✅ Stopped {len(containers)} container(s)")

        except subprocess.CalledProcessError as e:
            click.secho(f"❌ Error stopping containers: {e}", fg='red')
            sys.exit(1)
        return

    # Stop specific workspace
    workspace_path = Path(workspace).resolve()

    # Find active session
    logs_dir = Path.home() / '.vibedom' / 'logs'
    session = None

    if logs_dir.exists():
        # Find most recent session for this workspace
        for session_dir in sorted(logs_dir.glob('session-*'), reverse=True):
            session_log = session_dir / 'session.log'
            if session_log.exists():
                # Check if this session is for our workspace
                log_content = session_log.read_text()
                if str(workspace_path) in log_content:
                    session = Session(workspace_path, logs_dir)
                    session.session_dir = session_dir
                    break

    vm = VMManager(workspace_path, Path.home() / '.vibedom', session_dir=session.session_dir if session else None, runtime=runtime if runtime != 'auto' else None)

    if session:
        # Create bundle before stopping
        click.echo("Creating git bundle...")
        bundle_path = session.create_bundle()

        # Finalize session
        session.finalize()

        # Stop VM
        vm.stop()

        # Show user how to review
        if bundle_path:
            # Get current branch name from workspace
            try:
                current_branch = subprocess.run(
                    ['git', '-C', str(workspace_path), 'rev-parse', '--abbrev-ref', 'HEAD'],
                    capture_output=True, text=True, check=True
                ).stdout.strip()
            except subprocess.CalledProcessError:
                current_branch = 'main'

            click.echo(f"\n✅ Session complete!")
            click.echo(f"📦 Bundle: {bundle_path}")
            click.echo(f"\n📋 To review changes:")
            click.echo(f"  git remote add vibedom-xyz {bundle_path}")
            click.echo(f"  git fetch vibedom-xyz")
            click.echo(f"  git log vibedom-xyz/{current_branch}")
            click.echo(f"  git diff {current_branch}..vibedom-xyz/{current_branch}")
            click.echo(f"\n🔀 To merge into your feature branch (keep commits):")
            click.echo(f"  git merge vibedom-xyz/{current_branch}")
            click.echo(f"\n🔀 To merge (squash):")
            click.echo(f"  git merge --squash vibedom-xyz/{current_branch}")
            click.echo(f"  git commit -m 'Apply changes from vibedom session'")
            click.echo(f"\n🚀 Push for peer review:")
            click.echo(f"  git push origin {current_branch}")
            click.echo(f"\n🧹 Cleanup:")
            click.echo(f"  git remote remove vibedom-xyz")
        else:
            click.secho(f"⚠️  Bundle creation failed", fg='yellow')
            click.echo(f"📁 Live repo available: {session.session_dir / 'repo'}")
            click.echo(f"\nYou can still add it as a remote:")
            click.echo(f"  git remote add vibedom-live {session.session_dir / 'repo'}")
    else:
        # No session found, just stop container
        vm.stop()
        click.echo("✅ Container stopped")


@main.command('shell')
@click.argument('workspace', type=click.Path(exists=True))
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple'], case_sensitive=False),
              default='auto', help='Container runtime (auto-detect, docker, or apple)')
def shell(workspace: str, runtime: str) -> None:
    """Open shell in container's working directory (/work/repo)."""
    workspace_path = Path(workspace).resolve()

    if not workspace_path.is_dir():
        click.secho(f"❌ Error: {workspace_path} is not a directory", fg='red')
        sys.exit(1)

    # Detect runtime
    try:
        _, runtime_cmd = VMManager._detect_runtime(
            runtime if runtime != 'auto' else None
        )
    except RuntimeError as e:
        click.secho(f"❌ {e}", fg='red')
        sys.exit(1)

    # Build container name
    container_name = f'vibedom-{workspace_path.name}'

    # Build exec command
    cmd = [
        runtime_cmd, 'exec',
        '-it',
        '-w', '/work/repo',
        container_name,
        'bash'
    ]

    # Execute (give user interactive shell)
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        click.secho(f"❌ Container not running", fg='red')
        click.echo(f"Start it with: vibedom run {workspace_path}")
        sys.exit(1)
    except FileNotFoundError:
        click.secho(f"❌ Error: {runtime_cmd} command not found", fg='red')
        sys.exit(1)


@main.command('review')
@click.argument('workspace', type=click.Path(exists=True))
@click.option('--branch', help='Branch to review from bundle (default: current branch)')
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple'], case_sensitive=False),
              default='auto', help='Container runtime (auto-detect, docker, or apple)')
def review(workspace: str, branch: str, runtime: str) -> None:
    """Review changes from most recent session."""
    workspace_path = Path(workspace).resolve()

    if not workspace_path.is_dir():
        click.secho(f"❌ Error: {workspace_path} is not a directory", fg='red')
        sys.exit(1)

    # Check if workspace is a git repository
    try:
        subprocess.run(
            ['git', '-C', str(workspace_path), 'rev-parse', '--git-dir'],
            capture_output=True, check=True
        )
    except subprocess.CalledProcessError:
        click.secho(f"❌ Error: {workspace_path} is not a git repository", fg='red')
        sys.exit(1)

    # Find latest session
    logs_dir = Path.home() / '.vibedom' / 'logs'
    session_dir = find_latest_session(workspace_path, logs_dir)

    if not session_dir:
        click.secho(f"❌ No session found for {workspace_path.name}", fg='red')
        click.echo(f"Run 'vibedom run {workspace_path}' first.")
        sys.exit(1)

    # Check if session is still running
    container_name = f'vibedom-{workspace_path.name}'
    try:
        _, runtime_cmd = VMManager._detect_runtime(runtime if runtime != 'auto' else None)
    except RuntimeError as e:
        click.secho(f"❌ {e}", fg='red')
        sys.exit(1)

    # Check if container is running
    result = subprocess.run(
        [runtime_cmd, 'ps', '-q', '--filter', f'name={container_name}'],
        capture_output=True, text=True
    )
    if result.stdout.strip():
        click.secho(f"❌ Session is still running", fg='red')
        click.echo(f"Stop it first: vibedom stop {workspace_path}")
        sys.exit(1)

    # Check if bundle exists
    bundle_path = session_dir / 'repo.bundle'
    if not bundle_path.exists():
        click.secho(f"❌ Bundle not found at {bundle_path}", fg='red')
        click.echo("Session may have failed or been deleted.")
        sys.exit(1)

    # Get current branch or use --branch argument
    if not branch:
        try:
            result = subprocess.run(
                ['git', '-C', str(workspace_path), 'rev-parse', '--abbrev-ref', 'HEAD'],
                capture_output=True, text=True, check=True
            )
            branch = result.stdout.strip()
        except subprocess.CalledProcessError:
            click.secho(f"❌ Error: Could not determine current branch", fg='red')
            sys.exit(1)

    # Generate remote name from session timestamp
    session_id = session_dir.name.replace('session-', '')
    remote_name = f'vibedom-{session_id}'

    # Check if remote already exists
    result = subprocess.run(
        ['git', '-C', str(workspace_path), 'remote', 'get-url', remote_name],
        capture_output=True
    )

    if result.returncode != 0:
        # Add remote
        click.echo(f"Adding remote: {remote_name}")
        subprocess.run(
            ['git', '-C', str(workspace_path), 'remote', 'add', remote_name, str(bundle_path)],
            check=True
        )
    else:
        click.echo(f"Using existing remote: {remote_name}")

    # Fetch bundle
    click.echo("Fetching bundle...")
    try:
        subprocess.run(
            ['git', '-C', str(workspace_path), 'fetch', remote_name],
            check=True
        )
    except subprocess.CalledProcessError:
        click.secho(f"❌ Error: Failed to fetch bundle", fg='red')
        sys.exit(1)

    # Show session info
    click.echo(f"\n✅ Session: {session_dir.name}")
    click.echo(f"📦 Bundle: {bundle_path}")
    click.echo(f"🌿 Branch: {branch}\n")

    # Show commit log
    click.echo("📝 Commits:")
    result = subprocess.run(
        ['git', '-C', str(workspace_path), 'log', '--oneline',
         f'{branch}..{remote_name}/{branch}'],
        capture_output=True, text=True
    )
    if result.stdout:
        click.echo(result.stdout)
    else:
        click.echo("  (no new commits)")

    # Show diff
    click.echo("\n📊 Changes:")
    result = subprocess.run(
        ['git', '-C', str(workspace_path), 'diff',
         f'{branch}..{remote_name}/{branch}'],
        capture_output=True, text=True
    )
    if result.stdout:
        click.echo(result.stdout)
    else:
        click.echo("  (no changes)")

    # Show merge hint
    click.echo(f"\n💡 To merge: vibedom merge {workspace_path}")


@main.command('reload-whitelist')
@click.argument('workspace', type=click.Path(exists=True))
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple']), default='auto',
              help='Container runtime to use (auto-detects by default)')
def reload_whitelist(workspace: str, runtime: str) -> None:
    """Reload domain whitelist without restarting container.

    After editing ~/.vibedom/config/trusted_domains.txt, use this command
    to reload the whitelist in the running container.
    """
    workspace_path = Path(workspace).resolve()
    container_name = f'vibedom-{workspace_path.name}'

    # Determine runtime command
    if runtime == 'auto':
        try:
            detected_runtime, runtime_cmd = VMManager._detect_runtime()
        except RuntimeError as e:
            click.secho(f"❌ {e}", fg='red')
            sys.exit(1)
    elif runtime == 'docker':
        runtime_cmd = 'docker'
    elif runtime == 'apple':
        runtime_cmd = 'container'

    # Send SIGHUP to mitmdump process
    result = subprocess.run(
        [runtime_cmd, 'exec', container_name, 'pkill', '-HUP', 'mitmdump'],
        capture_output=True, text=True
    )

    if result.returncode == 0:
        click.echo(f"✅ Reloaded whitelist for {workspace_path.name}")
    else:
        click.secho(f"❌ Failed to reload: {result.stderr}", fg='red')
        sys.exit(1)


if __name__ == '__main__':
    main()
