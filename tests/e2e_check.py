"""Actual WebSockets + FastAPI + worker + tmux; scripted model only."""
import asyncio,json,os,pathlib,re,shutil,socket,sys,tempfile
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import httpx,uvicorn,websockets
from brain.server import Hub,create_app
from runner.worker import Worker
class Scripted:
    model='scripted-e2e'
    def __init__(self):self.step=0;self.results=[]
    async def chat(self,messages):
        self.results=[m['content'] for m in messages if m.get('content','').startswith('[Tool result')]
        self.step+=1
        if self.step==1:action={'tool':'run','args':{'command':'echo hello','timeout_s':10}}
        elif self.step==2:
            assert any('hello' in r for r in self.results)
            action={'tool':'run','args':{'command':'search python -n 1','timeout_s':45}}
        else:
            assert len(self.results)>=2
            action={'tool':'finish','args':{'summary':'e2e finished'}}
        return {'content':json.dumps(action)}
async def no_save(state):pass
async def start_server(hub,port):
    server=uvicorn.Server(uvicorn.Config(create_app(hub),host='127.0.0.1',port=port,log_level='critical',access_log=False,ws_max_size=1048576))
    task=asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:return server,task
        await asyncio.sleep(.05)
    raise RuntimeError('Local server startup failed')
def free_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
async def tunnel_url(port):
    process=await asyncio.create_subprocess_exec('cloudflared','tunnel','--url',f'http://127.0.0.1:{port}','--no-autoupdate',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT)
    try:
        async def read():
            while True:
                line=await process.stdout.readline()
                if not line:raise RuntimeError('Tunnel exited before startup')
                m=re.search(rb'https://[a-z0-9-]+\.trycloudflare\.com',line)
                if m:return m[0].decode()
        url=await asyncio.wait_for(read(),75)
        async def drain():
            while await process.stdout.readline():pass
        drain_task=asyncio.create_task(drain())
        return url,process,drain_task
    except BaseException:
        process.terminate();await process.wait();raise
async def run(tunnel=False,browser=False):
    llm=Scripted();hub=Hub(llm);hub.agent.save=no_save;port=free_port();server,st=await start_server(hub,port)
    base=f'http://127.0.0.1:{port}';proc=None;drain=None;worker_task=None
    tmp=tempfile.TemporaryDirectory();root=pathlib.Path(__file__).resolve().parents[1]
    bindir=pathlib.Path(tmp.name)/'bin';bindir.mkdir()
    helper=bindir/'search';helper.write_text('#!/bin/sh\nexec '+shutil.which('python')+' -m runner.helpers search "$@"\n');helper.chmod(0o755)
    os.environ['PATH']=str(bindir)+':'+os.environ['PATH'];os.environ['PYTHONPATH']=str(root)
    try:
        if tunnel:
            base,proc,drain=await tunnel_url(port)
            async with httpx.AsyncClient(timeout=15) as client:
                for _ in range(20):
                    try:
                        if (await client.get(base+'/health')).status_code==200:break
                    except httpx.HTTPError:pass
                    await asyncio.sleep(2)
                else:raise RuntimeError('Tunnel health check unavailable')
        w=Worker(base,hub.runner_token,tmp.name,offline_limit=30);worker_task=asyncio.create_task(w.serve())
        for _ in range(200):
            if hub.runner:break
            await asyncio.sleep(.1)
        assert hub.runner,'Worker did not connect'
        if browser:
            from playwright.async_api import async_playwright
            import functools,http.server,threading
            handler=functools.partial(http.server.SimpleHTTPRequestHandler,directory=str(root/'site'))
            httpd=http.server.ThreadingHTTPServer(('127.0.0.1',0),handler);thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
            import base64
            conn=base64.urlsafe_b64encode(json.dumps({'url':base,'token':hub.control_token}).encode()).decode().rstrip('=')
            try:
                async with async_playwright() as p:
                    browser_obj=await p.chromium.launch(headless=True)
                    page=await browser_obj.new_page(viewport={'width':390,'height':844})
                    await page.goto(f'http://127.0.0.1:{httpd.server_port}/#{conn}')
                    await page.wait_for_function("document.querySelector('#status').textContent.includes('Runner online')")
                    await page.fill('#task','run echo hello then search python and finish')
                    await page.click('#send')
                    await page.wait_for_function("document.querySelector('#chat').textContent.includes('e2e finished')",timeout=90000)
                    assert 'run echo hello' in await page.locator('#chat').inner_text()
                    assert 'hello' in await page.locator('#terminal').inner_text()
                    await page.click('#takeover');await page.wait_for_function("document.querySelector('#takeover').textContent.includes('Agent controls')")
                    await browser_obj.close()
                print('Mobile browser chat, live terminal and takeover passed')
            finally:httpd.shutdown()
        else:
            async with websockets.connect(base.replace('http','ws',1)+'/control',max_size=1048576) as ws:
                await ws.send(json.dumps({'type':'auth','token':hub.control_token}));assert json.loads(await ws.recv())['type']=='welcome'
                await ws.send(json.dumps({'type':'chat','text':'run echo hello and search python and finish'}));terminal='';finished=False
                async with asyncio.timeout(120):
                    while not finished:
                        event=json.loads(await ws.recv())
                        if event['type']=='terminal':terminal+=event['data']
                        if event.get('text')=='e2e finished':finished=True
                # tmux emits cursor-addressed screen diffs, not a plain text log.
                import pyte
                screen=pyte.HistoryScreen(120,40,history=2000);stream=pyte.Stream(screen);stream.feed(terminal)
                rendered='\n'.join(''.join(line[x].data for x in sorted(line)) for line in screen.history.top)+'\n'+'\n'.join(screen.display)
                # Cursor edits can split strings across raw frames; verify rendered screen too.
                observed=terminal+'\n'+rendered
                assert 'hello' in observed and ('search python' in observed or 'search python' in ''.join(rendered.splitlines())), repr(observed[-5000:])
                assert len(llm.results)>=2
                print(('Tunnel' if tunnel else 'Localhost')+' E2E passed: terminal commands, outputs to model, finish')
    finally:
        if worker_task:worker_task.cancel();await asyncio.gather(worker_task,return_exceptions=True)
        if proc:proc.terminate();await proc.wait()
        if drain:drain.cancel();await asyncio.gather(drain,return_exceptions=True)
        server.should_exit=True;await st;tmp.cleanup()
if __name__=='__main__':asyncio.run(run('--tunnel' in sys.argv,'--browser' in sys.argv))
