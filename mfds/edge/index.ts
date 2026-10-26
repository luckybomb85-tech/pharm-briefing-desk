import "jsr:@supabase/functions-js/edge-runtime.d.ts";

// MFDS indication-change monitor, v1. Public GET is read-only.
// POST collection requires an independent secret stored in Supabase Vault;
// no drug-approval claim is made without verification of changed indications.
const ORIGIN = "https://nedrug.mfds.go.kr";
const BASE = Deno.env.get("SUPABASE_URL") || "";
const KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
const HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Vary": "Origin",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  "Access-Control-Allow-Headers": "content-type,x-monitor-token",
  "Cache-Control": "no-store",
  "Content-Type": "application/json; charset=utf-8",
};
const reply = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: HEADERS });

function decodeHtml(s: string): string {
  return s.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&#39;|&#x27;|&apos;/gi, "'")
    .replace(/&nbsp;/g, " ").replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n)));
}
function plain(s: string): string {
  return decodeHtml(s.replace(/<span\s+class=["']s-th["'][^>]*>[\s\S]*?<\/span>/gi, "")
    .replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim());
}
async function db(method: string, route: string, data?: unknown, prefer?: string): Promise<any> {
  if (!BASE || !KEY) throw Error("Missing Supabase backend settings");
  const headers: Record<string, string> = {
    apikey: KEY, Authorization: "Bearer " + KEY, "Content-Type": "application/json",
  };
  if (prefer) headers.Prefer = prefer;
  const r = await fetch(BASE + "/rest/v1/" + route, {
    method, headers, body: data === undefined ? undefined : JSON.stringify(data),
  });
  const text = await r.text();
  if (!r.ok) throw Error("Database " + method + " failed: " + r.status + " " + text.slice(0, 280));
  return text ? JSON.parse(text) : null;
}
async function html(url: string): Promise<string> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const r = await fetch(url, {
      signal: controller.signal,
      headers: { "User-Agent": "Mozilla/5.0 (compatible; MFDS-news-monitor/1.0)",
        Accept: "text/html,application/xhtml+xml" },
    });
    if (!r.ok) throw Error("MFDS HTTP " + r.status);
    const s = await r.text();
    if (!s.includes("<table") || s.length < 10000) throw Error("Unexpected MFDS HTML response");
    return s;
  } finally { clearTimeout(timer); }
}
type Item = {
  source: string; source_id: string; source_url: string; title: string;
  category: string; company: string; product: string; ingredient: string;
  published_at: string | null; effective_at: string | null; stage: string; attachment_names: string[];
  classification: string; rationale: string; alert_state: string;
};
function parseRows(markup: string, source: "review" | "change_order"): Item[] {
  // Restrict extraction to actual table body rows, not headers or inline scripts.
  const all = [...markup.matchAll(/<tbody\b[^>]*>([\s\S]*?)<\/tbody>/gi)]
    .flatMap(x => [...x[1].matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)].map(m => m[1]));
  const items: Item[] = [];
  const seen = new Set<string>();
  for (const row of all) {
    const cells = [...row.matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/gi)].map(m => m[1]);
    if (source === "review" && cells.length < 9) continue;
    if (source === "change_order" && cells.length < 8) continue;
    const linkCell = cells[source === "review" ? 2 : 1];
    const link = linkCell.match(/<a\b[^>]*href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/i);
    if (!link) continue;
    const relative = decodeHtml(link[1]);
    const title = plain(link[2]);
    const id = source === "review"
      ? relative.match(/[?&]jdgmnResultInfoSeq=(\d+)/)?.[1]
      : relative.match(/[?&]infoNo=(\d+)/)?.[1];
    const cls = source === "change_order" ? relative.match(/[?&]infoClassCode=(\d+)/)?.[1] : "";
    if (!id) continue;
    const key = source === "review" ? id : id + "-" + (cls || "0");
    if (seen.has(key)) continue;
    seen.add(key);
    const linkUrl = source === "review"
      ? ORIGIN + "/pbp/CCBAC02/getItem?jdgmnResultInfoSeq=" + encodeURIComponent(id)
      : ORIGIN + "/CCBAR01F012/getList/getItem?infoNo=" + encodeURIComponent(id) +
        "&infoClassCode=" + encodeURIComponent(cls || "");
    const dates = cells.map(plain).filter(x => /^\d{4}-\d\d-\d\d$/.test(x));
    const category = plain(cells[source === "review" ? 1 : 2]);
    const published = source === "review" ? plain(cells[8]) : plain(cells[6]);
    // Change-order columns: [4] date of legal effect, [6] first posted date, [7] stage date.
    const effective = source === "change_order" ? plain(cells[4]) : null;
    const isChange = source === "review" && /변경/.test(title);
    const promising = /적응증|효능.{0,2}효과|치료대상|치료\s*범위|대상환자|허가\s*확대/i.test(title);
    const classification = source === "review"
      ? (isChange ? "unverified" : "other")
      : "monitor_only";
    items.push({
      source, source_id: key, source_url: linkUrl, title, category,
      company: source === "review" ? plain(cells[3]) : "",
      product: source === "review" ? plain(cells[4]) : "",
      ingredient: source === "review" ? plain(cells[5]) : "",
      published_at: /^\d{4}-\d\d-\d\d$/.test(published || "") ? published : null,
      effective_at: /^\d{4}-\d\d-\d\d$/.test(effective || "") ? effective : null,
      stage: source === "change_order" ? plain(cells[5]) : "",
      attachment_names: [], classification,
      rationale: source === "review"
        ? (isChange ? "변경허가 심사자료 공개. 적응증 추가 여부는 첨부 보고서 확인 필요."
          : "신규허가 또는 일반 심사자료")
        : "변경명령 게시물. 적응증 추가와 무관할 수 있음.",
      alert_state: "baseline",
    });
  }
  return items;
}
async function attachReportNames(item: Item): Promise<void> {
  try {
    const s = await html(item.source_url);
    const names = [...s.matchAll(/<span\b[^>]*id=["']fileNameTd\d+["'][^>]*>([\s\S]*?)<\/span>/gi)]
      .map(m => plain(m[1])).filter(Boolean);
    item.attachment_names = [...new Set(names)].slice(0, 10);
    const joined = names.join(" ");
    if (/적응증|효능.{0,2}효과|치료.{0,15}(?:추가|확대|축소|삭제)|질환.{0,12}(?:추가|확대|축소|삭제)|암.{0,22}(?:추가|확대|축소|삭제)|병용요법|병용.{0,5}확대|치료.?차수/i.test(joined)) {
      item.classification = "clinical_lead";
      item.rationale = "첨부 보고서 파일명에 적응증·치료영역 관련 표현. 실제 변경일 및 변경 전후 내용 확인 필요.";
    }
  } catch (_e) {
    item.rationale += " (첨부파일명 조회 실패)";
  }
}
async function fetchList(source: "review" | "change_order"): Promise<Item[]> {
  const path = source === "review" ? "/pbp/CCBAC02/getList" : "/CCBAR01F012/getList";
  const first = parseRows(await html(ORIGIN + path + "?page=1&limit=30"), source);
  if (first.length < 10) throw Error("MFDS list appears truncated for " + source);
  // A second page is needed only if all 30 entries are very recent, so large
  // publication bursts do not produce missed items.
  const lastDate = first.at(-1)?.published_at || "";
  const recentLimit = new Date(Date.now() - 48 * 3600 * 1000).toISOString().slice(0, 10);
  if (first.length >= 30 && lastDate && lastDate >= recentLimit) {
    const second = parseRows(await html(ORIGIN + path + "?page=2&limit=30"), source);
    return [...first, ...second.filter(x => !first.some(a => a.source_id === x.source_id))];
  }
  return first;
}

async function archiveSource(source: "review" | "change_order", maxPages: number): Promise<Record<string, unknown>> {
  const [progress] = await db("GET", "mfds_monitor_archive_cursor?select=source,next_page,total_pages,finished&source=eq."+source+"&limit=1");
  if (!progress) throw Error("No archive cursor row for "+source);
  if (progress.finished) return { source, complete:true, total_pages:progress.total_pages, newly_saved:0, pages:0 };
  const path = source==="review"?"/pbp/CCBAC02/getList":"/CCBAR01F012/getList";
  let saved=0, checked=0, page=Number(progress.next_page), lastDate="";
  let totalPages=progress.total_pages||null;
  for (let n=0;n<maxPages;n++) {
    try {
      const doc=await html(ORIGIN+path+"?page="+page+"&limit=50");
      if (!totalPages) {
        const match=doc.match(/name=["']totalPages["'][^>]*value=["'](\d+)["']/i);
        if (match) totalPages=Number(match[1]);
      }
      const rows=parseRows(doc,source);
      if (source==="change_order" && rows.length) await db("POST","rpc/mfds_monitor_repair_order_dates",{
        payload:rows.map(x=>({source_id:x.source_id,published_at:x.published_at,effective_at:x.effective_at}))
      });
      if (!rows.length && page === 1) throw Error("Empty initial archive page");
      if (!rows.length) {
        await db("PATCH","mfds_monitor_archive_cursor?source=eq."+source,
          {finished:true,total_pages:totalPages,last_run_at:new Date().toISOString(),last_error:null},"return=minimal");
        return {source,complete:true, pages:checked, newly_saved:saved, last_date:lastDate};
      }
      const existing=await db("GET","mfds_monitor_items?select=source_id&source=eq."+source+
        "&source_id=in.("+rows.map(x=>x.source_id).join(",")+")&limit=100");
      const known=new Set<string>((existing||[]).map((x: {source_id:string})=>x.source_id));
      const fresh=rows.filter(x=>!known.has(x.source_id));
      // Fetch PDF filenames only for changed reviews (never the PDF body).
      // Limit concurrency to respect the MFDS origin and Edge request budget.
      if (source==="review") {
        const important=fresh.filter(x=>x.classification==="unverified");
        for(let i=0;i<important.length;i+=5) {
          await Promise.all(important.slice(i,i+5).map(attachReportNames));
        }
      }
      fresh.forEach(x=>{x.alert_state="baseline";});
      if(fresh.length) await db("POST","mfds_monitor_items?on_conflict=source,source_id",
        fresh,"resolution=ignore-duplicates,return=minimal");
      saved+=fresh.length;checked++;
      lastDate=rows.at(-1)?.published_at||"";
      const ended=rows.length<50 || (totalPages!==null && page>=totalPages);
      await db("PATCH","mfds_monitor_archive_cursor?source=eq."+source,{
        next_page:page+1,last_completed_page:page,total_pages:totalPages,finished:ended,
        last_run_at:new Date().toISOString(),last_error:null
      },"return=minimal");
      page++;
      if(ended)break;
    }catch(e){
      const msg=String(e).slice(0,270);
      await db("PATCH","mfds_monitor_archive_cursor?source=eq."+source,
        {last_error:msg,last_run_at:new Date().toISOString()},"return=minimal");
      return {source,pages:checked,newly_saved:saved,next_page:page,last_date:lastDate,error:msg};
    }
  }
  return {source,pages:checked,newly_saved:saved,next_page:page,last_date:lastDate,total_pages:totalPages};
}

async function repairOrderHistory(): Promise<unknown> {
  let corrected=0;
  for(let page=1;page<=2;page++){
    const rows=parseRows(await html(ORIGIN+"/CCBAR01F012/getList?page="+page+"&limit=50"),"change_order");
    corrected+=await db("POST","rpc/mfds_monitor_repair_order_dates",{
      payload:rows.map(x=>({source_id:x.source_id,published_at:x.published_at,effective_at:x.effective_at}))
    });
  }
  return {corrected};
}
async function backfill(): Promise<unknown> {
  // Low-impact incremental archive import, separate from daily monitoring.
  const results=[];
  results.push(await archiveSource("review",3));
  results.push(await archiveSource("change_order",2));
  return {mode:"backfill",results,ran_at:new Date().toISOString()};
}
async function archiveFeed(query: URLSearchParams): Promise<unknown> {
  const kind=query.get("kind")==="orders"?"change_order":"review";
  const limit=Math.max(10,Math.min(50,Number(query.get("limit")||30)||30));
  const offset=Math.max(0,Math.min(10000,Number(query.get("offset")||0)||0));
  let route="mfds_monitor_items?select=id,source,source_id,source_url,title,category,company,product,ingredient,published_at,effective_at,stage,attachment_names,classification,rationale,alert_state,first_seen_at"+
    "&source=eq."+kind+"&order=published_at.desc.nullslast,id.desc&offset="+offset+"&limit="+(limit+1);
  if(kind==="review") route+="&title=ilike."+encodeURIComponent("*변경*");
  const year=query.get("year")||"";
  if(/^20\d\d$/.test(year)) route+="&published_at=gte."+year+"-01-01&published_at=lt."+(Number(year)+1)+"-01-01";
  const text=(query.get("q")||"").trim().slice(0,70).replace(/[(),.*%]/g," ").trim();
  if(text) {
    const term=encodeURIComponent("*"+text+"*");
    route+="&or="+encodeURIComponent("(title.ilike."+decodeURIComponent(term)+",company.ilike."+decodeURIComponent(term)+",product.ilike."+decodeURIComponent(term)+",ingredient.ilike."+decodeURIComponent(term)+")");
  }
  const rows=await db("GET",route);
  return {items:rows.slice(0,limit),has_more:rows.length>limit,next_offset:offset+limit,kind,year:year||null};
}

function equalHash(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let same = 0; for (let i = 0; i < a.length; i++) same |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return same === 0;
}
async function validToken(token: string): Promise<boolean> {
  if (token.length < 32 || token.length > 200) return false;
  const [stored] = await db("GET", "mfds_monitor_auth?select=token_hash&id=eq.true&limit=1");
  if (!stored) return false;
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token));
  const hex = [...new Uint8Array(digest)].map(n => n.toString(16).padStart(2, "0")).join("");
  return equalHash(hex, stored.token_hash);
}
async function collect(): Promise<unknown> {
  const [run] = await db("POST", "mfds_monitor_runs", [{status:"running"}], "return=representation");
  const report = { status: "success", reviews_checked: 0, changes_checked: 0,
    new_total: 0, new_candidates: 0, errors: [] as string[] };
  for (const source of ["review", "change_order"] as const) {
    try {
      const incoming = await fetchList(source);
      if (source === "change_order") await db("POST","rpc/mfds_monitor_repair_order_dates",{
        payload:incoming.map(x=>({source_id:x.source_id,published_at:x.published_at,effective_at:x.effective_at}))
      });
      if (source === "review") report.reviews_checked = incoming.length;
      else report.changes_checked = incoming.length;
      const knownRows = await db("GET",
        "mfds_monitor_items?select=source_id&source=eq." + source +
        "&order=id.desc&limit=5000");
      const known = new Set<string>((knownRows || []).map((x: any) => x.source_id));
      const baseline = known.size === 0;
      const fresh = incoming.filter(x => !known.has(x.source_id));
      const reportCandidates = fresh.filter(x => source === "review" && /변경/.test(x.title));
      for (let offset = 0; offset < reportCandidates.length; offset += 3) {
        await Promise.all(reportCandidates.slice(offset, offset + 3).map(attachReportNames));
      }
      for (const x of fresh) {
        x.alert_state = baseline ? "baseline" : "new";
      }
      if (fresh.length) {
        await db("POST", "mfds_monitor_items?on_conflict=source,source_id",
          fresh, "resolution=ignore-duplicates,return=minimal");
      }
      report.new_total += baseline ? 0 : fresh.length;
      report.new_candidates += baseline ? 0 :
        fresh.filter(x => x.classification === "verified_change").length;
    } catch (e) {
      report.errors.push(source + ": " + String(e).slice(0, 220));
    }
  }
  report.status = report.errors.length ? "partial" : "success";
  await db("PATCH", "mfds_monitor_runs?id=eq." + run.id,
    { ...report, finished_at: new Date().toISOString() }, "return=minimal");
  return { ...report, run_id: run.id };
}

async function feed(): Promise<unknown> {
  const [events, leads, recent, runs, stats] = await Promise.all([
    db("GET", "mfds_monitor_events?select=id,product,company,ingredient,event_date,event_type,change_area,title,before_text,after_text,details,evidence_url,mfds_url,verification,alert_state&verification=in.(reviewed,official_confirmed)&order=event_date.desc,id.desc&limit=300"),
    db("GET", "mfds_monitor_items?select=id,source,source_id,source_url,title,company,product,ingredient,published_at,attachment_names,classification,rationale,alert_state&source=eq.review&classification=eq.clinical_lead&order=published_at.desc,id.desc&limit=150"),
    db("GET", "mfds_monitor_items?select=id,source,source_id,source_url,title,category,company,product,ingredient,published_at,effective_at,stage,attachment_names,classification,rationale,alert_state,approval_changed_at,change_type,change_summary,first_seen_at&order=published_at.desc.nullslast,id.desc&limit=200"),
    db("GET", "mfds_monitor_runs?select=id,started_at,finished_at,status,reviews_checked,changes_checked,errors&order=id.desc&limit=5"),
    db("GET", "rpc/mfds_monitor_archive_stats")
  ]);
  return {
    events,leads,items:recent,runs,
    counts:{verified_events:stats.verified,leads:(leads||[]).length,review_records:stats.review_changes,orders_records:stats.orders_total,review_total:stats.review_total},
    archive:stats.cursors,
    description:"실제 허가변경일을 확인한 이벤트와 변경심사자료/변경명령의 공개이력을 별도 구분합니다. 미확인 자료는 확정 변경으로 분류하지 않습니다."
  };
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response(null,{status:204,headers:HEADERS});
  try {
    if (req.method === "GET") {
      const url=new URL(req.url);
      return reply(url.searchParams.get("view")==="archive"
        ? await archiveFeed(url.searchParams) : await feed());
    }
    if (req.method !== "POST") return reply({error:"Unsupported method"},405);
    if (!await validToken(req.headers.get("x-monitor-token") || "")) return reply({error:"Unauthorized"},401);
    const input=await req.json().catch(()=>({}));
    if(input?.mode==="backfill") return reply(await backfill());
    if(input?.mode==="repair_order_dates") return reply(await repairOrderHistory());
    return reply(await collect());
  } catch (e) {
    return reply({error:String(e).slice(0,420)},500);
  }
});