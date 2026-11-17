"""PAT is held in this object only; never in subprocess args, environment, or files."""

import base64
import hashlib
import io
import json
import tarfile
import time

import httpx
from nacl.public import PublicKey, SealedBox


class SetupError(RuntimeError):
    pass


class GitHub:
    def __init__(self, pat, repo_name='colab-agent', transport=None):
        token = (pat or '').strip()
        if not token:
            raise SetupError('GitHub PAT cannot be empty.')
        if any(ch in token for ch in '\r\n\0'):
            raise SetupError('GitHub PAT contains invalid newline or control characters.')
        self._client = httpx.Client(
            base_url='https://api.github.com',
            headers={
                'Authorization': 'Bearer ' + token,
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
            },
            timeout=60,
            transport=transport,
        )
        self.repo_name = repo_name
        self.owner = None
        self.base = None

    def _error_for_response(self, method, path, r):
        if r.status_code == 401:
            return SetupError('PAT rejected or expired. Check your token or create a new GitHub PAT.')
        msg = ''
        try:
            data = r.json()
            if isinstance(data, dict):
                msg = str(data.get('message', ''))
        except Exception:
            pass
        if r.status_code == 403:
            if r.headers.get('x-ratelimit-remaining') == '0':
                return SetupError('GitHub API rate limit reached. Wait and retry.')
            if path == '/user/repos' and method == 'POST':
                return SetupError(
                    f'PAT cannot create the repository "{self.repo_name}". '
                    'For a fine-grained PAT, grant Account "Administration: Read and write" (All repositories) '
                    f'or create an empty public "{self.repo_name}" repo on GitHub first and select it. '
                    'Classic PATs need the "repo" scope.'
                )
            if '/actions/secrets' in path:
                return SetupError(
                    'PAT lacks repository Secrets permission. For a fine-grained PAT, grant '
                    '"Secrets: Read and write" on this repo (and ensure the repo is selected). '
                    'For a classic PAT, grant "repo" and "workflow" scopes.'
                )
            if '/actions/' in path:
                return SetupError(
                    'PAT lacks repository Actions permission. For a fine-grained PAT, grant '
                    '"Actions: Read and write" on this repo. For a classic PAT, grant "repo" and "workflow" scopes.'
                )
            if '/git/' in path or '/contents/' in path:
                return SetupError(
                    'PAT lacks repository Contents or Workflows write permission. For a fine-grained PAT, '
                    'grant "Contents: Read and write" and "Workflows: Read and write" on this repo. '
                    'For a classic PAT, grant "repo" and "workflow" scopes.'
                )
            accepted = r.headers.get('x-accepted-github-permissions', '').strip()
            hint = f' ({accepted})' if accepted else ''
            return SetupError(
                f'PAT permissions insufficient{hint}. Classic PATs need "repo" and "workflow" scopes; '
                'fine-grained PATs need repository Actions, Secrets, Contents, and Workflows (Read and write).'
            )
        if r.status_code == 404:
            if '/actions/secrets' in path:
                return SetupError(
                    'Cannot access repository Actions secrets. Ensure the repository exists, Actions is enabled, '
                    'and if using a fine-grained PAT, that this repository is selected with "Secrets: Read and write".'
                )
            if '/dispatches' in path:
                return SetupError(
                    'Cannot dispatch runner.yml. Ensure .github/workflows/runner.yml exists on main, '
                    'Actions is enabled, and your PAT has Actions write access.'
                )
        if r.status_code == 422 and 'workflow' in msg.lower():
            return SetupError(
                'PAT cannot update workflow files. For a fine-grained PAT, grant "Workflows: Read and write". '
                'For a classic PAT, grant the "workflow" scope.'
            )
        return SetupError('GitHub request failed (HTTP ' + str(r.status_code) + '). Check repository access and retry.')

    def request(self, method, path, **kw):
        try:
            r = self._client.request(method, path, **kw)
        except httpx.HTTPError:
            raise SetupError('GitHub network request failed. Check the connection and retry.') from None
        if r.status_code not in (200, 201, 202, 204):
            raise self._error_for_response(method, path, r)
        return r

    def verify(self, allow_fine_grained=True):
        r = self.request('GET', '/user')
        has_oauth_header = 'x-oauth-scopes' in r.headers
        if has_oauth_header:
            scopes = {s.strip() for s in r.headers.get('x-oauth-scopes', '').split(',') if s.strip()}
            if not scopes:
                raise SetupError(
                    'Classic PAT has no scopes. Grant "repo" and "workflow" scopes, '
                    'or use a fine-grained PAT with repository Actions, Secrets, Contents, and Workflows permissions.'
                )
            for scope in ('repo', 'workflow'):
                if scope not in scopes:
                    raise SetupError('PAT is missing the ' + scope + ' scope.')
        elif not allow_fine_grained:
            raise SetupError('Use a classic PAT with repo and workflow scopes; fine-grained runtime tokens are disabled.')
        data = r.json()
        login = data.get('login') if isinstance(data, dict) else None
        if not login:
            raise SetupError('PAT did not return a GitHub user account. Use a user-scoped GitHub PAT.')
        self.owner = login
        self.base = '/repos/' + self.owner + '/' + self.repo_name
        return self.owner

    def repo_exists(self):
        try:
            response = self._client.get(self.base)
        except httpx.HTTPError:
            raise SetupError('GitHub network request failed. Check the connection and retry.') from None
        if response.status_code == 404:
            return False
        if response.status_code == 401:
            raise SetupError('PAT rejected or expired. Check your token or create a new GitHub PAT.')
        if response.status_code != 200:
            raise SetupError('Cannot read the repository; check PAT access.')
        if response.json().get('private'):
            raise SetupError('The agent repository must be public. Do not use a private repository with this free setup.')
        return True

    def check_access(self):
        self.request('GET', self.base + '/actions/secrets/public-key')

    def _seed_empty_repo(self):
        self.request(
            'PUT',
            self.base + '/contents/.template-version',
            json={
                'message': 'Initialize colab-agent repository',
                'content': base64.b64encode(b'pending').decode(),
                'branch': 'main',
            },
        )
        ref = self.request('GET', self.base + '/git/ref/heads/main')
        parent = ref.json()['object']['sha']
        commit = self.request('GET', self.base + '/git/commits/' + parent).json()
        base_tree = commit['tree']['sha']
        old_tree = {
            x['path']: x['sha']
            for x in self.request('GET', self.base + '/git/trees/' + base_tree + '?recursive=1').json()['tree']
            if x['type'] == 'blob'
        }
        return parent, base_tree, old_tree

    def ensure_repo(self, template='motionssalt/colab-agent'):
        exists = self.repo_exists()
        if not exists:
            self.request(
                'POST',
                '/user/repos',
                json={
                    'name': self.repo_name,
                    'private': False,
                    'auto_init': False,
                    'description': 'Colab agent workspace and runner',
                },
            )
        if self.owner + '/' + self.repo_name == template:
            return {'created': not exists, 'updated': False}
        # Read template as a tarball without sending the private PAT to a third party.
        try:
            source = httpx.get('https://api.github.com/repos/' + template + '/commits/main', timeout=60)
            if source.status_code != 200:
                raise SetupError('Cannot read the public template; retry later.')
            sha = source.json()['sha']
            tar = httpx.get(
                'https://api.github.com/repos/' + template + '/tarball/' + sha,
                follow_redirects=True,
                timeout=120,
            )
            tar.raise_for_status()
        except httpx.HTTPError:
            raise SetupError('Cannot download the public template; retry later.') from None
        files = {}
        with tarfile.open(fileobj=io.BytesIO(tar.content), mode='r:gz') as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                path = member.name.split('/', 1)[-1]
                if (
                    '..' in path.split('/')
                    or path.startswith('/')
                    or path in ('BUILD_STATE.json', 'docs/BUILD_PROMPT.md')
                    or path == '.github/workflows/deploy-site.yml'
                ):
                    continue
                if member.size > 3000000:
                    raise SetupError('Template file is unexpectedly large.')
                files[path] = archive.extractfile(member).read()
        files['.template-version'] = sha.encode()
        ref = self._client.get(self.base + '/git/ref/heads/main')
        parent = ref.json()['object']['sha'] if ref.status_code == 200 else None
        old_tree = {}
        base_tree = None
        if parent:
            commit = self.request('GET', self.base + '/git/commits/' + parent).json()
            base_tree = commit['tree']['sha']
            old_tree = {
                x['path']: x['sha']
                for x in self.request('GET', self.base + '/git/trees/' + base_tree + '?recursive=1').json()['tree']
                if x['type'] == 'blob'
            }
        prior = None
        if '.template-version' in old_tree:
            b = self.request('GET', self.base + '/git/blobs/' + old_tree['.template-version']).json()
            prior = base64.b64decode(b['content']).decode().strip()
        if prior == sha:
            return {'created': not exists, 'updated': False}
        prior_tree = {}
        if prior:
            response = httpx.get(
                'https://api.github.com/repos/' + template + '/git/trees/' + prior + '?recursive=1',
                timeout=60,
            )
            if response.status_code == 200:
                prior_tree = {x['path']: x['sha'] for x in response.json()['tree'] if x['type'] == 'blob'}
        changes = []
        for path, content in files.items():
            blob_sha = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
            if old_tree.get(path) == blob_sha:
                continue
            if (
                path in old_tree
                and path != '.template-version'
                and (not prior or old_tree[path] != prior_tree.get(path))
            ):
                raise SetupError(
                    'Local change in '
                    + path
                    + '. Template update stopped rather than overwriting your code; workspace branch is untouched.'
                )
            blob_payload = {'content': base64.b64encode(content).decode(), 'encoding': 'base64'}
            try:
                blob_resp = self._client.post(self.base + '/git/blobs', json=blob_payload)
            except httpx.HTTPError:
                raise SetupError('GitHub network request failed. Check the connection and retry.') from None
            if blob_resp.status_code == 409 and parent is None:
                parent, base_tree, old_tree = self._seed_empty_repo()
                blob_resp = self.request('POST', self.base + '/git/blobs', json=blob_payload)
            elif blob_resp.status_code not in (200, 201):
                raise self._error_for_response('POST', self.base + '/git/blobs', blob_resp)
            blob = blob_resp.json()
            changes.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
        if not changes:
            return {'created': not exists, 'updated': False}
        payload = {'tree': changes}
        if base_tree:
            payload['base_tree'] = base_tree
        tree = self.request('POST', self.base + '/git/trees', json=payload).json()
        commit = self.request(
            'POST',
            self.base + '/git/commits',
            json={
                'message': 'Synchronize trusted colab-agent template ' + sha[:12],
                'tree': tree['sha'],
                'parents': [parent] if parent else [],
            },
        ).json()
        if parent:
            self.request('PATCH', self.base + '/git/refs/heads/main', json={'sha': commit['sha'], 'force': False})
        else:
            self.request('POST', self.base + '/git/refs', json={'ref': 'refs/heads/main', 'sha': commit['sha']})
        return {'created': not exists, 'updated': True}

    def secret(self, name, value):
        key = self.request('GET', self.base + '/actions/secrets/public-key').json()
        cipher = SealedBox(PublicKey(base64.b64decode(key['key']))).encrypt(value.encode())
        self.request(
            'PUT',
            self.base + '/actions/secrets/' + name,
            json={'encrypted_value': base64.b64encode(cipher).decode(), 'key_id': key['key_id']},
        )

    def dispatch(self):
        path = self.base + '/actions/workflows/runner.yml/dispatches'
        try:
            r = self._client.post(path, json={'ref': 'main'})
        except httpx.HTTPError:
            raise SetupError('GitHub network request failed. Check the connection and retry.') from None
        if r.status_code == 404:
            time.sleep(2)
            r = self.request('POST', path, json={'ref': 'main'})
            return r
        if r.status_code not in (200, 201, 202, 204):
            raise self._error_for_response('POST', path, r)
        return r

    def cancel_runners(self):
        response = self._client.get(self.base + '/actions/workflows/runner.yml/runs?per_page=100')
        if response.status_code == 404:
            return
        if response.status_code != 200:
            raise self._error_for_response('GET', self.base + '/actions/workflows/runner.yml/runs', response)
        for run in response.json()['workflow_runs']:
            if run['status'] != 'completed':
                result = self._client.post(self.base + '/actions/runs/' + str(run['id']) + '/cancel')
                if result.status_code not in (202, 409):
                    if result.status_code == 403:
                        raise SetupError(
                            'Could not cancel an active runner job. Grant "Actions: Read and write" '
                            '(fine-grained PAT) or "repo" + "workflow" scopes (classic PAT), or cancel it on the Actions page.'
                        )
                    raise SetupError('Could not cancel a runner job. Cancel it on the Actions page.')

    def load_state(self):
        response = self._client.get(self.base + '/contents/state/session.json', params={'ref': 'workspace'})
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise SetupError('Could not read saved session state.')
        data = response.json()
        if data.get('size', 0) > 500000:
            raise SetupError('Saved state is too large; start a new conversation.')
        return json.loads(base64.b64decode(data['content']))

    def close(self):
        self._client.close()
