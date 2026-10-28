import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from flask import Flask, url_for
from static_assets import install_static_assets, validate_static_assets


class StaticAssetReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = Flask(__name__, root_path=str(self.root), static_folder='static')
        self.manifest = self.release({'lms.css': b'body{color:black}', 'fonts/Test.woff2': b'font'})

    def release(self, contents):
        files = {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)} for name, data in contents.items()}
        digest = hashlib.sha256(''.join(name+'\0'+files[name]['sha256']+'\n' for name in sorted(files)).encode()).hexdigest()
        manifest = dict(schema=1, revision='a'*40, digest=digest, prefix='_v/'+digest, files=files)
        for name, data in contents.items():
            for path in [self.root/'static'/name, self.root/'static'/manifest['prefix']/name]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        (self.root/'asset-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        return manifest

    def test_versioned_urls_preserve_queries_and_relative_fonts(self):
        install_static_assets(self.app)
        with self.app.test_request_context():
            prefix = '/static/'+self.manifest['prefix']+'/'
            self.assertEqual(url_for('static', filename='lms.css', v='7'), prefix+'lms.css?v=7')
            self.assertEqual(url_for('static', filename='fonts/Test.woff2', _external=True), 'http://localhost'+prefix+'fonts/Test.woff2')
            self.assertEqual(url_for('static', filename='private.txt'), '/static/private.txt')
            self.assertEqual(url_for('static', filename=self.manifest['prefix']+'/lms.css'), prefix+'lms.css')
        with self.app.test_client() as client:
            self.assertEqual(client.get(prefix+'fonts/Test.woff2', buffered=True).data, b'font')

    def test_missing_manifest_keeps_original_urls(self):
        (self.root/'asset-manifest.json').unlink()
        install_static_assets(self.app)
        with self.app.test_request_context():
            self.assertEqual(url_for('static', filename='lms.css'), '/static/lms.css')

    def test_source_or_versioned_mismatch_falls_back(self):
        for path in [self.root/'static/lms.css', self.root/'static'/self.manifest['prefix']/'lms.css']:
            original = path.read_bytes()
            path.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                validate_static_assets(self.app)
            install_static_assets(self.app)
            with self.app.test_request_context():
                self.assertEqual(url_for('static', filename='lms.css'), '/static/lms.css')
            path.write_bytes(original)

    def test_malformed_manifest_does_not_break_application_start(self):
        for content in ['[]', '{', '{"schema":1,"digest":null,"files":[]}']:
            (self.root/'asset-manifest.json').write_text(content, encoding='utf-8')
            install_static_assets(self.app)
            self.assertNotIn('static_asset_release', self.app.extensions)

    def test_older_real_files_survive_new_release_without_aliasing(self):
        old_prefix = self.manifest['prefix']
        new = self.release({'lms.css': b'body{color:blue}'})
        install_static_assets(self.app)
        with self.app.test_client() as client:
            self.assertEqual(client.get('/static/'+old_prefix+'/lms.css', buffered=True).data, b'body{color:black}')
            self.assertEqual(client.get('/static/'+new['prefix']+'/lms.css', buffered=True).data, b'body{color:blue}')
            self.assertEqual(client.get('/static/_v/'+'0'*64+'/lms.css').status_code, 404)

    def test_public_icons_use_immutable_urls_and_normalize_svg_line_endings(self):
        manifest = self.release({'icons/favicon.svg': b'<svg/>\n', 'icons/favicon-32.png': b'png'})
        (self.root/'static/icons/favicon.svg').write_bytes(b'<svg/>\r\n')
        install_static_assets(self.app)
        with self.app.test_request_context():
            self.assertEqual(url_for('static', filename='icons/favicon.svg'),
                             '/static/'+manifest['prefix']+'/icons/favicon.svg')
        with self.app.test_client() as client:
            response = client.get('/static/'+manifest['prefix']+'/icons/favicon.svg', buffered=True)
            self.assertEqual(response.mimetype, 'image/svg+xml')
            self.assertEqual(response.data, b'<svg/>\n')

    def test_icon_allowlist_does_not_publish_arbitrary_images_or_uploads(self):
        for name in ('icons/private.png', 'icons/member.svg', 'uploads/favicon.svg'):
            with self.subTest(name=name):
                self.release({name: b'private'})
                with self.assertRaises(ValueError):
                    validate_static_assets(self.app)

if __name__ == '__main__':
    unittest.main()
