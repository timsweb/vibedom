"""SSH key generation for deploy keys."""

import subprocess
from pathlib import Path

def generate_deploy_key(key_path: Path) -> None:
    """Generate an ed25519 SSH keypair.

    Args:
        key_path: Path where private key will be saved (public key gets .pub suffix)
    """
    key_path.parent.mkdir(parents=True, exist_ok=True)

    # Get hostname for key comment
    hostname_result = subprocess.run(
        ["hostname"],
        capture_output=True,
        text=True,
        check=True
    )
    hostname = hostname_result.stdout.strip()

    subprocess.run([
        'ssh-keygen',
        '-t', 'ed25519',
        '-f', str(key_path),
        '-N', '',  # No passphrase
        '-C', f'vibedom@{hostname}'
    ], check=True, capture_output=True)

def get_public_key(key_path: Path) -> str:
    """Read public key content.

    Args:
        key_path: Path to private key (will append .pub)

    Returns:
        Public key content as string
    """
    pub_path = Path(f"{key_path}.pub")
    return pub_path.read_text().strip()
