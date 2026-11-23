"""Review observed differences in the registered direction on SCU's official profile."""
import copy
from datetime import datetime
import hashlib
import json
import re

import yaml
from bs4 import UnicodeDammit

from crawler.model import Professor
from crawler.opportunity_monitor import OutputLockBusy, output_lock


UNIT = 'scu/cs'
FIELD = 'research_direction_raw'
KIND = 'research_direction_changed'
LABEL = '同源研究方向待复核'
REASON = '已核对的本人官方栏目与已登记方向不同，请查阅原文和登记出处。'
_REF = re.compile(r'[a-z0-9_-]+')
_SHA = re.compile(r'[a-f0-9]{64}')


def enabled(unit, cfg):
    return unit == UNIT and cfg.get('hook') == 'scu_cs'


def registration(person):
    return {key: person.get(key) for key in ('school', 'dept', 'slug', 'name', 'detail_url', FIELD)} | {
        'provenance': person.get('provenance', {}).get(FIELD, {}),
    }


def capture(original, proposal, response, digest, attempt):
    url = original['detail_url']
    if not (proposal and response.get('status') == 200 and response.get('redirected') is False
            and response.get('requested_url') == response.get('final_url') == url
            and _time(response.get('observed_utc'))):
        return None
    return {'registered': registration(original), 'proposal': proposal, 'attempt': attempt,
            'source': dict(response, url=url, sha256=digest,
                           path=f'cache/legacy_refresh/evidence/{digest}.body')}


def _time(value):
    try:
        stamp = datetime.fromisoformat(value)
        return stamp if stamp.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _record_verified(root, record, current, now):
    from sites.scu.scu_cs import replay_direction_observation

    try:
        event = record['research_direction_observation']
        registered, source, proposal = event['registered'], event['source'], event['proposal']
        digest, observed = source['sha256'], _time(source['observed_utc'])
        attempt = _time(event['attempt'])
        url = current['detail_url']
        expected_path = f'cache/legacy_refresh/evidence/{digest}.body'
        if not (record['status'] == 'ok' and record['last_attempt'] == event['attempt']
                and record['raw_sha256'] == digest and _SHA.fullmatch(digest) and source['path'] == expected_path
                and source['url'] == source['requested_url'] == source['final_url'] == url == record['source_url']
                and source['status'] == 200 and source['redirected'] is False and attempt and observed and attempt <= observed <= now
                and event['current'] == registration(current)):
            return None
        # Same-value refreshes may advance only the existing provenance date.
        if _registration_key(registered) != _registration_key(event['current']):
            return None
        body_path = root / expected_path
        if body_path.is_symlink():
            return None
        body = body_path.read_bytes()
        if hashlib.sha256(body).hexdigest() != digest:
            return None
        original = dict(registered, provenance={FIELD: registered['provenance']})
        html = UnicodeDammit(body).unicode_markup
        if html and replay_direction_observation(original, html, url) == proposal:
            return event, observed
    except (OSError, KeyError, ValueError, TypeError, AttributeError):
        pass
    return None


def _registration_key(registered):
    # Ignore an ordinary unchanged-source recheck's date when identifying the same registration.
    return dict(registered, provenance={key: value for key, value in registered['provenance'].items()
                                        if key != 'fetched_at'})


