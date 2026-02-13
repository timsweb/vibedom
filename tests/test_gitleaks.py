import json
import tempfile
from pathlib import Path
from vibedom.gitleaks import scan_workspace, categorize_secret

def test_scan_workspace_clean():
    """Should return empty list for clean workspace"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / "clean.py").write_text("print('hello')")

        findings = scan_workspace(workspace)

        assert findings == []

def test_scan_workspace_with_secrets():
    """Should detect hardcoded secrets"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / ".env").write_text("DB_PASSWORD=secret123")

        findings = scan_workspace(workspace)

        assert len(findings) > 0
        assert any('DB_PASSWORD' in f['Match'] for f in findings)

def test_categorize_secret_low_risk():
    """Should categorize local dev secrets as low risk"""
    finding = {
        'File': '.env.local',
        'Match': 'DB_PASSWORD=root'
    }

    risk, reason = categorize_secret(finding)

    assert risk == 'LOW_RISK'
    assert 'local dev' in reason.lower()

def test_categorize_secret_high_risk():
    """Should categorize production secrets as high risk"""
    finding = {
        'File': 'config/production.php',
        'Match': 'sk_live_1234567890'
    }

    risk, reason = categorize_secret(finding)

    assert risk == 'HIGH_RISK'
    assert 'production' in reason.lower()
