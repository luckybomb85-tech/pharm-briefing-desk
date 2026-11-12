(()=>{
"use strict";
const $=id=>document.getElementById(id);
const API="https://mqkhtnryxyntrrfrfing.supabase.co/functions/v1/fda-monitor-webpush";
const STORE="fda_monitor_push_token_v1";
let working=false,enabled=false;
const ios=()=>/iPhone|iPad|iPod/i.test(navigator.userAgent)||(navigator.platform==="MacIntel"&&navigator.maxTouchPoints>1);
const android=()=>/Android/i.test(navigator.userAgent);
const standalone=()=>matchMedia("(display-mode: standalone)").matches||navigator.standalone===true;
const supported=()=>isSecureContext&&"serviceWorker" in navigator&&"PushManager" in window&&"Notification" in window;
const currentPrefs=()=>window.FDADashboard?.getSettings()?.alerts||{safety:true,approval:true,recall:true,guidance:true,regulation:true};
const modal=()=>window.FDADashboard?.openDialog("notifyDialog");
function say(message){$("notifyMessage").textContent=message}
function redraw(){
 const b=$("bellBtn");b.classList.toggle("active",enabled);
 b.setAttribute("aria-label",enabled?"FDA 알림 켜짐 · 설정 보기":"FDA 알림 켜기");
 b.title=enabled?"FDA 알림 켜짐 · 설정":"FDA 알림 켜기";
 $("notifyEnable").hidden=enabled;
 $("notifyDisable").hidden=!enabled;
 $("notifyTest").hidden=!enabled;
 $("notifyEnable").disabled=working;
 $("notifyDisable").disabled=working;
 $("notifyTest").disabled=working;
}
function localToken(create=false){
 try{
  let t=localStorage.getItem(STORE);
  if(!t&&create){
   const arr=crypto.getRandomValues(new Uint8Array(32));
   t=[...arr].map(v=>v.toString(16).padStart(2,"0")).join("");
   localStorage.setItem(STORE,t);
  }
  return t;
 }catch{return null}
}
async function api(x){
 const r=await fetch(API,{method:"POST",headers:{"content-type":"application/json"},
 body:JSON.stringify(x),cache:"no-store"});
 const data=await r.json();
 if(!r.ok||data.error)throw Error(data.error||"알림 서버 연결 실패");
 return data;
}
function instructions(){
 // Both device guides remain visible regardless of the visitor's current device.
 $("iosInstructions").hidden=false;
 $("androidInstructions").hidden=false;
 $("otherInstructions").hidden=true;
}
function showHelp(message){
 instructions();say(message);redraw();modal();
}
async function status(){
 redraw();
 if(!supported()||(ios()&&!standalone()))return;
 if(Notification.permission!=="granted")return;
 const token=localToken();
 if(!token)return;
 try{
  const [res,reg]=await Promise.all([
   api({action:"status",device_token:token}),navigator.serviceWorker.getRegistration("./")
  ]);
  enabled=!!res.enabled&&!!(reg&&await reg.pushManager.getSubscription());
  redraw();
 }catch{redraw()}
}
async function enable(){
 if(working)return;
 if(ios()&&!standalone()){
  showHelp("아이폰: 홈 화면에 추가 → 홈 화면 앱 실행 → 🔔 알림 허용");return;
 }
 if(!supported()){
  showHelp("현재 브라우저에서 자동알림 사용 불가 · 기기별 설정 방법 확인");return;
 }
 if(Notification.permission==="denied"){
  showHelp("현재 알림 차단 상태 · 브라우저 사이트 설정에서 허용 필요");return;
 }
 // Permission must be requested in the direct button click, before any await.
 const permission=Notification.permission==="default"?
  Notification.requestPermission():Promise.resolve(Notification.permission);
 working=true;redraw();
 try{
  if(await permission!=="granted")throw Error("알림 권한 미허용");
  const token=localToken(true);if(!token)throw Error("기기 저장소 사용 불가");
  const conf=await fetch(API+"?view=config",{cache:"no-store"}).then(r=>r.json());
  if(!conf.public_key)throw Error("알림 서버 인증키 확인 필요");
  const text=conf.public_key.replace(/-/g,"+").replace(/_/g,"/");
  const raw=Uint8Array.from(atob(text.padEnd(Math.ceil(text.length/4)*4,"=")),c=>c.charCodeAt(0));
  const reg=await navigator.serviceWorker.register("./sw.js",{scope:"./"});
  await navigator.serviceWorker.ready;
  let sub=await reg.pushManager.getSubscription();
  if(!sub)sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:raw});
  await api({action:"subscribe",device_token:token,subscription:sub.toJSON(),preferences:currentPrefs()});
  enabled=true;
  say("FDA 자동알림 활성화 완료 · 선택한 분야 알림 수신");
  instructions();redraw();modal();
 }catch(e){
  enabled=false;showHelp("알림 연결 실패: "+e.message);
 }finally{working=false;redraw()}
}
async function disable(){
 if(working)return;working=true;redraw();
 try{
  const token=localToken();if(token)await api({action:"unsubscribe",device_token:token});
  const reg=await navigator.serviceWorker.getRegistration("./");
  const sub=reg&&await reg.pushManager.getSubscription();
  if(sub)await sub.unsubscribe();
  enabled=false;say("FDA 자동알림 해제 완료");
 }catch(e){say("알림 해제 실패: "+e.message)}
 finally{working=false;redraw()}
}
async function test(){
 if(working||!enabled)return;
 working=true;redraw();
 try{
  const token=localToken();
  if(!token)throw Error("등록된 기기가 없어.");
  await api({action:"test",device_token:token});
  say("테스트 알림 발송 완료 · 기기 알림 센터 확인");
 }catch(e){say("테스트 알림 실패: "+e.message)}
 finally{working=false;redraw()}
}
async function savePreferences(prefs){
 const token=localToken();if(!token||!enabled)return;
 const r=await api({action:"preferences",device_token:token,preferences:prefs});
 if(!r.ok)throw Error("알림 항목 저장 실패");
}
$("bellBtn").addEventListener("click",()=>{
 if(enabled){
  instructions();say("FDA 자동알림 활성화 상태 · 테스트 또는 해제 가능");modal();
 }else enable();
});
$("notifyEnable").addEventListener("click",enable);
$("notifyDisable").addEventListener("click",disable);
$("notifyTest").addEventListener("click",test);
$("notifyCopyLink").addEventListener("click",async()=>{
 try{await navigator.clipboard.writeText(location.href.split("?")[0]);say("웹사이트 주소 복사 완료")}
 catch{say("주소 복사 실패 · 브라우저 공유 메뉴의 '링크 복사' 선택")}
});
window.FDAPush={savePreferences,refreshStatus:status,isEnabled:()=>enabled};
status();
})();