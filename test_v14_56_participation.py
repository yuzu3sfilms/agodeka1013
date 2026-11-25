"""Offline participation and actual bot integration, with a fake Groq client."""
import sys, types, time, random, os
from ago_runtime import DialogueState
from participation import ParticipationModel
p=ParticipationModel(rng=random.Random(4))
assert p.base[0]>10000
S='Reiji Shioda'; T='村田'; now=100000
st=DialogueState()
def d(t,s=S,g=True):return p.decide(t,st,s,g,now=now)
for t in ['最近どう？','自我芽生えた？','名前は言える？','年齢は？','俺ってどんなやつだと思う？','どれ？','えー','橋本が昨日来たらしい']:
    assert not d(t)['reply'],t
assert d('顎、最近どう？')['reply']
assert d('あらくん')['reply']
assert not d('せっきー、最近どう？')['reply']
assert not d('いいね',g=False)['reply']
assert d('最近どう？',g=False)['reply']
st.last_reply_at=now-5;st.last_partner=S;st.turns=[{'role':'assistant','text':'何時ですか？','at':now-5}]
assert d('14時')['reason']=='active_continuation'
assert not d('14時',T)['reply']
assert not d('せっきー、何時？')['reply']
assert not d('了解')['reply']
st.last_reply_at=now-181
assert not d('14時')['reply']
# Deterministic stochastic branch and cooldown; must be eligible before sampling.
class Always:
    def random(self):return 0.0
p.rng=Always();st.last_reply_at=now-300;st.turns=[{'role':'user','speaker':S,'at':now-40},{'role':'user','speaker':T,'at':now-20}]
a=d('最近ジムで筋トレばかりしています')
assert a['reply'] and 0<a['probability']<=.08,a
st.last_spontaneous_at=now-1
assert d('最近ジムで筋トレばかりしています')['reason']=='spontaneous_cooldown'
# Integration: test real bot.reply entrypoint without sending anything or calling Groq.
try:import openai
except ImportError:
    mod=types.ModuleType('openai');mod.OpenAI=lambda **kw:None;sys.modules['openai']=mod
from bot import AgoHashimotoBot
os.environ.setdefault('GROQ_API_KEY','offline-test')
b=AgoHashimotoBot();b._generate=lambda *a:('はい。','offline_test','mock')
assert b.reply('Ctest','最近どう？',sender_display_name=S) is None
assert b.reply('Ctest','顎、最近どう？',sender_display_name=S)=='はい。'
assert b.reply('Ctest','いいね',sender_display_name=S) is None
assert b.reply('Ctest','どれ？',sender_display_name=T) is None
assert b.reply('Utest','俺ってどんなやつだと思う？',sender_display_name=S)=='はい。'
assert b.states['Utest'].last_intent=='person_opinion'
assert b.reply('Utest','じゃあムタは？',sender_display_name=S)=='はい。'
assert b.states['Utest'].last_target_id=='村田'
assert b.reply('Utest','いいね',sender_display_name=S) is None
assert not b.states['Utest'].last_predicate
b.set_shutdown('Ctest',True)
assert b.reply('Ctest','あらくん',sender_display_name=S) is None
print('ALL PARTICIPATION TESTS PASSED')
