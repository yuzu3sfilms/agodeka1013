from __future__ import annotations
import os, threading, time, json
from collections import defaultdict
from openai import OpenAI
from ago_runtime import DialogueState, STATIC_ALIASES
from participation import ParticipationModel
from persona_engine import PersonaEngine
from project_identity import PROJECT_VERSION
from token_budget import PROCESS_BUDGET, estimate, env_int
try:
    from shutdown_state import ShutdownStateStore
except ImportError:
    class ShutdownStateStore:
        def __init__(self): self._d={}
        def set(self,k,v): self._d[k]=bool(v)
        def get(self,k): return bool(self._d.get(k,False))
try:
    from speaker_resolver import SpeakerResolver
except ImportError:
    SpeakerResolver=None

class AgoHashimotoBot:
    def __init__(self, client=None, budget=None):
        self.model=os.environ.get('GROQ_MODEL','openai/gpt-oss-20b')
        self.client=client if client is not None else OpenAI(api_key=os.environ['GROQ_API_KEY'],base_url='https://api.groq.com/openai/v1',timeout=12.0,max_retries=0)
        self.engine=PersonaEngine()
        self.budget=budget if budget is not None else PROCESS_BUDGET
        self.completion=env_int("AGO_COMPLETION_TOKENS",768,256,1024)
        self.request_budget=env_int("AGO_REQUEST_TOKENS",4200,1800,7400)
        self.participation=ParticipationModel()
        self.states=defaultdict(DialogueState); self.locks=defaultdict(threading.RLock)
        self.shutdown_store=ShutdownStateStore(); self.speaker_resolver=SpeakerResolver() if SpeakerResolver else None
        self.aliases={a:k for k,v in STATIC_ALIASES.items() for a in v}
        self.max_history=max(60,min(240,int(os.getenv('AGO_HISTORY','60'))))
        print('bot_init:',{'version':PROJECT_VERSION,'hypotheses':len(self.engine.hypotheses),'evidence':len(self.engine.evidence),'participation_training':self.participation.base},flush=True)
    def set_shutdown(self,chat_id,value=True):self.shutdown_store.set(chat_id,bool(value))
    def is_shutdown(self,chat_id):
        try:return bool(self.shutdown_store.get(chat_id))
        except Exception:return False
    @staticmethod
    def _is_group(chat_id):return str(chat_id or '').startswith(('C','R'))
    def _speaker(self,sender_id,display):
        if self.speaker_resolver:
            try:
                p=self.speaker_resolver.resolve(sender_id=sender_id,display_name=display)
                return p.canonical_name or p.display_name or display or sender_id or ''
            except Exception:pass
        return self.aliases.get(display,display) if display else sender_id or ''
    def _observe(self,state,role,text,speaker,now):
        seq=getattr(state,'sequence',0)+1;state.sequence=seq
        state.turns.append({'id':seq,'role':role,'text':text,'speaker':speaker,'at':now})
        state.turns[:]=[t for t in state.turns[-self.max_history:] if 0<=now-t['at']<=86400]
    def _generate(self,state,now,decision,is_group):
        available=self.budget.available()
        cap=min(self.request_budget,available)
        msgs,history=self.engine.messages(state.turns,now,decision,is_group,cap,self.completion)
        if msgs is None:
            print('generation budget:',{'status':'local_budget_exhausted','available':available,'cap':cap},flush=True)
            return None,'local_budget_exhausted'
        tokens=estimate(msgs,self.completion)
        reservation=self.budget.reserve(tokens)
        if reservation is None:
            print('generation budget:',{'status':'local_budget_race','requested':tokens},flush=True)
            return None,'local_budget_exhausted'
        payload=json.loads(msgs[1]['content']); selected=payload['persona_evidence']['examples']
        print('generation budget:',{'estimate_upper_proxy':tokens,'request_cap':cap,'available_before':available,'completion':self.completion,'history_count':len(history),'hypotheses':len(payload['persona_evidence']['observations']),'evidence_count':len(selected)},flush=True)
        try:
            res=self.client.chat.completions.create(model=self.model,messages=msgs,temperature=float(os.getenv('TEMPERATURE','0.35')),max_completion_tokens=self.completion,response_format={'type':'json_object'},extra_body={'reasoning_effort':os.getenv('GROQ_REASONING_EFFORT','low')})
            usage=getattr(res,'usage',None);self.budget.reconcile(reservation,usage,self.completion)
            if usage is not None:
                print('generation usage:',{'prompt_tokens':getattr(usage,'prompt_tokens',None),'completion_tokens':getattr(usage,'completion_tokens',None),'total_tokens':getattr(usage,'total_tokens',None)},flush=True)
            raw=res.choices[0].message.content or ''
        except Exception as e:
            status=getattr(e,'status_code',None)
            if status in (413,429):
                # No blind retry in a webhook. A rejected/ambiguous request
                # remains reserved for 60s; shared-account limits can differ.
                self.budget.backoff(60 if status==429 else 10)
            print('generation failure:',type(e).__name__,str(e)[:250],flush=True);return None,'api_error'
        return self.engine.validate(raw,history,decision,{e['id'] for e in selected})
    def reply(self,chat_id,user_text,sender_id=None,sender_display_name=None):
        with self.locks[chat_id]:
            if self.is_shutdown(chat_id):return None
            state=self.states[chat_id];speaker=self._speaker(sender_id,sender_display_name);now=time.time();group=self._is_group(chat_id)
            decision=self.participation.decide(user_text,state,speaker,group,self.aliases,now)
            print('participation:',decision,flush=True)
            self._observe(state,'user',user_text,speaker,now)
            if not decision['reply']:
                state.participation_closed=True
                print('generation path: v14_66_participation_silence',flush=True);return None
            result,status=self._generate(state,now,decision,group)
            if result is None or result['action']=='silence':
                state.participation_closed=True
                print('generation path: v14_66_'+status,flush=True);return None
            text=result['text']; state.last_focus_ids=result['focus_ids'];state.last_action=result['action']
            selected=[t for t in state.turns if t['id'] in result['focus_ids'] and t['role']=='user']
            state.last_partner=selected[-1]['speaker'] if selected else speaker
            self._observe(state,'assistant',text,'AGO',now);state.last_reply_at=now;state.participation_closed=False
            if decision['reason']=='spontaneous_sample':state.last_spontaneous_at=now
            print('generation path: v14_66_integrated',flush=True)
            print('response_plan:',{'focus_ids':result['focus_ids'],'action':result['action'],'evidence_ids':result['evidence_ids'],'validation':status},flush=True)
            print('reply:',text,flush=True);return text
HashimotoArataBot=AgoHashimotoBot
