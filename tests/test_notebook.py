import base64,io,json,tarfile
import httpx,pytest,nbformat
from nacl.public import PrivateKey,SealedBox
from notebook.github_api import GitHub,SetupError

def test_classic_scope_errors():
    def handler(req):return httpx.Response(200,json={'login':'alice'},headers={'X-OAuth-Scopes':'repo'})
    gh=GitHub('not-a-real-pat',transport=httpx.MockTransport(handler))
    with pytest.raises(SetupError,match='workflow'):gh.verify()
    gh.close()
    gh=GitHub('not-a-real-pat',transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'login':'alice'})))
    with pytest.raises(SetupError,match='classic'):gh.verify()
    assert gh.verify(allow_fine_grained=True)=='alice';gh.close()

def test_sealed_secret_dispatch_cancel_and_resume():
    key=PrivateKey.generate();calls=[]
    def handler(req):
        path=req.url.path;calls.append((req.method,path,req.content))
        if path=='/user':return httpx.Response(200,json={'login':'alice'},headers={'x-oauth-scopes':'repo, workflow'})
        if path.endswith('/public-key'):return httpx.Response(200,json={'key':base64.b64encode(bytes(key.public_key)).decode(),'key_id':'key1'})
        if '/secrets/' in path:
            payload=json.loads(req.content);assert SealedBox(key).decrypt(base64.b64decode(payload['encrypted_value']))==b'private-session-value'
            assert payload['key_id']=='key1';return httpx.Response(201)
        if path.endswith('/dispatches'):
            assert json.loads(req.content)=={'ref':'main'};return httpx.Response(204)
        if path.endswith('/runs'):return httpx.Response(200,json={'workflow_runs':[{'id':1,'status':'in_progress'},{'id':2,'status':'completed'}]})
        if path.endswith('/cancel'):return httpx.Response(202)
        if path.endswith('/session.json'):
            assert req.url.params['ref']=='workspace'
            return httpx.Response(200,json={'size':30,'content':base64.b64encode(b'{"version":1}').decode()})
        raise AssertionError(path)
    gh=GitHub('not-a-real-pat',transport=httpx.MockTransport(handler));gh.verify();gh.secret('AGENT_RUNNER_TOKEN','private-session-value');gh.dispatch();gh.cancel_runners();assert gh.load_state()=={'version':1};gh.close()
    assert sum(p.endswith('/cancel') for _,p,_ in calls)==1
    assert all(b'private-session-value' not in body for _,_,body in calls)

def test_repo_creation_and_idempotent_template_sync(monkeypatch):
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w:gz') as archive:
        for path,data in [('runner/worker.py',b'print("worker")'),('.github/workflows/runner.yml',b'name: runner'),('.github/workflows/deploy-site.yml',b'skip')]:
            item=tarfile.TarInfo('template-root/'+path);item.size=len(data);archive.addfile(item,io.BytesIO(data))
    def public_get(url,**kwargs):
        if '/commits/' in url:return httpx.Response(200,json={'sha':'template-sha'})
        if '/tarball/' in url:return httpx.Response(200,content=buffer.getvalue(),request=httpx.Request('GET',url))
        raise AssertionError(url)
    monkeypatch.setattr(httpx,'get',public_get)
    state={'created':False,'parent':None,'tree':[],'blobs':{},'writes':0}
    def handler(req):
        p=req.url.path;method=req.method
        if p=='/user':return httpx.Response(200,json={'login':'alice'},headers={'x-oauth-scopes':'repo, workflow'})
        if p=='/user/repos':state['created']=True;return httpx.Response(201,json={})
        if p=='/repos/alice/colab-agent':return httpx.Response(200 if state['created'] else 404,json={'private':False})
        if p.endswith('/git/ref/heads/main'):return httpx.Response(200 if state['parent'] else 404,json={'object':{'sha':'commit1'}})
        if '/git/commits/' in p:return httpx.Response(200,json={'tree':{'sha':'tree1'}})
        if '/git/trees/' in p:return httpx.Response(200,json={'tree':state['tree']})
        if '/git/blobs/' in p:
            sha=p.rsplit('/',1)[1];return httpx.Response(200,json={'content':state['blobs'][sha]})
        if p.endswith('/git/blobs'):
            payload=json.loads(req.content);sha='blob'+str(len(state['blobs']));state['blobs'][sha]=payload['content'];state['writes']+=1;return httpx.Response(201,json={'sha':sha})
        if p.endswith('/git/trees'):
            state['tree']=json.loads(req.content)['tree'];return httpx.Response(201,json={'sha':'tree1'})
        if p.endswith('/git/commits'):return httpx.Response(201,json={'sha':'commit1'})
        if p.endswith('/git/refs') or p.endswith('/git/refs/heads/main'):state['parent']='commit1';return httpx.Response(201,json={})
        raise AssertionError((method,p))
    gh=GitHub('not-a-real-pat',transport=httpx.MockTransport(handler));gh.verify()
    assert gh.ensure_repo()=={'created':True,'updated':True}
    writes=state['writes'];assert gh.ensure_repo()=={'created':False,'updated':False};assert state['writes']==writes
    assert all(x['path']!='.github/workflows/deploy-site.yml' for x in state['tree']);gh.close()

def test_notebook_validation_and_no_outputs():
    n=nbformat.read('notebook/colab_agent.ipynb',as_version=4);nbformat.validate(n)
    for cell in n.cells:
        if cell.cell_type=='code':assert not cell.outputs and cell.execution_count is None;compile(cell.source,'notebook','exec')

def test_gpu_error(monkeypatch):
    from notebook.bootstrap import check_gpu
    monkeypatch.setattr('shutil.which',lambda x:None)
    with pytest.raises(SetupError,match='T4 GPU'):check_gpu()
