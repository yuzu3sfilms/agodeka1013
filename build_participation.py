"""Aggregate observed LINE next-speaker transitions; no raw messages stored."""
import argparse, json, re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from participation import features, explicit_address
from ago_runtime import HASHIMOTO_NAMES, STATIC_ALIASES

def build(path):
    rows=[]; date=None
    aliases={a:k for k,v in STATIC_ALIASES.items() for a in v}
    def is_ago(s): return re.sub(r'\s+',' ',s.strip()) in HASHIMOTO_NAMES
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        dm=re.match(r'^(\d{4})/(\d{1,2})/(\d{1,2})',line)
        if dm:
            date=tuple(map(int,dm.groups()));continue
        m=re.match(r'^(\d{1,2}):(\d{2})\t([^\t]+)\t(.+)$',line)
        if not m or not date: continue
        h,mi,s,t=m.groups()
        if re.search(r'グループ.*(?:しました|されました)|ノートに投稿しました|を招待しました|^\[.+\]$',t):continue
        try: ts=datetime(*date,int(h),int(mi)).timestamp()
        except ValueError: continue
        rows.append((ts,aliases.get(s,s),t,is_ago(s)))
    counts=defaultdict(lambda:[0,0]); base=[0,0]; last_ago=None; last_partner=None
    # Last 20% chronological holdout; training uses preceding 80% only.
    split=int(len(rows)*.8); held=[0,0]; active_held=[0,0]
    for i,(ts,sp,t,ago) in enumerate(rows[:-1]):
        if ago:
            last_ago=ts
            if i and not rows[i-1][3]:last_partner=rows[i-1][1]
            continue
        nxt=rows[i+1]; gap=nxt[0]-ts
        if gap<0 or gap>300:continue
        # Evaluate final message in a speaker burst, not every message in it.
        if nxt[1]==sp and not nxt[3]:continue
        active=last_ago is not None and 0<=ts-last_ago<=1800
        cont=bool(i and rows[i-1][3] and last_partner==sp and 0<=ts-rows[i-1][0]<=180)
        y=int(nxt[3]);
        # Explicit calls follow deterministic rules at runtime; exclude from spontaneous estimate.
        if explicit_address(t):continue
        if i>=split:
            held[0]+=1;held[1]+=y
            if active:active_held[0]+=1;active_held[1]+=y
            continue
        base[0]+=1;base[1]+=y
        for f in features(t,sp,active,cont):
            counts[f][0]+=1;counts[f][1]+=y
    return {'schema':'ago-participation-v14-56','base':base,'counts':{k:v for k,v in counts.items() if v[0]>=20},'heldout':held,'heldout_active':active_held,'parsed_messages':len(rows),'definition':'next distinct sender is AGO within 5 minutes; chronological 80/20 split; explicit calls excluded; no read receipts'}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('line_export');p.add_argument('--output',default='ago_participation_v14_56.json');a=p.parse_args()
    d=build(a.line_export);Path(a.output).write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8');print({k:v for k,v in d.items() if k!='counts'})
