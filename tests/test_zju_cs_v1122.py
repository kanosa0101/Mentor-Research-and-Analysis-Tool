import io
import json
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import openpyxl
import pytest
import yaml

from crawler import legacy_refresh, mentor_fields, mentor_quality
from sites.zju import zju_cs


LIST = 'http://www.cs.zju.edu.cn/csen/qyjscx_95580/list.htm'
INDEX = 'http://www.cs.zju.edu.cn/csen/27006/list.htm'
ARTICLE = 'http://www.cs.zju.edu.cn/csen/2021/0525/c27006a2377953/page.htm'
PDF_PATH = '/_upload/article/files/d4/45/e46a2ca6469693738d84d1fffc3f/7e0b4187-7b2b-44da-951d-f9439b508c1e.pdf'
PDF = 'http://www.cs.zju.edu.cn' + PDF_PATH


def faculty_payload(rows, total=None):
    body = json.dumps(dict(status=1, result='true', total=len(rows) if total is None else total,
                           data=rows, pageCount=1), ensure_ascii=False)
    return body.encode(), body


def documented_reader(name, faculty):
    query = zju_cs.faculty_query(LIST, name=name)
    bodies = {query:faculty,
              INDEX:(b'index', f'<a href="{ARTICLE}">计算机学院导师与导师团队信息-2026</a>'),
              ARTICLE:(b'article', f'<a href="{PDF_PATH}">2026全日制导师信息库-09.pdf</a>'),
              PDF:(b'%PDF-v1122 structure', '')}
    return {'_expected_name':name,'_read_source':bodies.__getitem__,
            'profile_contact_roster_index':INDEX,'profile_faculty_directory':LIST}


def test_named_faculty_query_honors_current_directory_and_visible_fields():
    name = '模拟导师'
    query = zju_cs.faculty_query(LIST, name=name)
    target = urlsplit(query)
    body = parse_qs(target.query)
    assert (target.scheme, target.hostname, target.path) == ('http','www.cs.zju.edu.cn','/_wp3services/generalQuery')
    assert (body['siteId'],body['columnId'],body['rows']) == (['484'],['93624'],['10'])
    assert json.loads(body['conditions'][0])[0]['orConditions'] == [{'field':'title','value':'%模拟导师%','judge':'like'}]
    assert {column['field'] for column in json.loads(body['returnInfos'][0])} == {'title','f1','f2','f3','url'}
    row = {'title':name,'f1':'副教授','f2':'personal@zju.edu.cn','f3':'<p>机器学习、软件工程</p>',
           'url':'https://person.zju.edu.cn/faculty'}
    cfg = documented_reader(name,faculty_payload([row]))
    parsed = zju_cs.parse_detail(cfg,'<p>温馨提示：请验证以继续访问。</p>','https://person.zju.edu.cn/faculty')
    assert parsed['name'] == parsed['_verified_roster_name'] == name
    assert parsed['title'] == '副教授' and parsed['research_direction_raw'] == '机器学习、软件工程'
    assert parsed['_field_sources']['research_direction_raw'] == query
    assert 'email' not in parsed and parsed['homepage'] == row['url']
    with pytest.raises(ValueError,match='姓名未与名册一致'):
        zju_cs.parse_detail(cfg,'<div class="personal_name">错误姓名</div>','https://person.zju.edu.cn/faculty')


@pytest.mark.parametrize('incomplete,duplicate', [(True,False),(False,True)])
def test_unverified_directory_email_is_not_taken_from_incomplete_or_same_name_rows(incomplete, duplicate):
    name = '模拟导师'
    row = {'title':name,'f2':'first@zju.edu.cn','url':'https://person.zju.edu.cn/first'}
    matches = [row, dict(row, f2='second@zju.edu.cn')] if duplicate else [row]
    cfg = documented_reader(name,faculty_payload(matches,total=22 if incomplete else len(matches)))
    with patch.object(zju_cs,'_contact_roster',return_value={}):
        assert zju_cs.parse_contact(cfg,{'name':name}) == {}


