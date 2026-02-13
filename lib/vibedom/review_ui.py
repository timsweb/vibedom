"""Interactive UI for reviewing Gitleaks findings."""

import click
from typing import List, Dict, Any
from vibedom.gitleaks import categorize_secret

def review_findings(findings: List[Dict[str, Any]]) -> bool:
    """Show findings to user and get approval to continue.

    Args:
        findings: List of Gitleaks findings

    Returns:
        True if user approves continuing, False otherwise
    """
    if not findings:
        return True

    click.echo("\n" + "⚠️ " * 20)
    click.secho(f"Found {len(findings)} potential secret(s):", fg='yellow', bold=True)
    click.echo("")

    for i, finding in enumerate(findings, 1):
        risk, reason = categorize_secret(finding)

        # Color-code by risk
        if risk == 'HIGH_RISK':
            color = 'red'
            icon = '🔴'
        elif risk == 'MEDIUM_RISK':
            color = 'yellow'
            icon = '🟡'
        else:
            color = 'white'
            icon = '⚪'

        click.echo(f"{i}. {finding.get('File', 'unknown')}:{finding.get('StartLine', '?')}")
        click.secho(f"   {icon} {risk}: {reason}", fg=color)
        click.echo(f"   Match: {finding.get('Match', '')[:80]}...")
        click.echo("")

    click.echo("Options:")
    click.echo("  [c] Continue anyway (I've reviewed these)")
    click.echo("  [x] Cancel and fix")

    choice = click.prompt("Your choice", type=click.Choice(['c', 'x']), default='x')

    return choice == 'c'
