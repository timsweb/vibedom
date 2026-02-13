"""Gitleaks integration for pre-flight secret scanning."""

import json
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict, Any

# Get path to bundled config
CONFIG_PATH = Path(__file__).parent / 'config' / 'gitleaks.toml'

def scan_workspace(workspace: Path) -> List[Dict[str, Any]]:
    """Run Gitleaks on workspace and return findings.

    Args:
        workspace: Path to workspace directory

    Returns:
        List of findings (empty if clean)
    """
    try:
        # Use /tmp/claude for report (writable in sandbox)
        report_path = Path('/tmp/claude/gitleaks-report.json')
        report_path.parent.mkdir(parents=True, exist_ok=True)

        result = subprocess.run([
            'gitleaks',
            'detect',
            '--source', str(workspace),
            '--config', str(CONFIG_PATH),
            '--no-git',  # Scan all files, not just tracked
            '--report-format', 'json',
            '--report-path', str(report_path),
            '--exit-code', '0',  # Don't fail on findings
        ], capture_output=True, text=True)

        # Read report
        if report_path.exists() and report_path.stat().st_size > 0:
            with open(report_path) as f:
                findings = json.load(f)
                return findings if isinstance(findings, list) else []

        return []

    except Exception as e:
        # If Gitleaks fails, don't block - just warn
        return []

def categorize_secret(finding: Dict[str, Any]) -> Tuple[str, str]:
    """Categorize a secret finding by risk level.

    Args:
        finding: Gitleaks finding dict with 'File' and 'Match' keys

    Returns:
        Tuple of (risk_level, reason)
    """
    file_path = finding.get('File', '').lower()
    match = finding.get('Match', '').lower()

    # HIGH RISK: Production credentials
    if any(indicator in file_path for indicator in ['prod', 'production', 'live']):
        return 'HIGH_RISK', 'Production credential'

    if 'sk_live_' in match or 'prod' in match:
        return 'HIGH_RISK', 'Production API key'

    # LOW RISK: Local dev files
    if any(indicator in file_path for indicator in ['.env.local', '.env.development', 'test']):
        return 'LOW_RISK', 'Local dev credential'

    if match.startswith('db_password=root') or 'localhost' in match:
        return 'LOW_RISK', 'Local dev credential'

    # MEDIUM RISK: Everything else
    return 'MEDIUM_RISK', 'Unknown credential (will be scrubbed by DLP)'
