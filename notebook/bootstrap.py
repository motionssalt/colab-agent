"""Thin notebook support. All secret-bearing operations stay in this process."""
import asyncio,base64,getpass,json,os,pathlib,re,secrets,shutil,socket,subprocess,threading,time,urllib.parse
import httpx
from notebook.github_api import GitHub,SetupError
class Session:
    def __init__(self,github):self.github=github;self.processes=[];self.server=None;self.thread=None;self._stopping=False;self.url=None
    async def dispatch(self):
        await asyncio.to_thread(self.github.dispatch)
    def shutdown(self):
        if self._stopping:return
        self._stopping=True
        try:self.github.cancel_runners()
        finally:
            if self.server:self.server.should_exit=True
            for p in reversed(self.processes):
                if p.poll() is None:p.terminate()
            for p in self.processes:
                try:p.wait(timeout=10)
                except subprocess.TimeoutExpired:p.kill()
            self.github.close()
        print('All off: runner cancellation requested; brain and tunnel stopped.')

def command(args,**kwargs):
    try:subprocess.run(args,check=True,**kwargs)
    except subprocess.CalledProcessError:raise SetupError('Setup command failed: '+str(args[0])+'. Retry the setup cell.') from None

def check_gpu():
    if not shutil.which('nvidia-smi'):raise SetupError('No GPU runtime: in Colab choose Runtime → Change runtime type → T4 GPU, then reconnect.')
    p=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total','--format=csv,noheader'],capture_output=True,text=True)
    if p.returncode or not p.stdout.strip():raise SetupError('GPU is unavailable. Switch runtime to T4 and retry; free GPU quota may be exhausted.')
    print('GPU detected:',p.stdout.strip())

