from click.testing import CliRunner
from vibedom.review_ui import review_findings

def test_review_findings_clean():
    """Should return True for clean workspace"""
    result = review_findings([])
    assert result is True

def test_review_findings_with_secrets_cancel(monkeypatch):
    """Should return False when user cancels"""
    monkeypatch.setattr('click.prompt', lambda *args, **kwargs: 'x')

    findings = [{'File': '.env', 'Match': 'SECRET=123', 'StartLine': 1}]
    result = review_findings(findings)

    assert result is False

def test_review_findings_with_secrets_continue(monkeypatch):
    """Should return True when user continues"""
    monkeypatch.setattr('click.prompt', lambda *args, **kwargs: 'c')

    findings = [{'File': '.env.local', 'Match': 'DB_PASSWORD=root', 'StartLine': 1}]
    result = review_findings(findings)

    assert result is True
