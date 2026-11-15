import tempfile
import unittest
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from scripts import maintain_public as maintain


class MaintenanceTests(unittest.TestCase):
    def test_failed_stage_does_not_cancel_independent_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def run(*args,**kwargs):
                if kwargs['kind']=='policies':raise ValueError('policy stage failed')
                return {'error':0,'attempted':40}
            with patch.object(maintain,'ROOT',root),patch.object(maintain,'run',side_effect=run),patch.object(maintain,'refresh_notices',return_value={'sources_error':0}) as notices,patch.object(maintain,'renew',return_value=[]),patch.object(maintain,'rebuild',return_value=2) as rebuild,patch.object(maintain,'build_snapshot',return_value={'id':'test'}):
                self.assertEqual(maintain.main(),1)
            notices.assert_called_once();rebuild.assert_called_once()
            report=json.loads((root/'cache/public-maintenance.json').read_text(encoding='utf-8'))
            self.assertIn('policies',report['failures'])
            self.assertEqual(report['professors']['attempted'],40)
    def test_notice_refresh_does_not_repeat_within_six_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data').mkdir()
            (root/'data/notices.json').write_text(json.dumps({'checked_at':datetime.now(timezone.utc).isoformat(),
                'summary':{'sources_ok':36,'sources_error':0}}),encoding='utf-8')
            with patch.object(maintain,'ROOT',root),patch.object(maintain,'collect_notices') as collect:
                report=maintain.refresh_notices()
            self.assertTrue(report['skipped'])
            collect.assert_not_called()

    def test_staging_uses_site_mount_and_preserves_unbuilt_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'site').mkdir()
            (root/'site/index.html').write_text('old')
            (root/'site/app.js').write_text('asset')
            def build():
                self.assertEqual(maintain.build_site.SITE.parent,root/'site')
                self.assertTrue(maintain.build_site.SITE.name.startswith('.'))
                (maintain.build_site.SITE/'index.html').write_text('new')
            with patch.object(maintain,'ROOT',root),patch.object(maintain.build_site,'main',build),patch.object(maintain.build_site,'SITE',root/'site'):
                self.assertEqual(maintain.rebuild(),1)
            self.assertEqual((root/'site/index.html').read_text(),'new')
            self.assertEqual((root/'site/app.js').read_text(),'asset')
            self.assertFalse(list((root/'site').glob('.build-*')))

    def test_build_failure_keeps_published_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'site').mkdir();(root/'site/index.html').write_text('published')
            def fail():
                (maintain.build_site.SITE/'index.html').write_text('incomplete')
                raise ValueError('bad source fixture')
            with patch.object(maintain,'ROOT',root),patch.object(maintain.build_site,'main',fail),patch.object(maintain.build_site,'SITE',root/'site'):
                with self.assertRaises(ValueError):maintain.rebuild()
            self.assertEqual((root/'site/index.html').read_text(),'published')
