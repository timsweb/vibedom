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
from vibedom.session import Session, SessionCleanup
from datetime import datetime, timedelta


def _format_session_info(session: dict) -> str:
    """Format session information for display.

    Args:
        session: Session dictionary with 'workspace', 'timestamp', 'dir' keys

    Returns:
        Formatted string: "workspace_name (X days old) - session_dir_name"
    """
    workspace_name = session['workspace'].name if session['workspace'] else 'unknown'
    age = datetime.now() - session['timestamp']

    if age.days > 0:
        age_str = f"{age.days} day{'s' if age.days > 1 else ''} old"
    elif age.seconds >= 3600:
        hours = age.seconds // 3600
        age_str = f"{hours} hour{'s' if hours > 1 else ''} old"
    elif age.seconds >= 60:
        minutes = age.seconds // 60
        age_str = f"{minutes} minute{'s' if minutes > 1 else ''} old"
    else:
        age_str = f"{age.seconds} second{'s' if age.seconds > 1 else ''} old"

    return f"{workspace_name} ({age_str}) - {session['dir'].name}"


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
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple'],
              case_sensitive=False), default='auto',
              help='Container runtime (auto-detect, docker, or apple)')
def run(workspace, runtime):
    """Run AI agent in sandboxed environment."""
    workspace_path = Path(workspace).resolve()
    if not workspace_path.is_dir():
        click.secho(f"❌ Error: {workspace_path} is not a directory", fg='red')
        sys.exit(1)

    logs_dir = Path.home() / '.vibedom' / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Resolve runtime before creating session so state.json has correct value
    try:
        resolved_runtime, _ = VMManager._detect_runtime(
            runtime if runtime != 'auto' else None
        )
    except RuntimeError as e:
        click.secho(f"❌ {e}", fg='red')
        sys.exit(1)

    session = Session.start(workspace_path, resolved_runtime, logs_dir)
    session.log_event('Starting sandbox...')

    try:
        click.echo("🔍 Scanning for secrets...")
        findings = scan_workspace(workspace_path)

        if not review_findings(findings):
            session.log_event('Cancelled by user', level='WARN')
            session.state.mark_abandoned(session.session_dir)
            click.secho("❌ Cancelled", fg='yellow')
            sys.exit(1)

        click.echo("🚀 Starting sandbox...")
        config_dir = Path.home() / '.vibedom'
        vm = VMManager(workspace_path, config_dir,
                       session_dir=session.session_dir,
                       runtime=resolved_runtime)
        vm.start()

        session.log_event('VM started successfully')

        click.echo(f"\n✅ Sandbox running!")
        click.echo(f"📋 Session ID: {session.state.session_id}")
        click.echo(f"📁 Session: {session.session_dir}")
        click.echo(f"📦 Live repo: {session.session_dir / 'repo'}")
        click.echo(f"\n💡 To test changes mid-session:")
        click.echo(f"  git remote add vibedom-live {session.session_dir / 'repo'}")
        click.echo(f"  git fetch vibedom-live")
        click.echo(f"\n🛑 To stop:")
        click.echo(f"  vibedom stop {session.state.session_id}")

    except Exception as e:
        session.log_event(f'Error: {e}', level='ERROR')
        session.state.mark_abandoned(session.session_dir)
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
def review(workspace: str, branch: Optional[str], runtime: str) -> None:
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
        try:
            subprocess.run(
                ['git', '-C', str(workspace_path), 'remote', 'add', remote_name, str(bundle_path)],
                check=True
            )
        except subprocess.CalledProcessError:
            click.secho(f"❌ Error: Failed to add git remote", fg='red')
            sys.exit(1)
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
        capture_output=True, text=True, check=True
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
        capture_output=True, text=True, check=True
    )
    if result.stdout:
        click.echo(result.stdout)
    else:
        click.echo("  (no changes)")

    # Show merge hint
    click.echo(f"\n💡 To merge: vibedom merge {workspace_path}")


@main.command('merge')
@click.argument('workspace', type=click.Path(exists=True))
@click.option('--branch', help='Branch to merge from bundle (default: current branch)')
@click.option('--merge', 'keep_history', is_flag=True,
              help='Keep full commit history (default: squash)')
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple'], case_sensitive=False),
              default='auto', help='Container runtime (auto-detect, docker, or apple)')
