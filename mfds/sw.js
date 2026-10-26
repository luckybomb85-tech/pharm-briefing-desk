/* MFDS indication tracker — notify only, no request interception or offline cache. */
const APP="/pharm-briefing-desk/mfds/";
self.addEventListener("push",event=>{
 let payload={};
 try{payload=event.data?.json()||{};}catch{
  payload={body:event.data?.text()||""};
 }
 const title=String(payload.title||"의약품 적응증 변경이력").slice(0,95);
 const body=String(payload.body||"새 효능·효과 변경이력이 확인됐습니다.").slice(0,175);
 const url=String(payload.url||APP);
 const validUrl=(()=>{
  try{const value=new URL(url,self.location.origin);
   return value.origin===self.location.origin&&value.pathname.startsWith(APP)?value.href:self.location.origin+APP;
  }catch{return self.location.origin+APP;}
 })();
 event.waitUntil(self.registration.showNotification(title,{
  body,tag:String(payload.tag||"mfds-indication").slice(0,128),
  data:{url:validUrl},requireInteraction:false
 }));
});
self.addEventListener("notificationclick",event=>{
 event.notification.close();
 const url=event.notification.data?.url||self.location.origin+APP;
 event.waitUntil((async()=>{
  const windows=await self.clients.matchAll({type:"window",includeUncontrolled:true});
  for(const client of windows){
   if(client.url.startsWith(self.location.origin+APP)){
    await client.focus();
    if("navigate" in client)await client.navigate(url);
    return;
   }
  }
  if(self.clients.openWindow)await self.clients.openWindow(url);
 })());
});