#!/usr/bin/env python3
"""vibedom CLI - Secure AI agent sandbox."""

import click
from pathlib import Path
from vibedom.ssh_keys import generate_deploy_key, get_public_key
from vibedom.gitleaks import scan_workspace
from vibedom.review_ui import review_findings
from vibedom.whitelist import create_default_whitelist

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

    click.echo(f"🔍 Pre-flight scan: {workspace_path}")

    # Run Gitleaks
    findings = scan_workspace(workspace_path)

    # Review findings
    if not review_findings(findings):
        click.secho("❌ Cancelled by user", fg='red')
        raise click.Abort()

    click.echo("✅ Pre-flight complete")
    click.echo(f"🚀 Starting sandbox for {workspace_path}...")

@main.command()
def stop():
    """Stop running sandbox session."""
    click.echo("Stopping sandbox...")

if __name__ == '__main__':
    main()
