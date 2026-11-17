"""Complete publication is bound to text, links and evidence bytes, not page counters."""
import hashlib
from datetime import timedelta

import pytest
import yaml

from crawler import automatic_evidence as evidence, automatic_review as automatic, opportunity_review as review, opportunity_util as util
from test_automatic_review_v18 import CONFIGS, HTML, NOW, URL, accepted, setup
from test_complete_evidence_v1116 import docx
from test_complete_sync_v1118 import published_bundle


def test_dynamic_counter_change_keeps_all_complete_evidence_and_can_publish(setup):
    root, queue, _ = setup
    count = 0
    def fetch(_):
        nonlocal count
        count += 1
        return HTML.replace(b'</article>', f'<span class="views">{count}</span></article>'.encode())
    result = automatic.process(root, queue, review.read_queue(queue)['drafts'][0], CONFIGS,
        publish=True, now=NOW, checker=accepted, fetcher=fetch)
    assert result['state'] == 'published' and count == 2
    confirmation = review.read_queue(queue)['drafts'][0]['review']['version_confirmation']
    assert confirmation['acknowledged_raw_sha256'] != confirmation['current_raw_sha256']
    assert util.load(root)['opportunities'][0]['source_content_sha256'] == confirmation['content_sha256']


@pytest.mark.parametrize('change', ['text', 'link', 'attachment', 'image'])
def test_any_actual_complete_evidence_change_after_ai_cannot_publish(setup, monkeypatch, change):
    root, queue, _ = setup
    raw = HTML
    if change == 'attachment':
        raw = raw.replace(b'</article>', b'<a href="/form.docx">form.docx</a></article>')
    if change == 'image':
        raw = raw.replace(b'</article>', '<p>2026冬季培训班精彩瞬间</p><p><img src="/past.png"></p></article>'.encode())
        records = [dict(sha256=hashlib.sha256(body).hexdigest(), kind='historical_photos', source_urls=[URL],
                        reviewer='fixture', reviewed_at='2026-11-15', description='Reviewed test gallery')
                   for body in (b'first verified photo', b'second verified photo')]
        (root/'sites/evidence_media.yaml').write_text(yaml.safe_dump(dict(version=1, images=records)), encoding='utf-8')
    counter = {'html':0, 'attachment':0, 'image':0}
    def fetch(_):
        counter['html'] += 1
        if counter['html'] == 2 and change == 'text':
            return raw.replace('成绩单'.encode(), '推荐信'.encode())
        if counter['html'] == 2 and change == 'link':
            return raw.replace(b'</article>', b'<a href="https://cs.example.edu.cn/updated">updated</a></article>')
        return raw
    def attachment(*_):
        counter['attachment'] += 1
        return docx('申请表：姓名。' if counter['attachment'] == 1 else '申请表：姓名、推荐人。')
    def image(*_):
        counter['image'] += 1
        return b'first verified photo' if counter['image'] == 1 else b'second verified photo'
    monkeypatch.setattr(evidence, 'fetch_image', image)
    result = automatic.process(root, queue, review.read_queue(queue)['drafts'][0], CONFIGS,
        publish=True, now=NOW, checker=accepted, fetcher=fetch, docx_fetcher=attachment)
    assert result['state'] == 'manual_required' and '版本变化' in result['reasons'][0], result
    assert not (root/'data/opportunities.json').exists()


