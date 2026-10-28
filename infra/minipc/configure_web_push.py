"""Explicitly approved host setup only; never rotates an existing VAPID identity."""
import base64
import os
from pathlib import Path
import stat
import tempfile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from dotenv import dotenv_values


def create_pair():
    private = ec.generate_private_key(ec.SECP256R1())
    raw = private.private_numbers().private_value.to_bytes(32, 'big')
    public = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip('=')
    return encode(raw), encode(public)


def configure(path):
    if os.name != 'posix' or os.geteuid() != 0:
        raise RuntimeError('Run as root on the approved Ubuntu host')
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise RuntimeError('Expected a root-owned private regular environment file')
    cfg = dotenv_values(path, interpolate=False)
    private, public = cfg.get('WEB_PUSH_PRIVATE_KEY'), cfg.get('WEB_PUSH_PUBLIC_KEY')
    if private or public:
        if not private or not public:
            raise RuntimeError('Partial VAPID configuration; do not overwrite')
        key = ec.derive_private_key(int.from_bytes(base64.urlsafe_b64decode(private+'='*(-len(private)%4)), 'big'), ec.SECP256R1())
        expected = base64.urlsafe_b64encode(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).decode().rstrip('=')
        if public != expected:
            raise RuntimeError('Existing VAPID key mismatch; do not overwrite')
        print('VAPID identity already configured; unchanged')
        return
    private, public = create_pair()
    content = path.read_text() + f'\nWEB_PUSH_PRIVATE_KEY={private}\nWEB_PUSH_PUBLIC_KEY={public}\n'
    fd, name = tempfile.mkstemp(prefix='.push-env-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    print('VAPID identity added; secret values were not printed')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--env', required=True)
    args = parser.parse_args()
    configure(args.env)