def _pin(event):
    registered, proposal = event['registered'], event['proposal']
    basis = [registered[key] for key in ('school', 'dept', 'slug', 'detail_url', FIELD)]
    basis.append(proposal['comparison_terms'])
    return hashlib.sha256(json.dumps(basis, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _archive(issue, now, state):
    previous = issue.get('automatic_check') or {}
    issue.setdefault('review_history', []).append({'date': now.isoformat(), 'automatic': True, 'state': state,
        'reviewed': issue.get('reviewed'), 'review_note': issue.get('review_note'), 'previous_check': previous})


def _close(issue, current, now, *, event=None, resolution):
    old = issue['automatic_check']
    _archive(issue, now, resolution)
    issue['resolved'] = True
    observed = event['source']['observed_utc'] if event else now.isoformat()
    reason = '本人官方栏目已与登记方向一致。' if event else '登记方向或来源已变化，结束旧差异复核。'
    issue['automatic_check'] = dict(old, status='resolved', resolution=resolution, pending_since=None,
                                    reason=reason, next_action='none', next_check_at=None, checked_at=observed,
                                    observation=event or old['observation'], registered=registration(current),
                                    evidence=[event['source']] if event else old['evidence'])


def _apply(issue, current, verified, now):
    """Return a changed existing issue or a newly constructed issue."""
    old = (issue or {}).get('automatic_check') or {}
    if issue and 'registered' not in old:
        return None
    closed = bool(issue and (issue.get('resolved') or issue.get('reviewed')))
    auto_restored = (closed and old.get('resolution') == 'source_restored'
                     and issue.get('reviewed') is None and not issue.get('review_note'))
    if verified:
        event, observed = verified
        checked = _time(old.get('checked_at'))
        if checked and observed <= checked:
            verified = None
    if not verified:
        if issue and not closed and _registration_key(registration(current)) != _registration_key(old['registered']):
            _close(issue, current, now, resolution='registration_changed')
            return issue
        return None
    if event['proposal']['same']:
        if not issue:
            return None
        if closed and not auto_restored:
            issue['automatic_check'] = dict(old, checked_at=event['source']['observed_utc'])
            return issue
        if auto_restored:
            issue['automatic_check'] = dict(old, checked_at=event['source']['observed_utc'], observation=event,
                                            evidence=[event['source']], registered=event['current'])
            return issue
        _close(issue, current, now, event=event, resolution='source_restored')
        return issue
    checked_at = event['source']['observed_utc']
    fingerprint = _pin(event)
    same = old.get('fingerprint') == fingerprint and _registration_key(old['registered']) == _registration_key(event['current'])
    if closed and same and not auto_restored:
        # Advance the observation watermark without changing the human decision.
        issue['automatic_check'] = dict(old, checked_at=checked_at)
        return issue
    if issue is None:
        issue = dict(kind=KIND, ref=current['slug'], first_seen=now.date().isoformat(), message=REASON, review_history=[])
    elif not same or closed:
        _archive(issue, now, 'reopened' if closed else 'candidate_changed')
    if not same or closed:
        issue.update(resolved=False, reviewed=None, review_note=None)
    issue['automatic_check'] = dict(status='pending', reason_code=KIND, category_label=LABEL,
        next_action='manual_review', action_label='对照已登记值和最新本人原文', reason=REASON, next_check_at=None,
        pending_since=old.get('pending_since') if not closed and old.get('pending_since') else checked_at,
        checked_at=checked_at, fingerprint=fingerprint, registered=event['current'], observation=event,
        evidence=[event['source']], source_urls={'profile': event['source']['url']})
    return issue


def seed(root, records, now, load_yaml, write_yaml):
    """Update the existing issue file using its lock and the current profile bytes."""
    issue_path = root / 'data/issues/scu-cs.yaml'
    prefix = 'professor/scu/cs/'
    observed = {key[len(prefix):-5]: row for key, row in records.items()
                if key.startswith(prefix) and key.endswith('.yaml') and row.get('research_direction_observation')}
    if not observed and not issue_path.is_file():
        return 0
    cfg_path = root / 'sites/scu/cs.yaml'
    if not cfg_path.is_file() or not enabled(UNIT, load_yaml(cfg_path)):
        return 0
    created = 0
    with output_lock(issue_path):
        issues = load_yaml(issue_path) or [] if issue_path.is_file() else []
        existing = {row['ref']: i for i, row in enumerate(issues) if row['kind'] == KIND}
        for ref in sorted(observed.keys() | existing.keys()):
            if not _REF.fullmatch(ref):
                continue
            index = existing.get(ref)
            current_issue = issues[index] if index is not None else None
            row = observed.get(ref, {})
            if current_issue is None:
                event = row.get('research_direction_observation')
                proposal = event.get('proposal') if isinstance(event, dict) else None
                if not isinstance(proposal, dict) or proposal.get('same') is not False:
                    continue
            profile = root / 'data/professors/scu/cs' / f'{ref}.yaml'
            if not profile.is_file() or profile.is_symlink():
                continue
            try:
                with output_lock(profile):
                    before = profile.read_bytes()
                    person = yaml.safe_load(before)
                    checked = Professor.model_validate(person)
                    if (checked.school, checked.dept, checked.slug) != ('scu', 'cs', ref):
                        continue
                    verified = _record_verified(root, row, person, now)
                    updated = _apply(copy.deepcopy(current_issue), person, verified, now)
                    if not updated or profile.read_bytes() != before:
                        continue
                    if index is None:
                        issues.append(updated)
                        created += 1
                    else:
                        issues[index] = updated
                    write_yaml(issue_path, issues)
            except (OSError, ValueError, yaml.YAMLError, OutputLockBusy):
                continue
    return created
