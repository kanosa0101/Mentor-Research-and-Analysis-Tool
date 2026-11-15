"""Compare paginated Python discovery with the existing JS rules on real data."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from crawler.public_discovery import candidates


def main():
    queries = [{}, {'name': ['张']}, {'school': ['nudt', 'scut']}, {'group': ['cyber']},
               {'context_school': ['tju'], 'dept': ['cs']}, {'context_school': ['tju'], 'dept': ['missing']},
               {'year': ['2027'], 'route': ['exam']}]
    for term in ('计算机视觉', 'AI', 'robot', 'ain', '研究方向', '不存在的研究词'):
        for mode in ('hard', 'soft', 'off'):
            queries.append({'topics': [json.dumps([term])], 'mode_research': [mode], 'keep_unknown': ['0']})
    for degree in ('master', 'phd'):
        for unknown in ('0', '1'):
            queries.append({'degree': [degree], 'mode_qualification': ['hard'], 'keep_unknown': [unknown]})
    queries += [{'mode_email': ['hard'], 'keep_unknown': ['0']},
                {'mode_opportunity': ['hard'], 'keep_unknown': ['0']},
                {'mode_eligibility': ['hard'], 'keep_unknown': ['1']}]
    cases = []
    for query in queries:
        query = dict(query, seed=['v17-parity😀'])
        result = candidates(ROOT, query)
        cases.append(dict(query=query, total=result['total'], matched=result['matched'],
                          rows=[dict(id=r['p']['page'], result=r['result']) for r in result['rows']]))
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const rules=require('./site/discovery-core.js'),ctx={window:{}};vm.createContext(ctx);
for(const name of ['discovery-data.js','search.js'])vm.runInContext(fs.readFileSync('site/'+name,'utf8'),ctx);
const data=ctx.window.MENTOR_DATA,corpus=ctx.window.MENTOR_SEARCH;
const extra=Object.fromEntries(data.map(p=>[p.page,{bio_excerpt:p.bio_excerpt}]));
const cases=JSON.parse(fs.readFileSync(0,'utf8'));
for(const c of cases){
 const q=c.query,get=(k,d='')=>q[k]?.[0]??d;
 const prefs={year:get('year')?Number(get('year')):null,degree:get('degree','any'),route:get('route','unknown'),
  topics:JSON.parse(get('topics','[]')),schools:q.school||[],keep_unknown:get('keep_unknown','1')==='1',
  modes:{research:get('mode_research','hard'),qualification:get('mode_qualification','soft'),email:get('mode_email','soft'),opportunity:get('mode_opportunity','soft'),eligibility:get('mode_eligibility','soft')}};
 const rows=data.map(p=>({p,result:rules.evaluate(p,prefs,{},prefs.topics.length?(corpus[p.page]||''):'')}))
  .filter(r=>r.result.visible&&(!get('name')||r.p.name.toLowerCase().includes(get('name').toLowerCase()))&&
   (!get('group')||r.p.unit_groups?.includes(get('group')))&&(!get('context_school')||r.p.school===get('context_school'))&&(!get('dept')||r.p.dept===get('dept')));
 const ranked=rules.rankCandidates(rows,prefs,extra,get('seed'));
 assert.strictEqual(rows.length,c.total,JSON.stringify(q));assert.strictEqual(ranked.matched,c.matched);
 const actual=ranked.rows.slice(0,20).map(r=>({id:r.p.page,result:JSON.parse(JSON.stringify(r.result))}));
 assert.deepStrictEqual(JSON.parse(JSON.stringify(actual)),c.rows,JSON.stringify(q));
}
console.log(JSON.stringify({passed:true,cases:cases.length,records:data.length,rule_evaluations:cases.length*data.length}));
"""
    result = subprocess.run(['node', '-e', script], input=json.dumps(cases, ensure_ascii=False),
                            text=True, encoding='utf8', cwd=ROOT, capture_output=True)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    target = ROOT / 'cache/v17/discovery-parity.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result.stdout, encoding='utf8')
    print(result.stdout)


if __name__ == '__main__':
    main()
