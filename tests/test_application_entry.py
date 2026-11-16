"""The application entry keeps data and dependent scripts in their original order."""
import re
from scripts import build_site


SOURCES = ('application-data.js', 'admissions-core.js', 'material-actions.js',
           'opportunities-core.js', 'workflow.js')


def test_bundle_preserves_real_payload_and_scripts_without_mutating_sources(tmp_path, monkeypatch):
    original = {name: (build_site.ROOT / 'site' / name).read_text(encoding='utf-8') for name in SOURCES}
    for name, text in original.items():
        (tmp_path / name).write_text(text, encoding='utf-8')
    monkeypatch.setattr(build_site, 'SITE', tmp_path)
    build_site.build_application_entry()
    assert (tmp_path / 'application-entry.js').read_text(encoding='utf-8') == '\n;\n'.join(original.values())
    for name, text in original.items():
        assert (tmp_path / name).read_text(encoding='utf-8') == text


def test_staged_payload_uses_staged_scripts_and_falls_back_only_for_missing_code(tmp_path):
    payload = 'window.MENTOR_DATA = [{"page":"staged-mentor"}];\nwindow.ADMISSIONS_DATA = {};\n'
    (tmp_path / 'application-data.js').write_text(payload, encoding='utf-8')
    code = 'window.stagedWorkflow = true;\n'
    (tmp_path / 'workflow.js').write_text(code, encoding='utf-8')
    build_site.build_application_entry(tmp_path)
    expected = [payload]
    expected.extend((build_site.ROOT / 'site' / name).read_text(encoding='utf-8') for name in SOURCES[1:-1])
    expected.append(code)
    assert (tmp_path / 'application-entry.js').read_text(encoding='utf-8') == '\n;\n'.join(expected)


def test_application_template_requests_one_entry_without_loading_its_parts_again():
    html = build_site.template_environment().get_template('applications.html.j2').render()
    scripts = re.findall(r'<script\b[^>]*\bsrc="([^"]+)"', html)
    assert sum(src.startswith('application-entry.js?') for src in scripts) == 1
    assert not any(src.split('?')[0] in SOURCES for src in scripts)
