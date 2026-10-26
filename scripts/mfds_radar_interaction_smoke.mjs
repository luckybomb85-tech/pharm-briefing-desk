import {spawn} from "node:child_process";
import {mkdtemp,rm} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
const url=process.argv[2]||"https://luckybomb85-tech.github.io/pharm-briefing-desk/mfds/?ui=efficacy";
const chrome=process.env.CHROME_BIN||"/usr/bin/google-chrome";
const profile=await mkdtemp(path.join(os.tmpdir(),"mfds-efficacy-test-"));
const port=22000+Math.floor(Math.random()*9000);
const proc=spawn(chrome,["--headless=new","--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--disable-background-networking","--no-first-run","--remote-allow-origins=*","--remote-debugging-port="+port,"--user-data-dir="+profile,url],{stdio:"ignore"});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let socket,seq=0;const pending=new Map();
async function evalPage(expression){
 const id=++seq;
 const promise=new Promise((resolve,reject)=>pending.set(id,{resolve,reject}));
 socket.send(JSON.stringify({id,method:"Runtime.evaluate",params:{expression,awaitPromise:true,returnByValue:true}}));
 const result=await promise;
 if(result.exceptionDetails)throw Error("JavaScript exception "+JSON.stringify(result.exceptionDetails).slice(0,400));
 return result.result?.value;
}
async function until(title,expr,test){
 let val;
 for(let i=0;i<125;i++){val=await evalPage(expr);if(test(val))return val;await sleep(300);}
 throw Error(title+" timed out: "+JSON.stringify(val));
}
async function submit(filter){
 const js='(()=>{const p='+JSON.stringify(filter)+';for(const [k,v] of Object.entries(p)){document.getElementById(k).value=v;}document.getElementById("searchForm").dispatchEvent(new Event("submit",{bubbles:true,cancelable:true}));return true})()';
 return evalPage(js);
}
function ensure(value,msg){if(!value)throw Error(msg)}
try{
 let tab;
 for(let i=0;i<55;i++){
  try{tab=(await(await fetch("http://127.0.0.1:"+port+"/json/list")).json()).find(x=>x.type==="page"&&x.webSocketDebuggerUrl);if(tab)break;}catch{}
  await sleep(310);
 }
 ensure(tab,"Chrome DevTools page missing");
 socket=new WebSocket(tab.webSocketDebuggerUrl);
 await new Promise((res,rej)=>{socket.addEventListener("open",res,{once:true});socket.addEventListener("error",rej,{once:true})});
 socket.addEventListener("message",e=>{
  const msg=JSON.parse(e.data);if(!msg.id)return;const p=pending.get(msg.id);
  if(!p)return;pending.delete(msg.id);if(msg.error)p.reject(Error(JSON.stringify(msg.error)));else p.resolve(msg.result);
 });
 const ready=await until("Original-first efficacy timeline",
  '({title:document.querySelector("h1")?.textContent,count:document.querySelector("#resultCount")?.textContent,cards:document.querySelectorAll("details.entry").length,first:document.querySelector("details.entry")?.textContent||"",noCards:!document.querySelector(".metrics"),noGuide:!document.querySelector(".guide"),dates:[...document.querySelectorAll("details.entry .date")].map(x=>x.textContent)})',
  v=>v.title?.includes("효능·효과 변경이력")&&v.count?.includes("오리지널 중심")&&Number((v.count||"").match(/\d+/)?.[0])>=50&&v.cards>=10&&v.noCards&&v.noGuide&&v.dates.every((d,i)=>i===0||d<=v.dates[i-1]));
 console.log("ORIGINAL_FIRST_CHRONOLOGY_OK",JSON.stringify({count:ready.count,first:ready.dates.slice(0,5)}));
 const summary=await evalPage('({subtitle:document.querySelector("header .subtitle")?.textContent||"",contextHidden:document.querySelector("#resultContext")?.hidden,label:document.querySelector("#resultCount")?.textContent||""})');
 ensure(!summary.subtitle&&summary.contextHidden&&!summary.label.includes("일부 품목"),"Original-only concise header invalid "+JSON.stringify(summary));
 console.log("ORIGINAL_COMPACT_HEADER_OK",JSON.stringify(summary));
 await evalPage('document.querySelector("details.entry summary").click()');
 const detail=await until("Expanding clinical change groups",
  '({open:document.querySelector("details.entry")?.open,text:document.querySelector("details.entry .content")?.textContent||"",diseases:document.querySelectorAll("details.entry[open] .disease-group").length,units:document.querySelectorAll("details.entry[open] .change-unit").length,originals:document.querySelectorAll("details.entry[open] .original-details").length})',
  v=>v.open&&v.text.includes("변경 후 효능·효과 전문")&&v.diseases>0&&v.units>0&&v.originals>0);
 console.log("CLINICAL_GROUPED_DIFF_OK",JSON.stringify({diseases:detail.diseases,changes:detail.units,originals:detail.originals}));
 await submit({keyword:"",year:"2026",type:"추가",scope:"all"});
 const changed=await until("Year and change-type filter",
  '({count:document.querySelector("#resultCount")?.textContent,cards:document.querySelectorAll("details.entry").length,body:document.querySelector("#entries")?.textContent||""})',
  v=>v.cards>=2&&v.count?.includes("건")&&v.body.includes("임핀지")&&v.body.includes("2026.03.23"));
 console.log("YEAR_TYPE_SEARCH_OK",changed.count);
 await submit({keyword:"더발루맙",year:"all",type:"all",scope:"compared"});
 const ingredient=await until("Ingredient search",
  '({cards:document.querySelectorAll("details.entry").length,names:[...document.querySelectorAll("details.entry .drug")].map(x=>x.textContent)})',
  v=>v.cards>=4&&v.names.every(x=>x.includes("임핀지")));
 console.log("INGREDIENT_SEARCH_OK",ingredient.cards);
 await submit({keyword:"",year:"all",type:"all",scope:"uncompared"});
 const old=await until("Old records without original XML",
  '({cards:document.querySelectorAll("details.entry").length,body:document.querySelector("#entries")?.textContent||"",count:document.querySelector("#resultCount")?.textContent})',
  v=>v.cards>=2&&v.count?.includes("건")&&v.body.includes("내용 확인 필요"));
 console.log("OLDER_CHANGES_FILTER_OK",old.cards);
 await submit({keyword:"",year:"all",type:"삭제",scope:"all"});
 const deletions=await until("Deletion filter",
  '({count:document.querySelector("#resultCount")?.textContent,cards:document.querySelectorAll("details.entry").length,body:document.querySelector("#entries")?.textContent||""})',
  v=>v.count?.includes("건")&&(v.cards>0||v.body.includes("검색 조건")));
 console.log("DELETION_FILTER_OK",deletions.count);

 // Tevimbra: two change dates, no misleading deletions from whitespace.
 await submit({keyword:"테빔브라",year:"all",type:"all",scope:"all"});
 const tevimbra=await until("Tevimbra scoped result count and disease summaries",
  '({count:document.querySelector("#resultCount")?.textContent,cards:document.querySelectorAll("details.entry").length,preview:document.querySelector("details.entry .entry-preview")?.textContent||"",catalogue:document.querySelectorAll(".catalogue-choice").length})',
  v=>v.count?.includes("2건")&&v.cards===2&&v.catalogue===1&&v.preview.includes("소세포폐암")&&v.preview.includes("비인두암"));
 console.log("TEVIMBRA_SCOPED_TWO_HISTORY_OK",JSON.stringify({count:tevimbra.count,cards:tevimbra.cards,preview:tevimbra.preview.slice(0,320)}));
 const officialCounts=await evalPage('document.querySelector("#resultContext")?.textContent||""');
 ensure(officialCounts.includes("전체 12개 항목 중 효능·효과 변경 2건"),"Missing official vs efficacy count distinction: "+officialCounts);
 console.log("TEVIMBRA_OFFICIAL_12_VS_EFFICACY_2_OK",officialCounts);
 const earliest=await evalPage('({baseline:document.querySelector("#entries .baseline-record")?.textContent||"",open:document.querySelector("#entries .baseline-record")?.open,hidden:document.querySelector("#moreWrap")?.hidden,display:getComputedStyle(document.querySelector("#moreWrap")).display,end:document.querySelector("#historyEnd")?.textContent||"",changedCards:document.querySelectorAll("#entries details.entry").length})');
 ensure(earliest.baseline.includes("2023.11.20")&&earliest.baseline.includes("변경 건수 제외")&&earliest.hidden&&earliest.display==="none"&&earliest.changedCards===2&&earliest.end.includes("2건"),"Tevimbra earliest official version or pagination state failed: "+JSON.stringify(earliest));
 console.log("TEVIMBRA_EARLIEST_ORIGINAL_AVAILABLE_OK",JSON.stringify({baseline:earliest.baseline.slice(0,200),hidden:earliest.hidden,display:earliest.display,end:earliest.end}));
 await evalPage('document.querySelector("#entries .baseline-record summary").click()');
 const originalVersion=await evalPage('({open:document.querySelector("#entries .baseline-record")?.open,lines:document.querySelectorAll("#entries .baseline-record .line.current").length})');
 ensure(originalVersion.open&&originalVersion.lines>=1,"Original Tevimbra version cannot expand: "+JSON.stringify(originalVersion));
 console.log("TEVIMBRA_ORIGINAL_VERSION_EXPAND_OK",JSON.stringify(originalVersion));
 await evalPage('document.querySelector("details.entry summary").click()');
 const tevimbraExpanded=await until("Tevimbra three substantive additions only",
  '({open:document.querySelector("details.entry")?.open,groups:document.querySelectorAll("details.entry[open] .disease-group").length,adds:document.querySelectorAll("details.entry[open] .change-unit:not(.modified):not(.removed)").length,removed:document.querySelectorAll("details.entry[open] .change-unit.removed").length,cosmetic:document.querySelector("details.entry[open] .cosmetic-note")?.textContent||"",hiddenOriginal:document.querySelectorAll("details.entry[open] details.original-details:not([open])").length})',
  v=>v.open&&v.groups===3&&v.adds===3&&v.removed===0&&v.cosmetic.includes("4건")&&v.hiddenOriginal>=2);
 console.log("TEVIMBRA_THREE_CLINICAL_ADDITIONS_OK",JSON.stringify(tevimbraExpanded));
 await evalPage('document.querySelector("details.entry[open] details.original-details summary").click()');
 const fullText=await until("Tevimbra official full text opened",
  '({original:document.querySelector("details.entry[open] details.original-details")?.open,lines:document.querySelectorAll("details.entry[open] details.original-details[open] .line.current").length,marked:document.querySelectorAll("details.entry[open] details.original-details[open] .line.is-added").length})',
  v=>v.original&&v.lines>=10&&v.marked===3);
 console.log("TEVIMBRA_COLLAPSIBLE_FULL_TEXT_OK",JSON.stringify(fullText));

 // New: unregistered MFDS catalogue entries must now be searchable.
 await submit({keyword:"오젬픽",year:"all",type:"all",scope:"all"});
 const ozempic=await until("Unregistered Ozempic live search",
  '({count:document.querySelector("#resultCount")?.textContent,match:document.querySelectorAll(".catalogue-choice").length,cards:document.querySelectorAll("details.entry").length,brand:document.querySelector("details.entry")?.textContent||""})',
  v=>v.match>=1&&v.cards>=1&&v.brand.includes("오젬픽")&&v.count?.includes("효능·효과 변경"));
 console.log("LIVE_UNREGISTERED_DRUG_SEARCH_OK",JSON.stringify({matches:ozempic.match,cards:ozempic.cards}));

 await evalPage('document.querySelector("#entries details.entry summary").click()');
 const relatedButton=await until("Same ingredient on-demand button visible",
  '({open:document.querySelector("#entries details.entry")?.open,button:document.querySelector("#entries .related-trigger")?.textContent||""})',
  v=>v.open&&v.button.includes("동일 성분 의약품"));
 console.log("ORIGINAL_RELATED_ON_DEMAND_BUTTON_OK",JSON.stringify(relatedButton));
 await evalPage('document.querySelector("#entries .related-trigger").click()');
 const relatedList=await until("Real-time related Ozempic ingredient matches",
  '({cards:document.querySelectorAll("#entries .related-item").length,text:document.querySelector("#entries .related-result")?.textContent||"",status:document.querySelector("#entries .related-status")?.textContent||""})',
  v=>v.cards>=5&&v.text.includes("위고비")&&v.text.includes("리벨서스"));
 console.log("RELATED_SEMAGLUTIDE_REAL_TIME_DISCOVERY_OK",JSON.stringify({items:relatedList.cards}));
 await evalPage('(()=>{const cards=[...document.querySelectorAll("#entries .related-item")];const wegovy=cards.find(x=>x.textContent.includes("위고비"));if(!wegovy)throw Error("No Wegovy related item");wegovy.querySelector(".related-check").click();return true})()');
 const relatedHistory=await until("Related drug official efficacy dates",
  '({items:[...document.querySelectorAll("#entries .related-item")].filter(x=>x.textContent.includes("위고비")).map(x=>({count:x.querySelectorAll(".related-detail details.entry").length,body:x.querySelector(".related-detail")?.textContent?.slice(0,360)||""}))})',
  v=>v.items?.some(x=>x.count>=1&&/2025|2024/.test(x.body)));
 console.log("RELATED_PRODUCT_OFFICIAL_EFFICACY_DETAIL_OK",JSON.stringify(relatedHistory.items[0]));

 await submit({keyword:"세마글루티드",year:"all",type:"all",scope:"all"});
 const ingredientMatches=await until("Global MFDS ingredient lookup",
  '({matches:document.querySelectorAll(".catalogue-choice").length,text:document.querySelector("#catalogueItems")?.textContent||"",count:document.querySelector("#resultCount")?.textContent||""})',
  v=>v.matches>=6&&v.text.includes("위고비")&&v.text.includes("오젬픽"));
 console.log("LIVE_INGREDIENT_PRODUCT_DISCOVERY_OK",ingredientMatches.matches);
 await evalPage('(()=>{const b=[...document.querySelectorAll(".catalogue-choice")].find(x=>x.textContent.includes("오젬픽"));if(!b)throw Error("no Ozempic product to select");b.click();return true})()');
 const chosen=await until("Product history for selected ingredient match",
  '({cards:document.querySelectorAll("details.entry").length,first:document.querySelector("details.entry")?.textContent||"",count:document.querySelector("#resultCount")?.textContent||""})',
  v=>v.cards>=1&&v.first.includes("오젬픽")&&v.count.includes("효능·효과 변경"));
 console.log("LIVE_PRODUCT_SELECT_HISTORY_OK",chosen.cards);
 await evalPage('document.querySelector("details.entry summary").click()');
 const relatedReady=await evalPage('document.querySelector("details.entry[open] .related-trigger")?.textContent||""');
 ensure(relatedReady.includes("동일 성분"),"On-demand related-drug button missing "+relatedReady);
 await evalPage('document.querySelector("details.entry[open] .related-trigger").click()');
 const related=await until("On-demand same-ingredient matched products",
  '({cards:document.querySelectorAll("details.entry[open] .related-item").length,txt:document.querySelector("details.entry[open] .related-result")?.textContent||"",status:document.querySelector("details.entry[open] .related-status")?.textContent||"",loading:document.querySelector("details.entry[open] .related-trigger")?.disabled})',
  v=>v.cards>=2&&v.txt.includes("위고비")&&!v.loading);
 console.log("SAME_INGREDIENT_OPT_IN_SEARCH_OK",JSON.stringify({cards:related.cards,sample:related.txt.slice(0,170)}));
 await submit({keyword:"노보노디스크",year:"all",type:"all",scope:"all"});
 const companyMatches=await until("Company-wide MFDS lookup",
  '({matches:document.querySelectorAll(".catalogue-choice").length,items:document.querySelector("#catalogueItems")?.textContent||""})',
  v=>v.matches>=8&&v.items.includes("노디트로핀"));
 console.log("LIVE_COMPANY_SEARCH_OK",companyMatches.matches);
 const pagingInitial=await evalPage('({total:document.querySelector("#catalogueTitle")?.textContent||"",moreHidden:document.querySelector("#catalogueFoot")?.hidden,buttonDisabled:document.querySelector("#catalogueMore")?.disabled})');
 ensure(!pagingInitial.moreHidden&&pagingInitial.total.includes("36개"),"Company first page hides actual remaining matches: "+JSON.stringify(pagingInitial));
 await evalPage('document.querySelector("#catalogueMore").click()');
 const second=await until("Company second page",
  '({items:document.querySelectorAll(".catalogue-choice").length,stillMore:!document.querySelector("#catalogueFoot").hidden,buttonDisabled:document.querySelector("#catalogueMore")?.disabled})',
  v=>v.items>=30&&v.stillMore&&!v.buttonDisabled);
 console.log("LIVE_COMPANY_PAGE_TWO_OK",JSON.stringify(second));
 await evalPage('document.querySelector("#catalogueMore").click()');
 const third=await until("Company third page exhausted",
  '({items:document.querySelectorAll(".catalogue-choice").length,moreHidden:document.querySelector("#catalogueFoot")?.hidden,display:getComputedStyle(document.querySelector("#catalogueFoot")).display,total:document.querySelector("#catalogueTitle")?.textContent||""})',
  v=>v.items===36&&v.moreHidden&&v.display==="none");
 console.log("LIVE_COMPANY_ALL_36_PAGES_OK",JSON.stringify(third));
 const id=++seq,awaitMetric=new Promise((resolve,reject)=>pending.set(id,{resolve,reject}));
 socket.send(JSON.stringify({id,method:"Emulation.setDeviceMetricsOverride",params:{width:390,height:844,deviceScaleFactor:1,mobile:true}}));
 await awaitMetric;
 const mobile=await evalPage('({width:window.innerWidth,documentWidth:document.documentElement.scrollWidth,searchRight:document.querySelector("#searchForm")?.getBoundingClientRect().right})');
 ensure(mobile.documentWidth<=mobile.width+3,"Mobile horizontal overflow "+JSON.stringify(mobile));
 console.log("MOBILE_EFFICACY_SEARCH_OK",JSON.stringify(mobile));
 console.log("MFDS_EFFICACY_INTERACTION_OK");
}finally{
 try{socket?.close()}catch{}
 proc.kill("SIGTERM");await sleep(260);
 await rm(profile,{recursive:true,force:true}).catch(()=>{});
}
