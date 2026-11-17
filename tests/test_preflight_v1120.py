"""Release-mode preflight only allows recorded source-quality issues."""
from pathlib import Path
import subprocess
import sys


def test_preflight_reports_open_issues_without_relaxing_structure(tmp_path):
    root = Path(__file__).resolve().parents[1]
    files = {
        '.gitignore': (root / '.gitignore').read_text(encoding='utf-8'),
        'site/index.html': 'const DATA = [];\n',
        'data/schools.yaml': 'schools: []\n',
        'data/issues/demo-cs.yaml': (
            '- {kind: source, ref: demo, message: Not yet reviewed, first_seen: "2026-01-01", resolved: false}\n'),
        'data/changes/demo-cs.jsonl': '{}\n',
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    command = [sys.executable, '-X', 'utf8', str(root / 'scripts/preflight.py'), '--root', str(tmp_path)]

    strict = subprocess.run(command, capture_output=True, encoding='utf-8')
    assert strict.returncode == 1 and 'open issues: demo-cs.yaml x1' in strict.stdout
    assert 'QUALITY WARNINGS' not in strict.stdout

    allowed = subprocess.run([*command, '--allow-open-issues'], capture_output=True, encoding='utf-8')
    assert allowed.returncode == 0 and 'QUALITY WARNINGS' in allowed.stdout
    assert 'open issues: demo-cs.yaml x1' in allowed.stdout and 'total: 0' in allowed.stdout

    (tmp_path / 'data/changes/demo-cs.jsonl').write_text('invalid json\n', encoding='utf-8')
    invalid = subprocess.run([*command, '--allow-open-issues'], capture_output=True, encoding='utf-8')
    assert invalid.returncode == 1 and 'bad change line: demo-cs.jsonl:1' in invalid.stdout

    (tmp_path / 'data/changes/demo-cs.jsonl').write_text('{}\n', encoding='utf-8')
    (tmp_path / 'data/issues/demo-cs.yaml').write_text('- resolved: false\n', encoding='utf-8')
    malformed_issue = subprocess.run([*command, '--allow-open-issues'], capture_output=True, encoding='utf-8')
    assert malformed_issue.returncode == 1 and 'issues schema: demo-cs.yaml:1' in malformed_issue.stdout
