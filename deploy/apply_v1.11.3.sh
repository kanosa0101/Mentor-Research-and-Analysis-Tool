#!/usr/bin/env bash
# Run after uploading the reviewed code archive, manifest and RELEASE_SOURCE.json to /tmp.
# Existing public sources and all account files remain authoritative on this server.
set -euo pipefail
root=/opt/mentor-assistant
stage=/opt/mentor-assistant-stage-v1113
backup=/opt/mentor-assistant-before-v1113.tar.gz
oldsite=/opt/mentor-assistant-site-before-v1113
report="$root/cache/convergence"
[ -d "$root" ] && [ ! -e "$stage" ] && [ ! -e "$backup" ] && [ ! -e "$oldsite" ]
mkdir -p "$report"
timers=(mentor-maintenance.timer mentor-monitor.timer mentor-review-pipeline.timer mentor-updates.timer)
services=(mentor-https.service mentor-public.service mentor-review-ui.service)
systemctl stop "${timers[@]}"
trap 'systemctl start "${timers[@]}"' EXIT
for unit in mentor-maintenance.service mentor-monitor.service mentor-review-pipeline.service mentor-updates.service; do
  for i in $(seq 1 120); do
    if ! systemctl is-active --quiet "$unit"; then break; fi
    sleep 2
  done
  if systemctl is-active --quiet "$unit"; then echo "Busy maintenance service: $unit"; exit 1; fi
done
cd "$root"
mkdir "$stage"
DEPLOY_STAGE="$stage" .venv/bin/python - <<'PY'
import os, shutil, tarfile
from pathlib import Path
r=Path.cwd();s=Path(os.environ['DEPLOY_STAGE'])
private={'workflow.yaml','outreach.yaml','discovery.yaml','student.yaml','student_sop.md','letters','backups'}
for name in ('crawler','scripts','site','sites','data'):
    def ignore(folder,names):
        return [n for n in names if n=='__pycache__' or (Path(folder)==r/'data' and n in private)]
    shutil.copytree(r/name,s/name,ignore=ignore)
for name in ('VERSION','release.json'): shutil.copy2(r/name,s/name)
with tarfile.open('/tmp/mentor-v1113-code.tar.gz') as archive: archive.extractall(s,filter='data')
PY
.venv/bin/python "$stage/scripts/maintain_public.py" --build-only > "$report/stage-build.log"
systemctl stop "${services[@]}"
trap 'systemctl start "${services[@]}" "${timers[@]}"' EXIT
.venv/bin/python - <<'PY'
import hashlib,json
from pathlib import Path
r=Path.cwd();files=[]
for name in ('data','sites','var/ai','var/push','var/accounts','var/users'):
    if (r/name).exists(): files.extend(p for p in (r/name).rglob('*') if p.is_file())
hashes={p.relative_to(r).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
(r/'cache/convergence/protected-before.json').write_text(json.dumps(hashes))
print('Protected file count:',len(hashes))
PY
tar --exclude='./.venv' --exclude='./cache' --exclude='./dist' -czf "$backup" -C "$root" .
chmod 600 "$backup"
tar -xzf /tmp/mentor-v1113-code.tar.gz -C "$root"
mv "$root/site" "$oldsite"
mv "$stage/site" "$root/site"
cp /tmp/mentor-v1113-source.json "$root/RELEASE_SOURCE.json"
chown -R mentor-assistant:mentor-assistant "$root/site"
.venv/bin/python - <<'PY'
import hashlib,json
from pathlib import Path
r=Path.cwd();before=json.loads((r/'cache/convergence/protected-before.json').read_text())
changed=[n for n,h in before.items() if not (r/n).is_file() or hashlib.sha256((r/n).read_bytes()).hexdigest()!=h]
assert not changed,changed
expected=json.loads(Path('/tmp/mentor-v1113-hashes.json').read_text())
generated={'site/data.js','site/contact-data.js','site/discovery-data.js','site/discovery-entry.js','site/opportunities-data.js','site/admissions-data.js','site/school-catalog.js','site/compare-data.js','site/search.js'}
code={n:h for n,h in expected.items() if n not in generated and not(n.startswith('site/') and n.endswith('.html'))}
assert all((r/n).is_file() and hashlib.sha256((r/n).read_bytes()).hexdigest()==h for n,h in code.items())
assert (r/'VERSION').read_text().strip()=='1.11.3'
result={'protected_files_unchanged':len(before),'source_files_verified':len(code),'backup':'/opt/mentor-assistant-before-v1113.tar.gz','previous_site':'/opt/mentor-assistant-site-before-v1113'}
result['backup_sha256']=hashlib.sha256(Path(result['backup']).read_bytes()).hexdigest()
(r/'cache/convergence/deployment.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
PY
systemctl start "${services[@]}"
systemctl is-active "${services[@]}"
