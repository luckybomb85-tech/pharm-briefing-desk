import {spawn} from "node:child_process";
import {mkdtemp,rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
const chrome=process.env.CHROME_BIN||"/usr/bin/google-chrome";
const dir=await mkdtemp(path.join(os.tmpdir(),"mfds-test-"));
const port=22000+Math.floor(Math.random()*8000);
const url="https://luckybomb85-tech.github.io/pharm-briefing-desk/mfds/?test=interactions";
const proc=spawn(chrome,["--headless=new","--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--disable-background-networking","--no-first-run","--remote-allow-origins=*","--remote-debugging-port="+port,"--user-data-dir="+dir,url],{stdio:"ignore"});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let socket,seq=0;const pending=new Map();
async function evalPage(expression){
 const id=++seq;const p=new Promise((resolve,reject)=>pending.set(id,{resolve,reject}));
 socket.send(JSON.stringify({id,method:"Runtime.evaluate",params:{expression,awaitPromise:true,returnByValue:true}}));
 const out=await p;if(out.exceptionDetails)throw Error("Browser JS exception: "+JSON.stringify(out.exceptionDetails));
 return out.result?.value;
}
async function until(name,expr,test){
 let v;for(let n=0;n<60;n++){v=await evalPage(expr);if(test(v))return v;await sleep(300);}
 throw Error(name+" timed out: "+JSON.stringify(v));
}
function ensure(value,msg){if(!value)throw Error(msg);}
try{
 let tab;
 for(let i=0;i<50;i++){
  try{const tabs=await(await fetch("http://127.0.0.1:"+port+"/json/list")).json();tab=tabs.find(x=>x.type==="page"&&x.webSocketDebuggerUrl);if(tab)break}catch{}
  await sleep(300);
 }
 ensure(tab,"Chrome did not start");
 socket=new WebSocket(tab.webSocketDebuggerUrl);
 await new Promise((resolve,reject)=>{socket.addEventListener("open",resolve,{once:true});socket.addEventListener("error",reject,{once:true})});
 socket.addEventListener("message",ev=>{
  const msg=JSON.parse(ev.data);if(!msg.id)return;const p=pending.get(msg.id);if(!p)return;
  pending.delete(msg.id);if(msg.error)p.reject(Error(JSON.stringify(msg.error)));else p.resolve(msg.result);
 });
 const start=await until("Counters and leads",
  '({verified:document.querySelector("#numVerified")?.textContent,leads:document.querySelector("#numLeads")?.textContent,review:document.querySelector("#numReview")?.textContent,orders:document.querySelector("#numOrders")?.textContent,cards:document.querySelectorAll("#list .item").length})',
  v=>Number(v?.leads)>=3&&Number(v?.review)>=11&&Number(v?.orders)>=60&&v.cards>=3);
 console.log("MFDS_COUNTERS_OK",JSON.stringify(start));
 await evalPage('document.querySelector("[data-view=verified]").click()');
 const verified=await until("Verified events",
  '({cards:document.querySelectorAll("#list .item").length,body:document.querySelector("#list")?.textContent||"",active:document.querySelector("[data-view=verified]")?.getAttribute("aria-pressed")})',
  v=>v.cards>=1&&v.body.includes("임델트라")&&v.body.includes("2026.07.15")&&v.active==="true");
 console.log("MFDS_VERIFIED_CLICK_OK",verified.cards);
 await evalPage('document.querySelector("[data-view=review]").click()');
 const review=await until("History tab",
  '({cards:document.querySelectorAll("#list .item").length,active:document.querySelector("[data-view=review]")?.getAttribute("aria-pressed"),hidden:document.querySelector("#moreWrap")?.hidden})',
  v=>v.cards>=25&&v.active==="true");
 console.log("MFDS_REVIEW_HISTORY_OK",JSON.stringify(review));
 if(review.cards<=60&&!review.hidden){
  await evalPage('document.querySelector("#moreButton").click()');
  const count=await until("Load older records",'document.querySelectorAll("#list .item").length',v=>v>review.cards);
  console.log("MFDS_MORE_HISTORY_OK",count);
 }
 await evalPage('document.querySelector("[data-view=orders]").click()');
 const orders=await until("Change orders",
  '({cards:document.querySelectorAll("#list .item").length,active:document.querySelector("[data-view=orders]")?.getAttribute("aria-pressed"),text:document.querySelector("#list")?.textContent||""})',
  v=>v.cards>=20&&v.active==="true"&&v.text.includes("최초등록"));
 console.log("MFDS_ORDERS_CLICK_OK",orders.cards);
 await evalPage('(()=>{const y=document.querySelector("#year");y.value="2025";y.dispatchEvent(new Event("change",{bubbles:true}));return true})()');
 const year=await until("Year filter", 
  '({cards:document.querySelectorAll("#list .item").length,date:document.querySelector("#list .item-date")?.textContent||""})',
  v=>v.cards>=1&&v.date.includes("2025."));
 console.log("MFDS_YEAR_SEARCH_OK",year.cards);
 await evalPage('(()=>{const y=document.querySelector("#year");y.value="all";y.dispatchEvent(new Event("change",{bubbles:true}));document.querySelector("[data-view=leads]").click();return true})()');
 const leads=await until("Lead metric",
  '({cards:document.querySelectorAll("#list .item").length,active:document.querySelector("[data-view=leads]")?.getAttribute("aria-pressed")})',
  v=>v.cards>=3&&v.active==="true");
 console.log("MFDS_LEADS_CLICK_OK",leads.cards);
 const id=++seq,wait=new Promise((resolve,reject)=>pending.set(id,{resolve,reject}));
 socket.send(JSON.stringify({id,method:"Emulation.setDeviceMetricsOverride",params:{width:390,height:844,deviceScaleFactor:1,mobile:true}}));
 await wait;
 const mobile=await evalPage('({width:window.innerWidth,scrollWidth:document.documentElement.scrollWidth,buttons:[...document.querySelectorAll(".metric")].map(x=>x.getBoundingClientRect().right)})');
 ensure(mobile.scrollWidth<=mobile.width+5,"Mobile horizontal overflow: "+JSON.stringify(mobile));
 console.log("MFDS_MOBILE_OK",JSON.stringify(mobile));
 console.log("MFDS_RADAR_INTERACTION_OK");
}finally{
 try{socket?.close()}catch{}
 proc.kill("SIGTERM");await sleep(250);
 await rm(dir,{recursive:true,force:true}).catch(()=>{});
}
