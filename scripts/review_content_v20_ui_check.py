"""Complete content classification through the existing local review editor, then publish."""
import json
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from review_v18_ui_check import fixture
from crawler import opportunity_review as review, opportunity_util as util
from scripts import serve_review


def main():
    out=ROOT/'cache/v20/content/review-ui';out.mkdir(parents=True,exist_ok=True)
    results=[]
    for width in (1440,390):
        with tempfile.TemporaryDirectory(prefix='review-content-v20-') as folder:
            root=Path(folder);ident,_,_=fixture(root)
            queue_path=root/'cache/opportunity_review.json'
            queue=review.read_queue(queue_path);draft=queue['drafts'][0]
            evidence=Path(draft['fetch']['evidence_file']).read_bytes()
            raw=evidence.replace(b'<article>','<article><p>主办单位：示例大学计算机学院</p>'.encode())
            review.fetch_evidence(draft,queue_path,lambda _:raw)
            draft['item'].pop('content_classification',None)
            review.atomic_json(queue_path,queue)
            server=serve_review.make_server(root,port=0)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            try:
                with patch.object(review,'fetch_source',return_value=raw),sync_playwright() as pw:
                    browser=pw.chromium.launch();page=browser.new_page(viewport={'width':width,'height':950});errors=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/review.html?draft='+ident)
                    expect(page.locator('#content-classification-editor')).to_be_visible()
                    expect(page.locator('.blockers')).to_contain_text('内容归类')
                    assert page.input_value('#classification-scope')=='pending'
                    assert page.input_value('#classification-organizer_level')=='unknown'
                    assert page.input_value('#classification-source_url')==draft['source_url']
                    assert page.locator('#classification-source_url').get_attribute('readonly') is not None
                    assert page.input_value('#classification-quote')==''
                    page.select_option('#classification-scope','institutional_activity')
                    page.select_option('#classification-organizer_level','school_department')
                    page.fill('#classification-organizer_name','示例大学计算机学院')
                    page.fill('#classification-quote','主办单位：示例大学计算机学院')
                    page.get_by_role('button',name='保存草稿',exact=True).click()
                    expect(page.locator('#message')).to_contain_text('尚未发布')
                    assert not (root/'data/opportunities.json').exists()
                    saved=review.read_queue(queue_path)['drafts'][0]
                    assert util.content_scope(saved['item'])=='institutional_activity'
                    assert not saved['item'].get('mentor_ids')
                    assert saved['reviewed_fields']['research_directions']==draft['reviewed_fields']['research_directions']
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    page.locator('#content-classification-editor').scroll_into_view_if_needed()
                    page.screenshot(path=str(out/f'classification-{width}.png'))
                    page.get_by_label('核验人',exact=True).fill('隔离UI验收')
                    page.get_by_label('核验说明（适用轮次、批次和材料阶段）',exact=True).fill('核对机构主办原句与既有字段依据')
                    page.locator('.publish-box input[type=checkbox]').check()
                    page.get_by_role('button',name='重新抓取并核验发布',exact=True).click()
                    expect(page.locator('#message')).to_contain_text('已通过核验')
                    published=util.load(root)['opportunities'][0]
                    assert util.content_scope(published)=='institutional_activity'
                    assert len(util.public_catalog(util.load(root))['opportunities'])==1
                    assert not errors,errors
                    results.append({'width':width,'explicit_classification_saved':True,'save_did_not_publish':True,'original_evidence_preserved':True,'live_version_publish_passed':True,'mentor_ids_not_required_for_activity':True,'page_errors':errors,'temporary_data_only':True})
                    browser.close()
            finally:
                server.shutdown();server.server_close()
    (out/'results.json').write_text(json.dumps({'passed':True,'checks':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS content review UI: desktop/mobile classify, save, source-bound publish')


if __name__=='__main__':main()
