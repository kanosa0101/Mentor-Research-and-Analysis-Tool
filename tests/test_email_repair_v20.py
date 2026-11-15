import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from scripts import repair_email_v20


class RepairMigration(unittest.TestCase):
    def test_idempotent_and_preserves_newer_public_and_private_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / 'data/migrations/email_repairs_v20.json'
            fixture.parent.mkdir(parents=True)
            records = []
            for slug in ('bad', 'newer'):
                name = f'data/professors/demo/cs/{slug}.yaml'
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(yaml.safe_dump(dict(slug=slug, name='测试导师', school='demo', dept='cs',
                    email='old@example.edu12' if slug=='bad' else 'new@example.edu', title='副教授', detail_url='https://example.edu/profile')))
                records.append(dict(path=name, old_email='old@example.edu12', email='old@example.edu',
                    source_url='https://example.edu/profile', fetched_at='2026-09-05'))
            fixture.write_text(json.dumps({'repairs':records}))
            private = root / 'data/workflow.yaml'
            private.write_bytes(b'private snapshot')
            with patch.object(repair_email_v20, 'ROOT', root):
                first = repair_email_v20.repair(root, apply=True)
                second = repair_email_v20.repair(root, apply=True)
            self.assertEqual(len(first['changed']), 1)
            self.assertEqual(second['changed'], [])
            self.assertEqual(len(second['already_correct']), 1)
            self.assertEqual(len(second['skipped_newer_or_missing']), 1)
            self.assertEqual(private.read_bytes(), b'private snapshot')
            value=yaml.safe_load((root/records[0]['path']).read_text(encoding='utf8'))
            self.assertEqual(value['title'], '副教授')
            self.assertEqual(value['provenance']['email']['fetched_at'],'2026-09-05')


if __name__ == '__main__':
    unittest.main()
