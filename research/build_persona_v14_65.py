"""Build a limited, source-addressable persona pack from audited research. No Excel or Unknown evidence."""
import argparse,json,re,hashlib
from pathlib import Path
from build_evidence_index import parse,norm

def build(raw,behavior,judgment,annotations):
    messages,_=parse(raw); by={m['line']:m for m in messages}; ix={m['line']:i for i,m in enumerate(messages)}
    b=json.loads(Path(behavior).read_text()); j=json.loads(Path(judgment).read_text()); a={x['sample_no']:x for x in map(json.loads,Path(annotations).read_text().splitlines())}
    evidence={}; rejected=[]
    def add(line,ctx,why):
        m=by.get(line)
        if not m or not m['valid'] or m['identity']!='primary_proxy':
            rejected.append({'line':line,'reason':'non-primary or invalid'});return None
        recent=messages[max(0,ix[line]-12):ix[line]]
        if any(x['identity']!='primary_proxy' and 0<=(m['t']-x['t']).total_seconds()<=1800 and norm(m['text'])==norm(x['text']) for x in recent):
            rejected.append({'line':line,'reason':'possible echo'});return None
        # Only prior context; never pass future observations as input.
        if not ctx:ctx=[x['line'] for x in recent[-4:]]
        rows=[]
        for l in ctx:
            x=by.get(l)
            if x and l<line:
                rows.append({'line':l,'speaker':x['sender'] if x['identity']!='ambiguous' else '帰属未確定','text':x['text'][:300]})
        eid=f'L{line}'; evidence[eid]={'id':eid,'date':m['t'].date().isoformat(),'sender':m['sender'],'context':rows,'utterance':m['text'][:600],'interpretation':why};return eid
    hypotheses=[]
    for h in b['hypotheses']:
        # Group lore is not personal biography, and the examples are unconfirmed.
        if h['id']=='H07':continue
        support=[add(x['line'],x.get('context_lines',[]),x['interpretation']) for x in h['support']]
        limits=[add(x['line'],x.get('context_lines',[]),x['interpretation']) for x in h['counter_or_boundary']]
        support=list(dict.fromkeys(x for x in support if x)); limits=list(dict.fromkeys(x for x in limits if x))
        if support:hypotheses.append({'id':h['id'],'observation':h['observation'],'conditions':h['domain'],'scope':h['runtime_implication'],'confidence':h['confidence'],'support':support,'limits':limits})
    for h in j['hypotheses']:
        def from_sample(n):
            x=a[n];return [add(l,x['target_context_lines'],x['note']) for l in x['target_response_lines']]
        support=[e for n in h['support_pre_2023'] for e in from_sample(n) if e]; later=[e for n in h['consistent_later'] for e in from_sample(n) if e];limits=[e for n in h['limits_or_alternatives'] for e in from_sample(n) if e]
        if support:hypotheses.append({'id':h['id'],'observation':h['candidate'],'conditions':h['conditions'],'scope':h['do_not_infer'],'confidence':'exploratory; not unique to person','support':list(dict.fromkeys(support+later)),'limits':list(dict.fromkeys(limits))})
    return {'schema':'ago-persona-v14.65','source_sha256':hashlib.sha256(Path(raw).read_bytes()).hexdigest(),'identity':'primary display-name proxy only; not verified legal identity','hypotheses':hypotheses,'evidence':evidence,'excluded':rejected}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('raw');p.add_argument('--out',default='ago_persona_v14_65.json');a=p.parse_args();d=build(a.raw,'behavior_hypotheses.json','judgment_hypotheses.json','contrast_annotations.jsonl');Path(a.out).write_text(json.dumps(d,ensure_ascii=False,indent=2));print(len(d['hypotheses']),len(d['evidence']),len(d['excluded']))
