"""The smaller application payload preserves contact and saved mentor identities."""
import gzip
import json
import unittest
from pathlib import Path

from scripts import build_site
import test_public_server as public_fixture


class ContactPayloadTests(unittest.TestCase):
    def test_only_contact_fields_are_exported_without_rewriting_values(self):
        source = dict(page='demo-cs-mentor', name='导师', school='demo', dept='cs',
                      school_name='示例大学', dept_name='计算机学院', email='mentor@demo.edu.cn',
                      research_direction_raw='视觉与机器人', bio_raw='长篇简介',
                      search_text='重复检索词', provenance={'email': {'source': 'https://demo.edu.cn'}},
                      private_note='must-not-export')
        result = build_site.contact_record(source)
        self.assertEqual(set(result), {'page', 'name', 'school', 'dept', 'school_name',
                                      'dept_name', 'email', 'research_direction_raw'})
        self.assertTrue(all(value == source[key] for key, value in result.items()))
        self.assertEqual(build_site.contact_record({'page': 'old-id', 'name': '资料待补'}),
                         {'page': 'old-id', 'name': '资料待补'})

    def test_current_roster_keeps_every_identity_and_existing_picker_context(self):
        path = Path(__file__).resolve().parents[1] / 'site/data.js'
        source = json.loads(path.read_text(encoding='utf8').split('=', 1)[1].strip().removesuffix(';'))
        contacts = [build_site.contact_record(p) for p in source]
        self.assertGreater(len(source), 0)
        self.assertEqual([p['page'] for p in contacts], [p['page'] for p in source])
        # Search, recipient defaults, research context and old records must all survive the split.
        for original, compact in zip(source, contacts):
            for key in ('name', 'school', 'dept', 'school_name', 'dept_name', 'email', 'research_direction_raw'):
                self.assertEqual(compact.get(key), original.get(key), (original['page'], key))
        self.assertLess(len(json.dumps(contacts, ensure_ascii=False)),
                        len(json.dumps(source, ensure_ascii=False)) * .6)


class ContactAssetTests(unittest.TestCase):
    setUp = public_fixture.PublicServerTests.setUp
    close = public_fixture.PublicServerTests.close
    request = public_fixture.PublicServerTests.request

    def test_contact_asset_is_public_compressed_and_cacheable(self):
        raw = ('window.MENTOR_DATA = ' + json.dumps([{'page': 'demo-' + str(i), 'name': '导师'}
                                                 for i in range(80)]) + ';\n').encode()
        (self.site / 'contact-data.js').write_bytes(raw)
        code, headers, body = self.request('/contact-data.js?v=ux1', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(code, 200)
        self.assertEqual(headers['Content-Encoding'], 'gzip')
        self.assertEqual(gzip.decompress(body), raw)
        self.assertIn('max-age=300', headers['Cache-Control'])
        code, _, body = self.request('/contact-data.js?v=ux1',
                                     headers={'Accept-Encoding': 'gzip', 'If-None-Match': headers['ETag']})
        self.assertEqual((code, body), (304, b''))
