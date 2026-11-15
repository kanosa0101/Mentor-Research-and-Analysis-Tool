"""Measure first discovery use in independent empty browser contexts."""
import argparse
import json
from pathlib import Path
from statistics import median
import time

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for attempt in range(3):
            context = browser.new_context(viewport={'width': 390, 'height': 844})
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            started = time.perf_counter()
            page.goto(args.base.rstrip('/') + '/discovery.html', wait_until='load')
            page.wait_for_function('window.DISCOVERY_READY')
            assert page.locator('[data-candidate]').count() == 20
            rows.append(dict(attempt=attempt + 1, ready_ms=round((time.perf_counter() - started) * 1000),
                             resources=page.evaluate('performance.getEntriesByType("resource").map(r=>({name:r.name.split("/").pop(),encoded:r.encodedBodySize,transfer:r.transferSize}))'),
                             errors=errors))
            assert not errors, errors
            target.write_text(json.dumps(dict(base=args.base, cold_browser_contexts=True, cases=rows,
                median_ready_ms=median(r['ready_ms'] for r in rows)), indent=2), encoding='utf8')
            print(attempt + 1, rows[-1]['ready_ms'], flush=True)
            context.close()
        browser.close()


if __name__ == '__main__':
    main()
