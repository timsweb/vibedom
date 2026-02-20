#!/usr/bin/env python3
"""vibedom CLI - Secure AI agent sandbox."""

import sys
import subprocess
import click
from pathlib import Path
from typing import Optional
from vibedom.ssh_keys import generate_deploy_key, get_public_key
from vibedom.gitleaks import scan_workspace
from vibedom.review_ui import review_findings
from vibedom.whitelist import create_default_whitelist
from vibedom.vm import VMManager
from vibedom.session import Session, SessionCleanup, SessionRegistry


def _execute_deletions(to_delete: list, skipped: int, force: bool, dry_run: bool) -> None:
    """Execute or preview deletions for prune/housekeeping commands.

    Args:
        to_delete: List of Session objects to delete
        skipped: Count of sessions skipped (still running)
        force: Delete without prompting if True
        dry_run: Preview without deleting if True
    """
    deleted = 0
    for session in to_delete:
        name = session.display_name
        if dry_run:
            click.echo(f"Would delete: {name}")
            deleted += 1
        elif force or click.confirm(f"Delete {name}?", default=True):
            SessionCleanup._delete_session(session.session_dir)
            click.echo(f"Deleted {name}")
            deleted += 1

    if dry_run:
        click.echo(f"\nWould delete {deleted} session(s), skip {skipped} (still running)")
    else:
        click.echo(f"\nDeleted {deleted} session(s), skipped {skipped} (still running)")

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
    click.echo("  Edit this file to add your internal domains")

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

        click.echo("\n✅ Sandbox running!")
        click.echo(f"📋 Session ID: {session.state.session_id}")
        click.echo(f"📁 Session: {session.session_dir}")
        click.echo(f"📦 Live repo: {session.session_dir / 'repo'}")
        click.echo("\n💡 To test changes mid-session:")
        click.echo(f"  git remote add vibedom-live {session.session_dir / 'repo'}")
        click.echo("  git fetch vibedom-live")
        click.echo("\n🛑 To stop:")
        click.echo(f"  vibedom stop {session.state.session_id}")

    except Exception as e:
        session.log_event(f'Error: {e}', level='ERROR')
        session.state.mark_abandoned(session.session_dir)
        click.secho(f"❌ Error: {e}", fg='red')
        sys.exit(1)

@main.command()
@click.argument('session_id', required=False)
def stop(session_id):
    """Stop a sandbox session and create git bundle.

    SESSION_ID is a session ID (e.g. myapp-happy-turing) or workspace name.
    If omitted, auto-selects the only running session or prompts.
    """
    logs_dir = Path.home() / '.vibedom' / 'logs'
    registry = SessionRegistry(logs_dir)

    session = registry.resolve(session_id, running_only=(session_id is None))

    if session.state.status != 'running':
        click.secho(
            f"Session '{session.state.session_id}' is not running "
            f"(status: {session.state.status})",
            fg='yellow'
        )
        sys.exit(1)

    # Create bundle + finalize (updates state.json)
    click.echo("Creating git bundle...")
    session.finalize()

    try:
        config_dir = Path.home() / '.vibedom'
        vm = VMManager(Path(session.state.workspace), config_dir,
                       session_dir=session.session_dir,
                       runtime=session.state.runtime)
        vm.stop()
    except Exception as e:
        click.secho(f"❌ Error stopping container: {e}", fg='red')
        sys.exit(1)

    if session.state.status == 'complete' and session.state.bundle_path:
        bundle_path = Path(session.state.bundle_path)
        click.echo("\n✅ Session complete!")
        click.echo(f"📋 Session ID: {session.state.session_id}")
        click.echo(f"📦 Bundle: {bundle_path}")
        click.echo(f"\n📋 To review: vibedom review {session.state.session_id}")
        click.echo(f"🔀 To merge:  vibedom merge {session.state.session_id}")
    else:
        click.secho("⚠️  Bundle creation failed", fg='yellow')
        click.echo(f"📁 Live repo available: {session.session_dir / 'repo'}")


@main.command('list')
def list_sessions():
    """List all sessions with their status."""
    logs_dir = Path.home() / '.vibedom' / 'logs'
    if not logs_dir.exists():
        click.echo("No sessions found")
        return

    registry = SessionRegistry(logs_dir)
    sessions = registry.all()

    if not sessions:
        click.echo("No sessions found")
        return

    # Header
    click.echo(f"{'ID':<40} {'WORKSPACE':<20} {'STATUS':<12} {'STARTED'}")
    click.echo('-' * 85)
    for session in sessions:
        workspace_name = Path(session.state.workspace).name
        click.echo(
            f"{session.state.session_id:<40} "
            f"{workspace_name:<20} "
            f"{session.state.status:<12} "
            f"{session.age_str}"
        )


@main.command('attach')
@click.argument('session_id', required=False)
def attach(session_id):
    """Open a shell in a running session's workspace (/work/repo).

    SESSION_ID is a session ID or workspace name.
    If omitted, auto-selects the only running session or prompts.
    """
    logs_dir = Path.home() / '.vibedom' / 'logs'
    registry = SessionRegistry(logs_dir)
    running = registry.running()

    session = registry.resolve(session_id, running_only=True, sessions=running)

    if session.state.status != 'running':
        click.secho(
            f"Session '{session.state.session_id}' is not running "
            f"(status: {session.state.status})",
            fg='red'
        )
        sys.exit(1)

    runtime_cmd = 'container' if session.state.runtime == 'apple' else 'docker'
    cmd = [runtime_cmd, 'exec', '-it', '-w', '/work/repo',
           session.state.container_name, 'bash']
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        click.secho("❌ Failed to attach to container", fg='red')
        sys.exit(1)
    except FileNotFoundError:
        click.secho(f"❌ Error: {runtime_cmd} command not found", fg='red')
        sys.exit(1)