def ollama_start(session,model,num_ctx):
    if not shutil.which('zstd'):command(['apt-get','update','-qq'],stdout=subprocess.DEVNULL);command(['apt-get','install','-y','zstd'],stdout=subprocess.DEVNULL)
    if not shutil.which('ollama'):
        print('Installing Ollama…')
        response=httpx.get('https://ollama.com/install.sh',follow_redirects=True,timeout=60);response.raise_for_status()
        # Official installer code is not a credential. Feed it via stdin, not a notebook log.
        command(['sh'],input=response.text.encode(),stdout=subprocess.DEVNULL)
    env=os.environ.copy();env.update(OLLAMA_HOST='127.0.0.1:11434',OLLAMA_KEEP_ALIVE='-1',OLLAMA_FLASH_ATTENTION='1',OLLAMA_KV_CACHE_TYPE='q8_0',OLLAMA_NUM_PARALLEL='1',OLLAMA_CONTEXT_LENGTH=str(num_ctx))
    try:ready=httpx.get('http://127.0.0.1:11434/api/tags',timeout=2).status_code==200
    except httpx.HTTPError:ready=False
    if not ready:
        p=subprocess.Popen(['ollama','serve'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);session.processes.append(p)
        for _ in range(90):
            try:
                if httpx.get('http://127.0.0.1:11434/api/tags',timeout=2).status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(1)
        else:raise SetupError('Ollama did not start. Restart the runtime and try again.')
    print('Pulling model '+model+' (the first pull can take several minutes)…')
    # Only public model download progress is displayed.
    command(['ollama','pull',model],env=env)

def start_tunnel(session,port):
    binary=shutil.which('cloudflared')
    if not binary:
        path=pathlib.Path('/tmp/colab-agent-cloudflared')
        response=httpx.get('https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64',follow_redirects=True,timeout=120);response.raise_for_status();path.write_bytes(response.content);path.chmod(0o755);binary=str(path)
    p=subprocess.Popen([binary,'tunnel','--url',f'http://127.0.0.1:{port}','--no-autoupdate'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1);session.processes.append(p)
    found=threading.Event();box={}
    def read():
        for line in p.stdout:
            m=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',line)
            if m and not found.is_set():box['url']=m[0];found.set()
    threading.Thread(target=read,daemon=True).start()
    if not found.wait(90):raise SetupError('Cloudflare quick tunnel did not start. Retry setup; no account or tunnel token is needed.')
    url=box['url']
    for _ in range(40):
        try:
            if httpx.get(url+'/health',timeout=10).status_code==200:return url
        except httpx.HTTPError:pass
        time.sleep(2)
    raise SetupError('Tunnel was created but is not reachable yet. Retry the setup cell.')

def setup(repo_name='colab-agent',site_url='https://colab-agent.pages.dev',model='qwen3:14b',num_ctx=16384,thinking=False,max_steps=60,resume='ask',pat=None):
    check_gpu()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',repo_name):raise SetupError('Use a simple GitHub repository name without slashes.')
    if not model.strip() or model.startswith('-'):raise SetupError('Enter a valid Ollama model name.')
    gh=GitHub(pat or getpass.getpass('GitHub PAT (classic or fine-grained): '),repo_name);session=Session(gh)
    try:
        owner=gh.verify();print('GitHub account verified:',owner)
        print('Preparing public repository (conversation state will be public)…');gh.ensure_repo();gh.check_access();gh.cancel_runners()
        saved=gh.load_state()
        if saved and resume=='ask':resume=input('Saved conversation found. Resume it? [y/N] ').strip().lower()=='y'
        from brain.server import Hub,create_app
        from brain.llm import Ollama
        import uvicorn
        ollama_start(session,model,num_ctx)
        hub=Hub(Ollama(model,num_ctx=num_ctx,thinking=thinking),dispatch=session.dispatch);hub.agent.max_steps=max_steps;hub.agent.num_ctx=num_ctx
        if saved and resume is True:
            hub.agent.restore(saved);print('Conversation restored. Send “continue” after the runner connects.')
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        session.server=uvicorn.Server(uvicorn.Config(create_app(hub),host='127.0.0.1',port=port,log_level='critical',access_log=False))
        session.thread=threading.Thread(target=session.server.run,daemon=True);session.thread.start()
        for _ in range(100):
            if session.server.started:break
            time.sleep(.1)
        else:raise SetupError('Brain server did not start. Restart setup.')
        print('Starting private session tunnel…');url=start_tunnel(session,port);session.url=url
        gh.secret('AGENT_TUNNEL_URL',url);gh.secret('AGENT_RUNNER_TOKEN',hub.runner_token);gh.dispatch()
        conn=base64.urlsafe_b64encode(json.dumps({'url':url,'token':hub.control_token}).encode()).decode().rstrip('=')
        print('Runner requested. Allow about a minute or longer for a cold start.')
        print('PRIVATE connection string (do not share):\n'+conn)
        link=site_url.rstrip('/')+'/#'+conn
        from IPython.display import display,HTML
        import html
        display(HTML('<a target="_blank" rel="noopener noreferrer" href="'+html.escape(link,quote=True)+'">Open your control panel</a>'))
        print('Keep the heartbeat cell running. It does not bypass Colab quota or session limits.')
        return session
    except BaseException as exc:
        try:session.shutdown()
        except Exception:pass
        # Do not let notebook tracebacks expose locals, headers, or the PAT.
        message=str(exc) if isinstance(exc,SetupError) else 'Setup failed ('+type(exc).__name__+'). Retry; if repeated, check the Actions page and docs/FIRST_RUN.md.'
        raise SetupError(message) from None

def heartbeat(session):
    try:
        while not session._stopping:
            if not session.thread or not session.thread.is_alive():print('Brain stopped. Rerun setup.');return
            print(time.strftime('%H:%M:%S',time.gmtime())+' UTC — brain running; leave this cell active.');time.sleep(60)
    except KeyboardInterrupt:print('Heartbeat stopped. To stop everything, run the All off cell.')
