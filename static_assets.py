"""Optional release manifest: real immutable files, never a mutable URL alias."""
import hashlib
import json
import re
from pathlib import Path

PUBLIC_FILE = re.compile(r'(?:[\w-]+\.(?:css|js)|fonts/[\w-]+\.woff2|fonts/(?:Lato|NotoSansKR)-OFL\.txt|og/club-preview\.png)', re.ASCII)


def validate_static_assets(app, manifest_path=None):
    path = Path(manifest_path or Path(app.root_path) / 'asset-manifest.json')
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict):
        raise ValueError('Invalid static asset manifest')
    digest = manifest['digest']
    files = manifest['files']
    if (manifest.get('schema') != 1 or not re.fullmatch(r'[0-9a-f]{64}', digest)
            or not re.fullmatch(r'[0-9a-f]{40}', manifest['revision'])
            or manifest.get('prefix') != '_v/' + digest or not isinstance(files, dict) or not files):
        raise ValueError('Invalid static asset manifest')
    static = Path(app.static_folder).resolve()
    source = Path(app.root_path) / 'static'
    for name, entry in files.items():
        if (not PUBLIC_FILE.fullmatch(name) or not isinstance(entry, dict)
                or not re.fullmatch(r'[0-9a-f]{64}', entry['sha256'])):
            raise ValueError('Unexpected static asset path or digest')
        original = source / name
        versioned = static / manifest['prefix'] / name
        if not original.resolve().is_relative_to(source.resolve()) or not versioned.resolve().is_relative_to(static):
            raise ValueError('Static asset escapes its directory')
        content = original.read_bytes()
        # Git stores these source text files as LF; Windows development may use CRLF.
        if original.suffix in {'.css', '.js', '.txt'}:
            content = content.replace(b'\r\n', b'\n')
        immutable = versioned.read_bytes()
        if (hashlib.sha256(content).hexdigest() != entry['sha256']
                or hashlib.sha256(immutable).hexdigest() != entry['sha256']
                or len(immutable) != entry['bytes']):
            raise ValueError('Static asset release mismatch: ' + name)
    expected = ''.join(name + '\0' + files[name]['sha256'] + '\n' for name in sorted(files))
    if hashlib.sha256(expected.encode()).hexdigest() != digest:
        raise ValueError('Static asset set digest mismatch')
    return manifest


def install_static_assets(app, manifest_path=None):
    try:
        manifest = validate_static_assets(app, manifest_path)
    except (OSError, ValueError, KeyError, TypeError):
        # An optimization failure must not stop login or serve stale UI bytes.
        app.logger.warning('Static asset manifest unavailable or mismatched; using origin URLs')
        return
    if manifest is None:
        return
    files = manifest['files']

    @app.url_defaults
    def version_static_url(endpoint, values):
        name = values.get('filename')
        if endpoint == 'static' and name in files:
            values['filename'] = manifest['prefix'] + '/' + name

    app.extensions['static_asset_release'] = {'revision': manifest['revision'], 'digest': manifest['digest']}
