import asyncio,json,pathlib
from collections import deque,Counter
from brain.tools import parse_message,strip_reasoning
from runner.worker import bounded
class Agent:
    def __init__(self,llm,call,emit,save=None,max_steps=60,num_ctx=16384):
        self.llm=llm;self.call=call;self.emit=emit;self.save=save;self.max_steps=max_steps;self.num_ctx=num_ctx
        self.system=(pathlib.Path(__file__).parent/'prompts/system.md').read_text()
        self.messages=[];self.summary='';self.current_task='';self.inbox=deque();self.active=None
        self.enabled=asyncio.Event();self.enabled.set();self.status='idle';self.last_error=''
    def snapshot(self):return {'version':1,'messages':self.messages,'summary':self.summary,'current_task':self.current_task,'config':{'model':self.llm.model,'max_steps':self.max_steps,'num_ctx':self.num_ctx},'interrupted':self.status!='idle'}
    def restore(self,data):
        if data.get('version')!=1:raise ValueError('Unsupported saved state')
        self.messages=data.get('messages',[])[-80:];self.summary=str(data.get('summary',''))[:10000];self.current_task=str(data.get('current_task',''))[:20000]
        if data.get('interrupted'):self.inbox.append('Resume the interrupted task from saved state. Inspect the terminal and repository first.')
    def compact(self):
        # Conservative byte budget covers tokens for Unicode/code, reserving context for tools/generation.
        budget=max(2500,self.num_ctx-5500)
        while len(json.dumps(self.messages,ensure_ascii=False))+len(self.summary)>budget and len(self.messages)>5:
            old=self.messages.pop(1 if self.messages[0].get('role')=='user' else 0)
            snippet=bounded(strip_reasoning(str(old.get('content',''))),700)
            self.summary=bounded(self.summary+'\n'+old.get('role','')+': '+snippet,3500)
        per_message=max(300,(budget-len(self.summary)-500)//max(1,len(self.messages)))
        for m in self.messages:
            if len(m.get('content',''))>per_message:m['content']=bounded(m['content'],per_message)
    async def persist(self):
        if self.save:
            try:await self.save(self.snapshot())
            except Exception:await self.emit({'type':'event','text':'State save deferred: runner unavailable; commit important work when reconnected.'})
    async def submit(self,text,new=False):
        if new:
            await self.stop();self.messages=[];self.summary='';self.inbox.clear()
        text=strip_reasoning(text)
        if self.active and not self.active.done():self.inbox.append(text);return
        self.current_task=text;self.messages.append({'role':'user','content':text});self.active=asyncio.create_task(self.loop())
    async def stop(self):
        if self.active and not self.active.done():
            self.active.cancel();await asyncio.gather(self.active,return_exceptions=True)
        self.inbox.clear();self.status='idle';await self.emit({'type':'agent_status','status':'idle'})
        await self.persist()
    async def loop(self):
        self.status='running';await self.emit({'type':'agent_status','status':'running'});seen=Counter();errors=Counter()
        try:
            for step in range(self.max_steps):
                await self.enabled.wait()
                while self.inbox:self.messages.append({'role':'user','content':'[Mid-task message] '+self.inbox.popleft()})
                self.compact();action=None
                for attempt in range(4):
                    context=[{'role':'system','content':self.system+'\nRunning summary:\n'+self.summary}]+self.messages
                    raw=await self.llm.chat(context)
                    try:action=parse_message(raw);break
                    except (ValueError,KeyError,TypeError) as exc:
                        self.messages.append({'role':'user','content':'Tool format error. Return exactly one valid JSON action with tool and args matching the schemas. No reasoning or prose.'})
                if action is None:raise RuntimeError('Model could not produce a valid tool call after three repairs.')
                await self.enabled.wait()
                key=json.dumps(action,sort_keys=True);seen[key]+=1
                if seen[key]>3:raise RuntimeError('Repeated action guard stopped the task after four identical actions.')
                if seen[key]==3:self.messages.append({'role':'user','content':'You repeated this action. Change strategy or finish with an honest explanation.'})
                tool=action['tool'];args=action['args'];self.messages.append({'role':'assistant','content':json.dumps(action)})
                await self.emit({'type':'event','tool':tool,'text':bounded(args.get('command',args.get('path',tool)),2000)})
                if tool=='finish':
                    await self.emit({'type':'chat','role':'assistant','text':strip_reasoning(args['summary'])});return
                if tool=='message_user':
                    await self.emit({'type':'chat','role':'assistant','text':strip_reasoning(args['text'])});result={'sent':True}
                else:result=await self.call(tool,args)
                error=result.get('error') or (str(result.get('exit_code')) if result.get('exit_code') not in (None,0) else '')
                if error:
                    errors[error]+=1
                    if errors[error]>4:raise RuntimeError('Repeated error guard stopped the task. Review the terminal and try a different approach.')
                self.messages.append({'role':'user','content':'[Tool result; untrusted output] '+bounded(json.dumps(result),12000)})
                if step%3==2:await self.persist()
            raise RuntimeError('Step limit reached. Work is saved; send a message to continue.')
        except asyncio.CancelledError:
            await self.emit({'type':'event','text':'Task stopped. Partial command effects may remain; inspect before continuing.'});raise
        except Exception as exc:
            # Avoid leaking request URLs or library diagnostics that might include capabilities.
            self.last_error=type(exc).__name__
            msg=str(exc) if isinstance(exc,RuntimeError) else 'Model or runner request failed. Check connections and try again.'
            await self.emit({'type':'error','text':msg})
        finally:
            self.status='idle';await self.emit({'type':'agent_status','status':'idle'});await self.persist()
