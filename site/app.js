"use strict";
const $=id=>document.getElementById(id);
const term=new Terminal({convertEol:false,fontSize:13,scrollback:3000,disableStdin:true,allowProposedApi:false});
const fit=new FitAddon.FitAddon();term.loadAddon(fit);term.open($('terminal'));fit.fit();
// Deliberately no hyperlink addon, HTML rendering, telemetry or third-party assets.
let socket=null,connection=null,retry=1000,timer=null,lastPong=0,takeover=false,runner=false,model='',agent='idle',authenticated=false;
function log(role,text){const line=document.createElement('div');line.className=role;line.textContent=(role==='event'?'· ':role+': ')+text;$('chat').appendChild(line);while($('chat').children.length>300)$('chat').firstChild.remove();$('chat').scrollTop=$('chat').scrollHeight;}
function status(offline=false){$('status').textContent=offline?'Brain offline — reconnecting':authenticated?`Brain online (${model}) · Runner ${runner?'online':'offline or booting'} · ${agent}`:'Connecting…';}
function send(message){if(socket&&socket.readyState===WebSocket.OPEN&&authenticated)socket.send(JSON.stringify(message));else log('error','Brain is offline. Wait for reconnection; the message was not sent.');}
function resize(){try{fit.fit();if(authenticated)send({type:'resize',cols:term.cols,rows:term.rows});}catch(e){}}
new ResizeObserver(resize).observe($('terminal'));
function mode(enabled){takeover=enabled;term.options.disableStdin=!enabled;$('takeover').textContent=enabled?'Agent controls':'I control the terminal';$('mode').textContent=enabled?'You control the terminal — agent waits':'View only — agent controls';}
function decode(raw){
 raw=raw.trim();if(raw.includes('#'))raw=raw.split('#').pop();
 const norm=raw.replace(/-/g,'+').replace(/_/g,'/');const data=JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(norm.padEnd(Math.ceil(norm.length/4)*4,'=')),c=>c.charCodeAt(0))));
 const url=new URL(data.url);
 if(url.protocol!=='https:'&&!(url.protocol==='http:'&&['localhost','127.0.0.1'].includes(url.hostname)))throw Error('HTTPS notebook tunnel required');
 if(url.username||url.password||url.search||url.hash||url.pathname!=='/'||typeof data.token!=='string'||data.token.length<16)throw Error('Invalid connection string');
 return {url:url.origin,token:data.token};
}
function connect(raw){
 try{connection=decode(raw);}catch(e){log('error',e.message);return;}
 try{localStorage.setItem('colab-agent-connection',raw);}catch(e){}
 if(timer)clearTimeout(timer);if(socket){socket.onclose=null;socket.close();}
 authenticated=false;status();
 socket=new WebSocket(connection.url.replace(/^http/,'ws')+'/control');const ws=socket;
 ws.onopen=()=>ws.send(JSON.stringify({type:'auth',token:connection.token}));
 ws.onmessage=event=>{
  let msg;try{msg=JSON.parse(event.data);}catch(e){return;}
  if(msg.type==='welcome'){
   authenticated=true;retry=1000;lastPong=Date.now();model=msg.model;runner=msg.runner;agent=msg.agent;mode(msg.takeover);term.reset();term.write(msg.scrollback||'');$('chat').replaceChildren();
   for(const e of msg.events||[])log(e.role||(e.type==='chat'?'assistant':e.type==='error'?'error':'event'),e.text||e.tool||'');status();resize();
  }else if(msg.type==='terminal')term.write(msg.data);
  else if(msg.type==='chat')log(msg.role,msg.text);
  else if(msg.type==='event'||msg.type==='error')log(msg.type,msg.text||msg.tool||'');
  else if(msg.type==='runner_status'){runner=msg.online;status();}
  else if(msg.type==='agent_status'){agent=msg.status;status();}
  else if(msg.type==='takeover')mode(msg.enabled);
  else if(msg.type==='pong'){lastPong=Date.now();}
 };
 ws.onerror=()=>status(true);
 ws.onclose=event=>{
  authenticated=false;status(true);
  if(event.code===4401){log('error','Connection token rejected. Paste the new connection string from the notebook.');return;}
  timer=setTimeout(()=>connect(raw),retry+Math.random()*500);retry=Math.min(30000,retry*2);
 };
}
$('connect').onclick=()=>connect($('connection').value);
$('forget').onclick=()=>{if(timer)clearTimeout(timer);if(socket){socket.onclose=null;socket.close();}connection=null;authenticated=false;try{localStorage.removeItem('colab-agent-connection');}catch(e){}$('connection').value='';history.replaceState(null,'',location.pathname+location.search);$('status').textContent='Brain offline';};
function task(fresh){let text=$('task').value.trim();if(!text)return;if(!authenticated){log('error','Not connected; your message remains in the box.');return;}send({type:fresh?'new_task':'chat',text});$('task').value='';}
$('send').onclick=()=>task(false);$('new').onclick=()=>task(true);$('stop').onclick=()=>send({type:'stop'});$('restart').onclick=()=>send({type:'restart_runner'});
$('takeover').onclick=()=>send({type:'takeover',enabled:!takeover});
term.onData(data=>{if(takeover)send({type:'input',data});});
for(const [id,data] of [['ctrlc','\x03'],['enter','\r'],['up','\x1b[A'],['down','\x1b[B'],['tab','\t']])$(id).onclick=()=>{if(takeover)send({type:'input',data});else log('event','Take terminal control first, or use Stop.');};
setInterval(async()=>{if(!connection||!authenticated)return;send({type:'ping'});try{await fetch(connection.url+'/health',{mode:'no-cors',cache:'no-store',referrerPolicy:'no-referrer',signal:AbortSignal.timeout(12000)});}catch(e){}if(lastPong&&Date.now()-lastPong>90000)socket.close();},45000);
setInterval(()=>{$('pong').textContent=lastPong?`Last pong ${Math.floor((Date.now()-lastPong)/1000)}s ago`:'No pong yet';},1000);
let initial=location.hash.slice(1);if(initial)history.replaceState(null,'',location.pathname+location.search);
if(!initial){try{initial=localStorage.getItem('colab-agent-connection')||'';}catch(e){}}
if(initial)connect(initial);
