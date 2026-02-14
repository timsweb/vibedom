import tempfile
from pathlib import Path


def test_load_gitleaks_patterns():
    """Should load and compile regex patterns from gitleaks.toml."""
    from dlp_scrubber import DLPScrubber

    config_path = Path(__file__).parent.parent / 'lib' / 'vibedom' / 'config' / 'gitleaks.toml'
    scrubber = DLPScrubber(gitleaks_config=str(config_path))

    # Should have loaded secret patterns from TOML
    assert len(scrubber.secret_patterns) > 0

    # Each pattern should have required fields
    for p in scrubber.secret_patterns:
        assert p.id, "Pattern must have an ID"
        assert p.regex, "Pattern must have a compiled regex"
        assert p.placeholder, "Pattern must have a placeholder"


def test_load_from_missing_config():
    """Should work with no gitleaks config (PII patterns only)."""
    from dlp_scrubber import DLPScrubber

    scrubber = DLPScrubber(gitleaks_config=None)

    assert len(scrubber.secret_patterns) == 0
    assert len(scrubber.pii_patterns) > 0


def test_load_from_empty_config():
    """Should handle empty/minimal TOML config."""
    from dlp_scrubber import DLPScrubber

    with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
        f.write('title = "Empty"\n')
        f.flush()

        scrubber = DLPScrubber(gitleaks_config=f.name)
        assert len(scrubber.secret_patterns) == 0
