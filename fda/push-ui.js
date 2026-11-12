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
 $("iosInstructions").hidden=!ios();
 $("androidInstructions").hidden=!android();
 $("otherInstructions").hidden=ios()||android();
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
  showHelp("아이폰에서는 Safari에 '홈 화면에 추가'한 뒤 그 앱에서 알림을 켤 수 있어.");return;
 }
 if(!supported()){
  showHelp("현재 브라우저에서는 직접 알림을 켤 수 없어. 아래 기기별 설정 방법을 확인해 줘.");return;
 }
 if(Notification.permission==="denied"){
  showHelp("이미 알림이 차단돼 있어. 아래 안내에 따라 사이트 알림을 허용해 줘.");return;
 }
 // Permission must be requested in the direct button click, before any await.
 const permission=Notification.permission==="default"?
  Notification.requestPermission():Promise.resolve(Notification.permission);
 working=true;redraw();
 try{
  if(await permission!=="granted")throw Error("알림 권한이 허용되지 않았어.");
  const token=localToken(true);if(!token)throw Error("이 기기의 로컬 저장소를 사용할 수 없어.");
  const conf=await fetch(API+"?view=config",{cache:"no-store"}).then(r=>r.json());
  if(!conf.public_key)throw Error("알림 서버 인증키가 준비되지 않았어.");
  const text=conf.public_key.replace(/-/g,"+").replace(/_/g,"/");
  const raw=Uint8Array.from(atob(text.padEnd(Math.ceil(text.length/4)*4,"=")),c=>c.charCodeAt(0));
  const reg=await navigator.serviceWorker.register("./sw.js",{scope:"./"});
  await navigator.serviceWorker.ready;
  let sub=await reg.pushManager.getSubscription();
  if(!sub)sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:raw});
  await api({action:"subscribe",device_token:token,subscription:sub.toJSON(),preferences:currentPrefs()});
  enabled=true;
  say("알림이 켜졌어. 설정에서 선택한 FDA 발표 분야를 이 기기로 알려줄게.");
  instructions();redraw();modal();
 }catch(e){
  enabled=false;showHelp("알림 연결을 완료하지 못했어: "+e.message);
 }finally{working=false;redraw()}
}
async function disable(){
 if(working)return;working=true;redraw();
 try{
  const token=localToken();if(token)await api({action:"unsubscribe",device_token:token});
  const reg=await navigator.serviceWorker.getRegistration("./");
  const sub=reg&&await reg.pushManager.getSubscription();
  if(sub)await sub.unsubscribe();
  enabled=false;say("FDA 자동알림을 껐어.");
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
  say("테스트 알림을 보냈어. 휴대전화 알림 센터에서 확인해 줘.");
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
  instructions();say("현재 FDA 알림이 켜져 있어. 아래에서 테스트하거나 끌 수 있어.");modal();
 }else enable();
});
$("notifyEnable").addEventListener("click",enable);
$("notifyDisable").addEventListener("click",disable);
$("notifyTest").addEventListener("click",test);
$("notifyCopyLink").addEventListener("click",async()=>{
 try{await navigator.clipboard.writeText(location.href.split("?")[0]);say("웹사이트 주소를 복사했어. Safari나 Chrome에서 열어 줘.")}
 catch{say("주소를 복사하지 못했어. 브라우저의 공유 메뉴에서 '링크 복사'를 선택해 줘.")}
});
window.FDAPush={savePreferences,refreshStatus:status,isEnabled:()=>enabled};
status();
})();