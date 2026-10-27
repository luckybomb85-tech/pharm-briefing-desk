import {spawn} from "node:child_process";
import {mkdtemp,rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
const site=process.argv[2]||"https://luckybomb85-tech.github.io/pharm-briefing-desk/mfds/";
const chrome=process.env.CHROME_BIN||"/usr/bin/google-chrome";
const profile=await mkdtemp(path.join(os.tmpdir(),"mfds-newui-"));
const port=23000+Math.floor(Math.random()*9000);
const browser=spawn(chrome,["--headless=new","--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--no-first-run","--remote-allow-origins=*","--remote-debugging-port="+port,"--user-data-dir="+profile,site],{stdio:"ignore"});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let ws,request=0;
const pending=new Map();
async function evalPage(expression){
 const id=++request;
 const promise=new Promise((resolve,reject)=>pending.set(id,{resolve,reject}));
 ws.send(JSON.stringify({id,method:"Runtime.evaluate",params:{expression,returnByValue:true,awaitPromise:true}}));
 const response=await promise;
 if(response.exceptionDetails)throw Error("Browser exception: "+JSON.stringify(response.exceptionDetails));
 return response.result?.value;
}
async function wait(title,expr,check){
 let data;
 for(let n=0;n<120;n++){
  data=await evalPage(expr);
  if(check(data))return data;
  await sleep(320);
 }
 throw Error(title+" timed out: "+JSON.stringify(data).slice(0,1100));
}
const assert=(ok,msg)=>{if(!ok)throw Error(msg)};
async function search(fields){
 const p={keyword:"",searchField:"product",periodSelect:"all",type:"all",startDate:"",endDate:"",...fields};
 return evalPage('(()=>{const p='+JSON.stringify(p)+';for(const [k,v] of Object.entries(p))document.getElementById(k).value=v;document.getElementById("periodSelect").dispatchEvent(new Event("change"));document.getElementById("searchForm").dispatchEvent(new Event("submit",{cancelable:true,bubbles:true}));return true})()');
}
try{
 let tab;
 for(let n=0;n<65;n++){
  try{tab=(await (await fetch("http://127.0.0.1:"+port+"/json/list")).json()).find(x=>x.type==="page"&&x.webSocketDebuggerUrl);if(tab)break;}catch{}
  await sleep(300);
 }
 assert(tab,"Chrome DevTools endpoint unavailable");
 ws=new WebSocket(tab.webSocketDebuggerUrl);
 await new Promise((resolve,reject)=>{ws.addEventListener("open",resolve,{once:true});ws.addEventListener("error",reject,{once:true})});
 ws.addEventListener("message",e=>{
  const message=JSON.parse(e.data),entry=pending.get(message.id);
  if(!entry)return;pending.delete(message.id);
  message.error?entry.reject(Error(JSON.stringify(message.error))):entry.resolve(message.result);
 });
 const loaded=await wait("Original indication timeline",
  '({title:document.querySelector("h1")?.textContent||"",count:document.querySelector("#resultCount")?.textContent||"",dates:[...document.querySelectorAll("details.entry .date")].map(x=>x.textContent),period:document.querySelector("#searchPeriod")?.textContent||"",maker:document.querySelector(".entry-main .meta-title")?.textContent||"",company:document.querySelector(".entry-main .meta-fields")?.textContent||"",brand:document.querySelector(".publisher")?.textContent||""})',
  d=>d.title.includes("적응증")&&/^변경이력 \d+건$/.test(d.count)&&d.dates.length>=10&&d.period.includes("검색 기간")&&d.maker==="업체"&&d.brand.includes("데일리팜"));
 assert(loaded.dates.every((x,i)=>!i||x<=loaded.dates[i-1]),"Events are not sorted by MFDS change date");
 assert(!loaded.company.includes("성분"),"Ingredient duplicated next to the manufacturer");
 console.log("INDICATION_TITLE_PERIOD_MANUFACTURER_OK",JSON.stringify({title:loaded.title,count:loaded.count,period:loaded.period}));
 const settings=await evalPage('(()=>{document.querySelector("#notificationSettings").click();return {dialog:document.querySelector("#pushDialog").open,types:[...document.querySelectorAll("#pushDialog input[type=checkbox]")].map(x=>x.id),enable:!!document.querySelector("#pushEnable"),disable:!!document.querySelector("#pushDisable")}})()');
 console.log("PUSH_DIALOG_DEBUG",JSON.stringify(settings));
 assert(settings.dialog&&settings.types.length===3&&settings.enable&&settings.disable,"Settings dialog and per-device type preferences missing");
 console.log("OPT_IN_PUSH_SETTINGS_DIALOG_OK",JSON.stringify(settings));
 await evalPage('document.querySelector("#pushClose").click()');
 const filters=await evalPage('({field:[...document.getElementById("searchField").options].map(x=>x.value),years:[...document.getElementById("periodSelect").options].map(x=>x.value),periodRect:document.getElementById("periodSelect").getBoundingClientRect().top,typeRect:document.getElementById("type").getBoundingClientRect().top})');
 assert(JSON.stringify(filters.field)===JSON.stringify(["product","company","ingredient"]),"Search field options must be product, company and ingredient");
 assert(JSON.stringify(filters.years)===JSON.stringify(["all","2026","2025","2024","2023","2022","custom"]),"Annual period choices must be the five requested years and custom");
 assert(Math.abs(filters.periodRect-filters.typeRect)<5,"Year and change type filters are not on the same row");
 console.log("SCOPED_SEARCH_AND_ANNUAL_FILTERS_OK",JSON.stringify(filters));
 await search({periodSelect:"2026",type:"추가"});
 const yearly=await wait("Annual year filter",
  '({rows:[...document.querySelectorAll("#entries details.entry .date")].map(x=>x.textContent),period:document.querySelector("#searchPeriod")?.textContent||""})',
  v=>v.period.includes("2026.01.01")&&v.period.includes("2026.12.31")&&v.rows.length>=1);
 assert(yearly.rows.every(x=>x.startsWith("2026.")),"Yearly filter returned an event outside 2026");
 console.log("ANNUAL_SEARCH_2026_OK",JSON.stringify({count:yearly.rows.length,period:yearly.period}));
 const period=await search({periodSelect:"custom",startDate:"2026-07-01",endDate:"2026-10-27",type:"추가"});
 const dated=await wait("Manual date interval filter",
  '({rows:[...document.querySelectorAll("#entries details.entry .date")].map(x=>x.textContent),count:document.querySelector("#resultCount")?.textContent||"",period:document.querySelector("#searchPeriod")?.textContent||""})',
  v=>v.count.startsWith("변경이력 ")&&v.period.includes("2026.07.01")&&v.period.includes("2026.10.27")&&v.rows.length>=1);
 assert(dated.rows.every(d=>d>="2026.07.01"&&d<="2026.10.27"),"Date range contains an out-of-range item");
 console.log("CUSTOM_PERIOD_SEARCH_OK",JSON.stringify({count:dated.count,period:dated.period}));
 await search({});
 await wait("Restore chronological timeline",'document.querySelector("#searchPeriod")?.textContent||""',v=>v.includes("검색 기간"));
 await evalPage('(()=>{let q=document.querySelector("#keyword");q.value="키트";q.dispatchEvent(new Event("input",{bubbles:true}));return true})()');
 const options=await wait("Two-character product autocomplete",
  '({count:document.querySelectorAll("#suggestions .suggest-option").length,text:document.querySelector("#suggestions")?.textContent||""})',
  v=>v.count>=1&&v.text.includes("키트루다"));
 console.log("KEYTRUDA_TWO_CHARACTER_SUGGESTION_OK",JSON.stringify({count:options.count}));
 await evalPage('(()=>{let b=[...document.querySelectorAll("#suggestions .suggest-option")].find(x=>x.textContent.includes("키트루다"));if(!b)throw Error("No Keytruda suggestion");b.click();return true})()');
 const selected=await wait("Selected original history from autocomplete",
  '({heading:document.querySelector("#resultCount")?.textContent||"",cards:document.querySelectorAll("#entries details.entry").length,drug:document.querySelector("#entries .drug")?.textContent||""})',
  v=>v.heading.startsWith("변경이력 ")&&v.cards>=1&&v.drug.includes("키트루다"));
 console.log("SUGGESTION_SELECTION_AND_DETAILS_OK",JSON.stringify({heading:selected.heading,cards:selected.cards}));
 const mobileId=++request,promise=new Promise((resolve,reject)=>pending.set(mobileId,{resolve,reject}));
 ws.send(JSON.stringify({id:mobileId,method:"Emulation.setDeviceMetricsOverride",params:{width:390,height:844,deviceScaleFactor:1,mobile:true}}));
 await promise;
 const mobile=await evalPage('({width:window.innerWidth,scroll:document.documentElement.scrollWidth,head:document.querySelector(".page-header")?.getBoundingClientRect().width,periodY:document.getElementById("periodSelect").getBoundingClientRect().top,typeY:document.getElementById("type").getBoundingClientRect().top,keywordRight:document.getElementById("keyword").getBoundingClientRect().right,fieldRight:document.getElementById("searchField").getBoundingClientRect().right})');
 assert(Math.abs(mobile.periodY-mobile.typeY)<5,"Mobile filters are not on the same row");
 assert(mobile.fieldRight>mobile.keywordRight,"Mobile search field chooser is not at the right edge of the keyword box");
 assert(mobile.scroll<=mobile.width+3,"Mobile view has horizontal overflow: "+JSON.stringify(mobile));
 console.log("MOBILE_PUSH_AND_INDICATION_LAYOUT_OK",JSON.stringify(mobile));
 // The browser push click must link to the exact licensed product.
 const deepLink=new URL(site);
 deepLink.searchParams.set("seq","201501487");
 const next=++request;
 const navigated=new Promise((resolve,reject)=>pending.set(next,{resolve,reject}));
 ws.send(JSON.stringify({id:next,method:"Page.navigate",params:{url:deepLink.href}}));
 await navigated;
 const item=await wait("Push item-sequence exact history deep link",
  '({count:document.querySelector("#resultCount")?.textContent||"",product:document.querySelector("#entries .drug")?.textContent||"",maker:document.querySelector("#entries .meta-fields")?.textContent||""})',
  v=>v.count.startsWith("변경이력 ")&&v.product.includes("키트루다")&&v.maker.includes("한국엠에스디"));
 console.log("PUSH_NOTIFICATION_EXACT_PRODUCT_DEEPLINK_OK",JSON.stringify(item));
 console.log("MFDS_USER_REQUEST_20261027_PASS");
}finally{
 try{ws?.close()}catch{}
 browser.kill("SIGTERM");await sleep(300);
 await rm(profile,{recursive:true,force:true}).catch(()=>{});
}