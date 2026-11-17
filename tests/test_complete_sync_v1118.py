"""A published full evidence bundle must survive the ordinary daily sync path."""
import copy
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from crawler import automatic_evidence as evidence, automatic_review as automatic, opportunity_review as review, opportunity_util as util
from test_automatic_review_v18 import CONFIGS, HTML, NOW, URL, accepted, setup
from test_complete_evidence_v1116 import docx


@pytest.fixture
def published_bundle(setup, monkeypatch):
    root, queue, _ = setup
    raw = HTML.replace(b'</article>', ('<a href="/form.docx">form.docx</a>'
        '<p>2026冬季培训班精彩瞬间</p><p><img src="/past.png"></p></article>').encode())
    records = [dict(sha256=hashlib.sha256(body).hexdigest(), kind='historical_photos', source_urls=[URL],
        reviewer='fixture', reviewed_at='2026-11-15', description='Reviewed fixture image')
        for body in (b'first reviewed image', b'second reviewed image')]
    (root/'sites/evidence_media.yaml').write_text(yaml.safe_dump(dict(version=1, images=records)), encoding='utf-8')
    state = dict(raw=raw, image=b'first reviewed image', attachment=docx('申请表：姓名及研究经历。'), requests=0)
    def fetch(_):
        state['requests'] += 1
        return state['raw']
    monkeypatch.setattr(evidence, 'fetch_image', lambda *_: state['image'])
    monkeypatch.setattr(review.attachments, 'fetch_docx', lambda *_: state['attachment'])
    result = automatic.process(root, queue, review.read_queue(queue)['drafts'][0], CONFIGS,
        publish=True, now=NOW, checker=accepted, fetcher=fetch)
    assert result['state'] == 'published', result
    draft = review.read_queue(queue)['drafts'][0]
    state['requests'] = 0
    return root, queue, state, fetch, draft


def freeze_review_clock(monkeypatch, at):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return at.astimezone(tz) if tz else at.replace(tzinfo=None)
    monkeypatch.setattr(review, 'datetime', Clock)


def test_reused_complete_bundle_without_rule_suggestions_is_not_downgraded(published_bundle):
    root, queue, state, fetch, original = published_bundle
    data = review.read_queue(queue)
    data['drafts'][0].pop('field_evidence', None)
    review.atomic_json(queue, data)
    at = datetime.fromisoformat(original['fetch']['checked_at']) + timedelta(hours=1)
    updated = review.sync({'candidates': []}, queue, CONFIGS, fetcher=fetch, now=at)['drafts'][0]
    assert state['requests'] == 0
    assert updated['fetch'] == original['fetch']
    assert review.status(updated) == 'published'
    assert updated['review']['evidence_mode'] == 'complete'


@pytest.mark.parametrize('counter_changes,legacy_record', [(False,False), (True,False), (True,True)])
def test_daily_sync_keeps_media_version_and_renews_unchanged_facts(published_bundle, monkeypatch, counter_changes, legacy_record):
    root, queue, state, fetch, original = published_bundle
    if legacy_record:
        data = review.read_queue(queue)
        data['drafts'][0]['fetch'].pop('complete_document')
        data['drafts'][0]['fetch'].pop('evidence_mode')
        data['drafts'][0]['review'].pop('evidence_mode')
        review.atomic_json(queue, data)
    if counter_changes:
        state['raw'] = state['raw'].replace(b'<article>', b'<article><span class="views">999</span>')
    at = datetime.fromisoformat(original['fetch']['checked_at']) + timedelta(hours=25)
    freeze_review_clock(monkeypatch, at)
    updated = review.sync({'candidates': []}, queue, CONFIGS, fetcher=fetch, now=at)['drafts'][0]
    assert state['requests'] == 1
    assert updated['fetch']['evidence_mode'] == 'complete'
    assert updated['fetch']['content_sha256'] == original['review']['content_sha256']
    assert review.status(updated) == 'published'
    assert review.renew(queue, root) == [original['item']['id']]
    current = util.load(root)['opportunities'][0]
    assert current['source_content_sha256'] == original['item']['source_content_sha256']
    assert current['source_sha256'] == hashlib.sha256(state['raw']).hexdigest()
    assert current['materials'] == original['item']['materials']
    assert current['verified_at'] == original['item']['verified_at']


@pytest.mark.parametrize('change', ['text', 'attachment', 'image'])
def test_daily_sync_does_not_renew_changed_complete_evidence(published_bundle, monkeypatch, change):
    root, queue, state, fetch, original = published_bundle
    before = copy.deepcopy(util.load(root))
    if change == 'text':
        state['raw'] = state['raw'].replace('成绩单'.encode(), '推荐信'.encode())
    elif change == 'attachment':
        state['attachment'] = docx('申请表：姓名及研究经历，并须导师签字。')
    else:
        state['image'] = b'second reviewed image'
    at = datetime.fromisoformat(original['fetch']['checked_at']) + timedelta(hours=25)
    freeze_review_clock(monkeypatch, at)
    updated = review.sync({'candidates': []}, queue, CONFIGS, fetcher=fetch, now=at)['drafts'][0]
    assert updated['fetch']['status'] == 'ok'
    assert updated['fetch']['content_sha256'] != original['review']['content_sha256']
    assert review.status(updated) == 'source_changed'
    assert review.renew(queue, root) == []
    assert util.load(root) == before
