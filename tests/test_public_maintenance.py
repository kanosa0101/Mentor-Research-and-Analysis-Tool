import tempfile
import unittest
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from scripts import maintain_public as maintain


class MaintenanceTests(unittest.TestCase):
    def test_quality_jobs_run_each_cycle_and_pending_work_does_not_prevent_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(maintain, 'ROOT', root), \
                    patch.object(maintain, 'run', return_value={'error':0}), \
                    patch.object(maintain.policy_revalidation, 'run', return_value={'attempted':20,'confirmed':20,'retry':0,'review_required':0}) as policies, \
                    patch.object(maintain.policy_intake, 'run', return_value={'attempted':2,'published':1,'pending':1}) as intake, \
                    patch.object(maintain.mentor_recovery, 'refresh_directories', return_value={'attempted':2,'error':0}) as directories, \
                    patch.object(maintain.mentor_quality, 'refresh_fields', return_value={'attempted':6,'errors':3}) as fields, \
                    patch.object(maintain.mentor_quality, 'run', return_value={'attempted':40,'resolved':38,'pending':2,'error':0}) as mentors, \
                    patch.object(maintain, 'refresh_notices', return_value={'sources_error':0}), \
                    patch.object(maintain, 'renew', return_value=[]), \
                    patch.object(maintain, 'rebuild', return_value=2) as rebuild:
                self.assertEqual(maintain.main(), 1)
            policies.assert_called_once_with(root,limit=20,workers=4,timeout=15)
            mentors.assert_called_once_with(root,limit=40)
            fields.assert_called_once_with(root,limit=48,request_budget=96,workers=4)
            intake.assert_called_once_with(root,limit=2,publish=True)
            directories.assert_called_once_with(root,max_units=2,request_budget=16)
            rebuild.assert_called_once()
            report=json.loads((root/'cache/public-maintenance.json').read_text(encoding='utf-8'))
            self.assertEqual(report['failures'],{})
            self.assertEqual(report['source_warnings']['mentor_quality']['pending'],2)
            self.assertEqual(report['source_warnings']['policy_intake']['pending'],1)
            self.assertEqual(report['source_warnings']['mentor_fields'],{'attempted':6,'errors':3})

    def test_failed_stage_does_not_cancel_independent_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def run(*args,**kwargs):
                if kwargs['kind']=='policies':raise ValueError('policy stage failed')
                return {'error':0,'attempted':40}
            with patch.object(maintain,'ROOT',root),patch.object(maintain,'run',side_effect=run),patch.object(maintain,'refresh_notices',return_value={'sources_error':0}) as notices,patch.object(maintain,'renew',return_value=[]),patch.object(maintain,'rebuild',return_value=2) as rebuild,patch('crawler.public_snapshot.build',side_effect=AssertionError('No client archive')) as snapshot:
                self.assertEqual(maintain.main(),1)
            notices.assert_called_once();rebuild.assert_called_once()
            snapshot.assert_not_called()
            report=json.loads((root/'cache/public-maintenance.json').read_text(encoding='utf-8'))
            self.assertIn('policies',report['failures'])
            self.assertEqual(report['professors']['attempted'],40)
            self.assertNotIn('public_snapshot',report)
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
            (root/'site/p').mkdir();(root/'site/p/old.html').write_text('old profile')
            def fail():
                (maintain.build_site.SITE/'index.html').write_text('incomplete')
                (maintain.build_site.SITE/'p').mkdir()
                raise ValueError('bad source fixture')
            with patch.object(maintain,'ROOT',root),patch.object(maintain.build_site,'main',fail),patch.object(maintain.build_site,'SITE',root/'site'):
                with self.assertRaises(ValueError):maintain.rebuild()
            self.assertEqual((root/'site/index.html').read_text(),'published')
            self.assertEqual((root/'site/p/old.html').read_text(),'old profile')

    def test_success_removes_only_stale_generated_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / 'site'
            for folder, extension in (('p', 'html'), ('admissions', 'json')):
                (site / folder / 'nested').mkdir(parents=True)
                (site / folder / f'old.{extension}').write_text('old')
                (site / folder / f'live.{extension}').write_text('keep')
                (site / folder / f'nested/old.{extension}').write_text('nested')
                (site / folder / 'asset.png').write_text('other extension')
            (site / 'about.html').write_text('other location')

            def build():
                for folder, extension in (('p', 'html'), ('admissions', 'json')):
                    path = maintain.build_site.SITE / folder
                    path.mkdir()
                    (path / f'live.{extension}').write_text('keep')

            with patch.object(maintain, 'ROOT', root), patch.object(maintain.build_site, 'main', build), \
                    patch.object(maintain.build_site, 'SITE', site):
                self.assertEqual(maintain.rebuild(), 2)
                self.assertEqual(maintain.rebuild(), 0)
            self.assertEqual({path.relative_to(site).as_posix() for path in site.rglob('*') if path.is_file()},
                             {'about.html', 'p/live.html', 'p/nested/old.html', 'p/asset.png',
                              'admissions/live.json', 'admissions/nested/old.json', 'admissions/asset.png'})

    def test_rebuild_does_not_traverse_linked_profile_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / 'site'
            outside = root / 'unrelated'
            site.mkdir(); outside.mkdir()
            (outside / 'old.html').write_text('outside')
            try:
                (site / 'p').symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest(f'symlink creation unavailable: {type(error).__name__}')

            def build():
                path = maintain.build_site.SITE / 'p'
                path.mkdir()
                (path / 'new.html').write_text('generated')

            with patch.object(maintain, 'ROOT', root), patch.object(maintain.build_site, 'main', build), \
                    patch.object(maintain.build_site, 'SITE', site), self.assertRaises(ValueError):
                maintain.rebuild()
            self.assertEqual([path.name for path in outside.iterdir()], ['old.html'])
