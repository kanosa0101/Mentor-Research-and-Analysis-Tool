import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from crawler import quality_status
from crawler.review_dashboard import Dashboard

NOW = datetime(2026, 11, 16, 14, tzinfo=timezone.utc)
URL = 'https://cs.example.edu.cn/new-policy.html'


def write(root, records):
    folder = root/'cache/policy_intake'
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'state.json').write_text(json.dumps({'version':1,'records':records}), encoding='utf-8')


def entry(status='budget_wait', **extra):
    return dict(title='2027年硕士招生报名政策',source_url=URL,listing_url='https://cs.example.edu.cn/list.html',
        status=status,first_seen=(NOW-timedelta(hours=25)).isoformat(),checked_at=NOW.isoformat(),
        next_attempt_at=(NOW+timedelta(hours=12)).isoformat(),reason='共享AI今日预算耗尽',
        reason_code='ai_budget_wait',next_action='等待共享AI额度恢复，不重置调用账本',**extra)


def test_new_policy_budget_wait_has_stable_sla_no_evidence_payload_and_dashboard_visibility(tmp_path):
    record=entry(proposed_policy={'fields':{'private_marker':'not-for-listing'}},ai={'raw':'not-for-listing'})
    write(tmp_path,{URL:record})
    first=quality_status.refresh(tmp_path,NOW)
    row=first['active'][0]
    assert first['summary']['new_policies']==1 and row['category']=='policy_intake'
    assert row['status']=='budget_wait' and row['overdue']
    assert row['opened_at']==record['first_seen'] and row['due_at']==(NOW-timedelta(hours=1)).isoformat()
    assert row['next_attempt_at']==record['next_attempt_at']
    assert row['action_label']==record['next_action']
    assert row['source_urls']==[URL,record['listing_url']]
    assert 'not-for-listing' not in json.dumps(first)
    record.update(checked_at=(NOW+timedelta(hours=1)).isoformat(),source_sha256='changed-public-body')
    write(tmp_path,{URL:record})
    again=quality_status.refresh(tmp_path,NOW+timedelta(hours=1))['active'][0]
    assert again['fingerprint']==row['fingerprint'] and again['due_at']==row['due_at']
    dashboard=Dashboard(tmp_path).listing()
    assert dashboard['metrics']['quality_alerts']['active'][0]['category']=='policy_intake'
    assert 'not-for-listing' not in json.dumps(dashboard)


def test_published_policy_exits_quality_queue_and_manual_or_eligible_remain_visible(tmp_path):
    write(tmp_path,{
        URL:entry(status='published'),
        'historical':entry(status='historical'),
        'manual':entry(status='manual_required'),
        'eligible':entry(status='eligible'),
    })
    result=quality_status.refresh(tmp_path,NOW)
    assert result['summary']['new_policies']==2
    assert {row['status'] for row in result['active']}=={'manual_required','eligible'}


def test_invalid_intake_clock_and_corrupt_state_are_unknown_not_silently_healthy(tmp_path):
    record=entry();record.pop('first_seen')
    write(tmp_path,{URL:record})
    result=quality_status.refresh(tmp_path,NOW)
    assert result['active'][0]['status']=='unknown'
    assert result['active'][0]['due_at'] is None and len(result['incomplete'])==1
    (tmp_path/'cache/policy_intake/state.json').write_text('not JSON')
    result=quality_status.refresh(tmp_path,NOW)
    assert result['failures']['policy_intake']=='JSONDecodeError'


def test_intake_pending_since_has_priority_over_older_discovery_time(tmp_path):
    record=entry(pending_since=(NOW-timedelta(hours=3)).isoformat())
    write(tmp_path,{URL:record})
    row=quality_status.refresh(tmp_path,NOW)['active'][0]
    assert row['opened_at']==record['pending_since'] and not row['overdue']


@pytest.mark.parametrize('width,height',[(1440,1000),(390,844)])
def test_maintainer_sees_policy_waits_reasons_sources_and_sla_in_real_browser(tmp_path,width,height):
    from playwright.sync_api import sync_playwright, expect
    from scripts.review_v18_ui_check import fixture
    from scripts import serve_review
    fixture(tmp_path)
    records={}
    for state in ('budget_wait','manual_required','eligible'):
        record=entry(status=state)
        record['title']='新政策验收 '+state
        record['reason_code']='ai_budget_wait' if state=='budget_wait' else state
        records[state]=record
    write(tmp_path,records)
    quality_status.refresh(tmp_path,NOW)
    server=serve_review.make_server(tmp_path,port=0)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    output=Path(__file__).resolve().parents[1]/'cache/v1116/maintainer-policy-ui'
    output.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch()
            page=browser.new_page(viewport={'width':width,'height':height})
            errors=[];writes=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:writes.append(request.url) if request.method not in ('GET','HEAD') else None)
            page.goto(f'http://127.0.0.1:{server.server_port}/review.html')
            expect(page.locator('#quality-summary')).to_contain_text('新政策核验 3')
            page.locator('#quality-panel > summary').click()
            for state in ('budget_wait','manual_required','eligible'):
                detail=page.locator('#quality-items > details').filter(has_text='新政策验收 '+state)
                detail.locator('summary').click()
                expect(detail).to_contain_text({'budget_wait':'AI额度等待','manual_required':'需人工核验','eligible':'证据通过待发布'}[state])
                expect(detail).to_contain_text('处理时限：')
                expect(detail).to_contain_text('下次检查：')
            page.locator('#quality-reason').select_option('ai_budget_wait')
            expect(page.locator('#quality-items > details')).to_have_count(1)
            page.locator('#quality-items > details > summary').click()
            expect(page.locator('#quality-items')).to_contain_text('等待共享AI额度恢复，不重置调用账本')
            expect(page.locator('#quality-items a')).to_have_count(2)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.locator('#quality-panel').screenshot(path=str(output/f'policy-wait-{width}.png'))
            assert not errors and not writes
            browser.close()
    finally:
        server.shutdown();server.server_close()