def test_adjacent_public_faculty_contact_and_bound_pdf_fields_keep_source_links():
    name='模拟导师'
    row={'title':name,'f2':'one@zju.edu.cn','url':'http://cspo.zju.edu.cn/2026/0724/c93629a3191337/page.htm'}
    cfg=documented_reader(name,faculty_payload([row]))
    table=[['研究生导师信息库-2026.09']+[None]*9,
           ['序号','所室机构','姓名','职称','学科专长及研究方向','办公地点','联系方式','Email','备注','科研团队名称'],
           ['1','系统所',name,'副教授','模型评估\n与部署',None,None,None,'硕导',None]]
    pdf=SimpleNamespace(pages=[SimpleNamespace(extract_tables=lambda:[table])])
    zju_cs.mentor_roster_rows.cache_clear()
    with patch('pdfplumber.open',return_value=nullcontext(pdf)):
        contact=zju_cs.parse_contact(cfg,{'name':name})
        assert contact['email']=='one@zju.edu.cn'
        assert contact['_field_sources']['email']==zju_cs.faculty_query(LIST,name=name)
        assert zju_cs.parse_contact(cfg,{'name':name,'email':'prior@zju.edu.cn'})=={}
        assert zju_cs.parse_contact(dict(cfg,_previous_email='prior@zju.edu.cn'),{'name':name})=={}
        detail=zju_cs.parse_detail(cfg,'<h1>资格目录</h1>',zju_cs._XLSX_ARTICLE+'#'+name)
    assert detail['research_direction_raw']=='模型评估与部署' and detail['title']=='副教授'
    assert detail['_field_sources']=={'title':PDF,'research_direction_raw':PDF}
    assert 'homepage' not in detail and 'email' not in detail


def test_current_workbook_header_never_becomes_a_person():
    book=openpyxl.Workbook()
    book.active.append(['学术学位']+[None]*11)
    book.active.append([value for subject in ('081200计算机科学与技术','083500软件工程','083900网络空间安全','085400电子信息')
                        for value in (subject,None,None)])
    book.active.append(['序号','博导','硕导']*4)
    book.active.append([1,'模拟导师','硕导']+[None]*9)
    book.active.append([None,'栏目字样','硕导']+[None]*9)
    raw=io.BytesIO()
    book.save(raw)
    with patch.object(zju_cs.fetch,'fetch_text',return_value=('<a href="/valid.xlsx">资格表</a>',None,None)), \
            patch.object(zju_cs.fetch,'fetch',return_value=(raw.getvalue(),None,None)):
        assert zju_cs._load_xlsx_supervisors() == {
            '模拟导师': {'supervisor':'博导','subjects':['计算机科学与技术']}}


def test_roster_uses_current_pages_without_registering_duplicate_names():
    expected = {'title':'唯一导师','url':'https://person.zju.edu.cn/only'}
    duplicate = {'title':'同名导师','url':'https://person.zju.edu.cn/one'}
    unrelated = dict(duplicate,url='https://person.zju.edu.cn/two')
    responses = {zju_cs.faculty_query(LIST):[expected,duplicate],
                 zju_cs.faculty_query(LIST,page=2):[unrelated]}
    qualified = {name:{'supervisor':'博导','subjects':[]} for name in ('唯一导师','同名导师','资格导师')}
    def retrieve(method,url):
        assert method == 'GET'
        return json.dumps(dict(status=1, result='true', total=3, pageCount=2, data=responses[url])), {}, False
    with patch.object(zju_cs.fetch,'fetch_text',side_effect=retrieve), \
            patch.object(zju_cs,'_load_xlsx_supervisors',return_value=qualified):
        rows,_ = zju_cs.iter_roster({'profile_faculty_directory':LIST})
    assert [(row['name'],row['url'],row['supervisor']) for row in rows] == [
        ('唯一导师',expected['url'],'博导'),
        ('资格导师',zju_cs._XLSX_ARTICLE+'#资格导师','博导'),
    ]


