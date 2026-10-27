import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import webpush from "npm:web-push@3.6.7";

const BASE=Deno.env.get("SUPABASE_URL")||"";
const API_KEY=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")||"";
const SITE="https://luckybomb85-tech.github.io";
const APP=SITE+"/pharm-briefing-desk/mfds/";
const HEADERS={
 "Access-Control-Allow-Origin":SITE,
 "Access-Control-Allow-Methods":"GET,POST,OPTIONS",
 "Access-Control-Allow-Headers":"content-type,x-monitor-token",
 "Cache-Control":"no-store",
 "Content-Type":"application/json; charset=utf-8",
 "Vary":"Origin"
};
function respond(data:unknown,status=200){
 return new Response(JSON.stringify(data),{status,headers:HEADERS});
}
async function db(method:string,path:string,payload?:any,prefer?:string):Promise<any>{
 if(!BASE||!API_KEY)throw Error("Backend credentials unavailable");
 const h:Record<string,string>={"apikey":API_KEY,"Authorization":"Bearer "+API_KEY,"Content-Type":"application/json"};
 if(prefer)h.Prefer=prefer;
 const res=await fetch(BASE+"/rest/v1/"+path,{method,headers:h,body:payload===undefined?undefined:JSON.stringify(payload)});
 const raw=await res.text();
 if(!res.ok)throw Error("Database "+res.status+": "+raw.slice(0,170));
 return raw?JSON.parse(raw):null;
}
async function sha(text:string):Promise<string>{
 const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(text));
 return [...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,"0")).join("");
}
function constantEqual(a:string,b:string){
 if(a.length!==b.length)return false;
 let value=0;for(let i=0;i<a.length;i++)value|=a.charCodeAt(i)^b.charCodeAt(i);
 return value===0;
}
async function authorizeDispatch(input:string):Promise<boolean>{
 if(input.length<32||input.length>200)return false;
 const stored=await db("GET","mfds_monitor_auth?select=token_hash&id=eq.true&limit=1");
 return !!stored?.[0]?.token_hash&&constantEqual(await sha(input),stored[0].token_hash);
}
const isToken=(v:unknown)=>typeof v==="string"&&/^[a-f0-9]{64}$/.test(v);
function permittedEndpoint(endpoint:string){
 try{
  const u=new URL(endpoint);const h=u.hostname.toLowerCase();
  return u.protocol==="https:"&&u.username===""&&u.password===""&&endpoint.length<1500&&
   (h.endsWith(".push.apple.com")||h==="fcm.googleapis.com"||h.endsWith(".googleapis.com")||
    h==="updates.push.services.mozilla.com"||h.endsWith(".mozilla.com")||
    h.endsWith(".notify.windows.com")||h.endsWith(".microsoft.com"));
 }catch{return false}
}
function prefs(input:any){
 return {
  notify_addition:input?.addition!==false,
  notify_change:input?.change!==false,
  notify_deletion:input?.deletion!==false
 };
}
async function vapid(){
 const data=await db("POST","rpc/mfds_webpush_get_vapid",{});
 if(!data?.public||!data?.private)throw Error("Push server VAPID is not configured");
 return data as {public:string,private:string};
}
async function manage(input:any):Promise<any>{
 const action=String(input?.action||"");
 if(!isToken(input?.device_token))throw Error("This device needs a new subscription token");
 const tokenHash=await sha(input.device_token);
 const path="mfds_webpush_subscriptions";
 if(action==="status"){
  const rows=await db("GET",path+"?select=enabled,notify_addition,notify_change,notify_deletion,updated_at&device_token_hash=eq."+tokenHash+"&limit=1");
  return {registered:!!rows.length,enabled:rows[0]?.enabled||false,
   preferences:{addition:rows[0]?.notify_addition??true,change:rows[0]?.notify_change??true,deletion:rows[0]?.notify_deletion??true},
   updated_at:rows[0]?.updated_at||null};
 }
 if(action==="subscribe"){
  const sub=input?.subscription||{};
  if(!permittedEndpoint(sub.endpoint)||!/^[-_A-Za-z0-9]{75,145}$/.test(sub?.keys?.p256dh||"")||
    !/^[-_A-Za-z0-9]{14,64}$/.test(sub?.keys?.auth||""))throw Error("Invalid browser push subscription");
  const existing=await db("GET",path+"?select=id&device_token_hash=eq."+tokenHash+"&limit=1");
  const data={
   device_token_hash:tokenHash,endpoint_hash:await sha(sub.endpoint),
   endpoint:sub.endpoint,p256dh:sub.keys.p256dh,auth_secret:sub.keys.auth,
   enabled:true,...prefs(input.preferences),updated_at:new Date().toISOString(),last_error:null
  };
  if(existing.length){
   await db("PATCH",path+"?device_token_hash=eq."+tokenHash,data,"return=minimal");
  }else{
   await db("POST",path+"?on_conflict=device_token_hash",data,"resolution=merge-duplicates,return=minimal");
  }
  return {ok:true,enabled:true,preferences:input.preferences||{addition:true,change:true,deletion:true}};
 }
 if(action==="preferences"){
  const update={...prefs(input.preferences),updated_at:new Date().toISOString()};
  const rows=await db("PATCH",path+"?device_token_hash=eq."+tokenHash+"&select=id",update,"return=representation");
  return {ok:rows.length>0};
 }
 if(action==="test"){
  const rows=await db("GET",path+"?select=id,endpoint,p256dh,auth_secret,last_sent_at&enabled=eq.true&device_token_hash=eq."+tokenHash+"&limit=1");
  if(!rows.length)throw Error("먼저 이 기기의 알림을 등록해 주세요.");
  const sub=rows[0];
  if(sub.last_sent_at&&Date.now()-Date.parse(sub.last_sent_at)<60000)
   throw Error("테스트 알림은 1분 간격으로 발송할 수 있습니다.");
  const keys=await vapid();
  webpush.setVapidDetails(SITE,keys.public,keys.private);
  const body=JSON.stringify({
   title:"적응증 변경 모니터 · 테스트",
   body:"테스트 알림입니다. 신규 적응증 변경이 확인되면 이 기기로 알려드립니다.",
   url:APP,tag:"mfds-webpush-test"
  });
  try{
   await webpush.sendNotification({endpoint:sub.endpoint,keys:{p256dh:sub.p256dh,auth:sub.auth_secret}},
    body,{TTL:300,urgency:"high",timeout:11000});
   await db("PATCH",path+"?id=eq."+sub.id,{last_sent_at:new Date().toISOString(),last_error:null},"return=minimal");
   return {ok:true,test_sent:true};
  }catch(e){
   const code=Number((e as any)?.statusCode||0);
   if(code===404||code===410)await db("PATCH",path+"?id=eq."+sub.id,{
    enabled:false,last_error:"push subscription expired"
   },"return=minimal");
   throw Error(code===404||code===410?"알림 등록이 만료됐습니다. 다시 연결해 주세요.":"테스트 푸시 발송에 실패했습니다. 잠시 후 다시 시도해 주세요.");
  }
 }
 if(action==="unsubscribe"){
  const rows=await db("PATCH",path+"?device_token_hash=eq."+tokenHash+"&select=id",
   {enabled:false,updated_at:new Date().toISOString()},"return=representation");
  return {ok:true,previously_registered:rows.length>0};
 }
 throw Error("Unknown push settings operation");
}
function groupedKey(x:any,kind:string){
 // An identical ingredient/approval day may be represented by multiple
 // strengths. Emit one notification for the same brand/formulation family.
 const brand=String(x.product||"").split("(")[0]
  .replace(/\d+(?:\.\d+)?\s*(?:밀리그램|mg|마이크로그램|mcg|밀리리터|mL|ml|IU|단위).*$/i,"")
  .replace(/[\s.,·]/g,"").toLocaleLowerCase("ko-KR");
 return [x.changed_at,x.company||"",x.ingredient||"",brand,kind].join(":");
}
function kindOf(row:any):string{
 const kind=String(row.classification||"");
 const adds=Array.isArray(row.added_lines)?row.added_lines.length:0;
 const removals=Array.isArray(row.removed_lines)?row.removed_lines.length:0;
 if(kind.includes("삭제")&&removals&&!adds)return "삭제";
 if(kind.includes("추가")&&adds&&!removals)return "추가";
 if(removals&&!adds)return "삭제";
 if(adds&&!removals)return "추가";
 return "변경";
}
async function scanRecent():Promise<any>{
 const cutoff=new Date(Date.now()-15*86400000).toISOString().slice(0,10);
 const [hist,roles,gaps,state]=await Promise.all([
  db("GET","mfds_monitor_efficacy_history?select=id,item_seq,product,company,ingredient,changed_at,classification,diff_status,added_lines,removed_lines&changed_at=gte."+cutoff+"&order=changed_at.desc,id.desc&limit=120"),
  db("GET","mfds_monitor_product_roles?select=item_seq,watch_scope,classification_confidence&watch_scope=eq.primary&classification_confidence=in.(official_list,verified_review)&limit=1500"),
  db("GET","mfds_monitor_indication_gap_watches?select=item_seq,observed_change_date,status&status=eq.closed&limit=200"),
  db("GET","mfds_webpush_state?select=id,initialized,activated_at&id=eq.1&limit=1")
 ]);
 const initialized=!!state?.[0]?.initialized;
 const eligibleRoles=new Set((roles||[]).map((r:any)=>r.item_seq));
 const gapsClosed=new Set((gaps||[]).map((r:any)=>r.item_seq+"@"+r.observed_change_date));
 const all=new Map<string,any>();
 const nowDate=new Date(Date.now()+9*3600000).toISOString().slice(0,10);
 for(const row of hist||[]){
  const validRole=eligibleRoles.has(row.item_seq)||gapsClosed.has(row.item_seq+"@"+row.changed_at);
  if(!validRole||row.changed_at>nowDate||row.diff_status!=="compared")continue;
  if(!(Array.isArray(row.added_lines)&&row.added_lines.length) &&
     !(Array.isArray(row.removed_lines)&&row.removed_lines.length))continue;
  const kind=kindOf(row);
  const key=await sha(groupedKey(row,kind));
  if(!all.has(key))all.set(key,{event_key:"change-"+key,item_seq:row.item_seq,product:row.product,
   company:row.company||"",change_kind:kind,change_date:row.changed_at,eligible:initialized});
 }
 let newRows:any[]=[];
 if(all.size){
  newRows=await db("POST","mfds_webpush_events?on_conflict=event_key&select=event_key,item_seq,product,company,change_kind,change_date,eligible",
   [...all.values()],"resolution=ignore-duplicates,return=representation");
 }
 if(!initialized){
  await db("PATCH","mfds_webpush_state?id=eq.1",{initialized:true,last_scanned_at:new Date().toISOString(),last_error:null},"return=minimal");
  return {bootstrap:true,baseline_events:all.size,queued:0};
 }
 let queued=0;
 if(newRows.length){
  const subscriptions=await db("GET","mfds_webpush_subscriptions?select=id,enabled,notify_addition,notify_change,notify_deletion&enabled=eq.true&limit=400");
  const deliveries=[];
  for(const event of newRows){
   for(const user of subscriptions){
    const typeOk=event.change_kind==="추가"?user.notify_addition:
      event.change_kind==="삭제"?user.notify_deletion:user.notify_change;
    if(typeOk)deliveries.push({subscription_id:user.id,event_key:event.event_key});
   }
  }
  for(let i=0;i<deliveries.length;i+=100){
   await db("POST","mfds_webpush_deliveries?on_conflict=subscription_id,event_key",
    deliveries.slice(i,i+100),"resolution=ignore-duplicates,return=minimal");
  }
  queued=deliveries.length;
 }
 await db("PATCH","mfds_webpush_state?id=eq.1",{
  last_scanned_at:new Date().toISOString(),last_error:null},"return=minimal");
 return {bootstrap:false,candidates:all.size,new_events:newRows.length,queued};
}
async function sendQueued():Promise<any>{
 const jobs=await db("POST","rpc/mfds_webpush_claim",{p_limit:18});
 if(!Array.isArray(jobs)||!jobs.length)return {claimed:0,sent:0,failed:0};
 const keys=await vapid();
 webpush.setVapidDetails(SITE,keys.public,keys.private);
 const results=[];
 for(let i=0;i<jobs.length;i+=3){
  const batch=jobs.slice(i,i+3);
  const part=await Promise.all(batch.map(async (job:any)=>{
   const url=APP+"?seq="+encodeURIComponent(job.item_seq)+"&date="+encodeURIComponent(job.change_date);
   const body=JSON.stringify({title:"적응증 변경 모니터 · "+job.change_kind,
    body:String(job.product).slice(0,100)+" · "+job.change_date+" 허가변경",
    url,tag:job.event_key});
   try{
    await webpush.sendNotification({endpoint:job.endpoint,keys:{p256dh:job.p256dh,auth:job.auth_secret}},body,
     {TTL:86400,urgency:"normal",timeout:11000});
    await db("PATCH","mfds_webpush_deliveries?id=eq."+job.delivery_id,
     {status:"sent",sent_at:new Date().toISOString(),last_error:null},"return=minimal");
    await db("PATCH","mfds_webpush_subscriptions?id=eq."+job.subscription_id,
     {last_sent_at:new Date().toISOString(),last_error:null},"return=minimal");
    return {sent:true};
   }catch(e){
    const code=Number((e as any)?.statusCode||0);
    const gone=code===404||code===410;
    await db("PATCH","mfds_webpush_deliveries?id=eq."+job.delivery_id,{
      status:gone?"dead":"pending",last_error:String(e).slice(0,180)
    },"return=minimal");
    if(gone)await db("PATCH","mfds_webpush_subscriptions?id=eq."+job.subscription_id,
      {enabled:false,last_error:"push subscription expired"},"return=minimal");
    return {sent:false,code};
   }
  }));
  results.push(...part);
 }
 return {claimed:jobs.length,sent:results.filter(x=>x.sent).length,
  failed:results.filter(x=>!x.sent).length};
}
Deno.serve(async (req:Request)=>{
 if(req.method==="OPTIONS")return new Response(null,{status:204,headers:HEADERS});
 try{
  if(req.method==="GET"){
   const url=new URL(req.url);
   if(url.searchParams.get("view")==="config"){
    const k=await vapid();
    return respond({public_key:k.public,site:APP});
   }
   return respond({error:"Not found"},404);
  }
  if(req.method!=="POST")return respond({error:"Method not allowed"},405);
  const input=await req.json().catch(()=>({}));
  if(input.action==="dispatch"){
   const token=req.headers.get("x-monitor-token")||"";
   if(!await authorizeDispatch(token))return respond({error:"Unauthorized"},401);
   const scanned=await scanRecent();
   const delivery=await sendQueued();
   return respond({mode:"webpush_dispatch",scanned,delivery});
  }
  if(req.headers.get("origin")!==SITE)return respond({error:"Origin not authorized"},403);
  if(JSON.stringify(input).length>5800)return respond({error:"Subscription too large"},413);
  return respond(await manage(input));
 }catch(e){return respond({error:String(e).slice(0,300)},400)}
});
