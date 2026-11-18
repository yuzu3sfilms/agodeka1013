"""Rebuild Project AGO v14.54 persona archive from primary sources.

Expected files in data/ or repo root:
- [LINE] 名前は言えねえけど14類のトーク.txt (Unicode spelling variants accepted by glob)
- arakun_reply_pairs_exhaustive.txt
- AI橋本用データセット.xlsx

Runtime does NOT need openpyxl because the generated .json.gz is bundled.
"""
from __future__ import annotations

import collections
import datetime as dt
import glob
import gzip
import hashlib
import json
import re
from pathlib import Path

from openpyxl import load_workbook

HASHIMOTO_NAMES={
    "橋本新","Arata Hashimoto","LIAR  OF  ARAKUN","LIAR OF ARAKUN",
    "あらくん","顎","AGODEKA","サブ垢です","Unknown",
}
SYS_RE=re.compile(r"(?:グループ(?:音声|ビデオ)?通話が(?:開始されました|終了しました)|グループ通話が(?:開始されました|終了しました)|.+がグループに参加しました|.+がグループから退出しました|.+が退出しました|.+がノートに投稿しました|.+が.+を招待しました)[。.]?$")
MEDIA_RE=re.compile(r"^\[(?:写真|スタンプ|動画|ファイル|アルバム)\]$|https?://",re.I)


def is_h(name):
    n=re.sub(r"\s+"," ",(name or "").strip())
    return n in HASHIMOTO_NAMES or "橋本" in n or "ARAKUN" in n.upper()


def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1<<20),b""):
            h.update(chunk)
    return h.hexdigest()


def find_one(patterns):
    roots=[Path("data"),Path(".")]
    hits=[]
    for root in roots:
        for pat in patterns:
            hits.extend(Path(x) for x in glob.glob(str(root/pat)))
    hits=[p for p in hits if p.is_file()]
    if not hits:
        raise FileNotFoundError(f"source not found: {patterns}")
    # Prefer the largest non-(1) duplicate.
    hits.sort(key=lambda p:("(1)" in p.name, -p.stat().st_size))
    return hits[0]


def parse_line(path):
    msgs=[]; cur=None; date=None
    with open(path,encoding="utf-8-sig",errors="ignore") as f:
        for raw in f:
            line=raw.rstrip("\r\n")
            dm=re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2})",line)
            if dm:
                date=tuple(map(int,dm.groups())); cur=None; continue
            m=re.match(r"^(\d{1,2}):(\d{2})\t([^\t]+)\t(.*)$",line)
            if m and date:
                y,mo,d=date
                ts=dt.datetime(y,mo,d,int(m.group(1)),int(m.group(2)))
                cur={"ts":ts.isoformat(timespec="minutes"),"sender":m.group(3).strip(),"text":m.group(4).strip()}
                msgs.append(cur)
            elif cur and line and not re.match(r"^\d{4}/\d",line):
                cur["text"]=(cur["text"]+" / "+line.strip()).strip(" /")
    return msgs


def act(text):
    t=(text or "").strip()
    if re.search(r"(?:自我|意識|感情).*(?:芽生|ある|持って|感じ)|(?:芽生|ある).*(?:自我|意識|感情)",t): return "meta_self"
    if re.search(r"(?:ありがとう|ありがと|助かった|サンキュ|感謝)",t,re.I): return "thanks"
    if re.search(r"(?:ごめん|すみません|すまん|申し訳|遅れ|遅刻)",t): return "apology"
    if re.search(r"(?:何時|何分|\d{1,2}時|いつ|今日|明日|来週|土曜|日曜|集合|予定|行ける|空いて|予約)",t): return "scheduling"
    if re.search(r"(?:どう思|どう感じ|好き|嫌い|おすすめ|良いと思|いいと思)",t): return "opinion"
    if re.search(r"(?:ww+|ｗｗ+|笑|草|ウケ|おもろ|面白)",t,re.I): return "banter"
    if re.search(r"[？?]$",t): return "yesno_question"
    if len(t)<=8: return "short_reaction"
    return "statement"


def features(t):
    return {"chars":len(t),"lines":t.count(" / ")+1,"question":bool(re.search(r"[？?](?:$| / )",t)),"laughter":bool(re.search(r"(?:ww+|ｗｗ+|笑|草|😂|😇|ｷｬ|きゃぴ)",t,re.I)),"polite":bool(re.search(r"(?:です|ます|でした|ません|すみません|ありがとう)",t))}


