import tempfile
from pathlib import Path
from vibedom.ssh_keys import generate_deploy_key, get_public_key

def test_generate_deploy_key():
    """Should generate ed25519 keypair"""
    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = Path(tmpdir) / "id_ed25519_vibedom"

        generate_deploy_key(key_path)

        assert key_path.exists()
        assert (key_path.parent / f"{key_path.name}.pub").exists()

        # Verify it's ed25519
        with open(f"{key_path}.pub") as f:
            pubkey = f.read()
            assert pubkey.startswith("ssh-ed25519")

def test_get_public_key():
    """Should read public key content"""
    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = Path(tmpdir) / "id_ed25519_vibedom"
        generate_deploy_key(key_path)

        pubkey = get_public_key(key_path)

        assert pubkey.startswith("ssh-ed25519")
        assert len(pubkey) > 50
