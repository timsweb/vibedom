#!/usr/bin/env python3
"""vibedom CLI - Secure AI agent sandbox."""

import click

@click.group()
@click.version_option()
def main():
    """Secure AI agent sandbox for running Claude Code and OpenCode."""
    pass

@main.command()
def init():
    """Initialize vibedom (first-time setup)."""
    click.echo("Initializing vibedom...")

@main.command()
@click.argument('workspace', type=click.Path(exists=True))
def run(workspace):
    """Run AI agent in sandboxed environment."""
    click.echo(f"Starting sandbox for {workspace}...")

@main.command()
def stop():
    """Stop running sandbox session."""
    click.echo("Stopping sandbox...")

if __name__ == '__main__':
    main()
