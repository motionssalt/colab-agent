import httpx
from brain.tools import TOOLS,strip_reasoning
class Ollama:
    def __init__(self,model='qwen3:14b',url='http://127.0.0.1:11434',num_ctx=16384,thinking=False):
        self.model=model;self.url=url;self.num_ctx=num_ctx;self.thinking=thinking;self.native=True
    async def chat(self,messages):
        payload={'model':self.model,'messages':messages,'stream':False,'keep_alive':-1,'options':{'num_ctx':self.num_ctx,'temperature':.2,'num_predict':2048}}
        if 'qwen3' in self.model or self.thinking:payload['think']=self.thinking
        if self.native:payload['tools']=TOOLS
        else:payload['format']='json'
        async with httpx.AsyncClient(timeout=240) as c:
            resp=await c.post(self.url+'/api/chat',json=payload)
            if resp.status_code in (400,422) and self.native:
                self.native=False;payload.pop('tools',None);payload['format']='json';resp=await c.post(self.url+'/api/chat',json=payload)
            resp.raise_for_status();msg=resp.json()['message'];msg.pop('thinking',None)
            msg['content']=strip_reasoning(msg.get('content',''));return msg