@pytest.mark.parametrize('changed', [False, True])
def test_renew_rechecks_registered_media_in_the_same_evidence_root(setup, monkeypatch, changed):
    root, queue, _ = setup
    raw = HTML.replace(b'</article>', '<p>2026冬季培训班精彩瞬间</p><p><img src="/past.png"></p></article>'.encode())
    records = [dict(sha256=hashlib.sha256(body).hexdigest(), kind='historical_photos', source_urls=[URL],
                    reviewer='fixture', reviewed_at='2026-11-15', description='Reviewed test gallery')
               for body in (b'first verified photo', b'second verified photo')]
    (root/'sites/evidence_media.yaml').write_text(yaml.safe_dump(dict(version=1, images=records)), encoding='utf-8')
    count = 0
    def image(*_):
        nonlocal count
        count += 1
        return b'second verified photo' if changed and count == 4 else b'first verified photo'
    monkeypatch.setattr(evidence, 'fetch_image', image)
    def run(now):
        return automatic.process(root, queue, review.read_queue(queue)['drafts'][0], CONFIGS,
            publish=True, now=now, checker=accepted, fetcher=lambda _: raw)
    assert run(NOW)['state'] == 'published'
    before = (root/'data/opportunities.json').read_bytes()
    result = run(NOW + timedelta(days=15))
    assert count == 4
    if changed:
        assert result['state'] == 'manual_required' and '版本变化' in result['reasons'][0]
        assert (root/'data/opportunities.json').read_bytes() == before
    else:
        assert result['state'] == 'renewed', result
        assert util.load(root)['review_log'][-1]['operation'] == 'automatic_evidence_recheck'


def test_daily_sync_then_ai_renewal_accepts_only_counter_changes(published_bundle):
    root, queue, state, fetch, original = published_bundle
    count = 0
    last_raw = None
    def dynamic(config):
        nonlocal count, last_raw
        count += 1
        last_raw = fetch(config).replace(b'<article>', f'<article><span class="views">{count}</span>'.encode())
        return last_raw
    later = NOW + timedelta(days=15)
    synced = review.sync({'candidates':[]}, queue, CONFIGS, fetcher=dynamic, now=later, refresh=True)['drafts'][0]
    assert review.status(synced) == 'published'
    result = automatic.process(root, queue, synced, CONFIGS, publish=True, now=later, checker=accepted, fetcher=dynamic)
    assert result['state'] == 'renewed' and count == 3, result
    current = review.read_queue(queue)['drafts'][0]
    expected = hashlib.sha256(last_raw).hexdigest()
    assert current['item']['source_sha256'] == current['review']['source_sha256'] == current['fetch']['sha256'] == expected
    assert current['fetch']['evidence_mode'] == 'complete'
    assert current['fetch']['content_sha256'] == original['fetch']['content_sha256']
    assert current['item']['materials'] == original['item']['materials']
    confirmation = current['review']['version_confirmation']
    assert confirmation['acknowledged_raw_sha256'] != confirmation['current_raw_sha256']
    assert confirmation['previous_raw_sha256'] == original['review']['source_sha256']
    assert util.load(root)['review_log'][-1]['source_sha256'] == expected


@pytest.mark.parametrize('change', ['text', 'link', 'attachment', 'image', 'human_edit'])
def test_existing_bundle_cannot_change_during_ai_recheck(published_bundle, change):
    root, queue, state, fetch, original = published_bundle
    before = (root/'data/opportunities.json').read_bytes()
    def checker(*args):
        if change == 'text':
            state['raw'] = state['raw'].replace('成绩单'.encode(), '推荐信'.encode())
        elif change == 'link':
            state['raw'] = state['raw'].replace(b'</article>', b'<a href="https://cs.example.edu.cn/new">new</a></article>')
        elif change == 'attachment':
            state['attachment'] = docx('申请表：姓名及研究经历，并须导师签字。')
        elif change == 'image':
            state['image'] = b'second reviewed image'
        else:
            data = review.read_queue(queue)
            data['drafts'][0]['notes'] = '人工正在复核此条，保留原内容'
            review.atomic_json(queue, data)
        return accepted(*args)
    result = automatic.process(root, queue, original, CONFIGS, publish=True, now=NOW+timedelta(days=15),
                               checker=checker, fetcher=fetch)
    assert result['state'] == 'manual_required', result
    assert (root/'data/opportunities.json').read_bytes() == before
    if change == 'human_edit':
        assert review.read_queue(queue)['drafts'][0]['notes'] == '人工正在复核此条，保留原内容'
