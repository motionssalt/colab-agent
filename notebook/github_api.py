"""PAT is held in this object only; never in subprocess args, environment, or files."""
import base64,io,json,tarfile,time
import httpx
from nacl.public import PublicKey,SealedBox
class SetupError(RuntimeError):pass
class GitHub:
    def __init__(self,pat,repo_name='colab-agent',transport=None):
        self._client=httpx.Client(base_url='https://api.github.com',headers={'Authorization':'Bearer '+pat,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'},timeout=60,transport=transport)
        self.repo_name=repo_name;self.owner=None;self.base=None
    def request(self,method,path,**kw):
        try:r=self._client.request(method,path,**kw)
        except httpx.HTTPError:raise SetupError('GitHub network request failed. Check the connection and retry.') from None
        if r.status_code not in (200,201,202,204):
            if r.status_code==401:raise SetupError('PAT rejected or expired. Create a new classic PAT.')
            if r.status_code==403:raise SetupError('PAT permissions insufficient or API rate limit reached. Check repo and workflow scopes.')
            raise SetupError('GitHub request failed (HTTP '+str(r.status_code)+'). Check repository access and retry.')
        return r
    def verify(self,allow_fine_grained=False):
        r=self.request('GET','/user');scopes={s.strip() for s in r.headers.get('x-oauth-scopes','').split(',') if s.strip()}
        if not scopes and not allow_fine_grained:raise SetupError('Use a classic PAT with repo and workflow scopes; fine-grained runtime tokens are not supported.')
        for scope in ('repo','workflow'):
            if scopes and scope not in scopes:raise SetupError('PAT is missing the '+scope+' scope.')
        self.owner=r.json()['login'];self.base='/repos/'+self.owner+'/'+self.repo_name;return self.owner
    def repo_exists(self):
        response=self._client.get(self.base)
        if response.status_code==404:return False
        if response.status_code!=200:raise SetupError('Cannot read the repository; check PAT access.')
        if response.json().get('private'):raise SetupError('The agent repository must be public. Do not use a private repository with this free setup.')
        return True
    def ensure_repo(self,template='motionssalt/colab-agent'):
        exists=self.repo_exists()
        if not exists:self.request('POST','/user/repos',json={'name':self.repo_name,'private':False,'auto_init':False,'description':'Colab agent workspace and runner'})
        if self.owner+'/'+self.repo_name==template:return {'created':not exists,'updated':False}
        # Read template as a tarball without sending the private PAT to a third party.
        source=httpx.get('https://api.github.com/repos/'+template+'/commits/main',timeout=60)
        if source.status_code!=200:raise SetupError('Cannot read the public template; retry later.')
        sha=source.json()['sha']
        tar=httpx.get('https://api.github.com/repos/'+template+'/tarball/'+sha,follow_redirects=True,timeout=120)
        tar.raise_for_status();files={}
        with tarfile.open(fileobj=io.BytesIO(tar.content),mode='r:gz') as archive:
            for member in archive.getmembers():
                if not member.isfile():continue
                path=member.name.split('/',1)[-1]
                if '..' in path.split('/') or path.startswith('/') or path in ('BUILD_STATE.json','docs/BUILD_PROMPT.md') or path=='.github/workflows/deploy-site.yml':continue
                if member.size>3000000:raise SetupError('Template file is unexpectedly large.')
                files[path]=archive.extractfile(member).read()
        files['.template-version']=sha.encode()
        ref=self._client.get(self.base+'/git/ref/heads/main')
        parent=ref.json()['object']['sha'] if ref.status_code==200 else None
        old_tree={};base_tree=None
        if parent:
            commit=self.request('GET',self.base+'/git/commits/'+parent).json();base_tree=commit['tree']['sha']
            old_tree={x['path']:x['sha'] for x in self.request('GET',self.base+'/git/trees/'+base_tree+'?recursive=1').json()['tree'] if x['type']=='blob'}
        prior=None
        if '.template-version' in old_tree:
            b=self.request('GET',self.base+'/git/blobs/'+old_tree['.template-version']).json();prior=base64.b64decode(b['content']).decode().strip()
        if prior==sha:return {'created':not exists,'updated':False}
        prior_tree={}
        if prior:
            response=httpx.get('https://api.github.com/repos/'+template+'/git/trees/'+prior+'?recursive=1',timeout=60)
            if response.status_code==200:prior_tree={x['path']:x['sha'] for x in response.json()['tree'] if x['type']=='blob'}
        import hashlib
        changes=[]
        for path,content in files.items():
            blob_sha=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
            if old_tree.get(path)==blob_sha:continue
            if path in old_tree and path!='.template-version' and (not prior or old_tree[path]!=prior_tree.get(path)):
                raise SetupError('Local change in '+path+'. Template update stopped rather than overwriting your code; workspace branch is untouched.')
            blob=self.request('POST',self.base+'/git/blobs',json={'content':base64.b64encode(content).decode(),'encoding':'base64'}).json()
            changes.append({'path':path,'mode':'100644','type':'blob','sha':blob['sha']})
        if not changes:return {'created':not exists,'updated':False}
        payload={'tree':changes}
        if base_tree:payload['base_tree']=base_tree
        tree=self.request('POST',self.base+'/git/trees',json=payload).json()
        commit=self.request('POST',self.base+'/git/commits',json={'message':'Synchronize trusted colab-agent template '+sha[:12],'tree':tree['sha'],'parents':[parent] if parent else []}).json()
        if parent:self.request('PATCH',self.base+'/git/refs/heads/main',json={'sha':commit['sha'],'force':False})
        else:self.request('POST',self.base+'/git/refs',json={'ref':'refs/heads/main','sha':commit['sha']})
        return {'created':not exists,'updated':True}
    def secret(self,name,value):
        key=self.request('GET',self.base+'/actions/secrets/public-key').json()
        cipher=SealedBox(PublicKey(base64.b64decode(key['key']))).encrypt(value.encode())
        self.request('PUT',self.base+'/actions/secrets/'+name,json={'encrypted_value':base64.b64encode(cipher).decode(),'key_id':key['key_id']})
    def dispatch(self):self.request('POST',self.base+'/actions/workflows/runner.yml/dispatches',json={'ref':'main'})
    def cancel_runners(self):
        response=self._client.get(self.base+'/actions/workflows/runner.yml/runs?per_page=100')
        if response.status_code==404:return
        if response.status_code!=200:raise SetupError('Could not list runner jobs for cancellation.')
        for run in response.json()['workflow_runs']:
            if run['status']!='completed':
                result=self._client.post(self.base+'/actions/runs/'+str(run['id'])+'/cancel')
                if result.status_code not in (202,409):raise SetupError('Could not cancel a runner job. Cancel it on the Actions page.')
    def load_state(self):
        response=self._client.get(self.base+'/contents/state/session.json',params={'ref':'workspace'})
        if response.status_code==404:return None
        if response.status_code!=200:raise SetupError('Could not read saved session state.')
        data=response.json()
        if data.get('size',0)>500000:raise SetupError('Saved state is too large; start a new conversation.')
        return json.loads(base64.b64decode(data['content']))
    def close(self):self._client.close()
