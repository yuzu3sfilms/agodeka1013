"""Build source-addressable research index, NOT a deployable persona or training set.
Usage: python build_evidence_index.py --line PATH --excel PATH --out PATH
Excel reading requires artifact_tool. Source text remains in original files.
"""
import argparse, collections, datetime as dt, gzip, hashlib, json, re, statistics
from pathlib import Path

PRIMARY={'LIAR  OF  ARAKUN','Arata Hashimoto'}
AMBIGUOUS={'橋本新','Unknown','サブ垢です'}
SYS=re.compile(r'グループ(?:音声|ビデオ)?通話が(?:開始されました|終了しました)|(?:グループに参加|グループから退出|退出|ノートに投稿)しました[。.]?$|メッセージの送信を取り消しました[。.]?$')
MEDIA=re.compile(r'^\[(?:写真|動画|スタンプ|ファイル|アルバム|ボイスメッセージ|連絡先|位置情報)\]$')
SCHED=re.compile(r'(?:\d{1,2}[時:：]\d*|集合|何時|待ち合わせ|遅れ|着[いくき]|何分|予約|到着)')
LIFT=re.compile(r'(?:筋トレ|スクワット|デッドリフト|ベンチプレス|筋肉痛|筋肥大|トレーニング|ボディビル|プロテイン|ダンベル)')
MARKERS={'polite':r'です|ます|ません|ください','question':r'[?？]|(?:ですか|ますか|でしょうか)[。\s]*$','apology':r'すみません|申し訳|ごめん|すいません','conditional':r'(?:場合|なら|によって|による|人による|だったら|であれば|に応じ)'}
NAME_PATTERNS={'塩田さん':'塩田さん','塩田（敬称なし候補）':'塩田(?!さん|君|くん|氏)','関口さん':'関口さん','せっきー':'[せセ][っッ][きキ][ーｰ]','ムタ系':'ムタ|むた|ムター|ムタファ|タムソン|ソンタム','村田':'村田'}
def norm(s):return re.sub(r'\s+','',str(s))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def parse(p):
    M=[];E=[];day=None;cur=None
    for i,raw in enumerate(open(p,encoding='utf-8-sig'),1):
        l=raw.rstrip('\r\n');d=re.fullmatch(r'(\d{4}/\d{1,2}/\d{1,2})\([^)]*\)',l)
        if d:
            day=dt.date.fromisoformat('-'.join(x.zfill(2) for x in d[1].split('/')));cur=None;continue
        m=re.match(r'^(\d{1,2}:\d{2})\t([^\t]+)\t(.*)$',l)
        if m and day:
            cur={'line':i,'t':dt.datetime.combine(day,dt.time(*map(int,m[1].split(':')))),'sender':m[2],'text':m[3]};M.append(cur)
        elif re.match(r'^\d{1,2}:\d{2}\t',l):
            if day:E.append(i);cur=None
        elif cur and l:cur['text']+='\n'+l
    session=-1;last=None
    for m in M:
        if last is None or not 0<=(m['t']-last).total_seconds()<=1800:session+=1
        t=m['text'].strip();m['session']=session;m['valid']=bool(t and not MEDIA.fullmatch(t) and not SYS.search(t) and not re.match(r'^https?://\S+$',t))
        m['identity']='primary_proxy' if m['sender'] in PRIMARY else 'ambiguous' if m['sender'] in AMBIGUOUS else 'other';last=m['t']
    return M,E

