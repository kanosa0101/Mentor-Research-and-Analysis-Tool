"""Discover unreviewed activity links once, or every six hours with --watch."""
import argparse
import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler.opportunity_monitor import fetch_source, output_lock, run_once


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'sites/opportunities.yaml')
    parser.add_argument('--output', type=Path, default=ROOT / 'cache/opportunities_live.json')
    parser.add_argument('--opportunities', type=Path, default=ROOT / 'data/opportunities.json')
    parser.add_argument('--timeout', type=float, default=25)
    parser.add_argument('--watch', action='store_true', help='每6小时检查，Ctrl+C退出；不安装定时任务')
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 120:
        parser.error('--timeout must be between 1 and 120 seconds')
    try:
        with output_lock(args.output):
            while True:
                configs = yaml.safe_load(args.config.read_text(encoding='utf-8'))['targets']
                document = json.loads(args.opportunities.read_text(encoding='utf-8')) if args.opportunities.exists() else {}
                opportunities = document.get('opportunities', document.get('items', []))
                print('正在检查官方栏目；仅发现待核验线索，不自动确认报名开放。', flush=True)
                result = run_once(configs, args.output, opportunities,
                                  fetcher=lambda config: fetch_source(config, args.timeout), lock=False)
                summary = result['summary']
                print(f"最近检查：{result['checked_at']}；下次应检：{result['next_check_at']}\n"
                      f"候选 {summary['candidate_count']}，本次新发现 {summary['new_count']}，首次基线 {summary['baseline_count']}；"
                      f"栏目成功 {summary['sources_ok']}/{summary['source_count']}，失败 {summary['sources_error']}；"
                      f"已整理来源变化 {summary['changed_count']}，检查失败 {summary['opportunity_errors']}。\n"
                      f"结果：{args.output}", flush=True)
                for source in [*result['sources'].values(), *result['opportunity_checks'].values()]:
                    if source.get('error'):
                        print(f"检查失败 {source['url']}：{source['error']}", file=sys.stderr, flush=True)
                if not args.watch:
                    return 0 if result['status'] == 'ok' else 1
                seconds = max(0, (datetime.fromisoformat(result['next_check_at']) - datetime.now(timezone.utc)).total_seconds())
                threading.Event().wait(seconds)
    except KeyboardInterrupt:
        print('已停止机会监测。', flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f'机会监测未完成：{error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
