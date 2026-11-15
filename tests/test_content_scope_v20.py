"""Content routing and migration use actual records; all writes are isolated."""
import copy
import json
from collections import Counter
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml

from crawler import content_migration, opportunity_util as util, push_util as push
from crawler import opportunity_review as review, automatic_review as automatic

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / 'data/migrations/opportunity-content-v20.json').read_text(encoding='utf-8'))


def catalog():
    return util.load(ROOT)


def write(root, data):
    path = root / 'data/opportunities.json'
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def test_all_eighteen_routes_keep_ids_source_and_directories():
    data = catalog()
    assert Counter(util.content_scope(i) for i in data['opportunities']) == {
        'institutional_activity': 9, 'mentor_recruitment': 6, 'admission_notice': 1, 'pending': 2}
    public = util.public_catalog(data)
    assert len(public['opportunities']) == 9 and len(public['other_contents']) == 9
    assert {i['id'] for i in data['opportunities']} == {i['id'] for i in public['opportunities'] + public['other_contents']}
    assert util.public_catalog(public) == public
    bound = [i for i in public['other_contents'] if i.get('mentor_ids')]
    assert len(bound) == 1 and bound[0]['mentor_ids'] == ['ruc-info-dongjinhao'] and bound[0]['dept_id'] == 'info'
    for item in data['opportunities']:
        if item['id'] != 'ihep-winter-2027':
            assert item['source_sha256'] and item['source_url'] and item['verified_at']


@pytest.mark.parametrize('change', [None, {'quote': ''}, {'organizer_level': 'individual_team'},
    {'source_url': 'https://other.edu.cn/fake'}, {'verified_at': '2099-01-01'}])
def test_absent_domain_only_and_misclassified_personal_records_fail_closed(change):
    item = copy.deepcopy(next(i for i in catalog()['opportunities'] if i['id'] == 'cibr-winter-training-2027'))
    if change is None:
        item.pop('content_classification')
    else:
        item['content_classification'].update(change)
    assert util.content_scope(item) == 'pending'
    assert util.public_catalog({'opportunities': [item]})['opportunities'] == []
    with pytest.raises(ValueError):
        util.validate_classification(item, '只有学校官网域名不能证明主办方', require_publishable=True)


def test_formal_admission_cannot_enter_institutional_activity():
    item = copy.deepcopy(next(i for i in catalog()['opportunities'] if i['kind'] == 'recommend'))
    item['content_classification']['scope'] = 'institutional_activity'
    assert util.content_scope(item) == 'pending'


def test_migration_idempotent_preserves_server_newer_rows_and_private_bytes(tmp_path):
    data = catalog()
    for item in data['opportunities']:
        for key in ('content_classification', 'mentor_ids', 'mentor_identity_evidence'):
            item.pop(key, None)
        if item['id'] == 'ruc-dongjinhao-research-contact':
            item['dept_id'] = 'cs'
    newer = copy.deepcopy(data['opportunities'][2]);newer['source_sha256'] = 'f' * 64
    data['opportunities'][2] = newer
    new = copy.deepcopy(data['opportunities'][3]);new['id'] = 'server-new-unknown'
    data['opportunities'].append(new)
    write(tmp_path, data)
    private = tmp_path / 'data/workflow.yaml';private.write_bytes(b'private: original-snapshots')
    before = (tmp_path / 'data/opportunities.json').read_bytes()
    preview = content_migration.migrate(tmp_path, MANIFEST)
    assert len(preview['changes']) == 17
    assert (tmp_path / 'data/opportunities.json').read_bytes() == before
    applied = content_migration.migrate(tmp_path, MANIFEST, apply=True)
    after = util.load(tmp_path)
    assert next(i for i in after['opportunities'] if i['id'] == newer['id']) == newer
    assert after['opportunities'][-1] == new
    assert private.read_bytes() == b'private: original-snapshots'
    raw = (tmp_path / 'data/opportunities.json').read_bytes()
    repeated = content_migration.migrate(tmp_path, MANIFEST, apply=True)
    assert repeated['changes'] == [] and (tmp_path / 'data/opportunities.json').read_bytes() == raw
    assert applied['publication_events_created'] == 0 and after.get('review_log') == data.get('review_log')


