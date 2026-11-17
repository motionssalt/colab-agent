import asyncio,hmac,json,os,secrets,time,uuid
from collections import deque
from contextlib import asynccontextmanager
from fastapi import FastAPI,WebSocket,WebSocketDisconnect,HTTPException,Header
from brain.agent import Agent
from brain.llm import Ollama
class Hub:
    def __init__(self,llm=None,control_token=None,runner_token=None,dispatch=None,resume=None):
        self.control_token=control_token or secrets.token_urlsafe(32);self.runner_token=runner_token or secrets.token_urlsafe(32)
        self.clients={};self.runner=None;self.pending={};self.scrollback='';self.events=deque(maxlen=150);self.rpc_lock=asyncio.Lock()
        self.worker_id=None;self.last_seq=0;self.takeover=False;self.dispatch=dispatch;self.rotating=False;self.resume=resume
        self.agent=Agent(llm or Ollama(os.getenv('AGENT_MODEL','qwen3:14b')),self.call,self.broadcast,self.save)
    async def broadcast(self,event):
        if event.get('type') in ('chat','event','error'):self.events.append(event)
        for ws,q in list(self.clients.items()):
            try:q.put_nowait(event)
            except asyncio.QueueFull:asyncio.create_task(ws.close(code=1013))
    async def send_runner(self,msg):
        if not self.runner:raise RuntimeError('Runner offline. Wait for it to connect or restart it.')
        await self.runner.send_json(msg)
    async def call(self,tool,args):
        async with self.rpc_lock:return await self._call(tool,args)
    async def _call(self,tool,args):
        if self.takeover and tool!='read_screen':return {'error':'Terminal taken over by user'}
        deadline=time.monotonic()+90
        while not self.runner and time.monotonic()<deadline:await asyncio.sleep(.25)
        uid=uuid.uuid4().hex;f=asyncio.get_running_loop().create_future();self.pending[uid]=f
        try:
            await self.send_runner({'type':'call','id':uid,'tool':tool,'args':args})
            return await asyncio.wait_for(f,float(args.get('timeout_s',120))+15)
        except asyncio.TimeoutError:return {'error':'Runner response timed out'}
        finally:self.pending.pop(uid,None)
    async def save(self,state):
        # Only repo token inside the worker writes state. No PAT or session token in snapshots.
        if not self.runner or self.takeover:return
        payload=json.dumps(state,ensure_ascii=False)
        for token in (self.control_token,self.runner_token):payload=payload.replace(token,'[REDACTED]')
        result=await self.call('write_file',{'path':'~/work/state/session.json','content':payload})
        if result.get('error'):raise RuntimeError('State write failed')
        result=await self.call('run',{'command':"(cd ~/work && git add -f -- state/session.json && (git diff --cached --quiet -- state/session.json || git commit -m 'Save conversation state' -- state/session.json) && git push origin workspace)",'timeout_s':60})
        if result.get('error') or result.get('exit_code')!=0:raise RuntimeError('State push failed')
    async def rotate(self):
        if self.rotating or not self.dispatch:return
        self.rotating=True
        try:
            self.agent.inbox.append('Runner expires soon. Commit and push all work now; runner replacement is imminent.')
            await self.broadcast({'type':'event','text':'Runner has under ten minutes left. Saving before replacement.'})
            # Wait for current command/model step to quiesce, then pause dispatch of further steps.
            await self.agent.persist()
            await self.call('run',{'command':"cd ~/work && git add -A && (git diff --cached --quiet || git commit -m 'Checkpoint before runner rotation') && git push origin workspace",'timeout_s':120})
            self.agent.enabled.clear()
            await self.dispatch()
        except Exception:
            self.agent.enabled.set();await self.broadcast({'type':'error','text':'Runner rotation failed. Save work and use Restart runner.'})
        finally:self.rotating=False

