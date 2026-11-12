(()=>{
"use strict";
const $=id=>document.getElementById(id);
const API="https://mqkhtnryxyntrrfrfing.supabase.co/functions/v1/fda-monitor-webpush";
const STORE="fda_monitor_push_token_v1";
let working=false,enabled=false;
const supported=()=>isSecureContext&&"serviceWorker" in navigator&&"PushManager" in window&&"Notification" in window;
const ios=()=>/iPhone|iPad|iPod/i.test(navigator.userAgent)||(navigator.platform==="MacIntel"&&navigator.maxTouchPoints>1);
const standalone=()=>window.matchMedia("(display-mode: standalone)").matches||navigator.standalone===true;
function say(s){$("pushStatus").textContent=s}
function toggle(){
 $("pushEnable").disabled=working||!supported()||(ios()&&!standalone())||Notification.permission==="denied";
 $("pushEnable").textContent=enabled?"알림 다시 연결":"중요 발표 알림 받기";
 $("pushDisable").hidden=!enabled;$("pushDisable").disabled=working;
 $("pushTest").hidden=!enabled;$("pushTest").disabled=working;
}
function localToken(create=false){
 try{let t=localStorage.getItem(STORE);
 if(!t&&create){const arr=crypto.getRandomValues(new Uint8Array(32));t=[...arr].map(x=>x.toString(16).padStart(2,"0")).join("");localStorage.setItem(STORE,t)}
 return t;}catch{return null}
}
async function api(payload){
 const r=await fetch(API,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload),cache:"no-store"});
 const x=await r.json();if(!r.ok||x.error)throw Error(x.error||"알림 서버 오류");return x;
}
async function status(){
 if(!supported()||(ios()&&!standalone())){
  say(ios()?"iPhone에서는 Safari의 '홈 화면에 추가' 후 홈 화면에서 실행해야 합니다.":"이 브라우저에서는 웹 푸시를 사용할 수 없습니다.");toggle();return;
 }
 if(Notification.permission==="denied"){say("사이트 알림 권한이 차단돼 있어요. 브라우저 설정에서 허용해 주세요.");toggle();return}
 const token=localToken();if(!token){say("알림을 켜면 앞으로 새로 확인되는 주요 발표를 알려드려요.");toggle();return}
 try{
  const [info,reg]=await Promise.all([api({action:"status",device_token:token}),navigator.serviceWorker.getRegistration("./")]);
  enabled=!!info.enabled&&Notification.permission==="granted"&&!!(reg&&await reg.pushManager.getSubscription());
  say(enabled?"FDA 중요 발표 알림이 켜져 있습니다.":"알림이 꺼져 있습니다.");toggle();
 }catch(e){say("알림 설정 확인 실패: "+e.message)}
}
async function enable(){
 if(working||!supported()||(ios()&&!standalone()))return;
 // Browser requires permission request immediately inside the user-gesture handler.
 const grant=Notification.permission==="default"?Notification.requestPermission():Promise.resolve(Notification.permission);
 working=true;toggle();
 try{
  if(await grant!=="granted")throw Error("알림 권한이 허용되지 않았어요.");
  const token=localToken(true);if(!token)throw Error("브라우저 저장공간에 접근할 수 없어요.");
  const r=await fetch(API+"?view=config",{cache:"no-store"});
  if(!r.ok)throw Error("알림 서버 공개키 확인 실패");
  const cfg=await r.json(),key=cfg.public_key;
  if(!key)throw Error("알림 서버 키가 준비되지 않았어요.");
  const b=key.replace(/-/g,"+").replace(/_/g,"/");
  const raw=Uint8Array.from(atob(b.padEnd(Math.ceil(b.length/4)*4,"=")),x=>x.charCodeAt(0));
  const reg=await navigator.serviceWorker.register("./sw.js",{scope:"./"});
  await navigator.serviceWorker.ready;
  let sub=await reg.pushManager.getSubscription();
  if(!sub)sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:raw});
  await api({action:"subscribe",device_token:token,subscription:sub.toJSON()});
  enabled=true;say("알림이 켜졌습니다. 이후 확인되는 주요 발표부터 알려드립니다.");
 }catch(e){enabled=false;say("알림 연결 실패: "+e.message)}
 finally{working=false;toggle()}
}
async function disable(){
 if(working)return;working=true;toggle();
 try{
  const token=localToken();if(token)await api({action:"unsubscribe",device_token:token});
  const reg=await navigator.serviceWorker.getRegistration("./");
  const sub=reg&&await reg.pushManager.getSubscription();if(sub)await sub.unsubscribe();
  enabled=false;say("이 기기의 FDA 알림을 껐습니다.");
 }catch(e){say("알림 해제 실패: "+e.message)}
 finally{working=false;toggle()}
}
async function test(){
 if(working||!enabled)return;working=true;toggle();
 try{const t=localToken();if(!t)throw Error("등록된 기기가 없습니다.");
  await api({action:"test",device_token:t});
  say("테스트 알림을 발송했습니다. 브라우저 알림 센터에서 확인해 주세요.");
 }catch(e){say("테스트 발송 실패: "+e.message)}
 finally{working=false;toggle()}
}
$("pushEnable").addEventListener("click",enable);
$("pushDisable").addEventListener("click",disable);
$("pushTest").addEventListener("click",test);
status();
})();