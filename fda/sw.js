/* FDA monitor — show browser push notifications; no request interception. */
const APP="/pharm-briefing-desk/fda/";
self.addEventListener("push",event=>{
 let data={};try{data=event.data?.json()||{}}catch{data={body:event.data?.text()||""}}
 const title=String(data.title||"FDA 의약품 중요 발표").slice(0,100);
 const body=String(data.body||"FDA 신규 의약품 규제 발표가 확인됐습니다.").slice(0,180);
 const url=(()=>{try{const u=new URL(data.url||APP,self.location.origin);
  return u.origin===self.location.origin&&u.pathname.startsWith(APP)?u.href:self.location.origin+APP;
 }catch{return self.location.origin+APP}})();
 event.waitUntil(self.registration.showNotification(title,{
  body,tag:String(data.tag||"fda-monitor").slice(0,120),
  data:{url},requireInteraction:false
 }));
});
self.addEventListener("notificationclick",event=>{
 event.notification.close();const dest=event.notification.data?.url||self.location.origin+APP;
 event.waitUntil((async()=>{
  const clients=await self.clients.matchAll({type:"window",includeUncontrolled:true});
  for(const c of clients){if(c.url.startsWith(self.location.origin+APP)){
   await c.focus();if("navigate" in c)await c.navigate(dest);return;
  }}
  if(self.clients.openWindow)await self.clients.openWindow(dest);
 })());
});