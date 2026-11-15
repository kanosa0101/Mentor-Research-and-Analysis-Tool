"""The staged site must use its newly generated directory without touching live assets."""
import json
from bs4 import BeautifulSoup
from scripts import build_site


def test_staged_directory_uses_dynamic_site_and_preserves_live_bundle(tmp_path, monkeypatch):
    live_bundle = build_site.ROOT / 'site' / 'discovery-entry.js'
    before = live_bundle.read_bytes() if live_bundle.exists() else None
    stage = tmp_path / 'stage'
    stage.mkdir()
    catalog = 'window.SCHOOL_CATALOG={schools:[{id:"new-stage-school",name:"分阶段新目录"}],units:[]};'
    (stage / 'school-catalog.js').write_text(catalog, encoding='utf-8')
    monkeypatch.setattr(build_site, 'SITE', stage)
    build_site.build_discovery_entry()
    result = (stage / 'discovery-entry.js').read_text(encoding='utf-8')
    assert result.startswith(catalog + '\n;\n')
    assert (build_site.ROOT / 'site' / 'discovery-core.js').read_text(encoding='utf-8') in result
    assert (build_site.ROOT / 'site' / 'discovery.js').read_text(encoding='utf-8') in result
    assert (live_bundle.read_bytes() if live_bundle.exists() else None) == before
    assert not (stage / 'discovery-core.js').exists()


def test_explicit_fixture_uses_its_own_sources(tmp_path):
    parts = ('window.SCHOOL_CATALOG={schools:[],units:[]};', 'window.fixtureCore=true;', 'window.fixtureDiscovery=true;')
    for name, text in zip(('school-catalog.js', 'discovery-core.js', 'discovery.js'), parts):
        (tmp_path / name).write_text(text, encoding='utf-8')
    build_site.build_discovery_entry(tmp_path)
    assert (tmp_path / 'discovery-entry.js').read_text(encoding='utf-8') == '\n;\n'.join(parts)


def test_inline_stage_uses_new_catalog_escapes_script_end_and_preserves_live_site(tmp_path, monkeypatch):
    live = [build_site.ROOT / 'site' / name for name in ('discovery.html', 'discovery-entry.js')]
    before = {path: path.read_bytes() if path.exists() else None for path in live}
    catalog = {'schools': [{'id': 'stage-only', 'name': '</ScRiPt><script>window.injected=true</SCRIPT>'}], 'units': []}
    (tmp_path / 'school-catalog.js').write_text('window.SCHOOL_CATALOG='+json.dumps(catalog)+';', encoding='utf-8')
    monkeypatch.setattr(build_site, 'SITE', tmp_path)
    html = build_site.render_discovery_page()
    build_site.write_html(tmp_path / 'discovery.html', html)
    soup = BeautifulSoup(html, 'html.parser')
    inline = soup.select('script:not([src])')
    assert len(inline) == 1
    assert {node['src'].split('?')[0] for node in soup.select('script[src]')} == {'account-session.js', 'cloud-library.js'}
    assert not soup.select('link[rel=stylesheet]')
    assert '<\\/ScRiPt>' in inline[0].string and '<\\/SCRIPT>' in inline[0].string
    assert 'stage-only' in inline[0].string
    assert (build_site.ROOT / 'site' / 'ui.css').read_text(encoding='utf-8') in html
    assert 'window.BrowserLibraryCore' in inline[0].string
    assert {path: path.read_bytes() if path.exists() else None for path in live} == before


def test_template_without_inline_values_keeps_external_fallback():
    html = build_site.template_environment().get_template('discovery.html.j2').render()
    soup = BeautifulSoup(html, 'html.parser')
    assert any(node['src'].startswith('discovery-entry.js?') for node in soup.select('script[src]'))
    assert soup.select('link[rel=stylesheet]')
