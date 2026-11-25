"""Next-speaker observations from primary display-name proxies only. Exclude ambiguous transitions."""
import argparse,json
from pathlib import Path
from collections import defaultdict
from build_evidence_index import parse
from participation import features,explicit_address
from ago_runtime import STATIC_ALIASES

def build(path):
    allrows,_=parse(path); rows=[m for m in allrows if m['valid']]; aliases={a:k for k,v in STATIC_ALIASES.items() for a in v};counts=defaultdict(lambda:[0,0]);base=[0,0];held=[0,0];ambig=0;last=None;partner=None;cut=int(len(rows)*.8)
    for i,m in enumerate(rows[:-1]):
        ts=m['t'];sp=aliases.get(m['sender'],m['sender']); nxt=rows[i+1]; dt=(nxt['t']-ts).total_seconds()
        if m['identity']=='primary_proxy':
            last=ts
            if i and rows[i-1]['identity']=='other':partner=aliases.get(rows[i-1]['sender'],rows[i-1]['sender'])
            continue
        if m['identity']=='ambiguous' or nxt['identity']=='ambiguous':ambig+=1;continue
        if dt<0 or dt>300 or (nxt['identity']=='other' and aliases.get(nxt['sender'],nxt['sender'])==sp) or explicit_address(m['text']):continue
        active=last is not None and 0<=(ts-last).total_seconds()<=1800
        cont=bool(i and rows[i-1]['identity']=='primary_proxy' and partner==sp and 0<=(ts-rows[i-1]['t']).total_seconds()<=180)
        y=int(nxt['identity']=='primary_proxy')
        if i>=cut:held[0]+=1;held[1]+=y;continue
        base[0]+=1;base[1]+=y
        for f in features(m['text'],sp,active,cont):counts[f][0]+=1;counts[f][1]+=y
    return {'schema':'ago-participation-v14-65','base':base,'heldout':held,'counts':{k:v for k,v in counts.items() if v[0]>=20},'parsed_messages':len(rows),'ambiguous_transitions_excluded':ambig,'definition':'next distinct speaker primary proxy within 5min, no read receipts; chronological 80/20; ambiguous endpoints excluded; context-only features, not calibrated'}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('raw');p.add_argument('--out',default='ago_participation_v14_65.json');a=p.parse_args();d=build(a.raw);Path(a.out).write_text(json.dumps(d,ensure_ascii=False,indent=2));print({k:v for k,v in d.items() if k!='counts'})
