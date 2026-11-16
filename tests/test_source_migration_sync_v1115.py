import copy
from datetime import datetime, timezone

from crawler import opportunity_review as review


def test_migrated_old_candidate_cannot_recreate_failed_url_or_steal_existing_id(tmp_path):
    now = datetime(2026, 11, 16, tzinfo=timezone.utc)
    old, new, listing = ('https://cs.example.edu.cn/' + n for n in ('old.htm', 'new.htm', 'admissions.htm'))
    queue = tmp_path/'cache/review.json'
    candidate = dict(url=old, source=listing, school='example', dept='cs', unit='计算机学院',
                     title='2027年冬令营', first_seen=now.isoformat(), last_seen=now.isoformat())
    configs = [{'url': listing}]
    raw = '<article>2027年冬令营：申请对象为2028届本科生。</article>'.encode()
    data = review.sync({'candidates': [candidate]}, queue, configs, fetcher=lambda _: raw, now=now)
    draft = data['drafts'][0]
    original_id = draft['id']
    draft['source_url'] = draft['item']['source_url'] = new
    draft['source_replacements'] = [dict(original_url=old, new_url=new, old_sha='a'*64,
        new_sha='b'*64, adopted_at=now.isoformat(), title=candidate['title'])]
    review.atomic_json(queue, data)
    other_listing = listing.replace('admissions.htm', 'camp.htm')
    configs.append({'url': other_listing})
    result = review.sync({'candidates': [dict(candidate, url=new, source=other_listing), candidate]}, queue, configs,
                         fetcher=lambda _: raw, now=now)
    assert len(result['drafts']) == 1 and result['drafts'][0]['source_url'] == new
    assert result['drafts'][0]['id'] == original_id
    assert result['summary']['retired_candidates'] == 1
    assert result['drafts'][0]['listing_url'] == other_listing
    # An old URL later reused for a different announcement remains discoverable.
    result = review.sync({'candidates': [dict(candidate, title='2028年冬令营')]}, queue,
                         configs, fetcher=lambda _: raw, now=now)
    assert len(result['drafts']) == 2
    assert len({d['id'] for d in result['drafts']}) == 2
    review.read_queue(queue)


def test_unverified_or_broken_migration_metadata_cannot_hide_candidate():
    draft = dict(source_url='https://example.edu.cn/new', source_replacements=[
        dict(original_url='https://example.edu.cn/old', new_url='https://example.edu.cn/new',
             old_sha='a'*64, new_sha='b'*64, adopted_at='2026-11-16T00:00:00+00:00')])
    assert review.replaced_sources(draft) == {'https://example.edu.cn/old'}
    for key, value in [('adopted_at', None), ('old_sha', 'invalid'), ('new_url', 'https://example.edu.cn/other')]:
        broken = copy.deepcopy(draft);broken['source_replacements'][0][key] = value
        assert review.replaced_sources(broken) == set()
