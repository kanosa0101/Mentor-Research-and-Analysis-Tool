"""维护者核验闭环：sync 取证 → 编辑草稿 item/quotes → list → publish 显式发布。

示例：python scripts/review_opportunities.py sync
     python scripts/review_opportunities.py list
     python scripts/review_opportunities.py publish ID --sha256 HASH --reviewer 姓名 --note 核验说明
默认文件均在本地；不会上传资料、发送通知或直接部署网站。
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler import opportunity_review as review
from crawler.opportunity_monitor import DomainThrottle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, default=ROOT, help='活动目录所在项目根目录')
    parser.add_argument('--queue', type=Path, default=ROOT / 'cache/opportunity_review.json')
    parser.add_argument('--monitoring', type=Path, default=ROOT / 'cache/opportunities_live.json')
    parser.add_argument('--config', type=Path, default=ROOT / 'sites/opportunities.yaml')
    commands = parser.add_subparsers(dest='command', required=True)
    sync = commands.add_parser('sync', help='取得新候选、失败或超过24小时的正文；保留人工字段，不发布')
    sync.add_argument('--refresh', action='store_true', help='强制重新抓取全部正文证据')
    sync.add_argument('--renew', action='store_true', help='续检既有已核验且正文/字段均未变化的记录；不发布新草稿')
    commands.add_parser('list', help='列出草稿状态、SHA 与来源')
    triage = commands.add_parser('triage', help='明确应用公开来源分流审计；不改人工草稿或发布状态')
    triage.add_argument('--audit', type=Path, required=True)
    accept = commands.add_parser('accept', help='明确采纳规则建议至草稿，不发布；默认只填空字段')
    accept.add_argument('id')
    accept.add_argument('--fields', nargs='+', help='仅采纳这些字段，省略则采纳受支持的建议字段')
    accept.add_argument('--replace', action='store_true', help='明确替换草稿中所选字段；仍需核验发布')
    commands.add_parser('renew', help='仅续检已核验且正文/字段未变化的记录，保留人工核验日期')
    publish = commands.add_parser('publish', help='重新抓取原文，通过核验后原子写入活动目录')
    publish.add_argument('id')
    publish.add_argument('--sha256', required=True, help='维护者已阅读并核验的原文 SHA')
    publish.add_argument('--content-sha256', help='显式确认既有HTML正文、链接及附件组合SHA；仅在实时组合SHA相同时允许浏览量等整页变化，默认不启用')
    publish.add_argument('--pdf-sha256', action='append', default=[], help='已核验PDF的SHA；每个文件重复提供一次，并填写草稿逐字段pages证据')
    publish.add_argument('--reviewer', required=True)
    publish.add_argument('--note', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'triage':
            count = review.apply_triage(args.queue, json.loads(args.audit.read_text(encoding='utf-8')))
            print(json.dumps({'classified': count, 'published': False}))
            return 0
        if args.command == 'accept':
            fields = review.accept(args.queue, args.id, args.fields, args.replace)
            print(json.dumps({'accepted_fields': fields, 'published': False}, ensure_ascii=False))
            return 0
        if args.command == 'renew':
            print(json.dumps({'renewed': review.renew(args.queue, args.root)}, ensure_ascii=False))
            return 0
        if args.command == 'list':
            queue = review.read_queue(args.queue)
        else:
            configs = yaml.safe_load(args.config.read_text(encoding='utf-8'))['targets']
            if args.command == 'publish':
                item = review.publish(args.queue, args.id, args.root, configs, acknowledged_hash=args.sha256,
                                      reviewer=args.reviewer, note=args.note, acknowledged_pdf_hashes=args.pdf_sha256,
                                      acknowledged_content_hash=args.content_sha256)
                print(f"已核验发布 {item['id']}；未自动部署或发送通知。")
                return 0
            monitoring = json.loads(args.monitoring.read_text(encoding='utf-8'))
            throttle = DomainThrottle(review.fetch_source, 1)
            def fetch_pdf(url, source_url):
                throttle.wait(url)
                return review.fetch_pdf(url, source_url)
            queue = review.sync(monitoring, args.queue, configs, refresh=args.refresh, fetcher=throttle, pdf_fetcher=fetch_pdf)
            if args.renew:
                renewed = review.renew(args.queue, args.root)
                queue = review.read_queue(args.queue)
                queue['renewed'] = renewed
        rows = [dict(id=d['id'], status=review.status(d), title=d['item'].get('title'),
                     source_url=d['source_url'], sha256=d.get('fetch', {}).get('sha256'),
                     content_sha256=d.get('fetch', {}).get('content_sha256'),
                     error=d.get('fetch', {}).get('error')) for d in queue['drafts']]
        for row, draft in zip(rows, queue['drafts']):
            row.update(classification=draft.get('classification'), suggestions=draft.get('suggestions', {}),
                       field_evidence=draft.get('field_evidence', {}), warnings=draft.get('warnings', []),
                       pdfs=[{key:pdf.get(key) for key in ('url','sha256','page_count','text_status')} for pdf in draft.get('fetch', {}).get('pdfs', [])])
        print(json.dumps({'queue': str(args.queue), 'summary': queue.get('summary'), 'renewed': queue.get('renewed', []), 'drafts': rows}, ensure_ascii=False, indent=2))
        return 1 if args.command == 'sync' and any(d.get('fetch', {}).get('status') not in ('ok', 'pdf_review') for d in queue['drafts']) else 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(f'核验操作未完成：{error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    sys.exit(main())
