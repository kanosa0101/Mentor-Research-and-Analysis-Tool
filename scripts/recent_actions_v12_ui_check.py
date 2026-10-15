"""Project recent actions with a frozen clock and temporary private records."""
import json
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.serve import create_server
from scripts.workflow_v8_ui_check import render_test_site

NOW = '2026-10-15T16:30:00Z'  # Beijing Oct 16; browser UTC still Oct 15.


def event(label, at, kind='plan', origin='manual'):
    return dict(label=label, at=at, kind=kind, origin=origin,
                policy_id='historical-policy' if origin == 'policy' else '',
                source_ids=['historical-source'] if origin == 'policy' else [],
                source_url='https://example.org/historical' if origin == 'policy' else '',
                quote='历史测试原文' if origin == 'policy' else '',
                locator='历史测试位置' if origin == 'policy' else '')


def main():
    out = ROOT / 'cache/ux_v12/recent_actions'
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        root = Path(tmp)
        server = create_server(site=render_test_site(root), outreach=root / 'private/outreach.yaml', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000}, timezone_id='UTC')
                page.clock.set_fixed_time(NOW)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                base = f'http://127.0.0.1:{server.server_port}'
                page.goto(base + '/applications.html')
                page.wait_for_function('window.WORKFLOW_READY')
                mentor = page.evaluate('MENTOR_DATA[0].page')
                mentor_name = page.evaluate('MENTOR_DATA[0].name')
                projects = {}
                for key, name in [('main', '申请中的项目'), ('today', '今天的安排'), ('precise', '跨时区安排'),
                                  ('mixed', '同日精度不同'), ('history', '仅有历史安排'), ('empty', '尚无日期'),
                                  ('archived', '已归档项目')]:
                    projects[key] = page.evaluate('p=>api("/projects",p,"POST")', {
                        'name': name, 'status': 'archived' if key == 'archived' else 'planned',
                        'mentor_ids': [mentor] if key == 'main' else []})['id']
                reminders = {}
                for key, title, day, completed, owner in [
                    ('main', '较晚待办', '2026-10-18', False, ''),
                    ('main', '更早但已完成', '2026-10-01', True, ''),
                    ('today', '其他项目更早逾期', '2026-10-01', False, ''),
                    ('main', '需要跟进导师回复', '2026-10-15', False, mentor),
                    ('main', '今日核对文件', '2026-10-16', False, ''),
                    ('archived', '归档后保留的提醒', '2026-10-15', False, '')]:
                    reminders[title] = page.evaluate('p=>api("/reminders",p,"POST")', {
                        'title': title, 'project_id': projects[key], 'due_date': day,
                        'completed': completed, 'mentor_id': owner})['id']
                # Restore historical snapshots into the temporary index, as the existing v3 contract permits.
                backup = page.evaluate('api("/backup")')
                dates = {
                    'main': [event('较晚个人计划', '2026-10-20'),
                             event('昨日已截止', '2026-10-15', 'deadline', 'policy'),
                             event('今日已过的精确截止', '2026-10-16T00:15:00+08:00', 'deadline', 'policy'),
                             event('今日日期未注明时刻', '2026-10-16', 'deadline', 'policy')],
                    'today': [event('今日核对计划', '2026-10-16')],
                    'precise': [event('原文日期较早但北京时间较晚', '2026-10-15T23:30:00-12:00'),
                                event('同日较晚考核', '2026-10-16T19:00:00+08:00', 'exam', 'policy'),
                                event('同日较早资格安排', '2026-10-16T10:00:00+00:00', 'qualification', 'policy')],
                    'mixed': [event('同日未写时刻', '2026-10-16'),
                              event('同日明确时刻', '2026-10-16T01:00:00+08:00')],
                    'history': [event('历史截止', '2026-09-30', 'deadline', 'policy'),
                                event('历史个人计划', '2026-10-15')],
                    'empty': [],
                    'archived': [event('归档保留的后续日期', '2026-10-20')],
                }
                # UTC-12 example is Beijing Oct 16 19:30, after both Oct 16 18:00/19:00.
                for key, values in dates.items():
                    backup['workflow']['projects'][projects[key]]['deadlines'] = values
                page.evaluate('p=>api("/restore",p,"POST")', backup)
                page.evaluate('refresh()')
                before = page.evaluate('api("/backup")')

                def card(key):
                    return page.locator(f'#project-list > article:has([data-edit-project="{projects[key]}"])')

                def summary(key):
                    return card(key).locator('.project-next-actions')

                def show_projects():
                    page.click('[data-section="project"]')
                    page.select_option('#filter-project', '')

                assert summary('main').count() == 1, 'project card must have a recent-action summary'
                text = summary('main').inner_text()
                assert '逾期未完成' in text and '需要跟进导师回复' in text and mentor_name in text
                assert '今日日期未注明时刻' in text and '2026-10-16' in text
                assert '官方事件快照' in text and '报名 / 材料截止' in text
                assert '报名是否开放仍须核实' in text
                assert '原政策已变化 / 未找到' in text and '申请前核对原文' in text
                assert '未完成提醒 · 3 项' in text
                assert all(label not in text for label in ['较晚待办', '更早但已完成', '其他项目更早逾期', '昨日已截止', '今日已过的精确截止'])
                assert '同日较早资格安排' in summary('precise').inner_text()
                assert '资格相关时间' in summary('precise').inner_text()
                assert '2026-10-16T10:00:00+00:00' in summary('precise').inner_text()
                assert '同日未写时刻' in summary('mixed').inner_text()
                assert '同日另有 1 条安排' in summary('mixed').inner_text()
                assert '先后未确定' in summary('mixed').inner_text()
                assert '今日核对计划' in summary('today').inner_text() and '个人计划' in summary('today').inner_text()
                for key in ('history', 'empty'):
                    assert '尚未登记后续安排' in summary(key).inner_text()
                    assert '暂无未完成提醒' in summary(key).inner_text()
                    assert '历史截止' not in summary(key).inner_text()
                assert '已归档' in summary('archived').inner_text()
                assert '归档后保留的提醒' in summary('archived').inner_text()
                assert '正在申请' not in summary('archived').inner_text()
                card('history').locator('[data-project-requirements]').click()
                assert '历史截止' in card('history').inner_text()
                assert '历史个人计划' in card('history').inner_text()
                # Read-only summary selection must not reorder stored dates.
                assert page.evaluate('api("/backup")') == before
                for width, height in ((1440, 1000), (390, 844)):
                    page.set_viewport_size({'width': width, 'height': height})
                    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'), width
                    card('main').scroll_into_view_if_needed()
                    page.screenshot(path=str(out / f'recent-actions-{width}.png'))
                page.set_viewport_size({'width': 1440, 'height': 1000})
                # Existing dirty guard also protects the new visible reminder shortcut.
                url = page.url
                page.fill('#project-name', '尚未保存的输入')
                page.once('dialog', lambda dialog: dialog.dismiss())
                summary('main').locator('[data-project-section="reminder"]').click()
                assert page.input_value('#project-name') == '尚未保存的输入'
                assert page.locator('#section-project').is_visible() and page.url == url
                page.once('dialog', lambda dialog: dialog.accept())
                summary('main').locator('[data-project-section="reminder"]').click()
                assert page.locator('#section-reminder').is_visible()
                assert page.input_value('#filter-project') == projects['main']
                assert page.input_value('#reminder-project') == projects['main']
                assert '其他项目更早逾期' not in page.inner_text('#reminder-list')
                today_row = page.locator('#reminder-list article').filter(has_text='今日核对文件')
                assert '今天' in today_row.inner_text(), 'reminder list must use Beijing day even in a UTC browser'
                assert today_row.locator('.overdue').count() == 0
                assert page.locator('#reminder-list article').filter(has_text='需要跟进导师回复').locator('.overdue').count() == 1
                assert '逾期未完成' in page.locator('#reminder-list article').filter(has_text='需要跟进导师回复').inner_text()
                page.click(f'[data-toggle-reminder="{reminders["需要跟进导师回复"]}"]')
                page.wait_for_function('(id)=>WORKFLOW.reminders[id].completed', arg=reminders['需要跟进导师回复'])
                show_projects()
                assert '今天' in summary('main').inner_text() and '项目事项' in summary('main').inner_text()
                assert '今日核对文件' in summary('main').inner_text()
                assert '今日日期未注明时刻' in summary('main').inner_text(), 'completion cannot remove an official date'
                page.evaluate('id=>api("/reminders/"+id,{completed:true},"PATCH")', reminders['今日核对文件'])
                page.evaluate('refresh()')
                assert '待办' in summary('main').inner_text() and '较晚待办' in summary('main').inner_text()
                # Reordering precise-only input still chooses the actual earliest instant.
                page.evaluate('(id)=>{WORKFLOW.projects[id].deadlines.reverse();render()}', projects['precise'])
                assert '同日较早资格安排' in summary('precise').inner_text()
                # Advance into the earliest exact event: exam becomes the next event, with its own kind.
                page.clock.set_fixed_time('2026-10-16T10:30:00Z')
                page.evaluate('render()')
                assert '同日较晚考核' in summary('precise').inner_text()
                assert '考试 / 考核安排' in summary('precise').inner_text()
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
    result = {'status': 'PASS', 'frozen_now': NOW, 'browser_timezone': 'UTC',
              'checks': ['project isolation', 'pending reminder order', 'Beijing today', 'date precision',
                         'timezone sorting', 'exact timestamp expiry', 'date-only today', 'archived records',
                         'history retained', 'dirty cancellation', 'reminder shortcut', '390/1440 no overflow']}
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('recent_actions_v12_ui_check: PASS (temporary records, frozen clock, all recent-action scenarios)')


if __name__ == '__main__':
    main()