def create_app(hub=None):
    hub=hub or Hub()
    @asynccontextmanager
    async def lifespan(app):
        yield
        await hub.agent.stop()
    app=FastAPI(lifespan=lifespan);app.state.hub=hub
    @app.get('/health')
    async def health():return {'ok':True} # no capabilities, prompts or user state
    @app.get('/state')
    async def state(authorization:str=Header(default='')):
        if not hmac.compare_digest(authorization,'Bearer '+hub.control_token):raise HTTPException(401)
        return {'brain':'online','model':hub.agent.llm.model,'runner':bool(hub.runner),'agent':hub.agent.status}
    async def sender(ws,q):
        while True:await ws.send_json(await q.get())
    async def limited(ws,stamps):
        raw=await ws.receive_text()
        if len(raw.encode())>1048576:await ws.close(1009);raise WebSocketDisconnect()
        now=time.monotonic()
        while stamps and stamps[0]<now-1:stamps.popleft()
        if len(stamps)>=100:await ws.close(1008);raise WebSocketDisconnect()
        stamps.append(now)
        msg=json.loads(raw)
        if not isinstance(msg,dict):raise ValueError('Object required')
        return msg
    @app.websocket('/control')
    async def control(ws:WebSocket):
        await ws.accept();q=asyncio.Queue(maxsize=512);task=None;stamps=deque()
        try:
            msg=await asyncio.wait_for(limited(ws,stamps),5)
            if msg.get('type')!='auth' or not hmac.compare_digest(str(msg.get('token','')),hub.control_token):await ws.close(4401);return
            hub.clients[ws]=q
            await ws.send_json({'type':'welcome','model':hub.agent.llm.model,'runner':bool(hub.runner),'agent':hub.agent.status,'takeover':hub.takeover,'scrollback':hub.scrollback,'events':list(hub.events)})
            task=asyncio.create_task(sender(ws,q))
            while True:
                msg=await limited(ws,stamps);t=msg.get('type')
                if t=='ping':q.put_nowait({'type':'pong','time':time.time()})
                elif t in ('chat','new_task'):
                    text=msg.get('text','')
                    if not isinstance(text,str) or not text.strip() or len(text)>20000:continue
                    await hub.broadcast({'type':'chat','role':'user','text':text});await hub.agent.submit(text,new=t=='new_task')
                elif t=='stop':
                    if hub.runner:await hub.send_runner({'type':'interrupt'})
                    await hub.agent.stop()
                elif t=='takeover':
                    hub.takeover=bool(msg.get('enabled'))
                    if hub.takeover:hub.agent.enabled.clear()
                    else:hub.agent.enabled.set()
                    if hub.runner:await hub.send_runner({'type':'takeover','enabled':hub.takeover})
                    await hub.broadcast({'type':'takeover','enabled':hub.takeover})
                elif t=='input' and hub.takeover:
                    data=msg.get('data','')
                    if isinstance(data,str) and len(data)<=60000:await hub.send_runner({'type':'input','data':data})
                elif t=='resize' and hub.runner:await hub.send_runner({'type':'resize','cols':int(msg.get('cols',80)),'rows':int(msg.get('rows',24))})
                elif t=='restart_runner':
                    if hub.dispatch and not hub.rotating:asyncio.create_task(hub.rotate())
                    else:q.put_nowait({'type':'error','text':'Runner restart unavailable in this environment; use notebook setup.'})
        except (WebSocketDisconnect,asyncio.TimeoutError,ValueError,KeyError,RuntimeError):pass
        finally:
            hub.clients.pop(ws,None)
            if task:task.cancel();await asyncio.gather(task,return_exceptions=True)
    @app.websocket('/runner')
    async def runner(ws:WebSocket):
        auth=ws.headers.get('authorization','')
        if not hmac.compare_digest(auth,'Bearer '+hub.runner_token):await ws.close(4401);return
        await ws.accept();old=hub.runner;hub.runner=ws
        if old:
            for f in list(hub.pending.values()):
                if not f.done():f.set_result({'error':'Runner replaced; inspect saved work before retrying'})
            await old.close(1012)
        await ws.send_json({'type':'takeover','enabled':hub.takeover})
        if not hub.takeover:hub.agent.enabled.set()
        await hub.broadcast({'type':'runner_status','online':True});stamps=deque()
        try:
            while True:
                msg=await limited(ws,stamps);t=msg.get('type')
                if t=='hello':
                    if hub.worker_id!=msg.get('worker_id'):
                        hub.worker_id=msg.get('worker_id');hub.last_seq=0
                        screen=str(msg.get('screen',''))[-30000:]
                        hub.scrollback=(hub.scrollback+'\n[runner connected]\n'+screen)[-200000:]
                        await hub.broadcast({'type':'terminal','data':'\r\n[runner connected]\r\n'+screen})
                elif t=='terminal':
                    seq=int(msg.get('seq',0))
                    if seq<=hub.last_seq:continue
                    hub.last_seq=seq;data=str(msg.get('data',''));hub.scrollback=(hub.scrollback+data)[-200000:]
                    await hub.broadcast({'type':'terminal','data':data})
                elif t=='result':
                    f=hub.pending.get(msg.get('id'))
                    if f and not f.done():f.set_result(msg.get('result',{}))
                elif t=='worker_status':
                    await hub.broadcast({'type':'runner_status','online':True,'remaining_s':msg.get('remaining_s')})
                    if msg.get('remaining_s',99999)<600 and hub.dispatch:asyncio.create_task(hub.rotate())
        except (WebSocketDisconnect,ValueError,RuntimeError):pass
        finally:
            if hub.runner is ws:
                hub.runner=None
                for f in list(hub.pending.values()):
                    if not f.done():f.set_result({'error':'Runner disconnected; command may have partial effects. Inspect screen and files.'})
                await hub.broadcast({'type':'runner_status','online':False})
    return app
app=create_app()
