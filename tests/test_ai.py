import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crawler import ai_util
from crawler.model import Professor
from test_maintenance import script


class AiTests(unittest.TestCase):
    def test_unrelated_quote_does_not_support_claim(self):
        claims = [{'text': '该导师今年有三个招生名额', 'evidence': ['计算机视觉']}]
        self.assertEqual(ai_util.validate_claims(claims, {'research_direction_raw': '计算机视觉'}), ([], 1))

    def test_extractive_claim_has_field_binding(self):
        kept, dropped = ai_util.validate_claims(
            [{'text': '计算机视觉', 'evidence': ['研究方向为计算机视觉']}],
            {'research_direction_raw': '研究方向为计算机视觉'})
        self.assertEqual(dropped, 0)
        self.assertEqual(kept[0]['source_field'], 'research_direction_raw')

    def test_malformed_output_is_rejected(self):
        self.assertIsNone(ai_util.parse_llm_json('[1, 2]'))
        kept, dropped = ai_util.validate_claims([None, 'bad', {'text': 4}, {'text': '计算机视觉', 'evidence': '计算机视觉'}], {'bio_raw': '计算机视觉'})
        self.assertEqual((kept, dropped), ([], 4))

    def test_dry_run_with_cached_response_never_saves(self):
        enrich = script('ai_enrich')
        p = Professor(slug='example',name='测试',school='test',dept='cs',detail_url='https://example.org',bio_raw='计算机视觉')
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / 'cache'
            cache.mkdir()
            inp = ai_util.build_input(p)
            fp = ai_util.fingerprint(inp, enrich.PROMPT_VERSION, 'mock')
            (cache / (fp + '.json')).write_text(json.dumps({'raw': json.dumps({'research_summary': [{'text': '计算机视觉', 'evidence': ['计算机视觉']}]}), 'generated_at': '2026-10-13'}))
            with patch.object(enrich, 'CACHE', cache), patch.object(enrich.store, 'load_all', return_value={p.slug: p}), \
                    patch.object(enrich.store, 'save_professor') as save, \
                    patch.object(enrich, 'call_llm') as call, \
                    patch('sys.argv', ['ai_enrich', '--school','test','--dept','cs','--mock','--dry']):
                before = sorted(f.name for f in cache.iterdir())
                enrich.main()
                self.assertEqual(before, sorted(f.name for f in cache.iterdir()))
            save.assert_not_called()
            call.assert_not_called()
