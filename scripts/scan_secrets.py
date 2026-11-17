import pathlib,re,sys
patterns=[r"github_pat_[A-Za-z0-9_]{20,}",r"gh[pousr]_[A-Za-z0-9]{20,}",r"cfat_[A-Za-z0-9_-]{20,}",r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"]
bad=[]
for p in pathlib.Path('.').rglob('*'):
 if not p.is_file() or any(x in p.parts for x in ('.git','.venv','node_modules','__pycache__','.pytest_cache')): continue
 try: text=p.read_text()
 except (UnicodeError,OSError): continue
 if any(re.search(x,text) for x in patterns): bad.append(str(p))
if bad: print('Potential credentials in: '+', '.join(bad));sys.exit(1)
print('Secret-pattern scan passed')
