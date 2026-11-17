import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crawler import fetch, store
from crawler.model import Facet, Issue, Professor, Provenance

ROOT = Path(__file__).resolve().parent.parent


def script(name):
    path = ROOT / 'scripts' / (name.replace('\\', '/') + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / 'data'
        self.data.mkdir()
        self.patcher = patch.object(store, 'DATA', self.data)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.prof = Professor(slug='test', name='测试', school='test', dept='cs',
                              detail_url='https://example.org/person',
                              last_verified='2026-09-06', bio_raw='研究材料')
        store.save_professor(self.prof)
        self.crawl = script('crawl')

    def test_test_module_paths_work_with_both_separators_and_native_absolute_path(self):
        module_path = ROOT / 'sites' / 'related_roster'
        for path in ('../sites/related_roster', r'..\sites\related_roster', str(module_path)):
            with self.subTest(path=path):
                self.assertEqual(Path(script(path).__file__).resolve(), module_path.with_suffix('.py'))

    def test_explicit_supervisor_only_does_not_infer_from_bio(self):
        class Hook:
            def parse_detail(self, *args):
                return {'bio_raw': '曾任教授、博士生导师'}
        with patch.object(fetch, 'fetch_text', return_value=('html', {'fetched_at': '2026-10-14'}, True)):
            self.crawl.phase_enrich({'school': 'test', 'dept': 'cs', 'explicit_supervisor_only': True}, Hook(), False)
        self.assertIsNone(store.load_all('test', 'cs')['test'].supervisor)

    def test_existing_sites_keep_supervisor_bio_fallback(self):
        class Hook:
            def parse_detail(self, *args):
                return {'bio_raw': '教授、博士生导师'}
        with patch.object(fetch, 'fetch_text', return_value=('html', {'fetched_at': '2026-10-14'}, True)):
            self.crawl.phase_enrich({'school': 'test', 'dept': 'cs'}, Hook(), False)
        self.assertEqual(store.load_all('test', 'cs')['test'].supervisor, '博导')

    def test_cached_parse_does_not_advance_verified_date(self):
        class Hook:
            def parse_detail(self, *args):
                return {'bio_raw': '研究材料'}
        with patch.object(fetch, 'fetch_text', return_value=(
                'html', {'fetched_at': '2026-09-06'}, True)):
            self.crawl.phase_enrich({'school': 'test', 'dept': 'cs'}, Hook(), False)
        p = store.load_all('test', 'cs')['test']
        self.assertEqual(p.last_verified, '2026-09-06')
        self.assertEqual(p.last_fetched, '2026-09-06')
        self.assertEqual(p.last_parsed, self.crawl.TODAY)

    def test_roster_record_keeps_its_own_page_source_and_date(self):
        class Hook:
            def iter_roster(self, cfg):
                return [{'name': '新教师', 'url': 'https://example.org/person2', 'email': 'new@example.org',
                         'institutes': ['第二系'], 'roster_source': 'https://example.org/list2', 'roster_fetched_at': '2026-09-01'}], {'fetched_at': '2026-10-14'}
        self.crawl.phase_roster({'school': 'test', 'dept': 'cs', 'list': {'url': 'https://example.org/list1'}}, Hook(), False)
        p = next(p for p in store.load_all('test', 'cs').values() if p.name == '新教师')
        self.assertEqual(p.provenance['name'].source, 'https://example.org/list2')
        self.assertEqual(p.provenance['email'].fetched_at, '2026-09-01')
        self.assertEqual(p.provenance['institutes'].source, 'https://example.org/list2')
        self.assertEqual(p.provenance['institutes'].fetched_at, '2026-09-01')

    def test_roster_refresh_reaches_auxiliary_http_call(self):
        wp = self.crawl.load_hook({'school': 'test', 'hook': 'wp'})
        url = 'https://example.org/list.htm'
        cfg = {'school': 'test', 'dept': 'cs', 'list': {'channels': [{'url': url}]}}
        with patch.object(fetch, 'CACHE', self.data / 'http'):
            key = fetch._key('GET', url, None)
            fetch.CACHE.mkdir()
            (fetch.CACHE / (key + '.body')).write_bytes(b'<html></html>')
            (fetch.CACHE / (key + '.meta.json')).write_text(json.dumps({'fetched_at': '2026-09-06'}))
            import requests
            response = requests.Response()
            response.status_code = 200
            response._content = '<a href="/c1a2/page.htm">新增</a>'.encode()
            with patch.object(fetch, '_request', return_value=response) as request:
                self.crawl.phase_roster(cfg, wp, True)
            self.assertEqual(request.call_count, 1)
        self.assertTrue(any(p.name == '新增' for p in store.load_all('test', 'cs').values()))

    def test_cdp_fallback_preserves_refresh_and_cache_hit(self):
        import requests
        response = requests.Response()
        response.status_code = 403
        with patch.object(fetch, 'CACHE', self.data / 'http'), \
                patch.object(fetch, '_cdp_fallback', True), \
                patch.object(fetch, '_request', return_value=response), \
                patch.object(fetch, 'fetch_cdp', return_value=('html', {'fetched_at': '2026-09-06'}, True)) as cdp:
            _, _, hit = fetch.fetch('GET', 'https://example.org/waf', refresh=True)
        self.assertTrue(cdp.call_args.kwargs.get('refresh'))
        self.assertTrue(hit)

    def test_recurring_issue_reopens_and_preserves_review(self):
        issues = [Issue(kind='missing_in_list', ref='test', message='old',
                        first_seen='2026-09-06', resolved=True, reviewed=True,
                        review_note='之前恢复正常')]
        store.upsert_issue(issues, 'missing_in_list', 'test', '再次消失')
        self.assertFalse(issues[0].resolved)
        self.assertFalse(issues[0].reviewed)
        self.assertEqual(issues[0].review_history[-1]['review_note'], '之前恢复正常')

    def test_repeated_unresolved_reviewed_issue_keeps_review(self):
        issues = [Issue(kind='fetch_or_parse_error', ref='test', message='same',
                        first_seen='2026-09-06', reviewed=True, review_note='源确实死链')]
        store.upsert_issue(issues, 'fetch_or_parse_error', 'test', 'same')
        self.assertTrue(issues[0].reviewed)

    def test_manual_facets_survive_recompute_and_late_material_matches(self):
        tags = script('tag_facets')
        self.prof.facets = [Facet(id='topic.hci', origin='manual')]
        self.prof.bio_raw = '无方向文字' * 400 + '计算机视觉'
        store.save_professor(self.prof)
        previous = Path.cwd()
        try:
            os.chdir(self.tmp.name)
            tags.main()
        finally:
            os.chdir(previous)
        p = store.load_all('test', 'cs')['test']
        self.assertIn(('topic.hci', 'manual'), {(f.id, f.origin) for f in p.facets})
        self.assertIn('topic.cv', {f.id for f in p.facets})

    def test_manual_fields_are_not_overwritten(self):
        self.prof.email = 'manual@example.org'
        self.prof.provenance['email'] = Provenance(origin='manual', source='https://example.org', fetched_at='2026-09-06')
        self.crawl._merge(self.prof, 'email', 'new@example.org', Provenance(source='https://example.org', fetched_at='2026-10-13'))
        self.assertEqual(self.prof.email, 'manual@example.org')

    def test_related_identity_change_withdraws_only_automatic_detail_values(self):
        cfg = self.crawl.load_cfg('csu', 'auto')
        hook = self.crawl.load_hook(cfg)
        url = 'https://faculty.csu.edu.cn/zhangsan/zh_CN/index.htm'
        cfg['_roster_names'] = {url: '张三'}
        detail = Provenance(source=url, fetched_at='2026-09-06')
        roster = Provenance(source=cfg['list']['urls'][0], fetched_at='2026-09-06')
        manual = Provenance(origin='manual', source=url, fetched_at='2026-09-06')
        other = Provenance(source='https://example.org/trusted', fetched_at='2026-09-06')
        prof = Professor(slug='zhangsan', name='张三', school='csu', dept='auto', detail_url=url,
                         status='enriched', title='教授', email='other@csu.edu.cn', bio_raw='李四的简介',
                         research_direction_raw='李四的方向', phone='13800000000', supervisor='硕导',
                         homepage='https://example.org/home', institutes=['人工智能系'],
                         provenance={'name': roster, 'title': detail, 'email': detail, 'bio_raw': detail,
                                     'research_direction_raw': detail, 'phone': manual, 'supervisor': roster,
                                     'homepage': other, 'institutes': roster})
        store.save_professor(prof)
        html = '<title>中南大学 李四</title><div class="name">李四</div><div class="jbqk">职称：教授<p>邮箱：other@csu.edu.cn</p></div>'
        with patch.object(fetch, 'fetch_text', return_value=(html, {'fetched_at': '2026-10-14'}, False)):
            stats = self.crawl.phase_enrich(cfg, hook, False)
        saved = store.load_all('csu', 'auto')['zhangsan']
        for field in ('title', 'email', 'bio_raw', 'research_direction_raw'):
            self.assertIsNone(getattr(saved, field))
            self.assertNotIn(field, saved.provenance)
        self.assertEqual(saved.status, 'roster')
        self.assertEqual(saved.phone, prof.phone)
        self.assertEqual(saved.supervisor, prof.supervisor)
        self.assertEqual(saved.homepage, prof.homepage)
        self.assertEqual(saved.institutes, prof.institutes)
        self.assertEqual(saved.name, '张三')
        self.assertEqual(stats['failed'], 1)
        history = [json.loads(line) for line in (self.data / 'changes/csu-auto.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual({x['field'] for x in history}, {'title', 'email', 'bio_raw', 'research_direction_raw'})
        self.assertTrue(all(x['reason'] == 'detail_identity_mismatch' and x['new'] is None for x in history))
        self.assertEqual(next(x for x in history if x['field'] == 'email')['old'], 'other@csu.edu.cn')
        self.assertEqual(next(x for x in history if x['field'] == 'email')['old_provenance']['source'], url)
        build = script('build_site')
        public = build.list_record(saved.model_dump(mode='json', exclude_none=True))
        self.assertNotIn('email', public)
        self.assertNotIn('title', public)
        self.assertNotIn('other@csu.edu.cn', public['search_text'])
        self.assertNotIn('李四', build.search_record(saved.model_dump(mode='json')))
        self.assertFalse(build.compare_record(saved.model_dump(mode='json'))['bio_excerpt'])

    def test_related_missing_identity_and_network_failure_preserve_history(self):
        cfg = self.crawl.load_cfg('csu', 'auto')
        hook = self.crawl.load_hook(cfg)
        url = 'https://faculty.csu.edu.cn/zhangsan/zh_CN/index.htm'
        cfg['_roster_names'] = {url: '张三'}
        for failure in ('missing_identity', 'generic_identity', 'timeout'):
            with self.subTest(failure=failure):
                prof = Professor(slug='zhangsan', name='张三', school='csu', dept='auto', detail_url=url,
                                 status='enriched', title='教授', email='old@csu.edu.cn', bio_raw='张三的简介',
                                 provenance={f: Provenance(source=url, fetched_at='2026-09-06')
                                             for f in ('title', 'email', 'bio_raw')})
                store.save_professor(prof)
                html = '<title>Home</title><div>模板没有姓名</div>' if failure == 'missing_identity' else '<title>中南大学 个人信息</title><div class="name">个人信息</div>'
                kwargs = {'side_effect': TimeoutError('timeout')} if failure == 'timeout' else {
                    'return_value': (html, {'fetched_at': '2026-10-14'}, False)}
                with patch.object(fetch, 'fetch_text', **kwargs):
                    stats = self.crawl.phase_enrich(cfg, hook, False)
                saved = store.load_all('csu', 'auto')['zhangsan']
                self.assertEqual(saved.model_dump(), prof.model_dump())
                self.assertEqual(stats['failed'], 1)
                self.assertFalse((self.data / 'changes/csu-auto.jsonl').exists())

    def test_manual_institutes_survive_roster_and_detail(self):
        self.prof.institutes = ['人工指定研究所']
        self.prof.provenance['institutes'] = Provenance(origin='manual', source='https://example.org', fetched_at='2026-09-06')
        store.save_professor(self.prof)
        class Hook:
            def iter_roster(inner, cfg):
                return [{'name': self.prof.name, 'url': self.prof.detail_url, 'institutes': ['自动研究所']}], {'fetched_at': '2026-09-06'}
            def parse_detail(inner, *args):
                return {'institute_from_detail': ['自动研究所']}
        cfg = {'school': 'test', 'dept': 'cs', 'list': {'url': 'https://example.org/list'}}
        self.crawl.phase_roster(cfg, Hook(), False)
        with patch.object(fetch, 'fetch_text', return_value=('html', {'fetched_at': '2026-09-06'}, True)):
            self.crawl.phase_enrich(cfg, Hook(), False)
        self.assertEqual(store.load_all('test', 'cs')['test'].institutes, ['人工指定研究所'])

    def test_new_roster_from_cache_keeps_source_date(self):
        class Hook:
            def iter_roster(inner, cfg):
                return [{'name': '新增', 'url': 'https://example.org/new'}], {'fetched_at': '2026-09-06'}
        cfg = {'school': 'test', 'dept': 'cs', 'list': {'url': 'https://example.org/list'}}
        self.crawl.phase_roster(cfg, Hook(), False)
        p = next(p for p in store.load_all('test', 'cs').values() if p.name == '新增')
        self.assertEqual(p.provenance['name'].fetched_at, '2026-09-06')


if __name__ == '__main__':
    unittest.main()
