#!/usr/bin/env python3
"""vibedom CLI - Secure AI agent sandbox."""

import sys
import click
from pathlib import Path
from vibedom.ssh_keys import generate_deploy_key, get_public_key
from vibedom.gitleaks import scan_workspace
from vibedom.review_ui import review_findings
from vibedom.whitelist import create_default_whitelist
from vibedom.vm import VMManager
from vibedom.session import Session

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
def run(workspace):
    """Run AI agent in sandboxed environment."""
    workspace_path = Path(workspace).resolve()
    config_dir = Path.home() / '.vibedom'
    logs_dir = config_dir / 'logs'

    # Create session
    session = Session(workspace_path, logs_dir)
    session.log_event('Starting sandbox...')

    try:
        # Pre-flight scan
        click.echo(f"🔍 Pre-flight scan: {workspace_path}")
        session.log_event('Running Gitleaks scan')

        findings = scan_workspace(workspace_path)

        if not review_findings(findings):
            session.log_event('Cancelled by user', level='WARN')
            session.finalize()
            click.secho("❌ Cancelled by user", fg='red')
            sys.exit(1)

        session.log_event(f'Pre-flight complete ({len(findings)} findings approved)')
        click.echo("✅ Pre-flight complete")

        # Start VM
        click.echo(f"🚀 Starting sandbox...")
        session.log_event('Starting VM')

        vm = VMManager(workspace_path, config_dir)
        vm.start()

        session.log_event('VM started successfully')
        click.echo(f"✅ Sandbox running!")
        click.echo(f"   Workspace: {workspace_path}")
        click.echo(f"   Logs: {session.session_dir}")
        click.echo("")
        click.echo("To stop: vibedom stop")
        click.echo("To inspect: docker exec -it vibedom-{} sh".format(workspace_path.name))

    except Exception as e:
        session.log_event(f'Error: {e}', level='ERROR')
        session.finalize()
        click.secho(f"❌ Error: {e}", fg='red')
        sys.exit(1)

@main.command()
@click.argument('workspace', required=False)
def stop(workspace):
    """Stop running sandbox session."""
    if workspace:
        workspace_path = Path(workspace).resolve()
        container_name = f"vibedom-{workspace_path.name}"
    else:
        # Stop all vibedom containers
        import subprocess
        result = subprocess.run([
            'docker', 'ps', '-a', '--filter', 'name=vibedom-', '--format', '{{.Names}}'
        ], capture_output=True, text=True)

        containers = result.stdout.strip().split('\n')
        if not containers or not containers[0]:
            click.echo("No running sandboxes found")
            return

        for container in containers:
            click.echo(f"Stopping {container}...")
            subprocess.run(['docker', 'rm', '-f', container], capture_output=True)

        click.echo("✅ All sandboxes stopped")
        return

    # Stop specific container
    config_dir = Path.home() / '.vibedom'
    vm = VMManager(workspace_path, config_dir)

    # Get diff before stopping
    click.echo("Generating diff...")
    diff = vm.get_diff()

    if diff:
        click.echo("\n" + "="*60)
        click.echo("Changes made in sandbox:")
        click.echo("="*60)
        click.echo(diff[:2000])  # Show first 2000 chars
        if len(diff) > 2000:
            click.echo(f"\n... ({len(diff) - 2000} more characters)")
        click.echo("="*60)

        apply = click.confirm("\nApply these changes to workspace?", default=False)

        if apply:
            # Apply patch
            import subprocess
            import tempfile

            with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as f:
                f.write(diff)
                patch_file = f.name

            try:
                with open(patch_file) as f:
                    subprocess.run([
                        'patch', '-d', str(workspace_path), '-p2'
                    ], stdin=f, check=True)
                click.echo("✅ Changes applied")
            except subprocess.CalledProcessError as e:
                click.secho(f"❌ Failed to apply patch: {e}", fg='red')
            finally:
                Path(patch_file).unlink()
    else:
        click.echo("No changes made")

    vm.stop()
    click.echo("✅ Sandbox stopped")

if __name__ == '__main__':
    main()
