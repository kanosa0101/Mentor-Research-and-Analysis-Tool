"""Explicit live push smoke test in a disposable Chrome profile; removes its subscription."""
import argparse
import json
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    args = parser.parse_args()
    result = {}
    with tempfile.TemporaryDirectory(prefix='mentor-push-browser-') as profile, sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(profile, channel='chrome', headless=True,
            ignore_default_args=['--disable-background-networking'], permissions=['notifications'])
        page = context.pages[0]
        try:
            page.goto(args.origin+'/opportunities.html', wait_until='networkidle', timeout=60000)
            page.locator('#push-panel > summary').click()
            page.wait_for_function("!document.querySelector('#push-subscribe').disabled")
            page.locator('#push-subscribe').click()
            page.wait_for_function("!!localStorage.getItem('mentor-push') || document.querySelector('#push-status').textContent.includes('订阅未完成')", timeout=35000)
            result['subscribed'] = page.evaluate("!!localStorage.getItem('mentor-push')")
            assert result['subscribed'], page.locator('#push-status').inner_text()
            result['subscriber_id'] = page.evaluate("JSON.parse(localStorage.getItem('mentor-push')).id")
            page.locator('#push-test').click()
            page.wait_for_function("!document.querySelector('#push-test').disabled", timeout=25000)
            result['test_status'] = page.locator('#push-status').inner_text()
            for _ in range(15):
                result['notifications'] = page.evaluate("async()=>{const r=await navigator.serviceWorker.ready;return (await r.getNotifications()).map(n=>({title:n.title,tag:n.tag}));}")
                if result['notifications']:
                    break
                page.wait_for_timeout(1000)
            result['passed'] = any(n['tag']=='connection-test' for n in result['notifications'])
        except Exception as error:
            result.update(passed=False, error=str(error)[:400])
        finally:
            if page.evaluate("!!localStorage.getItem('mentor-push')"):
                page.locator('#push-unsubscribe').click()
                page.wait_for_function("!localStorage.getItem('mentor-push')", timeout=15000)
                result['unsubscribed'] = True
            context.close()
    out = Path(__file__).resolve().parents[1]/'cache/deploy_v13'
    out.mkdir(parents=True, exist_ok=True)
    (out/'browser-push-final.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('passed') and result.get('unsubscribed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