def build(line,excel):
    M,E=parse(line); primary=[m for m in M if m['identity']=='primary_proxy' and m['valid']]
    sessions={};rows=[];stats=collections.defaultdict(list); bytext=collections.defaultdict(list); primarycounts=collections.Counter(norm(m['text']) for m in primary)
    for i,m in enumerate(M):
        sid=m['session']; sessions.setdefault(sid,{'start_line':m['line'],'start':m['t'].isoformat(),'messages':0});sessions[sid]['end_line']=m['line'];sessions[sid]['end']=m['t'].isoformat();sessions[sid]['messages']+=1
        bytext[norm(m['text'])].append(m)
        if not m['valid'] or m['identity']=='other':continue
        # Training inputs only use prior lines. Future lines are for human audit ONLY.
        prev=[x for x in M[max(0,i-12):i] if x['session']==sid]
        nxt=[x for x in M[i+1:i+7] if x['session']==sid]
        echo=[x['line'] for x in M[max(0,i-12):i] if x['identity']=='other' and 0<=(m['t']-x['t']).total_seconds()<=1800 and norm(x['text'])==norm(m['text'])]
        row={'line':m['line'],'timestamp':m['t'].isoformat(),'sender':m['sender'],'identity':m['identity'],'session':sid,'analysis_period':'through_2022' if m['t'].year<2023 else '2023_plus_exploratory','prior_lines':[x['line'] for x in prev],'audit_only_future_lines':[x['line'] for x in nxt],'echo_candidate_prior_lines':echo,'primary_exact_text_frequency':primarycounts[norm(m['text'])],'text_sha256':hashlib.sha256(m['text'].encode()).hexdigest()}
        rows.append(row)
        if m['identity']!='primary_proxy' or (i and M[i-1]['identity']=='primary_proxy' and M[i-1]['session']==sid):continue
        ctx=[x for x in M[max(0,i-8):i] if x['session']==sid and 0<=(m['t']-x['t']).total_seconds()<=600 and x['valid'] and x['identity']=='other'][-3:]
        if not ctx:continue
        st='\n'.join(x['text'] for x in ctx);cat='schedule' if SCHED.search(st) else 'lifting' if LIFT.search(st) else 'other';stats[(row['analysis_period'],cat)].append(m['text'])
    measures=[]
    for (period,cat),ls in sorted(stats.items()):
        measures.append({'period':period,'context':cat,'n':len(ls),'median_chars':statistics.median(map(len,ls)),**{name:round(100*sum(bool(re.search(pat,s)) for s in ls)/len(ls),2) for name,pat in MARKERS.items()}})
    xrows=[];exmeta=None
    if excel:
        from artifact_tool import Blob,SpreadsheetFile
        w=SpreadsheetFile.import_xlsx(Blob.load(str(excel))); vals=w.worksheets.get_item_at(0).get_range('B2:B413').values
        seen={}
        for i,(v,) in enumerate(vals,2):
            if not v:continue
            s=norm(v);hits=bytext.get(s,[]);names=sorted({m['sender'] for m in hits});status='unmatched' if not hits else 'other_only_match' if not set(names)&(PRIMARY|AMBIGUOUS) else 'primary_only_match' if set(names)<=PRIMARY else 'ambiguous_only_match' if set(names)<=AMBIGUOUS else 'mixed_match'
            xrows.append({'row':i,'normalized_sha256':hashlib.sha256(s.encode()).hexdigest(),'duplicate_of_row':seen.get(s),'exact_match_lines':[m['line'] for m in hits],'exact_match_senders':names,'status':status,'use_as_persona_evidence':False});seen.setdefault(s,i)
        exmeta={'filename':Path(excel).name,'sha256':sha(excel),'sheet':'Sheet1','rows':len(xrows),'unique_normalized':len(seen),'status_counts':dict(collections.Counter(x['status'] for x in xrows))}
    out={'schema':'ago-persona-evidence-research-v14.57','status':'exploratory_not_deployable','source':{'filename':Path(line).name,'sha256':sha(line),'message_rows':len(M),'valid_message_rows':sum(m['valid'] for m in M),'system_or_unparsed_time_rows':len(E),'sessions_30_min':len(sessions)},'identity_policy':{'primary_proxy':sorted(PRIMARY),'ambiguous_quarantined':sorted(AMBIGUOUS),'note':'Display names are proxies, not confirmed account identity. The 2020 exchange around source lines 71915 and 72204 explicitly calls identity into question. Unknown and alternate accounts remain separate pending verification.'},'valid_by_identity':dict(collections.Counter(m['identity'] for m in M if m['valid'])),'candidate_by_sender':dict(collections.Counter(m['sender'] for m in M if m['valid'] and m['identity']!='other')),'primary_by_year':dict(collections.Counter(m['t'].year for m in primary)),'context_marker_rates_pct':measures,'primary_name_mention_counts':{k:sum(bool(re.search(v,m['text'])) for m in primary) for k,v in NAME_PATTERNS.items()},'excel':exmeta,'excel_row_index':xrows,'candidate_message_index':rows,'session_index':sessions,'limitations':['30-minute session segmentation is heuristic and may break slow conversations.','Nearby preceding messages do not prove addressee or reply ownership.','A full psychological annotation or independent blind prediction evaluation has not been completed.','Future context and post-2022 examples are exploratory evidence; do not expose to runtime or call this a clean held-out test.','Excel exact matching normalizes whitespace only; a match to another sender may be a quotation or repost, not proof of authorship.']}
    return out
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--line',required=True);p.add_argument('--excel');p.add_argument('--out',required=True);a=p.parse_args();o=build(a.line,a.excel)
    with gzip.open(a.out,'wt',encoding='utf-8') as f:json.dump(o,f,ensure_ascii=False,separators=(',',':'))
    print({k:o[k] for k in ['source','valid_by_identity','candidate_by_sender','excel','context_marker_rates_pct']})
