import datetime
import json
from pathlib import Path

from crawler.model import Issue, Professor

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TODAY = datetime.date.today().isoformat()


def professors_dir(school, dept):
    return DATA / "professors" / school / dept


def issues_file(school, dept):
    return DATA / "issues" / f"{school}-{dept}.yaml"


def load_all(school, dept):
    d = professors_dir(school, dept)
    if not d.exists():
        return {}
    out = {}
    for p in sorted(d.glob("*.yaml")):
        prof = Professor.model_validate_json(json.dumps(_yaml_load(p)))
        out[prof.slug] = prof
    return out


def _yaml_load(path):
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def save_professor(prof):
    import yaml

    d = professors_dir(prof.school, prof.dept)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{prof.slug}.yaml"
    data = prof.model_dump(mode="json", exclude_none=True)
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_issues(school, dept):
    f = issues_file(school, dept)
    if not f.exists():
        return []
    return [Issue.model_validate(i) for i in _yaml_load(f) or []]


def save_issues(school, dept, issues):
    import yaml

    f = issues_file(school, dept)
    f.parent.mkdir(parents=True, exist_ok=True)
    data = [i.model_dump(mode="json") for i in issues]
    f.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def upsert_issue(issues, kind, ref, message):
    for i in issues:
        if i.kind == kind and i.ref == ref:
            i.message = message
            return
    issues.append(Issue(kind=kind, ref=ref, message=message, first_seen=TODAY))


def append_changes(school, dept, changes):
    d = DATA / "changes"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{school}-{dept}.jsonl"
    with f.open("a", encoding="utf-8") as fh:
        for c in changes:
            c = dict(c, date=TODAY)
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
