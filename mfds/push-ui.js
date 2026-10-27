(()=>{
"use strict";
const $=x=>document.querySelector(x);
const URL="https://mqkhtnryxyntrrfrfing.supabase.co/functions/v1/mfds-webpush";
const TOKEN="mfds_indication_push_device_v1",PREFS="mfds_indication_push_preferences_v1";
let active=false,busy=false,timer=0;
const supported=()=>isSecureContext&&"serviceWorker" in navigator&&"PushManager" in window&&"Notification" in window;
const ios=()=>/iPhone|iPad|iPod/.test(navigator.userAgent)||(navigator.platform==="MacIntel"&&navigator.maxTouchPoints>1);
const standalone=()=>matchMedia("(display-mode: standalone)").matches||navigator.standalone===true;
const value=()=>({addition:$("#pushAddition").checked,change:$("#pushChange").checked,deletion:$("#pushDeletion").checked});
function apply(x){for(const [a,b] of [["addition","pushAddition"],["change","pushChange"],["deletion","pushDeletion"]])if(typeof x?.[a]==="boolean")$("#"+b).checked=x[a]}
function localToken(create=false){try{
 let v=localStorage.getItem(TOKEN);
 if(!v&&create){let b=crypto.getRandomValues(new Uint8Array(32));v=[...b].map(x=>x.toString(16).padStart(2,"0")).join("");localStorage.setItem(TOKEN,v)}
 return v;
}catch{return null}}
async function call(data){
 const r=await fetch(URL,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data),cache:"no-store"});
 const j=await r.json();if(!r.ok||j.error)throw Error(j.error||"알림 연결 오류");return j;
}
function say(msg){$("#pushStatus").textContent=msg}
function buttons(){
 $("#pushEnable").disabled=busy||!supported()||(ios()&&!standalone())||("Notification" in window&&Notification.permission==="denied");
 $("#pushDisable").disabled=busy;$("#pushDisable").hidden=!active;
 const test=$("#pushTest");if(test){test.disabled=busy;test.hidden=!active;}
 $("#pushEnable").textContent=active?"알림 다시 연결":"알림 받기";
 $("#notificationSettings").classList.toggle("active",active);
}
async function refresh(){
 try{apply(JSON.parse(localStorage.getItem(PREFS)||"null"))}catch{}
 if(!supported()||(ios()&&!standalone())){
  active=false;say(ios()?"iPhone에서는 Safari 공유 → 홈 화면에 추가 → 홈 화면의 앱에서 설정하세요.":"이 브라우저에서는 웹 푸시를 지원하지 않습니다.");buttons();return;
 }
 if(Notification.permission==="denied"){active=false;say("기기 설정에서 이 사이트의 알림 차단을 해제해 주세요.");buttons();return}
 const id=localToken();if(!id){active=false;say("현재 자동알림은 꺼져 있습니다.");buttons();return}
 try{
  const [data,reg]=await Promise.all([call({action:"status",device_token:id}),navigator.serviceWorker.getRegistration("./")]);
  active=!!data.enabled&&Notification.permission==="granted"&&!!(reg&&await reg.pushManager.getSubscription());
  if(data.registered)apply(data.preferences);
  say(active?"새 적응증 변경을 이 기기로 알리고 있습니다.":"현재 이 기기의 알림이 꺼져 있습니다.");
 }catch(e){active=false;say("알림 상태 확인 실패: "+e.message)}
 buttons();
}
async function enable(){
 if(busy||!supported()||(ios()&&!standalone()))return;
 // Request permission in the direct click event, before any awaits.
 const permission=Notification.permission==="default"?Notification.requestPermission():Promise.resolve(Notification.permission);
 busy=true;buttons();
 try{
  if(await permission!=="granted")throw Error("알림을 허용하지 않았습니다.");
  const id=localToken(true);if(!id)throw Error("브라우저 저장공간을 사용할 수 없습니다.");
  const conf=await fetch(URL+"?view=config",{cache:"no-store"}).then(r=>r.json());
  if(!conf.public_key)throw Error("알림 서버 인증키 없음");
  const key=conf.public_key.replace(/-/g,"+").replace(/_/g,"/");
  const raw=Uint8Array.from(atob(key.padEnd(Math.ceil(key.length/4)*4,"=")),x=>x.charCodeAt(0));
  const reg=await navigator.serviceWorker.register("./sw.js",{scope:"./"});
  await navigator.serviceWorker.ready;
  let sub=await reg.pushManager.getSubscription();
  if(!sub)sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:raw});
  await call({action:"subscribe",device_token:id,subscription:sub.toJSON(),preferences:value()});
  active=true;say("자동알림이 켜졌습니다. 이후 새로 확인된 적응증 변경부터 알려드립니다.");
 }catch(e){active=false;say("알림 연결 실패: "+e.message)}
 finally{busy=false;buttons()}
}
async function testNotification(){
 if(busy||!active)return;
 busy=true;buttons();
 try{
  const id=localToken();
  if(!id)throw Error("이 기기의 알림 등록 정보가 없습니다.");
  const result=await call({action:"test",device_token:id});
  if(!result.test_sent)throw Error("테스트 알림 발송이 확인되지 않았습니다.");
  say("테스트 알림을 발송했습니다. 기기의 잠금 화면이나 알림 센터에서 도착 여부를 확인해 주세요.");
 }catch(e){say("테스트 알림 실패: "+e.message)}
 finally{busy=false;buttons()}
}
async function disable(){
 if(busy)return;busy=true;buttons();
 try{
  const id=localToken();if(id)await call({action:"unsubscribe",device_token:id});
  const reg=await navigator.serviceWorker.getRegistration("./");
  const sub=reg&&await reg.pushManager.getSubscription();
  if(sub)await sub.unsubscribe();
  active=false;say("이 기기의 자동알림을 껐습니다.");
 }catch(e){say("알림 해제 실패: "+e.message)}
 finally{busy=false;buttons()}
}
function change(){
 try{localStorage.setItem(PREFS,JSON.stringify(value()))}catch{}
 clearTimeout(timer);if(!active)return;
 timer=setTimeout(async()=>{
  try{const id=localToken();if(id)await call({action:"preferences",device_token:id,preferences:value()});say("수신 유형 설정을 저장했습니다.")}catch(e){say("유형 설정 저장 실패: "+e.message)}
 },350);
}
$("#notificationSettings").addEventListener("click",()=>{
 const dialog=$("#pushDialog");if(dialog.showModal)dialog.showModal();else dialog.setAttribute("open","");
 refresh();
});
$("#pushClose").addEventListener("click",()=>$("#pushDialog").close());
$("#pushEnable").addEventListener("click",enable);
$("#pushDisable").addEventListener("click",disable);
$("#pushTest")?.addEventListener("click",testNotification);
for(const id of ["pushAddition","pushChange","pushDeletion"])$("#"+id).addEventListener("change",change);
})();