"""Conversation participation is independent of response generation.
Historical rates estimate next-turn participation, not whether a message was read.
"""
from __future__ import annotations
import json, os, random, re, time
from pathlib import Path
from collections import Counter
from ago_runtime import dialogue_act, ACK_RE, QUESTION_RE, STATIC_ALIASES

SELF = r'(?:橋本新|橋本|あらくん|顎|アゴ|AGODEKA)'
# An explicit address, not merely a mention in a third-person statement.
VOCATIVE = re.compile(r'^\s*@?'+SELF+r'(?:さん|くん)?(?:[、,:：\s]|$|[？?！!]|(?:は|って)?(?:今|何|どう|いつ|どこ|いる|おる|来|行|教|聞|見|知|覚|元気|最近|自我|名前|年齢|お前|ありがとう|ありがと|すまん|おつ|頼む))', re.I)
THIRD = re.compile(SELF+r'(?:が|の|と|に|も|を)(?!どう思)',re.I)
TOPICS = {
 'fitness': r'筋トレ|トレーニング|筋肉|ジム|ベンチプレス|スクワット|プロテイン|ボディビル',
 'food': r'二郎|ラーメン|サイゼ|食べ|ご飯|飯|カレー|焼肉',
 'hobby': r'ガンダム|フィギュア|仮面ライダー|玩具|ゲーム|映画|ギター|プラモ',
 'humor': r'ｗｗ|ww|笑|草|ネタ|うんち|うんこ',
 'plans': r'集合|待ち合わせ|何時|予約|行ける|着く',
}

def topic(text):
    for key,pat in TOPICS.items():
        if re.search(pat,text or '',re.I): return key
    return 'other'

def explicit_address(text):
    t=(text or '').strip()
    if re.search(r'@'+SELF+r'(?:\s|$|[、,:：])',t,re.I): return True
    if THIRD.match(t): return False
    return bool(VOCATIVE.search(t) or re.fullmatch(SELF+r'(?:さん|くん)?[？?！!]*',t,re.I))

def other_address(text, aliases=None):
    # Only clear vocatives. A name somewhere in a sentence is not an address.
    t=(text or '').strip()
    names=set().union(*STATIC_ALIASES.values())
    for a in (aliases or {}):
        if len(a)>=2: names.add(a)
    for a in sorted(names,key=len,reverse=True):
        if len(a)<2: continue
        if re.match(r'^@?'+re.escape(a)+r'(?:さん|くん)?(?:[、,:：\s]|[？?！!]|$|(?:は|って)?(?:今|何|どう|いつ|どこ|いる|おる|来|行|教|聞|見|知|元気|最近))',t): return True
    return False

def features(text,speaker,active,continuing):
    return [f'act:{dialogue_act(text)}',f'topic:{topic(text)}',f'active:{int(active)}',f'continuing:{int(continuing)}',f'speaker:{speaker}']

class ParticipationModel:
    def __init__(self,path=None,rng=None,clock=None):
        self.rng=rng or random.Random()
        self.clock=clock or time.time
        candidates=[path,os.environ.get('AGO_PARTICIPATION_MODEL'),str(Path(__file__).with_name('ago_participation_v14_56.json')),'data/ago_participation_v14_56.json']
        self.data={}
        for p in candidates:
            if p and Path(p).is_file():
                self.data=json.loads(Path(p).read_text(encoding='utf-8'));break
        self.counts=self.data.get('counts',{})
        self.base=self.data.get('base',[0,0])
    def probability(self,text,speaker,active,continuing):
        n,y=self.base
        if not n: return 0.0
        prior=(y+1)/(n+2)
        # Smoothed marginal estimates; avoid multiplying correlated features.
        estimates=[]
        for f in features(text,speaker,active,continuing):
            a,b=self.counts.get(f,[0,0])
            if a>=20: estimates.append((b+50*prior)/(a+50))
        return sum(estimates)/len(estimates) if estimates else prior
    def decide(self,text,state,speaker,is_group,aliases=None,now=None):
        now=self.clock() if now is None else now
        t=(text or '').strip(); act=dialogue_act(t)
        prev=state.turns[-1] if state.turns else {}
        age=now-state.last_reply_at if state.last_reply_at else float('inf')
        active=age<=1800
        continuity=(prev.get('role')=='assistant' and state.last_partner==speaker and age<=180 and not state.participation_closed)
        called=explicit_address(t)
        other=other_address(t,aliases) if is_group else False
        def result(reply,reason,p=None):
            return {'reply':reply,'reason':reason,'probability':p,'active':active,'continuation':continuity,'called':called}
        if not t: return result(False,'empty')
        if is_group and other and not called: return result(False,'other_addressee')
        if ACK_RE.match(t) and not called: return result(False,'natural_closure')
        if called: return result(True,'direct_address')
        if not is_group:
            # Direct chat is addressed to AGO. Short acknowledgements above close it.
            if re.fullmatch(r'(?:[wｗ]+|笑+|草|[😂🤣😇]+)[!！。]*',t,re.I):
                return result(False,'reaction_only')
            return result(True,'direct_chat')
        if continuity:
            if re.fullmatch(r'(?:[wｗ]+|笑+|草|[😂🤣😇]+)[!！。]*',t,re.I): return result(False,'reaction_only')
            return result(True,'active_continuation')
        # An ambiguous question or third-person mention is not an invitation.
        if QUESTION_RE.search(t) or THIRD.search(t) or re.search(SELF,t,re.I):
            return result(False,'ambiguous_addressee')
        if len(t)<10 or act in {'short_reaction','thanks','apology','scheduling'}:
            return result(False,'low_information_or_private_exchange')
        if os.getenv('AGO_SPONTANEOUS','1')=='0': return result(False,'spontaneous_disabled')
        if topic(t)=='other': return result(False,'no_topic_signal')
        recent=[x for x in state.turns[-8:] if x.get('role')=='user' and 0<=now-x.get('at',0)<=180]
        if len(recent)<2 or len({x.get('speaker') for x in recent}|{speaker})<2: return result(False,'not_enough_group_context')
        if state.last_spontaneous_at and now-state.last_spontaneous_at<600:
            return result(False,'spontaneous_cooldown')
        if age<90: return result(False,'recent_reply_cooldown')
        # Conservative cap: historical next-turn rates are not read receipts.
        p=min(.08 if active else .025, self.probability(t,speaker,active,False)*.25)
        return result(self.rng.random()<p,'spontaneous_sample',round(p,5))