def test_feed_preserves_relocated_ids_and_old_snapshot_duplicate(tmp_path):
    public = util.public_catalog(catalog())
    response = Mock();response.json.return_value = public
    session = Mock();session.__enter__ = Mock(return_value=session);session.__exit__ = Mock(return_value=False)
    session.get.return_value = response
    with patch.object(util.requests, 'Session', return_value=session):
        merged = util.remote_catalog(tmp_path, 'https://example.edu.cn/api/opportunities')
    assert len(merged['opportunities']) == 18
    assert len(util.remote_catalog(tmp_path, 'https://example.edu.cn/api/opportunities')['opportunities']) == 18
    item = next(i for i in merged['opportunities'] if i['id'] == 'ruc-dongjinhao-research-contact')
    old_snapshot = dict(item);old_snapshot.pop('content_classification');old_snapshot['dept_id'] = 'cs'
    private = {'projects': {'old': {'id': 'old', 'opportunity': old_snapshot}}}
    saved, result = util.save(private, {'opportunity_id': item['id'], 'name': '既有申请', 'reminder_date': ''}, set(), {}, merged)
    assert result == {'project_id': 'old', 'duplicate': True} and saved == private
    assert saved['projects']['old']['opportunity'] == old_snapshot
    with pytest.raises(ValueError, match='新去向'):
        util.save({'projects': {}}, {'opportunity_id': item['id'], 'name': '新的活动申请', 'reminder_date': ''}, set(), {}, merged)


def test_migration_does_not_broadcast_and_individual_updates_never_create_activity_events(tmp_path):
    data = catalog();write(tmp_path, data)
    with push.database(tmp_path) as db:
        db.execute("INSERT INTO snapshots VALUES ('initialized','{}')")
    assert push.record(tmp_path, data) == 0
    individual = next(i for i in data['opportunities'] if util.content_scope(i) == 'mentor_recruitment')
    individual['materials'].append('导师个人新增材料')
    assert push.record(tmp_path, data) == 0
    with push.database(tmp_path) as db:
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 0


def test_pre_migration_queued_personal_alert_is_not_delivered_or_deleted(tmp_path):
    from test_push_util import subscription
    write(tmp_path, catalog())
    push.subscribe(tmp_path, {'subscription': subscription(), 'filters': dict(school='',kind='',year='',query='',discoveries=True)})
    with push.database(tmp_path) as db:
        event={'id':'legacy-alert','kind':'published','opportunity_id':'ruc-dongjinhao-research-contact'}
        db.execute('INSERT INTO events(key,body) VALUES (?,?)', ('legacy-alert',json.dumps(event)))
    sender=Mock()
    assert push.dispatch(tmp_path,sender)['sent']==0
    sender.assert_not_called()
    assert push.recent(tmp_path)==[]
    with push.database(tmp_path) as db:
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0]==1


def test_recruitment_identity_rejects_same_name_or_wrong_department():
    item = next(i for i in catalog()['opportunities'] if i.get('mentor_ids'))
    text = item['mentor_identity_evidence'][0]['quote']
    util.validate_mentor_links(ROOT, item, text)
    wrong = copy.deepcopy(item);wrong['dept_id'] = 'cs'
    with pytest.raises(ValueError, match='身份'):
        util.validate_mentor_links(ROOT, wrong, text)
    wrong = copy.deepcopy(item);wrong['mentor_identity_evidence'][0]['mentor_id'] = 'zju-cs-zhangfan'
    with pytest.raises(ValueError, match='身份'):
        util.validate_mentor_links(ROOT, wrong, text)


