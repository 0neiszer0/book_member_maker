"""Build a NoCloud seed ISO from a public SSH key; no private keys in the ISO."""
import argparse
import io
from pathlib import Path
import uuid

import pycdlib
import yaml


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--public-key', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Output already exists; inspect before replacing.')
    public_key = args.public_key.read_text(encoding='ascii').strip()
    if not public_key.startswith('ssh-ed25519 ') or '\n' in public_key:
        raise SystemExit('An Ed25519 SSH public key is required.')
    config = yaml.safe_load(Path(__file__).with_name('autoinstall.yaml.example').read_text())
    config['autoinstall']['ssh']['authorized-keys'] = [public_key]
    user_data = ('#cloud-config\n' + yaml.safe_dump(config, sort_keys=False)).encode()
    meta_data = (f'instance-id: bookmembers-{uuid.uuid4()}\nlocal-hostname: bookmembers-ubuntu\n').encode()
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, joliet=3, rock_ridge='1.09', vol_ident='CIDATA')
    for data, iso_name, name in ((user_data, 'USERDATA.;1', 'user-data'), (meta_data, 'METADATA.;1', 'meta-data')):
        iso.add_fp(io.BytesIO(data), len(data), iso_path='/' + iso_name,
                   rr_name=name, joliet_path='/' + name)
    iso.write(str(args.output))
    iso.close()
    check = pycdlib.PyCdlib()
    check.open(str(args.output))
    readback = io.BytesIO()
    check.get_file_from_iso_fp(readback, rr_path='/user-data')
    check.close()
    if readback.getvalue() != user_data:
        raise SystemExit('Seed ISO readback mismatch.')
    print('CIDATA ISO created and read back; contains public key only.')


if __name__ == '__main__':
    main()
