import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from crawler.static_assets import AssetCache
from crawler.public_catalog import selected, search
import test_public_server as public_fixture
import json


class CacheTests(unittest.TestCase):
    def test_cached_representation_and_revision_invalidation(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'data.js';p.write_text('x'*3000);cache=AssetCache()
            first=cache.read(p,True)
            with patch.object(Path,'read_bytes',side_effect=AssertionError('cache miss')):
                self.assertEqual(cache.read(p,True),first)
            p.write_text('changed'*600)
            self.assertNotEqual(cache.read(p,True)[1],first[1])

    def test_cache_memory_and_entry_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=AssetCache(max_bytes=100,max_entries=2)
            for n in range(6):
                p=Path(folder)/str(n);p.write_text('x'*40);cache.read(p,False)
            self.assertLessEqual(cache.size,100);self.assertLessEqual(len(cache.entries),2)

    def test_selected_comparison_only_returns_requested_public_records(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'site').mkdir()
            (root/'site/data.js').write_text('window.MENTOR_DATA = '+json.dumps([{'page':'a','name':'A'},{'page':'b','name':'B'}])+';')
            (root/'site/compare-data.js').write_text('window.MENTOR_COMPARE = '+json.dumps({'a':{'bio_excerpt':'public'}})+';')
            self.assertEqual(selected(root,['a']),[{'page':'a','name':'A','bio_excerpt':'public'}])
            self.assertEqual(selected(root,[]),[])
            with self.assertRaises(ValueError):selected(root,['a']*6)

    def test_search_preserves_known_but_unmatched_and_english_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'site').mkdir()
            (root/'site/data.js').write_text('window.MENTOR_DATA = '+json.dumps([{'page':'a','school':'demo'},{'page':'b','school':'other'},{'page':'c','school':'demo'}])+';')
            (root/'site/search.js').write_text('window.MENTOR_SEARCH = '+json.dumps({'a':'training and ai research','b':'chain algorithms','c':''})+';')
            result=search(root,['ai'])
            self.assertEqual(set(result['known_ids']),{'a','b'})
            self.assertEqual(list(result['matches']),['a'])
            self.assertEqual(search(root,['missing'],['demo']),{'known_ids':['a'],'matches':{}})
            with self.assertRaises(ValueError):search(root,['x']*21)


class StaticHTTPTests(unittest.TestCase):
    setUp=public_fixture.PublicServerTests.setUp
    close=public_fixture.PublicServerTests.close
    request=public_fixture.PublicServerTests.request

    def test_conditional_requests_return_no_body_and_new_source_invalidates(self):
        _,headers,body=self.request('/data.js')
        self.assertIn('max-age=300',headers['Cache-Control'])
        code,_,empty=self.request('/data.js',headers={'If-None-Match':headers['ETag']})
        self.assertEqual((code,empty),(304,b''))
        (self.site/'data.js').write_text('window.DATA=[1];')
        code,new,body=self.request('/data.js',headers={'If-None-Match':headers['ETag']})
        self.assertEqual(code,200);self.assertNotEqual(new['ETag'],headers['ETag'])
        self.assertEqual(self.request('/start.html')[1]['Cache-Control'],'no-cache')
        self.assertEqual(self.request('/start.html')[1]['X-Frame-Options'], 'DENY')
        self.assertEqual(self.request('/start.html')[1]['Content-Security-Policy'], "frame-ancestors 'none'")

    def test_local_release_download_is_retired_even_when_file_exists(self):
        (self.root/'dist').mkdir();(self.root/'dist/mentor-assistant-v1.6.0-local.zip').write_bytes(b'zip')
        (self.root/'dist/private.json').write_text('private')
        code, _, body = self.request('/download/mentor-assistant-v1.6.0-local.zip')
        self.assertEqual(code, 410)
        self.assertIn('在线服务'.encode(), body)
        self.assertEqual(self.request('/download/mentor-assistant-v1.6.0-local.zip.sha256')[0], 410)
        for path in ('/download/private.json','/download/../data/workflow.yaml','/dist/mentor-assistant-v1.6.0-local.zip'):
            self.assertEqual(self.request(path)[0],404)
