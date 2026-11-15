"""Initialize server-only VAPID credentials; never print or package the private key."""
import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if __name__ == '__main__':
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    args = parser.parse_args()
    folder = ROOT / 'var/push'
    folder.mkdir(parents=True, exist_ok=True)
    keypath = folder / 'vapid.pem'
    if keypath.exists():
        key = serialization.load_pem_private_key(keypath.read_bytes(), password=None)
    else:
        key = ec.generate_private_key(ec.SECP256R1())
        keypath.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        keypath.chmod(0o600)
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    (folder / 'config.json').write_text(json.dumps({'origin': args.origin, 'public_key': base64.urlsafe_b64encode(public).decode().rstrip('=')}), encoding='utf-8')
    print('Server notification credentials ready; private key retained locally.')
