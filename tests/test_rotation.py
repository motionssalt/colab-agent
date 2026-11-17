import asyncio,json,os,pathlib,shutil,subprocess,sys
sys.path.insert(0,str(pathlib.Path(__file__).parent))
from e2e_check import start_server,free_port
from brain.server import Hub
from runner.worker import Worker

def git(cwd,*args):return subprocess.run(['git',*args],cwd=cwd,check=True,capture_output=True).stdout

async def test_saved_conversation_and_workspace_across_runner_replacement(tmp_path,monkeypatch):
    home=tmp_path/'home';home.mkdir();work=home/'work';remote=tmp_path/'remote.git'
    git(tmp_path,'init','--bare',str(remote));monkeypatch.setenv('HOME',str(home))
    def clone():
        git(home,'clone',str(remote),str(work));git(work,'config','user.name','test');git(work,'config','user.email','test@example.invalid')
    clone();git(work,'checkout','-b','workspace');(work/'README').write_text('test');git(work,'add','.');git(work,'commit','-m','init');git(work,'push','-u','origin','workspace')
    waiting=asyncio.Event();allow=asyncio.Event();events=[]
    class Model:
        model='rotation-stub'
        step=0
        async def chat(self,messages):
            self.step+=1
            if self.step==1:a={'tool':'run','args':{'command':'echo persisted-proof > proof.txt','timeout_s':10}}
            elif self.step==2:
                waiting.set();await allow.wait();a={'tool':'run','args':{'command':'cat proof.txt','timeout_s':10}}
            else:
                assert any('persisted-proof' in m.get('content','') for m in messages)
                a={'tool':'finish','args':{'summary':'rotation finished'}}
            return {'content':json.dumps(a)}
    h=Hub(Model());server,server_task=await start_server(h,free_port());port=server.config.port
    workers=[]
    async def connect_worker():
        w=Worker(f'http://127.0.0.1:{port}',h.runner_token,work);t=asyncio.create_task(w.serve());workers.append(t)
        for _ in range(100):
            if h.runner:return
            await asyncio.sleep(.05)
        raise AssertionError('worker did not connect')
    async def dispatch():
        workers[0].cancel();await asyncio.gather(workers[0],return_exceptions=True)
        for _ in range(100):
            if not h.runner:break
            await asyncio.sleep(.01)
        shutil.rmtree(work);clone();git(work,'checkout','workspace')
        await connect_worker();allow.set()
    h.dispatch=dispatch
    original=h.broadcast
    async def emit(event):events.append(event);await original(event)
    h.agent.emit=emit
    try:
        await connect_worker();await h.agent.submit('Write proof, then read it after rotation')
        await asyncio.wait_for(waiting.wait(),10)
        await asyncio.wait_for(h.rotate(),20)
        await asyncio.wait_for(h.agent.active,20)
        assert (work/'proof.txt').read_text().strip()=='persisted-proof'
        saved=json.loads((work/'state/session.json').read_text())
        assert saved['version']==1 and saved['current_task'].startswith('Write proof')
        assert h.runner_token not in json.dumps(saved) and h.control_token not in json.dumps(saved)
        assert any(e.get('text')=='rotation finished' for e in events)
        h.agent.restore(saved);assert h.agent.current_task==saved['current_task']
    finally:
        h.agent.save=None
        for t in workers:t.cancel()
        await asyncio.gather(*workers,return_exceptions=True);server.should_exit=True;await server_task
