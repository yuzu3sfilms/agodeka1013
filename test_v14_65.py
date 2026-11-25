import unittest,sys,types,json,os,time
try:import openai
except ImportError:
    mod=types.ModuleType('openai');mod.OpenAI=lambda **kw:None;sys.modules['openai']=mod
from bot import AgoHashimotoBot
from persona_engine import PersonaEngine
from participation import explicit_address,other_address,ParticipationModel
from project_identity import health_payload
class Fake:
    def __init__(self):self.calls=[];self.mode='valid';self.chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))
    def create(self,**kw):
        p=json.loads(kw['messages'][1]['content']);self.calls.append(p)
        if self.mode=='error':raise TimeoutError('simulated')
        d={'focus_ids':[p['current_id']],'action':'comment','evidence_ids':[],'text':'テスト応答です。'}
        if self.mode=='older':d['focus_ids']=[p['history'][0]['id']];d['action']='answer'
        if self.mode=='bad_evidence':d['evidence_ids']=['L9999999']
        if self.mode=='bad_focus':d['focus_ids']=[9999999]
        if self.mode=='empty':d['text']=''
        if self.mode=='silence':d['action']='silence';d['text']=''
        if self.mode=='bad_json':return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='bad'))])
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=json.dumps(d)))])
class Tests(unittest.TestCase):
    def setUp(self):self.fake=Fake();self.b=AgoHashimotoBot(client=self.fake);os.environ['AGO_SPONTANEOUS']='0'
    def send(self,t,chat='Ctest',speaker='Reiji Shioda'):return self.b.reply(chat,t,sender_display_name=speaker)
    def test_startup_and_evidence(self):
        self.assertEqual(health_payload()['version'],'v14.65');self.assertEqual(len(self.b.engine.hypotheses),9)
        self.assertEqual(len(self.b.engine.evidence),49);self.assertNotIn('L102008',self.b.engine.evidence)
        self.assertTrue(all(x['sender'] in {'LIAR  OF  ARAKUN','Arata Hashimoto'} for x in self.b.engine.evidence.values()))
        self.assertGreater(self.b.participation.base[0],10000)
    def test_observe_silent_and_explicit(self):
        self.assertIsNone(self.send('チンティンはまぁええか',speaker='む'))
        self.assertEqual(self.send('あらくんはどう思うの？'),'テスト応答です。')
        p=self.fake.calls[-1];self.assertEqual([x['text'] for x in p['history']],['チンティンはまぁええか','あらくんはどう思うの？']);self.assertEqual(p['history'][0]['speaker'],'村田')
        self.assertEqual(self.send('興味なさそう'),'テスト応答です。');self.assertEqual(self.fake.calls[-1]['history'][-2]['role'],'AGO_generated')
    def test_other_address_and_ack(self):
        self.assertIsNone(self.send('ムタは？'));self.assertIsNone(self.send('最近どう？'));self.assertEqual(len(self.fake.calls),0)
        self.assertEqual(self.send('あらくんは？'),'テスト応答です。');self.assertIsNone(self.send('了解'))
    def test_direct_context_and_older_focus(self):
        self.send('明日はどうする？','Utest');self.fake.mode='older';self.assertEqual(self.send('そういえば今日寒い','Utest'),'テスト応答です。');self.assertEqual(self.b.states['Utest'].last_focus_ids,[1])
    def test_group_older_focus_explicit_rejected(self):
        self.send('前の話');self.fake.mode='older';self.assertIsNone(self.send('あらくんは？'))
    def test_api_error_no_fallback(self):
        self.fake.mode='error';self.assertIsNone(self.send('あらくん'));self.assertEqual(len(self.b.states['Ctest'].turns),1)
    def test_invalid_outputs_no_fallback(self):
        for mode in ('bad_evidence','bad_focus','empty','bad_json','silence'):
            self.fake.mode=mode;self.assertIsNone(self.send('あらくん'));self.assertEqual(self.b.states['Ctest'].turns[-1]['role'],'user')
    def test_shutdown(self):self.b.set_shutdown('Ctest',True);self.assertIsNone(self.send('あらくん'));self.assertEqual(len(self.fake.calls),0)
    def test_chat_isolation_and_history(self):
        self.send('秘密の話','U1');self.send('こんにちは','U2');self.assertEqual(len(self.fake.calls[-1]['history']),1)
        st=self.b.states['U2'];st.turns[0]['at']-=90000;self.send('今日の話','U2');self.assertNotIn('こんにちは',[x['text'] for x in self.fake.calls[-1]['history']])
    def test_address(self):
        for t in ('あらくんは？','顎も？','あらくんはどう思うの？'):self.assertTrue(explicit_address(t),t)
        self.assertFalse(explicit_address('橋本が昨日来たらしい'));self.assertTrue(other_address('ムタは？'))
    def test_spontaneous_without_topic_gate(self):
        os.environ['AGO_SPONTANEOUS']='1'
        try:
            self.b.participation.rng=types.SimpleNamespace(random=lambda:0.0)
            self.send('うん',speaker='村田');self.send('そうだね',speaker='坂口')
            self.assertEqual(self.send('この前のあの話は意外と面白かった'),'テスト応答です。')
            self.assertEqual(self.fake.calls[-1]['participation_reason'],'spontaneous_sample')
        finally:os.environ['AGO_SPONTANEOUS']='0'
    def test_history_limit(self):
        st=self.b.states['Utest'];now=time.time()
        for i in range(80):self.b._observe(st,'user',f'発言{i}','相手',now)
        self.send('最新','Utest');p=self.fake.calls[-1];self.assertEqual(len(p['history']),60);self.assertEqual(p['history'][-1]['text'],'最新')
if __name__=='__main__':unittest.main(verbosity=2)