def test_source_migration_merges_urls_preserves_unknown_and_is_idempotent(tmp_path):
    write(tmp_path, catalog())
    path = tmp_path / 'sites/opportunities.yaml';path.parent.mkdir()
    target = {'url': MANIFEST['source_patches'][0]['url'], 'name': 'server name', 'enabled': False, 'selector': '.server'}
    unknown = {'url': 'https://new.edu.cn/admissions', 'name': 'server new', 'custom': 'preserve'}
    path.write_text(yaml.safe_dump({'targets': [target, unknown], 'server_setting': 17}), encoding='utf-8')
    result = content_migration.migrate(tmp_path, MANIFEST, apply=True)
    merged = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert merged['server_setting'] == 17 and merged['targets'][1] == unknown
    assert merged['targets'][0] == dict(target, content_scope_hint='mentor_recruitment')
    assert len(merged['targets']) == 3 and result['source_changes']
    before = path.read_bytes()
    assert content_migration.migrate(tmp_path, MANIFEST, apply=True)['source_changes'] == []
    assert path.read_bytes() == before


def test_queue_migration_only_matches_original_untouched_item(tmp_path):
    classified = catalog();write(tmp_path, classified)
    item = copy.deepcopy(next(i for i in classified['opportunities'] if i['id'] == 'iscas-research-2026'))
    for key in ('content_classification','mentor_ids','mentor_identity_evidence'):
        item.pop(key)
    row = next(r for r in MANIFEST['records'] if r['id'] == item['id'])
    assert content_migration.item_hash(item) == row['base_item_sha256']
    untouched = {'id':'draft','item':item,'review':{'reviewed_at':'original','item_sha256':row['base_item_sha256']}}
    edited = copy.deepcopy(untouched);edited['id']='edited';edited['manual_edit']={'by':'human'}
    path = tmp_path / 'cache/opportunity_review.json';path.parent.mkdir()
    path.write_text(json.dumps({'drafts':[untouched,edited]}),encoding='utf-8')
    result = content_migration.migrate(tmp_path, MANIFEST, apply=True)
    assert result['queue_changes'] == ['draft']
    queue = json.loads(path.read_text(encoding='utf-8'))
    assert queue['drafts'][1] == edited and queue['drafts'][0]['review']['reviewed_at'] == 'original'
    assert queue['drafts'][0]['review']['item_sha256'] == row['classified_item_sha256']


def test_new_publication_rejects_missing_or_unmatched_classification(tmp_path):
    from test_opportunity_review import ReviewTests
    case = ReviewTests();case.setUp()
    try:
        draft = case.ready();queue = review.read_queue(case.queue)
        queue['drafts'][0]['item'].pop('content_classification')
        review.atomic_json(case.queue,queue)
        with pytest.raises(ValueError,match='归类'):
            case.publish(draft)
        assert not case.catalog.exists()
        queue['drafts'][0]['item']['content_classification'] = dict(draft['item']['content_classification'],quote='虚构主办单位')
        review.atomic_json(case.queue,queue)
        with pytest.raises(ValueError,match='当前官方正文'):
            case.publish(draft)
        assert not case.catalog.exists()
    finally:
        case.doCleanups()


def test_ai_does_not_infer_institution_from_domain_or_team_recruitment(tmp_path):
    from test_automatic_review_v18 import HTML, CONFIGS, NOW
    (tmp_path/'data').mkdir()
    (tmp_path/'data/schools.yaml').write_text('schools:\n- id: example\n  name: 示例大学\n',encoding='utf-8')
    queue=tmp_path/'cache/opportunity_review.json'
    monitoring={'candidates':[dict(url='https://cs.example.edu.cn/camp.htm',source=CONFIGS[0]['url'],school='example',dept='cs',unit='示例计算机学院',title='2027年计算机冬令营',first_seen=NOW.isoformat(),last_seen=NOW.isoformat())]}
    for raw in [HTML.replace('<p>主办单位：示例计算机学院</p>'.encode(),b''), HTML.replace(b'</article>','<p>课题组长期招收本科实习生</p></article>'.encode())]:
        review.sync(monitoring,queue,CONFIGS,fetcher=lambda _:raw,refresh=True,now=NOW)
        draft=review.read_queue(queue)['drafts'][0]
        result=automatic.process(tmp_path,queue,draft,CONFIGS,publish=True,now=NOW,
            checker=lambda *args:pytest.fail('unsupported organizer must not consume AI or publish'),fetcher=lambda _:raw)
        assert result['state']=='manual_required' and not (tmp_path/'data/opportunities.json').exists()
