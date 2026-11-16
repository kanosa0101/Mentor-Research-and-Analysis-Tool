import pytest

from crawler import opportunity_review as review
from crawler.review_dashboard import Dashboard
from crawler.pipeline_metrics import summarize
from test_review_preflight_v1116 import CONFIGS, CURRENT, NOW, fixture
import yaml


@pytest.mark.parametrize('legacy', [False, True])
def test_evidence_error_has_dashboard_label_specific_blocker_and_no_publication(tmp_path, legacy):
    path, draft = fixture(tmp_path, CURRENT)
    (tmp_path/'sites').mkdir()
    (tmp_path/'sites/opportunities.yaml').write_text(yaml.safe_dump({'targets':CONFIGS}), encoding='utf8')
    draft['fetch'].update(status='error' if legacy else 'evidence_error', error_kind='evidence',
                          error='正文图片含申请信息，需完整核验')
    review.atomic_json(path, {'version':1, 'drafts':[draft]})
    dashboard = Dashboard(tmp_path)
    before = path.read_bytes()
    listing = dashboard.listing()
    detail = dashboard.detail(draft['id'])
    assert listing['drafts'][0]['status_label'] == '附件或图片待核验'
    assert listing['metrics']['review_states'] == {'needs_evidence_review':1}
    assert detail['status'] == 'needs_evidence_review' and '2028' in detail['source_text']
    assert any('正文图片含申请信息' in reason for reason in detail['blockers'])
    assert any('不能发布' in reason for reason in detail['blockers'])
    assert all('原文未成功取得' not in reason for reason in detail['blockers'])
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match='不能发布'):
        dashboard.mutate(draft['id'], 'publish', {'revision': detail['revision'], 'confirmed': True,
            'sha256':draft['fetch']['sha256'], 'reviewer':'fixture', 'note':'incomplete evidence must not publish'})
    assert not (tmp_path/'data/opportunities.json').exists()


def test_monitor_source_errors_are_separate_from_draft_evidence_errors(tmp_path):
    path, draft = fixture(tmp_path, CURRENT)
    draft['fetch'].update(status='error', error_kind='evidence')
    review.atomic_json(tmp_path/'cache/opportunities_live.json', {'sources': {
        'working':{'status':'ok'}, 'failed':{'status':'error'}, 'retired':{'status':'removed'}}})
    metrics = summarize(tmp_path, {'drafts':[draft]}, NOW)
    assert metrics['source_count'] == 2 and metrics['source_errors'] == 1
    assert metrics['review_states'] == {'needs_evidence_review':1}