@pytest.mark.parametrize('maintenance', ['legacy', 'fields', 'quality'])
def test_maintenance_replays_gap_sources_without_replacing_existing_fields(tmp_path, maintenance):
    name = '模拟导师'
    source = zju_cs._XLSX_ARTICLE + '#' + name
    cfg_path = Path(zju_cs.__file__).with_name('cs.yaml')
    local_cfg = tmp_path / 'sites/zju/cs.yaml'
    local_cfg.parent.mkdir(parents=True)
    local_cfg.write_bytes(cfg_path.read_bytes())
    local_cfg.with_name('zju_cs.py').write_bytes(Path(zju_cs.__file__).read_bytes())
    profile_path = tmp_path / 'data/professors/zju/cs/example.yaml'
    profile_path.parent.mkdir(parents=True)
    existing_title = {'origin':'crawled','source':source,'fetched_at':'2026-09-01','confidence':'auto'}
    manual_homepage = {'origin':'manual','source':source,'fetched_at':'2026-09-01','confidence':'confirmed'}
    original = {'slug':'example','name':name,'school':'zju','dept':'cs','status':'enriched',
                'detail_url':source,'title':'教授','email':'current@zju.edu.cn',
                'supervisor':'博导','subjects':'计算机科学与技术','first_seen':'2026-09-01',
                'provenance':{'title':existing_title,'homepage':manual_homepage}}
    profile_path.write_text(yaml.safe_dump(original,allow_unicode=True),encoding='utf-8')
    alternate_homepage = 'https://person.zju.edu.cn/alternate'
    directory = faculty_payload([{'title':name,'f1':'副教授','url':alternate_homepage}])
    cfg = documented_reader(name,directory)
    table = [['研究生导师信息库-2026.09']+[None]*9,
             ['序号','所室机构','姓名','职称','学科专长及研究方向','办公地点','联系方式','Email','备注','科研团队名称'],
             ['1','系统所',name,'副教授','模型评估与部署',None,None,None,'硕导',None]]
    pdf = SimpleNamespace(pages=[SimpleNamespace(extract_tables=lambda:[table])])
    observed = []
    def bounded(url, scope, *, allow_pdf=False, accepted_types, before_request=None):
        if before_request:
            before_request()
        observed.append((url,allow_pdf,accepted_types))
        assert scope == 'http://www.cs.zju.edu.cn'
        assert url != alternate_homepage
        body, html = cfg['_read_source'](url)
        return body if url == PDF else html.encode('utf-8')
    def primary(source):
        if source.get('official_scope'):
            fetch = legacy_refresh.fetch_source if maintenance == 'legacy' else mentor_quality.fetch_source
            return fetch(source)
        assert source['url'].split('#')[0] == zju_cs._XLSX_ARTICLE
        return '<html><h1>导师资格目录</h1></html>'.encode('utf-8')
    def field_source(url, scope, **options):
        if url == zju_cs._XLSX_ARTICLE:
            if before_request := options.get('before_request'):
                before_request()
            return primary({'url':url})
        return bounded(url,scope,**options)
    now = datetime(2026,11,22,16,0,tzinfo=timezone.utc)
    zju_cs.mentor_roster_rows.cache_clear()
    with patch('pdfplumber.open',return_value=nullcontext(pdf)), \
            patch('crawler.source_discovery.fetch_html',side_effect=field_source):
        if maintenance == 'legacy':
            report = legacy_refresh.run(tmp_path,kind='professors',units=('zju/cs',),fetcher=primary,now=now)
            assert report['ok'] == 1, report
            result = yaml.safe_load(profile_path.read_bytes())
        elif maintenance == 'fields':
            report = mentor_fields.run(tmp_path,units=('zju/cs',),workers=1,now=now)
            assert report['results'][0]['filled_fields'] == ['research_direction_raw'], report
            result = yaml.safe_load(profile_path.read_bytes())
        else:
            sources = mentor_quality.Sources(tmp_path,primary,now.isoformat())
            result, _, changed, _ = mentor_quality.profile(tmp_path,original,yaml.safe_load(local_cfg.read_bytes()),sources)
            assert changed == ['research_direction_raw']
    assert result['title'] == '教授' and result['provenance']['title'] == existing_title
    assert 'homepage' not in result and result['provenance']['homepage'] == manual_homepage
    assert result['research_direction_raw'] == '模型评估与部署'
    assert result['provenance']['research_direction_raw']['source'] == PDF
    assert (PDF,True,('application/pdf',)) in observed