def build_raw_episodes(chat):
    eps=[]; i=0; eid=0
    def ts(x): return dt.datetime.fromisoformat(x)
    while i<len(chat):
        if not is_h(chat[i]["sender"]) or i==0 or is_h(chat[i-1]["sender"]):
            i+=1; continue
        first=i; start=ts(chat[first]["ts"]); replies=[]; j=first
        while j<len(chat) and is_h(chat[j]["sender"]) and len(replies)<8:
            if (ts(chat[j]["ts"])-start).total_seconds()>15*60: break
            replies.append(chat[j]); j+=1
        ctx=[]; k=first-1
        while k>=0 and len(ctx)<8:
            if (start-ts(chat[k]["ts"])).total_seconds()>3*3600: break
            ctx.append(chat[k]); k-=1
        ctx=list(reversed(ctx))
        if ctx and not is_h(ctx[-1]["sender"]):
            reply=" / ".join(x["text"] for x in replies if x["text"])
            if reply:
                eid+=1
                eps.append({"id":f"raw-{eid}","source":"line_raw","ts":replies[0]["ts"],"context":[{"sender":x["sender"],"text":x["text"],"is_hashimoto":is_h(x["sender"])} for x in ctx],"last_speaker":ctx[-1]["sender"],"stimulus":ctx[-1]["text"],"act":act(ctx[-1]["text"]),"reply":reply,"features":features(reply)})
        i=max(i+1,j)
    return eps


def build_derived(path):
    out=[]
    with open(path,encoding="utf-8",errors="ignore") as f:
        for idx,line in enumerate(f,1):
            if line.startswith("#"): continue
            parts=line.rstrip("\n").split("::",2)
            if len(parts)!=3: continue
            _,ctx,rep=parts
            rep=rep.strip()
            if not rep or SYS_RE.search(rep) or MEDIA_RE.search(rep): continue
            body=ctx.split("|",1)[1].strip() if "|" in ctx else ctx
            turns=[]; last=""
            for seg in [x.strip() for x in body.split(" / ") if x.strip()]:
                if seg.startswith("相手:"):
                    txt=seg[3:].strip()
                    if SYS_RE.search(txt) or MEDIA_RE.search(txt): continue
                    turns.append({"sender":"相手","text":txt,"is_hashimoto":False}); last=txt
                elif seg.startswith("あらくん:"):
                    txt=seg[len("あらくん:"):].strip()
                    if SYS_RE.search(txt) or MEDIA_RE.search(txt): continue
                    turns.append({"sender":"橋本新","text":txt,"is_hashimoto":True})
            if last:
                out.append({"id":f"pair-{idx}","source":"reply_pairs","ts":"","context":turns[-8:],"last_speaker":"相手","stimulus":last,"act":act(last),"reply":rep,"features":features(rep)})
    return out


def main():
    line=find_one(["*LINE*トーク*.txt","*14類*トーク*.txt"])
    pairs=find_one(["arakun_reply_pairs_exhaustive.txt"])
    xlsx=find_one(["AI橋本用*データセット*.xlsx","AI橋本用*データセット*.xlsx"])
    msgs=parse_line(line)
    chat=[m for m in msgs if m["text"] and not SYS_RE.search(m["text"]) and not MEDIA_RE.search(m["text"])]
    raw_eps=build_raw_episodes(chat)
    derived=build_derived(pairs)
    wb=load_workbook(xlsx,read_only=True,data_only=True)
    statements=[r[1].strip() for r in wb.active.iter_rows(values_only=True) if len(r)>1 and isinstance(r[1],str) and r[1].strip()]
    utts=[{"ts":m["ts"],"sender":m["sender"],"text":m["text"]} for m in chat if is_h(m["sender"])]
    cnt=collections.Counter(x["text"].strip() for x in utts if 1<=len(x["text"].strip())<=20 and " / " not in x["text"])
    archive={
      "schema":"ago-persona-archive-v14-54",
      "created_from":{
        "line_raw":{"file":line.name,"sha256":sha256(line),"message_count":len(msgs),"chat_message_count":len(chat),"hashimoto_utterance_count":len(utts)},
        "reply_pairs":{"file":pairs.name,"sha256":sha256(pairs),"episode_count":len(derived)},
        "ai_dataset":{"file":xlsx.name,"sha256":sha256(xlsx),"statement_count":len(statements)},
      },
      "aliases":{
        "Reiji Shioda":["Reiji Shioda","塩田","塩田さん","れーじ","レージ","れいじ"],
        "Ryo Sekiguchi":["Ryo Sekiguchi","関口","関口さん","関口諒","せきぐち","せっきー","セッキー","せっき","セッキ"],
        "中山 貴文":["中山 貴文","中山","中山さん","貴文","ぽつぉ","ぽつお","ポツォ","ポッツォ","ぽつ","ぽっつぉ"],
        "村田":["村田","村田さん","ムタ","むた","む"],"坂口":["坂口","坂口さん","さかぐち"]},
      "raw_episodes":raw_eps,"derived_context_episodes":derived,"self_statements":statements,"hashimoto_utterances":utts,"short_reactions":[{"text":t,"count":n} for t,n in cnt.most_common(150)]}
    out=Path("ago_persona_archive_v14_54.json.gz")
    with gzip.open(out,"wt",encoding="utf-8",compresslevel=9) as f:
        json.dump(archive,f,ensure_ascii=False,separators=(",",":"))
    print({"output":str(out),"raw_messages":len(msgs),"raw_episodes":len(raw_eps),"reply_pair_episodes":len(derived),"dataset_statements":len(statements),"hashimoto_utterances":len(utts)})

if __name__=="__main__": main()
