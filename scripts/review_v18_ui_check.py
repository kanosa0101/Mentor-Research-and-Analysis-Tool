"""Real loopback API/UI acceptance using temporary public-evidence fixtures only."""
import argparse
import base64
import copy
import json
import shutil
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import yaml
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from crawler import maintenance_push, opportunity_review as review, review_queue, source_discovery, quality_status
from scripts import serve_review


def fixture(root):
    now = datetime.now(timezone.utc)
    deadline = (now + timedelta(days=1)).date().isoformat()
    listing = 'https://cs.example.edu.cn/list.htm'
    configs = [dict(url=listing, school='example', dept='cs', unit='示例大学计算机学院')]
    (root / 'sites').mkdir()
    (root / 'sites/opportunities.yaml').write_text(yaml.safe_dump(dict(targets=configs)), encoding='utf8')
    queue = root / 'cache/opportunity_review.json'
    raw = f'<article><p>2027年冬令营面向2028届本科毕业生。</p><p>报名截止{deadline}。</p><p>申请材料：成绩单、个人简历。</p></article>'.encode()
    candidate = dict(url='https://cs.example.edu.cn/camp.htm', source=listing, title='示例大学计算机冬令营', school='example', dept='cs', unit='计算机学院', first_seen=(now-timedelta(days=3)).isoformat(), last_seen=now.isoformat())
    data = review.sync(dict(candidates=[candidate]), queue, configs, fetcher=lambda _: raw)
    draft = data['drafts'][0]
    draft['item'].update(kind='winter_camp', cycle='current', school_name='示例大学', eligibility=['面向2028届本科毕业生'], evidence=['隔离验收数据，不是真实机会'], deadline=deadline)
    quote = '2027年冬令营面向2028届本科毕业生。'
    draft['quotes'] = [quote]
    hidden = dict(quote=quote, source_url=candidate['url'], locator='申请对象第1段', content_sha256=draft['fetch']['content_sha256'])
    draft['reviewed_fields'] = dict(research_directions=hidden, deadline=dict(quote=f'报名截止{deadline}。', source_url=candidate['url'], locator='报名截止第2段', precision='date', content_sha256=draft['fetch']['content_sha256']))
    draft['automatic_review'] = dict(state='manual_required', reasons=['材料提交阶段不完整，保留人工处理'], checked_at=now.isoformat(), policy_version='v1.8-extractive-1', source_sha256=draft['fetch']['sha256'], ai=dict(field_checks=[dict(field='eligibility', quote=quote)]), assistance=dict(state='ready', suggestions=1, scope='仅HTML正文逐字建议；未核验附件、申请届别或资格，不构成可发布结论'))
    other = copy.deepcopy(draft)
    other.update(id='budget-fixture', first_seen=now.isoformat(), automatic_review=dict(state='budget_wait', reasons=['本轮AI调用额度已用尽'], checked_at=now.isoformat(), next_attempt_at=(now+timedelta(hours=1)).isoformat()))
    other['item'].update(id=other['id'], title='人工智能科研实践等待核验')
    data['drafts'].append(other)
    review.atomic_json(queue, data)
    review_queue.refresh_alerts(root)
    review.atomic_json(root/'cache/automatic-review.json', dict(version=1, mode='publish', completed_at=now.isoformat(), counts=dict(manual_required=1, budget_wait=1), errors=['AI服务HTTP 503；当前未完成自动核验']))
    review.atomic_json(root/'cache/review-pipeline.json', dict(status='partial', completed_at=now.isoformat(), failures=dict(automatic='AI服务HTTP 503')))
    review.atomic_json(root/'cache/policy_revalidation/state.json', dict(policies={
        'policy-retry': dict(title='示例大学计算机与人工智能学院招生政策', status='retry',
            pending_since=(now-timedelta(hours=25)).isoformat(), last_attempt=now.isoformat(),
            next_attempt=(now+timedelta(hours=2)).isoformat(), source_urls={'notice':listing},
            reasons=[dict(message='官方材料附件暂时无法取回，保留旧证据并按计划重试；不能确认最新材料要求。')]),
        'policy-review': dict(title='示例大学网络空间安全学院材料清单', status='review_required',
            pending_since=(now-timedelta(hours=3)).isoformat(), last_attempt=now.isoformat(),
            next_attempt=(now+timedelta(hours=1)).isoformat(), source_urls={'notice':listing},
            reasons=['官方正文发生变化，申请条件与材料提交阶段需要重新核对。']),
        'policy-confirmed': dict(title='不应出现在待办里的已确认政策', status='confirmed')}))
    review.atomic_json(root/'cache/mentor_quality/state.json', dict(records={
        'mentor-pending': dict(title='示例大学智能科学与技术学院导师研究方向与联系人资料', status='pending',
            pending_since=(now-timedelta(hours=2)).isoformat(), checked_at=now.isoformat(),
            next_check_at=(now+timedelta(hours=6)).isoformat(), reason='官网未明确公开邮箱，等待后续来源更新。',
            evidence=[dict(url='https://cs.example.edu.cn/people/teacher-profile.htm')]),
        'mentor-error': dict(title='示例大学自动化学院导师详情', status='error',
            pending_since=(now-timedelta(hours=26)).isoformat(), checked_at=now.isoformat(),
            next_check_at=(now+timedelta(hours=6)).isoformat(), reason='导师页面暂时返回访问验证页，未以导航文本补充研究方向。',
            evidence=dict(source_url='https://cs.example.edu.cn/people/teacher-profile.htm')),
        'mentor-resolved': dict(title='不应出现在待办里的已解决导师', status='resolved')}))
    quality_status.refresh(root, now)
    column = '<html><title>计算机科研实践</title><a href="newcamp.htm">2027年大学生冬令营报名通知</a></html>'.encode()
    url = 'https://cs.example.edu.cn/research.htm'
    source = dict(id='fixture-source', url=url, label='示例大学科研实践栏目', school='example', dept='', unit='科研实践', parent_url=listing, parent_label='已配置官方栏目', first_seen=now.isoformat(), checked_at=now.isoformat(), status='candidate', kind='column', reason='同机构栏目内发现招生公告', **source_discovery.inspect(column, url))
    review.atomic_json(root/'cache/source-discovery.json', dict(version=1, checked_at=now.isoformat(), candidates=[source]))
    (root/'site').mkdir()
    for name in ('review.html', 'review.js', 'review-worker.js', 'ui.css'):
        shutil.copyfile(ROOT/'site'/name, root/'site'/name)
    (root/'var/push').mkdir(parents=True)
    key = base64.urlsafe_b64encode(b'\x04'+b'a'*64).decode().rstrip('=')
    review.atomic_json(root/'var/push/config.json', dict(public_key=key))
    (root/'var/push/vapid.pem').write_text('isolated-key-fixture', encoding='utf8')
    review.atomic_json(root/'var/review-notifications/last-delivery.json', dict(retry_exhausted=1))
    return draft['id'], column, hidden


