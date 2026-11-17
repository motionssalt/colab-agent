# Generate the committed Colab notebook from readable Python cell sources.
import pathlib,nbformat
root=pathlib.Path(__file__).resolve().parents[1]
setup_source='''#@title 1. Set up colab-agent (T4 GPU required)
MODEL = "qwen3:14b" #@param ["qwen3:14b", "qwen2.5-coder:14b", "qwen3:8b"]
MODEL_OVERRIDE = "" #@param {type:"string"}
REPO_NAME = "colab-agent" #@param {type:"string"}
SITE_URL = "https://colab-agent.pages.dev" #@param {type:"string"}
NUM_CTX = 16384 #@param {type:"integer"}
MAX_STEPS = 60 #@param {type:"integer"}
THINKING = False #@param {type:"boolean"}
# Thinking is slower; off is recommended for the agent loop.
RESUME = "ask" #@param ["ask", "yes", "no"]

import pathlib,subprocess,sys,importlib
root=pathlib.Path('/content/colab-agent-source')
if 'SESSION' in globals() and SESSION is not None:
    SESSION.shutdown()
SESSION=None
if not root.exists():
    subprocess.run(['git','clone','--depth','1','https://github.com/motionssalt/colab-agent.git',str(root)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
else:
    subprocess.run(['git','-C',str(root),'pull','--ff-only'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
subprocess.run([sys.executable,'-m','pip','install','-q','-r',str(root/'requirements.txt')],check=True)
# Google Colab also installs a package named notebook. Clear only our package
# names before importing our freshly pulled source, never save a PAT in a cell.
for name in list(sys.modules):
    if name in ('notebook','brain','runner') or name.startswith(('notebook.','brain.','runner.')):sys.modules.pop(name,None)
sys.path.insert(0,str(root))
from notebook.bootstrap import setup,SetupError
try:
    SESSION=setup(repo_name=REPO_NAME,site_url=SITE_URL,model=MODEL_OVERRIDE.strip() or MODEL,num_ctx=NUM_CTX,thinking=THINKING,max_steps=MAX_STEPS,resume={'ask':'ask','yes':True,'no':False}[RESUME])
except SetupError as error:
    print(str(error))
'''
heartbeat_source='''#@title 2. Keep running (required)
from notebook.bootstrap import heartbeat
if SESSION is None:
    print('Run setup successfully first.')
else:
    heartbeat(SESSION)
'''
off_source='''#@title 3. All off (interrupt the heartbeat cell first)
if 'SESSION' in globals() and SESSION is not None:
    SESSION.shutdown()
    SESSION=None
else:
    print('No session in this runtime. Check GitHub Actions if an old runner is still active.')
'''
nb=nbformat.v4.new_notebook(cells=[nbformat.v4.new_markdown_cell('# colab-agent\n\nChoose **Runtime → Change runtime type → T4 GPU**. Run Setup, paste a **GitHub PAT** (classic with `repo` + `workflow` scopes, or fine-grained with repository Actions, Secrets, Contents, and Workflows Read/write — plus Account Administration Read/write if auto-creating the repo) into the hidden prompt, open the private control-panel link, then run Keep running. Never type a PAT into notebook source or share notebook output.\n\nEverything you save to the public workspace or Releases is public. The model can run arbitrary shell commands. Pings and heartbeat do not bypass Colab quotas, disconnects or service policies. No hosted model APIs.\n\nSetup may take several minutes. Interrupt heartbeat before running All off. See docs/FIRST_RUN.md in the repository.'),nbformat.v4.new_code_cell(setup_source),nbformat.v4.new_code_cell(heartbeat_source),nbformat.v4.new_code_cell(off_source)],metadata={'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python'},'colab':{'name':'colab_agent.ipynb','provenance':[]},'accelerator':'GPU'})
nbformat.validate(nb);nbformat.write(nb,root/'notebook/colab_agent.ipynb')
print('Generated and validated Colab notebook')
