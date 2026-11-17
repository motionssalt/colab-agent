import asyncio,pathlib
import pytest
from runner.worker import Terminal,Worker,bounded

async def test_terminal_completion_and_persistence(tmp_path):
    chunks=[];t=Terminal(tmp_path,chunks.append)
    try:
        await asyncio.sleep(.3)
        result=await t.run('echo hello; false',3)
        assert result['exit_code']==1 and 'hello' in result['output']
        await t.run('mkdir nested; cd nested',3)
        await t.write_file('test.txt','hello\nworld')
        assert (tmp_path/'nested/test.txt').read_text()=='hello\nworld'
        assert chunks
    finally:t.close()

async def test_timeout_interrupt_and_usable(tmp_path):
    t=Terminal(tmp_path)
    try:
        await asyncio.sleep(.2)
        result=await t.run('sleep 20',.3)
        assert result['timed_out'] and result['exit_code']==124
        result=await t.run('echo recovered',3)
        assert result['exit_code']==0 and 'recovered' in result['output']
        task=asyncio.create_task(t.run('sleep 20',30));await asyncio.sleep(.2);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert (await t.run('echo after_cancel',3))['exit_code']==0
    finally:t.close()

def test_bounding():
    s=bounded('A'*20000+'END',1000)
    assert len(s)<=1000 and s.startswith('A') and s.endswith('END')

async def test_worker_reconnect(tmp_path):
    import websockets,json
    connections=[]
    async def handler(ws):
        connections.append(ws);await ws.recv()
        if len(connections)==1:await ws.close();return
        await ws.send(json.dumps({'type':'call','id':'a','tool':'run','args':{'command':'echo reconnect_ok','timeout_s':3}}))
        async for raw in ws:
            msg=json.loads(raw)
            if msg.get('type')=='result':
                assert msg['result']['exit_code']==0
                assert 'reconnect_ok' in msg['result']['output']
                done.set();return
    done=asyncio.Event()
    async with websockets.serve(handler,'127.0.0.1',0) as server:
        port=server.sockets[0].getsockname()[1];w=Worker(f'http://127.0.0.1:{port}','test',tmp_path,offline_limit=5)
        task=asyncio.create_task(w.serve())
        try:await asyncio.wait_for(done.wait(),10);assert len(connections)>=2
        finally:task.cancel();await asyncio.gather(task,return_exceptions=True)
