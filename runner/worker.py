"""Silent outbound worker. Terminal bytes go only over the authenticated socket."""
import asyncio,base64,codecs,json,os,pathlib,pty,secrets,signal,subprocess,time,uuid
import websockets

def bounded(text,limit=12000):
    if len(text)<=limit:return text
    half=(limit-80)//2
    return text[:half]+"\n… [output truncated; head and tail retained] …\n"+text[-half:]

class Terminal:
    def __init__(self,cwd,on_output=lambda s:None):
        self.cwd=pathlib.Path(cwd).resolve();self.cwd.mkdir(parents=True,exist_ok=True)
        self.name='agent-'+uuid.uuid4().hex[:12];self.on_output=on_output
        self.history='';self.lock=asyncio.Lock();self.decoder=codecs.getincrementaldecoder('utf8')('replace')
        env={k:v for k,v in os.environ.items() if not k.startswith(('AGENT_','CLOUDFLARE_')) and k not in ('GITHUB_PAT','GITHUB_TOKEN')};env['TERM']='xterm-256color';env['PS1']='agent$ '
        subprocess.run(['tmux','-L',self.name,'new-session','-d','-s','agent','-x','100','-y','30','-c',str(self.cwd),'bash --noprofile --norc'],check=True,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        # Stream the pane PTY directly; detached tmux attach clients may suppress
        # redraws in CI. pipe-pane preserves every byte independent of viewers.
        self.fifo=pathlib.Path('/tmp')/(self.name+'.fifo');os.mkfifo(self.fifo,0o600)
        self.master=os.open(self.fifo,os.O_RDWR|os.O_NONBLOCK)
        self.tmux('pipe-pane','-O','-t','agent','cat > '+str(self.fifo))
        asyncio.get_running_loop().add_reader(self.master,self._read)
    def _read(self):
        try:data=os.read(self.master,65536)
        except (BlockingIOError,OSError):return
        if data:
            text=self.decoder.decode(data);self.history=(self.history+text)[-200000:];self.on_output(text)
    def tmux(self,*args):
        return subprocess.run(['tmux','-L',self.name,*args],capture_output=True,check=True).stdout
    def send_keys(self,keys):
        aliases={'CTRL_C':'\x03','ENTER':'\r','UP':'\x1b[A','DOWN':'\x1b[B','LEFT':'\x1b[D','RIGHT':'\x1b[C','TAB':'\t','ESC':'\x1b'}
        data=aliases.get(keys,keys).encode()
        # tmux literal key delivery avoids a partial nonblocking PTY write.
        if keys=='CTRL_C':self.tmux('send-keys','-t','agent','C-c')
        else:
            for i in range(0,len(data),2048):self.tmux('send-keys','-t','agent','-l','--',data[i:i+2048].decode('utf8','replace'))
    def interrupt(self):self.tmux('send-keys','-t','agent','C-c')
    def read_screen(self):return self.tmux('capture-pane','-p','-t','agent','-S','-200').decode('utf8','replace')[-24000:]
    async def run(self,command,timeout_s=120):
        import shlex
        async with self.lock:
            marker=pathlib.Path('/tmp')/('agent-result-'+secrets.token_hex(16));start=len(self.history)
            # eval runs in the persistent interactive shell: cd/export persist between calls.
            text='eval '+shlex.quote(command)+'; __agent_ec=$?; printf "%s" "$__agent_ec" > '+str(marker)
            self.send_keys(text+'\r');deadline=time.monotonic()+timeout_s;timed_out=False
            try:
                while not marker.exists():
                    if time.monotonic()>deadline:
                        timed_out=True;self.interrupt();await asyncio.sleep(.25);break
                    await asyncio.sleep(.05)
                await asyncio.sleep(.1)
                code=124 if timed_out else int(marker.read_text())
                # capture-pane is stable even when the raw ANSI history rolls over.
                output=self.read_screen()
                return {'exit_code':code,'timed_out':timed_out,'output':bounded(output)}
            except asyncio.CancelledError:
                self.interrupt();raise
            finally:marker.unlink(missing_ok=True)
    async def write_file(self,path,content):
        import shlex
        # Relative paths resolve against the shell's actual current directory.
        cwd=self.tmux('display-message','-p','-t','agent','#{pane_current_path}').decode().strip()
        p=pathlib.Path(path).expanduser()
        if not p.is_absolute():p=pathlib.Path(cwd)/p
        p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
        self.send_keys('printf "%s\\n" '+shlex.quote('# wrote '+str(p)+' ('+str(len(content.encode()))+' bytes)')+'\r')
        return {'path':str(p),'bytes':len(content.encode())}
    def close(self):
        asyncio.get_running_loop().remove_reader(self.master)
        try:self.tmux('kill-server')
        except Exception:pass
        os.close(self.master);self.fifo.unlink(missing_ok=True)

class Worker:
    def __init__(self,url,token,cwd,offline_limit=600,lifetime=340*60):
        self.url=url.rstrip('/').replace('https://','wss://').replace('http://','ws://')+'/runner'
        self.token=token;self.queue=asyncio.Queue(maxsize=1024);self.uid=uuid.uuid4().hex;self.seq=0
        self.terminal=Terminal(cwd,self.output);self.offline_limit=offline_limit;self.lifetime=lifetime
        self.started=time.monotonic();self.active=None;self.takeover=False;self.socket=None
    def output(self,text):
        self.seq+=1;event={'type':'terminal','data':text,'seq':self.seq,'worker_id':self.uid}
        if self.queue.full():self.queue.get_nowait()
        self.queue.put_nowait(event)
    async def execute(self,ws,msg):
        try:
            tool=msg['tool'];a=msg.get('args',{})
            if self.takeover and tool!='read_screen':raise ValueError('Terminal is under user control')
            if tool=='run':result=await self.terminal.run(str(a['command']),max(1,min(1800,float(a.get('timeout_s',120)))))
            elif tool=='send_keys':self.terminal.send_keys(a['keys']);result={'sent':True}
            elif tool=='read_screen':result={'output':self.terminal.read_screen()}
            elif tool=='write_file':result=await self.terminal.write_file(a['path'],a['content'])
            else:raise ValueError('Unknown worker tool')
            await ws.send(json.dumps({'type':'result','id':msg['id'],'result':result}))
        except asyncio.CancelledError:
            self.terminal.interrupt()
            try:await ws.send(json.dumps({'type':'result','id':msg['id'],'result':{'error':'Interrupted'}}))
            except Exception:pass
        except Exception as exc:
            await ws.send(json.dumps({'type':'result','id':msg.get('id'),'result':{'error':str(exc)[:300]}}))
    async def sender(self,ws):
        while True:await ws.send(json.dumps(await self.queue.get()))
    async def heartbeat(self,ws):
        while True:
            left=self.lifetime-(time.monotonic()-self.started)
            await ws.send(json.dumps({'type':'worker_status','remaining_s':int(left)}))
            await asyncio.sleep(15)
    async def serve(self):
        last_ok=time.monotonic();delay=1
        try:
            while time.monotonic()-last_ok<self.offline_limit and time.monotonic()-self.started<self.lifetime:
                try:
                    async with websockets.connect(self.url,additional_headers={'Authorization':'Bearer '+self.token},max_size=1048576,ping_interval=20,open_timeout=20) as ws:
                        self.socket=ws;last_ok=time.monotonic();delay=1
                        await ws.send(json.dumps({'type':'hello','worker_id':self.uid,'screen':self.terminal.read_screen()}))
                        sender=asyncio.create_task(self.sender(ws));heartbeat=asyncio.create_task(self.heartbeat(ws))
                        try:
                            async for raw in ws:
                                last_ok=time.monotonic();msg=json.loads(raw);t=msg.get('type')
                                if t=='call':
                                    if self.active and not self.active.done():
                                        await ws.send(json.dumps({'type':'result','id':msg['id'],'result':{'error':'Worker busy'}}))
                                    else:self.active=asyncio.create_task(self.execute(ws,msg))
                                elif t=='interrupt':
                                    self.terminal.interrupt()
                                    if self.active:self.active.cancel()
                                elif t=='takeover':
                                    enabled=bool(msg.get('enabled'))
                                    if enabled and not self.takeover:
                                        self.terminal.interrupt()
                                        if self.active:self.active.cancel()
                                    self.takeover=enabled
                                elif t=='input' and self.takeover:self.terminal.send_keys(msg['data'])
                                elif t=='resize':
                                    self.terminal.tmux('resize-window','-t','agent','-x',str(max(20,min(240,int(msg['cols'])))),'-y',str(max(5,min(100,int(msg['rows'])))))
                        finally:
                            sender.cancel();heartbeat.cancel();await asyncio.gather(sender,heartbeat,return_exceptions=True)
                            if self.active:self.active.cancel();await asyncio.gather(self.active,return_exceptions=True)
                except (OSError,websockets.WebSocketException,ValueError):
                    await asyncio.sleep(delay);delay=min(30,delay*2)
        finally:self.terminal.close()

def main():
    # Credentials read from environment only. No stdout, exception URLs or auth headers.
    try:asyncio.run(Worker(os.environ['AGENT_TUNNEL_URL'],os.environ['AGENT_RUNNER_TOKEN'],os.environ.get('AGENT_WORKDIR',os.path.expanduser('~/work')),float(os.getenv('AGENT_OFFLINE_LIMIT','600'))).serve())
    except (Exception,KeyboardInterrupt):raise SystemExit(1)
if __name__=='__main__':main()
