import asyncio,json
import pytest
from brain.agent import Agent
from brain.tools import parse_message,strip_reasoning
from brain.server import Hub,create_app
from fastapi.testclient import TestClient
class FakeLLM:
    model='scripted'
    def __init__(self,actions):self.actions=iter(actions);self.seen=[]
    async def chat(self,messages):
        self.seen.append(messages.copy());a=next(self.actions)
        return {'content':a if isinstance(a,str) else json.dumps(a)}
def action(t,**kw):return {'tool':t,'args':kw}
async def execute(actions,call=None):
    events=[];llm=FakeLLM(actions)
    async def emit(e):events.append(e)
    async def default_call(t,a):return {'exit_code':0,'output':'hello'}
    agent=Agent(llm,call or default_call,emit);await agent.submit('task');await agent.active
    return agent,events,llm
async def test_multistep_repair_and_reasoning():
    a,e,l=await execute(['bad','<think>private thought</think>'+json.dumps(action('run',command='echo hello')),action('finish',summary='Done')])
    assert any(x.get('text')=='Done' for x in e)
    assert any('hello' in m.get('content','') for m in a.messages)
    assert 'private thought' not in json.dumps(a.snapshot())
async def test_repeat_guard():
    a,e,l=await execute([action('run',command='false')]*5)
    assert any('Repeated action' in x.get('text','') for x in e)
async def test_mid_task():
    holder={}
    async def call(t,a):holder['agent'].inbox.append('change direction');return {'exit_code':0}
    llm=FakeLLM([action('run',command='pwd'),action('finish',summary='ok')])
    async def emit(e):pass
    a=Agent(llm,call,emit);holder['agent']=a;await a.submit('task');await a.active
    assert any('Mid-task message' in m.get('content','') for m in llm.seen[-1])
async def test_stop_aborts_generation():
    class Slow:
        model='slow'
        async def chat(self,m):await asyncio.sleep(60)
    async def noop(*a):return {}
    a=Agent(Slow(),noop,noop);await a.submit('task');await asyncio.sleep(.01);await a.stop();assert a.status=='idle' and a.active.done()
async def test_compact_restore_and_repair_limit():
    a,e,l=await execute(['bad']*4);assert any(x['type']=='error' for x in e)
    a.messages=[{'role':'user','content':'latest task'}]+[{'role':'user','content':'x'*5000} for _ in range(30)];a.compact()
    assert len(json.dumps(a.messages))<12000 and a.summary
    b=Agent(l,a.call,a.emit);b.restore(a.snapshot());assert b.summary==a.summary

def test_schema_strict():
    for msg in [{'content':'{"tool":"run","args":{"command":"ls","timeout_s":"5"}}'}, {'tool_calls':[{'function':{'name':'run','arguments':{'command':'ls'}}}]*2}]:
        with pytest.raises(ValueError):parse_message(msg)
    assert strip_reasoning('<think>secret</think>ok')=='ok'

def test_auth_health_and_rate_limit():
    h=Hub(FakeLLM([]),control_token='control',runner_token='runner')
    with TestClient(create_app(h)) as c:
        assert c.get('/health').json()=={'ok':True};assert c.get('/state').status_code==401
        with c.websocket_connect('/control') as ws:
            ws.send_json({'type':'auth','token':'wrong'})
            from starlette.websockets import WebSocketDisconnect
            with pytest.raises(WebSocketDisconnect):ws.receive_json()
        with c.websocket_connect('/control') as ws:
            ws.send_json({'type':'auth','token':'control'});assert ws.receive_json()['type']=='welcome'
            ws.send_json({'type':'ping'});assert ws.receive_json()['type']=='pong'
            ws.send_text('x'*1048577)
            with pytest.raises(WebSocketDisconnect):ws.receive_json()