MOCK_BROWSER = """() => {
 window.__notices=[];window.__permissionRequests=0;window.__pushSubscriptions=0;
 class Notice { static permission='default';static async requestPermission(){window.__permissionRequests++;Notice.permission='granted';return 'granted';}constructor(title,options){window.__notices.push({title,...options});}}
 Object.defineProperty(window,'Notification',{value:Notice,configurable:true});
 const enc=s=>btoa(s).replaceAll('+','-').replaceAll('/','_').replaceAll('=','');
 let sub=null;const manager={getSubscription:async()=>sub,subscribe:async()=>{window.__pushSubscriptions++;sub={toJSON:()=>({endpoint:'https://fcm.googleapis.com/fcm/send/ui-fixture',keys:{auth:enc('a'.repeat(16)),p256dh:enc(String.fromCharCode(4)+'a'.repeat(64))}}),unsubscribe:async()=>{sub=null;return true;}};return sub;}};
 const registration={pushManager:manager};Object.defineProperty(navigator,'serviceWorker',{value:{register:async()=>registration,ready:Promise.resolve(registration),getRegistration:async()=>registration},configurable:true});
 Object.defineProperty(window,'PushManager',{value:function(){},configurable:true});
}"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'cache/v18/review-ui')
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    checks = []
    with tempfile.TemporaryDirectory(prefix='maintainer-review-v18-') as folder:
        root = Path(folder); ident, column, hidden = fixture(root)
        server = serve_review.make_server(root, port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            parent = '<meta charset="utf-8"><a href="research.htm">示例大学科研实践栏目</a>'.encode()
            with patch.object(source_discovery, 'fetch_html', side_effect=lambda url,*_: parent if url.endswith('/list.htm') else column), patch('crawler.push_util.send', return_value=201), sync_playwright() as pw:
                browser = pw.chromium.launch()
                for width, height in ((1440,1000),(390,844)):
                    context = browser.new_context(viewport=dict(width=width,height=height))
                    context.add_init_script('('+MOCK_BROWSER+')()')
                    page = context.new_page(); errors=[]; page.on('pageerror', lambda e:errors.append(str(e)))
                    page.on('dialog', lambda dialog:dialog.accept())
                    page.goto(base+'/review.html?draft='+ident)
                    expect(page.locator('#detail h2')).to_have_text('示例大学计算机冬令营' if width==1440 else '人工保存后的标题')
                    expect(page.locator('#auto-errors')).to_contain_text('503')
                    expect(page.locator('#alert-list')).to_contain_text('已超时')
                    expect(page.locator('#push-delivery')).to_contain_text('重试已用尽')
                    assert page.evaluate('window.__permissionRequests') == 0
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    page.evaluate('window.scrollTo(0,0)'); page.screenshot(path=str(args.output/f'review-{width}-overview.png'))
                    page.locator('#quality-panel > summary').click()
                    expect(page.locator('#quality-summary')).to_contain_text('政策待处理 2 · 导师资料待处理 2 · 超时 2')
                    expect(page.locator('#quality-items > details')).to_have_count(4)
                    for summary in page.locator('#quality-items > details > summary').all():
                        summary.click()
                    expect(page.locator('#quality-items')).to_contain_text('等待来源重试 · 已超时')
                    expect(page.locator('#quality-items')).to_contain_text('变更或证据需核对')
                    expect(page.locator('#quality-items')).to_contain_text('来源或解析失败 · 已超时')
                    expect(page.locator('#quality-items')).to_contain_text('待补齐')
                    expect(page.locator('#quality-items')).not_to_contain_text('不应出现在待办')
                    expect(page.locator('#quality-items a')).to_have_count(4)
                    expect(page.locator('#quality-items')).to_contain_text('下次检查')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    page.locator('#quality-panel').screenshot(path=str(args.output/f'review-{width}-quality.png'))
                    page.locator('#quality-panel > summary').click()
                    checks.append(f'{width}px quality panel: retry/review_required/pending/error, overdue and next retry visible, resolved rows absent, 4 official source links, no overflow')
                    expect(page.locator('.automation-result')).to_contain_text('已生成 1 条AI辅助摘录')
                    page.locator('#detail').evaluate("element=>element.scrollIntoView({block:'start'})")
                    page.screenshot(path=str(args.output/f'review-{width}-detail.png'))
                    page.locator('#priority-filter').select_option('retry')
                    expect(page.locator('#queue button')).to_have_count(1)
                    expect(page.locator('#queue')).to_contain_text('等待AI调用额度')
                    page.locator('#priority-filter').select_option('overdue')
                    expect(page.locator('#queue button')).to_have_count(1)
                    page.locator('#priority-filter').select_option('active')
                    page.locator('#notify-alerts').click()
                    assert page.evaluate('window.__notices.length') == 1
                    page.evaluate('window.REVIEW_POLL()')
                    assert page.evaluate('window.__notices.length') == 1
                    page.locator('#subscribe-push').click()
                    expect(page.locator('#push-status')).to_contain_text('已登记维护者后台订阅')
                    assert len(maintenance_push.read(maintenance_push.paths(root)[0])) == 1
                    page.locator('#test-push').click()
                    expect(page.locator('#push-status')).to_contain_text('测试通知已交给发送服务')
                    page.locator('#unsubscribe-push').click()
                    expect(page.locator('#push-status')).to_contain_text('已取消维护者后台订阅')
                    assert not maintenance_push.read(maintenance_push.paths(root)[0])
                    assert not (root/'var/push/alerts.sqlite').exists()
                    if width==1440:
                        title = page.get_by_label('活动名称', exact=True)
                        title.fill('尚未保存的人工输入')
                        data = review.read_queue(root/'cache/opportunity_review.json')
                        data['drafts'][0]['automatic_review']['reasons'].append('后台更新了审核原因')
                        review.atomic_json(root/'cache/opportunity_review.json', data)
                        page.evaluate('window.REVIEW_POLL()')
                        expect(title).to_have_value('尚未保存的人工输入')
                        expect(page.locator('#live-status')).to_contain_text('此处输入保留')
                        page.get_by_role('button',name='保存草稿',exact=True).click()
                        expect(page.locator('#message')).to_contain_text('其他')
                        expect(title).to_have_value('尚未保存的人工输入')
                        page.locator('#reload').click()
                        title = page.get_by_label('活动名称', exact=True)
                        expect(title).to_have_value('示例大学计算机冬令营')
                        title.fill('人工保存后的标题')
                        page.locator('#source-panel summary').first.click()
                        page.get_by_role('button',name='核准接入监测',exact=True).click()
                        expect(page.locator('#message')).to_contain_text('来源已核准进入监测')
                        expect(page.locator('#source-candidates')).to_contain_text('已接入监测')
                        expect(title).to_have_value('人工保存后的标题')
                        assert len(yaml.safe_load((root/'sites/opportunities.yaml').read_text(encoding='utf8'))['targets'])==2
                        assert list((root/'cache/source-discovery-backups').glob('*.yaml'))
                        page.locator('#source-panel').scroll_into_view_if_needed(); page.screenshot(path=str(args.output/'review-1440-source-approved.png'))
                        page.get_by_role('button',name='保存草稿',exact=True).click()
                        expect(page.locator('#message')).to_contain_text('草稿已更新')
                        saved=review.read_queue(root/'cache/opportunity_review.json')['drafts'][0]
                        assert saved['manual_edit']['action']=='save'
                        assert saved['reviewed_fields']['research_directions']==hidden
                        assert saved['reviewed_fields']['deadline']['precision']=='date'
                        assert saved['reviewed_fields']['deadline']['content_sha256']
                        checks.append('dirty polling/stale409/manual marker/hidden and version-bound evidence preserved/source config backed up')
                    assert not errors, errors
                    assert not (root/'data/opportunities.json').exists()
                    checks.append(f'{width}px real API, no overflow/page errors, priority filters, opt-in foreground dedup, isolated background subscribe/test/unsubscribe')
                    context.close()
                context = browser.new_context()
                context.add_init_script("window.__realPermissionRequests=0;const original=Notification.requestPermission.bind(Notification);Notification.requestPermission=(...args)=>{window.__realPermissionRequests++;return original(...args);};")
                page = context.new_page(); page.goto(base+'/review.html')
                expect(page.locator('#queue button')).to_have_count(2)
                assert page.request.get(base+'/review-worker.js').status==200
                assert page.request.get(base+'/var/review-notifications/subscriptions.json').status==404
                registered = page.evaluate("async()=>{const worker=await navigator.serviceWorker.register('/review-worker.js');await navigator.serviceWorker.ready;const active=!!worker.active;await worker.unregister();return active;}")
                assert registered
                assert page.evaluate('window.__realPermissionRequests')==0
                checks.append('real browser service worker installed/activated without requesting notification permission; private store URL denied')
                context.close()
                browser.close()
        finally:
            server.shutdown(); server.server_close()
    report=dict(passed=True,checks=checks,notification_delivery='Browser/system display mocked; real loopback HTTP and independent maintainer store exercised. No actual external push delivery claimed.',production_mutations=False)
    (args.output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()
