import tempfile
from pathlib import Path
from vibedom.whitelist import load_whitelist, is_domain_allowed, create_default_whitelist

def test_load_whitelist():
    """Should load domains from file, ignoring comments"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("# Comment\napi.anthropic.com\n\ngithub.com\n")
        f.flush()

        domains = load_whitelist(Path(f.name))

        assert 'api.anthropic.com' in domains
        assert 'github.com' in domains
        assert len(domains) == 2

def test_is_domain_allowed():
    """Should check if domain is in whitelist"""
    whitelist = {'api.anthropic.com', 'github.com'}

    assert is_domain_allowed('api.anthropic.com', whitelist) is True
    assert is_domain_allowed('evil.com', whitelist) is False

def test_is_domain_allowed_subdomains():
    """Should allow subdomains of whitelisted domains"""
    whitelist = {'github.com'}

    assert is_domain_allowed('api.github.com', whitelist) is True
    assert is_domain_allowed('raw.githubusercontent.com', whitelist) is False

def test_create_default_whitelist():
    """Should create whitelist file with default domains"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)
        whitelist_path = config_dir / 'trusted_domains.txt'

        create_default_whitelist(config_dir)

        assert whitelist_path.exists()
        domains = load_whitelist(whitelist_path)
        assert 'api.anthropic.com' in domains
