import os
import unittest
from unittest.mock import Mock, patch
from flask import Flask
from storage_media import browser_storage_url, install_storage_media, image_session


class StorageMediaTests(unittest.TestCase):
    def app(self, enabled=True, upstream='http://127.0.0.1:55480'):
        app = Flask(__name__)
        with patch.dict(os.environ, {'LOCAL_STORAGE_PROXY':str(enabled), 'SUPABASE_URL':upstream}):
            install_storage_media(app)
        return app

    def response(self, status=200, mime='image/webp', chunks=(b'webp',)):
        value = Mock(status_code=status, headers={'Content-Type':mime})
        value.iter_content.return_value = iter(chunks)
        value.__enter__ = Mock(return_value=value)
        value.__exit__ = Mock(return_value=None)
        return value

    def test_hosted_urls_and_missing_local_route_unchanged(self):
        app = self.app(False)
        with app.test_request_context():
            self.assertEqual(browser_storage_url('https://example.test/object'), 'https://example.test/object')
        self.assertEqual(app.test_client().get('/media/storage/public/book-covers/a.webp').status_code, 404)
        with app.test_request_context(), self.assertRaises(ValueError):
            browser_storage_url('http://127.0.0.1:55480/storage/v1/object/public/book-covers/a.webp')
        with image_session() as session:
            self.assertFalse(session.trust_env)

    def test_loopback_configuration_only(self):
        for upstream in ['http://example.test:55480', 'http://localhost:55480', 'http://127.0.0.1:55480/rest/v1', 'http://user:pw@127.0.0.1:55480']:
            with self.subTest(upstream=upstream), self.assertRaises(ValueError):
                self.app(upstream=upstream)

    def test_signed_url_is_same_origin_without_leaking_internal_host(self):
        app = self.app()
        with app.test_request_context():
            value = browser_storage_url('http://127.0.0.1:55480/storage/v1/object/sign/board-uploads/posts/1/a.png?token=a.b-c_d')
            self.assertEqual(value, '/media/storage/sign/board-uploads/posts/1/a.png?token=a.b-c_d')
            for bad in ['https://evil.test/storage/v1/object/public/book-covers/a.webp',
                        'http://127.0.0.1:55480/rest/v1/members',
                        'http://127.0.0.1:55480/storage/v1/object/sign/board-uploads/a.png?token=a&token=b']:
                with self.assertRaises(ValueError):
                    browser_storage_url(bad)

    def test_public_cover_and_private_signature_have_separate_cache_rules(self):
        client = self.app().test_client()
        for path, cache in [('/media/storage/public/book-covers/a.webp', 'public, max-age=86400'),
                            ('/media/storage/sign/board-uploads/posts/1/a.png?token=a.b.c', 'private, no-store')]:
            with patch('storage_media.requests.Session.get', return_value=self.response()) as get:
                response = client.get(path, headers={'Cookie':'session=secret', 'Authorization':'secret'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['Cache-Control'], cache)
                self.assertNotIn('headers', get.call_args.kwargs)
                self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_private_public_bypass_traversal_and_api_paths_cannot_fetch(self):
        client = self.app().test_client()
        paths = ['/media/storage/public/board-uploads/a.png', '/media/storage/sign/board-uploads/a.png',
                 '/media/storage/public/book-covers/../a.webp', '/media/storage/public/book-covers/%252e%252e/a.webp',
                 '/media/storage/public/book-covers/a.webp?url=http://evil.test',
                 '/media/storage/rest/members/a', '/media/storage/sign/board-uploads/a.png?token=a&token=b']
        with patch('storage_media.requests.Session.get') as get:
            for path in paths:
                self.assertIn(client.get(path).status_code, {403, 404})
            get.assert_not_called()

    def test_redirect_active_content_oversize_and_errors_fail_closed(self):
        client = self.app().test_client()
        for response in [self.response(status=302), self.response(mime='text/html'),
                         self.response(mime='image/svg+xml'), self.response(chunks=(b'a'*(10*1024*1024+1),))]:
            with patch('storage_media.requests.Session.get', return_value=response):
                self.assertEqual(client.get('/media/storage/public/book-covers/a.webp').status_code, 502)
        with patch('storage_media.requests.Session.get', return_value=self.response(status=403)):
            self.assertEqual(client.get('/media/storage/sign/board-uploads/a.png?token=a.b.c').status_code, 404)


if __name__ == '__main__':
    unittest.main()