def merge(workspace: str, branch: Optional[str], keep_history: bool, runtime: str) -> None:
    """Merge changes from most recent session (squash by default)."""
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

    # Check for uncommitted changes
    result = subprocess.run(
        ['git', '-C', str(workspace_path), 'status', '--porcelain'],
        capture_output=True, text=True
    )
    if result.stdout.strip():
        click.secho(f"❌ Cannot merge: you have uncommitted changes", fg='red')
        click.echo("Commit or stash them first, then try again.")
        sys.exit(1)

    # Find latest session
    logs_dir = Path.home() / '.vibedom' / 'logs'
    session_dir = find_latest_session(workspace_path, logs_dir)

    if not session_dir:
        click.secho(f"❌ No session found for {workspace_path.name}", fg='red')
        click.echo(f"Run 'vibedom run {workspace_path}' first.")
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

    # Generate remote name
    session_id = session_dir.name.replace('session-', '')
    remote_name = f'vibedom-{session_id}'

    # Check if remote exists (might have been added by review)
    result = subprocess.run(
        ['git', '-C', str(workspace_path), 'remote', 'get-url', remote_name],
        capture_output=True
    )

    if result.returncode != 0:
        # Add remote
        click.echo(f"Adding remote: {remote_name}")
        try:
            subprocess.run(
                ['git', '-C', str(workspace_path), 'remote', 'add', remote_name, str(bundle_path)],
                check=True
            )
        except subprocess.CalledProcessError:
            click.secho(f"❌ Error: Failed to add git remote", fg='red')
            sys.exit(1)

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
    else:
        click.echo(f"Using existing remote: {remote_name}")

    # Perform merge
    remote_branch = f'{remote_name}/{branch}'

    try:
        if keep_history:
            # Regular merge (keep commits)
            click.echo(f"Merging {remote_branch} (keeping commit history)...")
            subprocess.run(
                ['git', '-C', str(workspace_path), 'merge', remote_branch],
                check=True
            )
        else:
            # Squash merge (default)
            click.echo(f"Merging {remote_branch} (squash)...")
            subprocess.run(
                ['git', '-C', str(workspace_path), 'merge', '--squash', remote_branch],
                check=True
            )

            # Create commit with summary message
            commit_msg = f"""Apply changes from vibedom session

Session: {session_id}
Bundle: {bundle_path}
Branch: {branch}

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"""

            subprocess.run(
                ['git', '-C', str(workspace_path), 'commit', '-m', commit_msg],
                check=True
            )
    except subprocess.CalledProcessError:
        click.secho(f"❌ Merge failed", fg='red')
        click.echo("Resolve conflicts manually and commit.")
        # Don't remove remote - user might need it
        sys.exit(1)

    # Clean up remote
    click.echo(f"Cleaning up remote: {remote_name}")
    subprocess.run(
        ['git', '-C', str(workspace_path), 'remote', 'remove', remote_name],
        check=True
    )

    click.echo(f"\n✅ Merge complete!")


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


@main.command()
@click.option('--force', '-f', is_flag=True, help='Delete without prompting')
@click.option('--dry-run', is_flag=True, help='Preview without deleting')
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple']),
              default='auto', help='Container runtime (auto-detect, docker, or apple)')
def prune(force: bool, dry_run: bool, runtime: str) -> None:
    """Remove all session directories without running containers."""
    logs_dir = Path.home() / '.vibedom' / 'logs'
    sessions = SessionCleanup.find_all_sessions(logs_dir, runtime)
    to_delete = SessionCleanup._filter_not_running(sessions)
    skipped = len(sessions) - len(to_delete)

    if not to_delete:
        click.echo("No sessions to delete")
        return

    click.echo(f"Found {len(to_delete)} session(s) to delete")

    deleted = 0
    for session in to_delete:
        session_info = _format_session_info(session)
        if dry_run:
            click.echo(f"Would delete: {session_info}")
            deleted += 1
        elif force or click.confirm(f"Delete {session_info}?", default=True):
            SessionCleanup._delete_session(session['dir'])
            click.echo(f"✓ Deleted {session_info}")
            deleted += 1

    if dry_run:
        click.echo(f"\nWould delete {deleted} session(s), skip {skipped} (still running)")
    else:
        click.echo(f"\n✅ Deleted {deleted} session(s), skipped {skipped} (still running)")


@main.command()
@click.option('--days', '-d', default=7, help='Delete sessions older than N days')
@click.option('--force', '-f', is_flag=True, help='Delete without prompting')
@click.option('--dry-run', is_flag=True, help='Preview without deleting')
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple']),
              default='auto', help='Container runtime (auto-detect, docker, or apple)')
def housekeeping(days: int, force: bool, dry_run: bool, runtime: str) -> None:
    """Remove sessions older than N days."""
    logs_dir = Path.home() / '.vibedom' / 'logs'
    sessions = SessionCleanup.find_all_sessions(logs_dir, runtime)
    old_sessions = SessionCleanup._filter_by_age(sessions, days)
    to_delete = SessionCleanup._filter_not_running(old_sessions)
    skipped = len(old_sessions) - len(to_delete)

    if not to_delete:
        click.echo(f"No sessions older than {days} days")
        return

    click.echo(f"Found {len(to_delete)} session(s) older than {days} days")

    deleted = 0
    for session in to_delete:
        session_info = _format_session_info(session)
        if dry_run:
            click.echo(f"Would delete: {session_info}")
            deleted += 1
        elif force or click.confirm(f"Delete {session_info}?", default=True):
            SessionCleanup._delete_session(session['dir'])
            click.echo(f"✓ Deleted {session_info}")
            deleted += 1

    if dry_run:
        click.echo(f"\nWould delete {deleted} session(s), skip {skipped} (still running)")
    else:
        click.echo(f"\n✅ Deleted {deleted} session(s), skipped {skipped} (still running)")


if __name__ == '__main__':
    main()
