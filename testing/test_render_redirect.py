"""Boundary tests for the retired public address: no open redirects or write replay."""
import importlib.util
from pathlib import Path
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

spec=importlib.util.spec_from_file_location('legacy_redirect',Path(__file__).parents[1]/'infra/render-redirect/server.py')
redirect=importlib.util.module_from_spec(spec)
spec.loader.exec_module(redirect)


class RedirectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http=redirect.ThreadingHTTPServer(('127.0.0.1',0),redirect.Handler)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()
        cls.url='http://127.0.0.1:'+str(cls.http.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.thread.join()

    def test_only_fixed_destination(self):
        for raw in ['//evil.test/','https://evil.test/','/\\evil.test/','/%0d%0aLocation:bad']:
            self.assertEqual(redirect.destination(raw),'https://knu-read.xyz/')

    def test_old_share_link_and_auth_boundary(self):
        self.assertEqual(redirect.destination('/shared_topics?token=example'), 'https://knu-read.xyz/shared_topics?token=example')
        self.assertEqual(redirect.destination('/login/kakao/callback?code=private&state=old'), 'https://knu-read.xyz/login')

    def test_notice_and_no_referrer(self):
        with urlopen(self.url+'/') as r:
            body=r.read().decode()
            self.assertEqual(r.status,200)
            self.assertIn('공식 홈페이지',body)
            self.assertIn('3;url=https://knu-read.xyz/',body)
            self.assertEqual(r.headers['Referrer-Policy'],'no-referrer')
            self.assertEqual(r.headers['Cache-Control'],'no-store')

    def test_post_is_not_replayed(self):
        with self.assertRaises(HTTPError) as cm:
            urlopen(Request(self.url+'/save',data=b'private=test',method='POST'))
        self.assertEqual(cm.exception.code,410)
        self.assertNotIn(b'http-equiv="refresh"',cm.exception.read())
        self.assertIsNone(cm.exception.headers.get('Location'))

    def test_health_and_head(self):
        with urlopen(self.url+'/healthz') as r:self.assertEqual(r.read(),b'OK\n')
        with urlopen(Request(self.url+'/',method='HEAD')) as r:
            self.assertEqual(r.status,200);self.assertEqual(r.read(),b'')


if __name__=='__main__':unittest.main()
