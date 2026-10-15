// Run browser interaction checks against the public Pages desk using installed Chrome.
// No Playwright/Selenium dependency: only Node 22 WebSocket and Chrome DevTools Protocol.
import {spawn} from 'node:child_process';
import {mkdtemp, rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const url = process.argv[2] || 'https://luckybomb85-tech.github.io/pharm-briefing-desk/?date=2026-10-13';
const chrome=process.env.CHROME_BIN||'/usr/bin/google-chrome';
const minCards=Number(process.argv[3]||14),section=process.argv[4]||'domestic';
const profile=await mkdtemp(path.join(os.tmpdir(),'desk-ui-'));
const port=19000+Math.floor(Math.random()*10000);
const proc=spawn(chrome,[
 '--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu',
 '--disable-background-networking','--no-first-run','--remote-debugging-port='+port,
 '--remote-allow-origins=*','--user-data-dir='+profile,
 '--host-resolver-rules=MAP cdn.jsdelivr.net ~NOTFOUND',url
],{stdio:'ignore'});
let ws=null,seq=0;
const pending=new Map();
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const fail=msg=>{throw new Error(msg)};
async function pages(){
 const r=await fetch('http://127.0.0.1:'+port+'/json/list');return r.json();
}
async function cdp(method,params={}){
 const id=++seq;
 const p=new Promise((resolve,reject)=>pending.set(id,{resolve,reject}));
 ws.send(JSON.stringify({id,method,params}));
 return p;
}
async function evaluate(expression){
 const out=await cdp('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
 if(out.exceptionDetails)fail('Browser JavaScript exception: '+JSON.stringify(out.exceptionDetails).slice(0,300));
 return out.result?.value;
}
try{
 let page;
 for(let i=0;i<45;i++){
  try{page=(await pages()).find(x=>x.type==='page'&&x.webSocketDebuggerUrl);if(page)break}catch{}
  await sleep(350);
 }
 if(!page)fail('Could not connect to Chrome DevTools');
 ws=new WebSocket(page.webSocketDebuggerUrl);
 await new Promise((res,rej)=>{ws.addEventListener('open',res,{once:true});ws.addEventListener('error',rej,{once:true})});
 ws.addEventListener('message',e=>{
  const j=JSON.parse(e.data);if(!j.id)return;
  const p=pending.get(j.id);if(!p)return;pending.delete(j.id);
  if(j.error)p.reject(new Error(JSON.stringify(j.error)));else p.resolve(j.result);
 });
 if(section==='global'){
  let ready=false;
  for(let attempt=0;attempt<45;attempt++){
   const state=await evaluate("(()=>{const tab=document.querySelector('[data-tab=global]');if(!tab)return 'waiting';tab.click();return 'ready'})()");
   if(state==='ready'){ready=true;break}
   await sleep(350);
  }
  if(!ready)fail('Global tab not mounted in the browser');
 }
 let n=0;
 for(let i=0;i<50;i++){n=await evaluate("document.querySelectorAll('.card').length");if(n>=minCards)break;await sleep(350)}
 if(n<minCards)fail('Expected at least '+minCards+' published cards; found '+n);
 const detail=await evaluate(`(()=>{
  const button=document.querySelector('.card .summaryToggle');
  if(!button)return {error:'No summary button'};
  button.click();
  const opened=document.querySelector('#detail-0');
  const txt=opened?.querySelector('p')?.textContent||'';
  const visible=opened?.classList.contains('open');
  const aria=button.getAttribute('aria-expanded');
  render();
  return {visible,aria,summary:txt,stillOpen:document.querySelector('#detail-0')?.classList.contains('open')};
 })()`);
 if(!detail.visible||detail.aria!=='true'||!detail.stillOpen||(url.includes('2026-10-13')&&(!detail.summary.includes('42개사')||!detail.summary.includes('추산'))))fail('Summary toggle, verified summary text or rerender failed: '+JSON.stringify(detail));
 const writing=await evaluate(`(()=>{
  const buttons=document.querySelectorAll('.card:first-child .actions button');
  buttons[1].click();
  const w=document.querySelector('#writer-0');
  const preview=w?.textContent||'';
  const initialTitle=w?.querySelector('.previewTitleRow strong')?.textContent||'';
  const initialLead=w?.querySelector('.previewBody p')?.textContent||'';
  w?.querySelector('.refreshTitle')?.click();
  const refreshedTitle=w?.querySelector('.previewTitleRow strong')?.textContent||'';
  const refreshedLead=w?.querySelector('.previewBody p')?.textContent||'';
  const quickRefreshChanged=initialTitle!==refreshedTitle&&initialLead!==refreshedLead;
  const active=w?.classList.contains('open');
  window.__writerOpenCalls=[];
  window.open=(target,name)=>{window.__writerOpenCalls.push({target,name});return {opener:null}};
  w?.querySelector('.draftBtn')?.click();
  const quick=window.__writerOpenCalls[0]?.target||'';
  buttons[2].click();
  const deepPreview=document.querySelector('#writer-0')?.textContent||'';
  const deepInitialTitle=w?.querySelector('.previewTitleRow strong')?.textContent||'';
  const deepInitialLead=w?.querySelector('.previewBody p')?.textContent||'';
  w?.querySelector('.refreshTitle')?.click();
  const deepTitle=w?.querySelector('.previewTitleRow strong')?.textContent||'';
  const deepLead=w?.querySelector('.previewBody p')?.textContent||'';
  const deepRefreshChanged=deepInitialTitle!==deepTitle&&deepInitialLead!==deepLead;
  document.querySelector('#writer-0 .draftBtn')?.click();
  const deep=window.__writerOpenCalls[1]?.target||'';
  const q=new URL(quick).searchParams.get('q')||'';
  const d=new URL(deep).searchParams.get('q')||'';
  return {active,preview,deepPreview,quickRefreshChanged,deepRefreshChanged,titleDistinct:initialTitle!==document.querySelector('.card:first-child .title')?.textContent?.replace('⌄','').trim(),quickOpened:quick.startsWith('https://chatgpt.com/?q='),deepOpened:deep.startsWith('https://chatgpt.com/?q='),quickPrompt:q.includes('[바로 기사화]'),deepPrompt:d.includes('[심층 기사화]'),sourceIncluded:q.includes('https://')};
 })()`);
 if(!writing.active||!writing.quickRefreshChanged||!writing.deepRefreshChanged||!writing.titleDistinct||!writing.quickOpened||!writing.deepOpened||!writing.quickPrompt||!writing.deepPrompt||!writing.sourceIncluded)fail('Article actions failed: '+JSON.stringify(writing));
 await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 const mobile=await evaluate(`(()=>{
   const w=document.querySelector('#writer-0'),box=w?.querySelector('.previewBox');
   const header=w?.querySelector('.previewHead'),tools=w?.querySelector('.previewControls');
   const deep=w?.querySelector('.previewAngle');
   const title=w?.querySelector('.previewTitleRow strong');
   const lead=w?.querySelector('.previewLead');
   const btn=w?.querySelector('.draftBtn');
   const bounds=box?.getBoundingClientRect();
   const actions=tools?.getBoundingClientRect();
   return {width:window.innerWidth,boxWidth:bounds?.width||0,
     noCardOverflow:!!bounds&&bounds.right<=window.innerWidth+2,
     horizontalHeader:getComputedStyle(header).display==='flex',
     buttonInHeader:!!btn&&header.contains(btn),
     buttonsFit:!!actions&&actions.right<=bounds.right+1,
     titleWrap:getComputedStyle(title).overflowWrap,
     leadClamp:getComputedStyle(lead).webkitLineClamp,
     deepAngle:!!deep,deepDirection:!!deep?.querySelector('.previewDirection')
   };
 })()`);
 if(!mobile.noCardOverflow||!mobile.horizontalHeader||!mobile.buttonInHeader||!mobile.buttonsFit||!mobile.deepAngle||!mobile.deepDirection)fail('Compact mobile article-writing layout failed: '+JSON.stringify(mobile));
 console.log('MOBILE_COMPACT_ARTICLE_CARD_OK',JSON.stringify(mobile));
 console.log('INTERACTION_BROWSER_OK:',JSON.stringify({cards:n,summary:detail,writing:{
  active:writing.active,quickOpened:writing.quickOpened,deepOpened:writing.deepOpened,
  quickPrompt:writing.quickPrompt,deepPrompt:writing.deepPrompt,sourceIncluded:writing.sourceIncluded,quickRefreshChanged:writing.quickRefreshChanged,deepRefreshChanged:writing.deepRefreshChanged
 }}));
}finally{
 try{ws?.close()}catch{}
 proc.kill('SIGTERM');
 await sleep(250);
 await rm(profile,{recursive:true,force:true}).catch(()=>{});
}
