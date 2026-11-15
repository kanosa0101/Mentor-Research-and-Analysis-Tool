"""Idempotent public classification migration; private records and new server rows stay intact."""
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
import yaml

from crawler import opportunity_util as util
from crawler.opportunity_monitor import atomic_json, output_lock


def item_hash(item):
    return hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def migrate(root, manifest, *, apply=False, output=None):
    path = Path(root) / 'data/opportunities.json'
    queue_path = Path(root) / 'cache/opportunity_review.json'
    with output_lock(queue_path), output_lock(path):
        raw = path.read_bytes()
        catalog = json.loads(raw)
        migrated = copy.deepcopy(catalog)
        rows = {row['id']: row for row in manifest['records']}
        changes, skipped, unchanged = [], [], []
        for item in migrated['opportunities']:
            row = rows.get(item['id'])
            if row is None:
                skipped.append({'id': item['id'], 'reason': 'new_server_record_preserved'})
                continue
            patch = row['patch']
            if all(item.get(key) == value for key, value in patch.items()):
                unchanged.append(item['id'])
                continue
            if item.get('content_classification'):
                skipped.append({'id': item['id'], 'reason': 'existing_classification_preserved'})
                continue
            if item.get('source_url') != row['source_url'] or item.get('source_sha256', '') != row['source_sha256']:
                skipped.append({'id': item['id'], 'reason': 'newer_or_different_source_preserved'})
                continue
            before = {key: copy.deepcopy(item[key]) for key in patch if key in item}
            item.update(copy.deepcopy(patch))
            util.validate(item)
            changes.append({'id': item['id'], 'before': before, 'after': patch})
        report = {'migration': manifest['id'], 'applied': apply, 'changes': changes, 'unchanged': unchanged,
                  'skipped': skipped, 'before_sha256': hashlib.sha256(raw).hexdigest(),
                  'private_records_touched': False, 'publication_events_created': 0}
        queue_raw = queue_path.read_bytes() if queue_path.exists() else None
        queue = json.loads(queue_raw) if queue_raw else None
        queue_changes = []
        final = {item['id']: item for item in migrated['opportunities']}
        for draft in (queue or {}).get('drafts', []):
            before = draft.get('item', {})
            row = rows.get(before.get('id'))
            current = final.get(before.get('id'))
            if (row and current and not draft.get('manual_edit') and
                    item_hash(before) == row.get('base_item_sha256') and
                    item_hash(current) == row.get('classified_item_sha256')):
                draft['item'].update(copy.deepcopy(row['patch']))
                if draft.get('review'):
                    draft['review']['item_sha256'] = item_hash(draft['item'])
                    draft['review']['content_classification'] = copy.deepcopy(current['content_classification'])
                    draft['review']['content_migration'] = manifest['id']
                queue_changes.append(draft['id'])
        report['queue_changes'] = queue_changes
        config_path = Path(root) / 'sites/opportunities.yaml'
        config_raw = config_path.read_bytes() if config_path.exists() else None
        config = yaml.safe_load(config_raw) if config_raw else None
        source_changes = []
        if config is not None:
            by_url = {row['url']: row for row in config['targets']}
            for addition in manifest.get('source_additions', []):
                if addition['url'] not in by_url:
                    config['targets'].append(copy.deepcopy(addition))
                    by_url[addition['url']] = config['targets'][-1]
                    source_changes.append({'url': addition['url'], 'operation': 'add_reviewed_source'})
            for update in manifest.get('source_patches', []):
                target = by_url.get(update['url'])
                if target is not None:
                    for key, value in update['patch'].items():
                        if key not in target:
                            target[key] = value
                            source_changes.append({'url': update['url'], 'field': key, 'operation': 'add_routing_hint'})
        report['source_changes'] = source_changes
        if apply and changes:
            # Exact pre-migration bytes are recoverable; no review_log publication is manufactured.
            folder = Path(output) if output else Path(root) / 'cache/content_migrations'
            folder.mkdir(parents=True, exist_ok=True)
            backup = folder / (manifest['id'] + '-' + report['before_sha256'][:16] + '.before.json')
            if not backup.exists():
                backup.write_bytes(raw)
            atomic_json(path, migrated)
            report['backup'] = str(backup)
        if apply and queue_changes:
            folder = Path(output) if output else Path(root) / 'cache/content_migrations'
            folder.mkdir(parents=True, exist_ok=True)
            queue_backup = folder / (manifest['id'] + '-queue-' + hashlib.sha256(queue_raw).hexdigest()[:16] + '.before.json')
            if not queue_backup.exists():
                queue_backup.write_bytes(queue_raw)
            atomic_json(queue_path, queue)
            report['queue_backup'] = str(queue_backup)
        if apply and source_changes:
            folder = Path(output) if output else Path(root) / 'cache/content_migrations'
            folder.mkdir(parents=True, exist_ok=True)
            config_backup = folder / (manifest['id'] + '-sources-' + hashlib.sha256(config_raw).hexdigest()[:16] + '.before.yaml')
            if not config_backup.exists():
                config_backup.write_bytes(config_raw)
            fd, temporary = tempfile.mkstemp(dir=config_path.parent, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    yaml.safe_dump(config, stream, allow_unicode=True, sort_keys=False)
                os.replace(temporary, config_path)
            finally:
                Path(temporary).unlink(missing_ok=True)
            report['source_backup'] = str(config_backup)
        report['after_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        return report
