import json,re
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,TypeAdapter,ValidationError
class Args(BaseModel):model_config=ConfigDict(extra='forbid',strict=True)
class Run(Args):
    command:str=Field(min_length=1,max_length=60000)
    timeout_s:int=Field(default=120,ge=1,le=1800)
class Keys(Args):keys:str=Field(max_length=60000)
class Screen(Args):pass
class Write(Args):
    path:str=Field(min_length=1,max_length=4096)
    content:str=Field(max_length=500000)
class Message(Args):text:str=Field(min_length=1,max_length=12000)
class Finish(Args):summary:str=Field(min_length=1,max_length=12000)
SCHEMAS={'run':Run,'send_keys':Keys,'read_screen':Screen,'write_file':Write,'message_user':Message,'finish':Finish}
TOOLS=[{'type':'function','function':{'name':n,'description':d,'parameters':SCHEMAS[n].model_json_schema()}} for n,d in [('run','Run one bash command; wait for completion.'),('send_keys','Send text or CTRL_C, ENTER, UP, DOWN, LEFT, RIGHT, TAB, ESC.'),('read_screen','Read the live terminal.'),('write_file','Write a UTF-8 file without typing a heredoc.'),('message_user','Send a brief progress update.'),('finish','Finish the current task.')]]
def strip_reasoning(s):return re.sub(r'<think>.*?</think>','',s,flags=re.S).split('<think>')[0].strip()
def validate(name,args):
    if name not in SCHEMAS:raise ValueError('Unknown tool name')
    if isinstance(args,str):args=json.loads(args)
    return {'tool':name,'args':SCHEMAS[name].model_validate(args).model_dump()}
def parse_message(msg):
    calls=msg.get('tool_calls',[])
    if calls:
        if len(calls)!=1:raise ValueError('Exactly one tool call is allowed')
        f=calls[0]['function'];return validate(f['name'],f['arguments'])
    s=strip_reasoning(msg.get('content',''))
    if s.startswith('```'):
        s=re.sub(r'^```(?:json)?\s*','',s);s=re.sub(r'\s*```$','',s)
    obj=json.loads(s)
    if not isinstance(obj,dict) or set(obj)!={'tool','args'}:raise ValueError('Return only {"tool":name,"args":object}')
    return validate(obj['tool'],obj['args'])
