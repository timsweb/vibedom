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


def make_scrubber():
    """Create scrubber with gitleaks patterns loaded."""
    from dlp_scrubber import DLPScrubber

    config_path = Path(__file__).parent.parent / 'lib' / 'vibedom' / 'config' / 'gitleaks.toml'
    return DLPScrubber(gitleaks_config=str(config_path))


def test_scrub_aws_key():
    """Should scrub AWS access key."""
    scrubber = make_scrubber()
    text = "aws_key = AKIAIOSFODNN7EXAMPLE"
    result = scrubber.scrub(text)

    assert "AKIAIOSFODNN7EXAMPLE" not in result.text
    assert result.was_scrubbed
    assert any(f.pattern_id == 'aws-access-key' for f in result.findings)


def test_scrub_stripe_key():
    """Should scrub Stripe API key."""
    scrubber = make_scrubber()
    text = '{"key": "sk_test_4eC39HqLyjWDarjtT1zdp7dc"}'
    result = scrubber.scrub(text)

    assert "sk_test_4eC39HqLyjWDarjtT1zdp7dc" not in result.text
    assert result.was_scrubbed


def test_scrub_email():
    """Should scrub email addresses."""
    scrubber = make_scrubber()
    text = "Contact: admin@company.com for help"
    result = scrubber.scrub(text)

    assert "admin@company.com" not in result.text
    assert "[REDACTED_EMAIL]" in result.text
    assert any(f.category == 'PII' for f in result.findings)


def test_scrub_private_key():
    """Should scrub private key headers."""
    scrubber = make_scrubber()
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow..."
    result = scrubber.scrub(text)

    assert "-----BEGIN RSA PRIVATE KEY-----" not in result.text
    assert result.was_scrubbed


def test_scrub_multiple_findings():
    """Should scrub multiple secrets in one text."""
    scrubber = make_scrubber()
    text = 'email=admin@corp.com&api_key=sk_live_abc123def456xyz789012345'
    result = scrubber.scrub(text)

    assert "admin@corp.com" not in result.text
    assert "sk_live_abc123def456xyz789012345" not in result.text
    assert len(result.findings) >= 2


def test_scrub_clean_text():
    """Should pass through clean text unchanged."""
    scrubber = make_scrubber()
    text = "Hello world, this is normal code: x = 42"
    result = scrubber.scrub(text)

    assert result.text == text
    assert not result.was_scrubbed
    assert len(result.findings) == 0


def test_scrub_preserves_json_structure():
    """Should preserve JSON structure after scrubbing."""
    import json
    scrubber = make_scrubber()

    original = json.dumps({
        "user": "admin@company.com",
        "message": "hello world",
        "count": 42
    })
    result = scrubber.scrub(original)

    parsed = json.loads(result.text)
    assert parsed["message"] == "hello world"
    assert parsed["count"] == 42
    assert "admin@company.com" not in parsed["user"]


def test_scrub_skips_oversized_text():
    """Should skip scrubbing for text exceeding size limit."""
    from dlp_scrubber import MAX_SCRUB_SIZE

    scrubber = make_scrubber()
    # Create text larger than MAX_SCRUB_SIZE
    text = "admin@company.com " * (MAX_SCRUB_SIZE // 10)
    result = scrubber.scrub(text)

    # Should return text unchanged (too large to scrub)
    assert result.text == text
    assert not result.was_scrubbed
