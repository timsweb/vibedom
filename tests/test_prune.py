"""Tests for prune CLI command."""

import click
from pathlib import Path
from click.testing import CliRunner
from vibedom.cli import main


def test_prune_help():
    """Test prune command has help text."""
    runner = CliRunner()
    result = runner.invoke(main, ['prune', '--help'])
    assert result.exit_code == 0
    assert 'prune' in result.output.lower()