@main.command('review')
@click.argument('session_id')
@click.option('--branch', help='Branch to review from bundle (default: current branch)')
def review(session_id: str, branch: Optional[str]) -> None:
    """Review changes from a session bundle.

    SESSION_ID is a session ID (e.g. myapp-happy-turing) or workspace name.
    """
    logs_dir = Path.home() / '.vibedom' / 'logs'
    registry = SessionRegistry(logs_dir)
    session_obj = registry.find(session_id)

    if not session_obj:
        click.secho(f"❌ No session found for '{session_id}'", fg='red')
        sys.exit(1)

    workspace_path = Path(session_obj.state.workspace)
    session_dir = session_obj.session_dir

    # Check if workspace is a git repository
    try:
        subprocess.run(
            ['git', '-C', str(workspace_path), 'rev-parse', '--git-dir'],
            capture_output=True, check=True
        )
    except subprocess.CalledProcessError:
        click.secho(f"❌ Error: {workspace_path} is not a git repository", fg='red')
        sys.exit(1)

    # Check if session is still running
    if session_obj.is_container_running():
        click.secho("❌ Session is still running. Stop it first:", fg='red')
        click.echo(f"  vibedom stop {session_obj.state.session_id}")
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
            click.secho("❌ Error: Could not determine current branch", fg='red')
            sys.exit(1)

    # Generate remote name from session ID
    session_id = session_obj.state.session_id
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
            click.secho("❌ Error: Failed to add git remote", fg='red')
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
        click.secho("❌ Error: Failed to fetch bundle", fg='red')
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
    click.echo(f"\n💡 To merge: vibedom merge {session_obj.state.session_id}")


@main.command('merge')
@click.argument('session_id')
@click.option('--branch', help='Branch to merge from bundle (default: current branch)')
@click.option('--merge', 'keep_history', is_flag=True,
              help='Keep full commit history (default: squash)')
def merge(session_id: str, branch: Optional[str], keep_history: bool) -> None:
    """Merge changes from a session bundle (squash by default).

    SESSION_ID is a session ID (e.g. myapp-happy-turing) or workspace name.
    """
    logs_dir = Path.home() / '.vibedom' / 'logs'
    registry = SessionRegistry(logs_dir)
    session_obj = registry.find(session_id)

    if not session_obj:
        click.secho(f"❌ No session found for '{session_id}'", fg='red')
        sys.exit(1)

    workspace_path = Path(session_obj.state.workspace)

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
        click.secho("❌ Cannot merge: you have uncommitted changes", fg='red')
        click.echo("Commit or stash them first, then try again.")
        sys.exit(1)

    if session_obj.is_container_running():
        click.secho("❌ Session is still running. Stop it first:", fg='red')
        click.echo(f"  vibedom stop {session_obj.state.session_id}")
        sys.exit(1)

    session_dir = session_obj.session_dir

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
            click.secho("❌ Error: Could not determine current branch", fg='red')
            sys.exit(1)

    # Generate remote name from session ID
    session_id = session_obj.state.session_id
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
            click.secho("❌ Error: Failed to add git remote", fg='red')
            sys.exit(1)

        # Fetch bundle
        click.echo("Fetching bundle...")
        try:
            subprocess.run(
                ['git', '-C', str(workspace_path), 'fetch', remote_name],
                check=True
            )
        except subprocess.CalledProcessError:
            click.secho("❌ Error: Failed to fetch bundle", fg='red')
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
        click.secho("❌ Merge failed", fg='red')
        click.echo("Resolve conflicts manually and commit.")
        # Don't remove remote - user might need it
        sys.exit(1)

    # Clean up remote
    click.echo(f"Cleaning up remote: {remote_name}")
    subprocess.run(
        ['git', '-C', str(workspace_path), 'remote', 'remove', remote_name],
        check=True
    )

    click.echo("\n✅ Merge complete!")


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
def prune(force: bool, dry_run: bool) -> None:
    """Remove all session directories without running containers."""
    logs_dir = Path.home() / '.vibedom' / 'logs'
    if not logs_dir.exists():
        click.echo("No sessions to delete")
        return
    registry = SessionRegistry(logs_dir)
    sessions = registry.all()
    to_delete = SessionCleanup._filter_not_running(sessions)
    skipped = len(sessions) - len(to_delete)

    if not to_delete:
        click.echo("No sessions to delete")
        return

    click.echo(f"Found {len(to_delete)} session(s) to delete")
    _execute_deletions(to_delete, skipped, force, dry_run)


@main.command()
@click.option('--days', '-d', default=7, help='Delete sessions older than N days')
@click.option('--force', '-f', is_flag=True, help='Delete without prompting')
@click.option('--dry-run', is_flag=True, help='Preview without deleting')
def housekeeping(days: int, force: bool, dry_run: bool) -> None:
    """Remove sessions older than N days without running containers."""
    logs_dir = Path.home() / '.vibedom' / 'logs'
    if not logs_dir.exists():
        click.echo(f"No sessions older than {days} days")
        return
    registry = SessionRegistry(logs_dir)
    sessions = registry.all()
    old_sessions = SessionCleanup._filter_by_age(sessions, days)
    to_delete = SessionCleanup._filter_not_running(old_sessions)
    skipped = len(old_sessions) - len(to_delete)

    if not to_delete:
        click.echo(f"No sessions older than {days} days")
        return

    click.echo(f"Found {len(to_delete)} session(s) older than {days} days")
    _execute_deletions(to_delete, skipped, force, dry_run)


if __name__ == '__main__':
    main()
