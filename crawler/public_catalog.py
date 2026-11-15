"""Read only the selected public mentor profiles for the comparison page."""
import json
import re
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=4)
def _read(path, stamp, size, inode):
    raw=Path(path).read_text(encoding='utf-8')
    return json.loads(raw.split('=',1)[1].strip().removesuffix(';'))


def load(root, name):
    path=Path(root)/'site'/name;stat=path.stat()
    return _read(str(path.resolve()),stat.st_mtime_ns,stat.st_size,stat.st_ino)


def selected(root, ids):
    if len(ids)>5 or any(not isinstance(value,str) or not 0<len(value)<=256 for value in ids):
        raise ValueError('最多对比5位导师')
    if not ids:return []
    wanted=set(ids);extra=load(root,'compare-data.js')
    return [dict(p,**extra.get(p['page'],{})) for p in load(root,'data.js') if p['page'] in wanted]


def search(root, terms, schools=()):
    if not isinstance(terms,list) or not 1<=len(terms)<=20 or any(not isinstance(t,str) or not 0<len(t)<=200 for t in terms) or sum(map(len,terms))>1000 or len(schools)>39:
        raise ValueError('研究关键词过多或过长')
    patterns=[re.compile(r'(^|[^a-z0-9])'+re.escape(t)+r'($|[^a-z0-9])',re.I) if re.fullmatch(r'[a-z0-9 ._-]+',t,re.I) else re.compile(re.escape(t),re.I) for t in terms]
    corpus=load(root,'search.js');known=[];matches={}
    for p in load(root,'data.js'):
        if schools and p['school'] not in schools:continue
        text=corpus.get(p['page'],'')
        if not text:continue
        known.append(p['page']);snippets=[]
        for pattern in patterns:
            hit=pattern.search(text)
            if hit:snippets.append(text[max(0,hit.start()-25):hit.end()+70])
        if snippets:matches[p['page']]='\n'.join(snippets)
    return {'known_ids':known,'matches':matches}
