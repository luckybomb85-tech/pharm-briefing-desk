import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import * as XLSX from "npm:xlsx@0.18.5";

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



function decodeXmlAttr(raw: string): string {
  let s=raw;
  for(let i=0;i<3;i++){
    const t=decodeHtml(s).replace(/&#x([0-9a-fA-F]+);/g,(_,n)=>String.fromCodePoint(parseInt(n,16)));
    if(t===s)break;
    s=t;
  }
  return s.replace(/&nbsp;/g," ").replace(/\u00a0/g," ");
}
function extractEfficacyLines(docData: string): string[] {
  // The official MFDS per-revision XML is transmitted as an escaped HTML
  // data-docdata attribute, not as an XML API response.
  let xml=decodeXmlAttr(docData);
  xml=xml.replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g,(_,t)=>t)
    .replace(/<SECTION\b[^>]*title="([^"]+)"[^>]*>/gi,(_,t)=>"\n"+decodeXmlAttr(t)+"\n")
    .replace(/<ARTICLE\b[^>]*title="([^"]*)"[^>]*\/?>/gi,(_,t)=>"\n"+decodeXmlAttr(t)+"\n")
    .replace(/<PARAGRAPH\b[^>]*>/gi,"\n")
    .replace(/<\/PARAGRAPH>/gi,"\n")
    .replace(/<BR\b[^>]*\/?>/gi,"\n")
    .replace(/<\/(?:ARTICLE|SECTION|ROW|CELL)>/gi,"\n")
    .replace(/<[^>]+>/g," ");
  const seen=new Set<string>();
  const lines:string[]=[];
  for(const chunk of decodeXmlAttr(xml).split(/\r?\n/)){
    const cleaned=chunk.replace(/\s+/g," ").trim();
    if(!cleaned || cleaned==="효능효과" || cleaned==="효능·효과") continue;
    const canonical=cleaned.normalize("NFKC").replace(/\s+/g," ").trim();
    if(seen.has(canonical))continue;
    seen.add(canonical);lines.push(cleaned);
  }
  return lines;
}
function comparisonKey(line: string): string {
  return line.normalize("NFKC").replace(/^\s*\d{1,2}\s*[.)]\s*/,"").replace(/[\u00a0\s]+/g," ").trim();
}
type EfficacyVersion={history_seq:number,changed_at:string,lines:string[]};
function parseOfficialHistoryVersions(htmlText: string): EfficacyVersion[] {
  const result:EfficacyVersion[]=[];
  for(const row of htmlText.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)){
    const m=row[1].match(/data-docdata="([\s\S]*?)"\s+onclick="detailHist\(&#39;(\d+)&#39;,\s*&#39;(\d{4}-\d{2}-\d{2})&#39;/i);
    if(!m)continue;
    const lines=extractEfficacyLines(m[1]);
    if(!lines.length)continue;
    result.push({history_seq:Number(m[2]),changed_at:m[3],lines});
  }
  return result.sort((a,b)=>a.changed_at.localeCompare(b.changed_at)||a.history_seq-b.history_seq);
}
async function syncOfficialEfficacyHistory(): Promise<unknown> {
  const targets=await db("GET","mfds_monitor_drug_targets?select=item_seq,product,company,ingredient,source_url,active&active=eq.true&order=item_seq.asc&limit=100");
  const results:Record<string,unknown>[]=[];
  for(const target of targets){
    try{
      const detail=await html(target.source_url);
      const section=detail.slice(detail.indexOf('id="tblChf"'));
      const tbody=section.match(/<tbody\b[^>]*>([\s\S]*?)<\/tbody>/i)?.[1]||"";
      if(!tbody)throw Error("Official efficacy-change history table missing");
      const officialDates=new Set<string>();
      const officialRows=[...tbody.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)];
      for(const row of officialRows){
        const cols=[...row[1].matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/gi)].map(x=>plain(x[1]));
        const day=cols.find(x=>/^\d{4}-\d{2}-\d{2}$/.test(x));
        if(day&&/효능.?효과/.test(cols.at(-1)||""))officialDates.add(day);
      }
      await db("POST","mfds_monitor_history_summaries?on_conflict=item_seq",{
        item_seq:target.item_seq,official_change_total:officialRows.length,
        official_efficacy_total:officialDates.size,verified_at:new Date().toISOString()
      },"resolution=merge-duplicates,return=minimal");
      const url=ORIGIN+"/pbp/CCBBB01/getItemChangeHistList?itemSeq="+target.item_seq+"&docType=EE&page=1";
      const versionResponse=await fetch(url,{headers:{"User-Agent":"Mozilla/5.0 (compatible; MFDS-monitor/1.0)","Accept":"text/html"}});
      if(!versionResponse.ok)throw Error("MFDS history HTTP "+versionResponse.status);
      const versionHtml=await versionResponse.text();
      if(!versionHtml.includes('id="hist_list"'))throw Error("MFDS version list markup missing");
      const versions=parseOfficialHistoryVersions(versionHtml);
      // MFDS marks the first digital version with a star. It is a comparison
      // baseline, not proof of a new indication on that date.
      const indexed=new Map<string,Record<string,unknown>>();
      const now=new Date().toISOString();
      const older=versions.slice().sort((a,b)=>a.changed_at.localeCompare(b.changed_at));
      for(let i=0;i<older.length;i++){
        const newer=older[i],prior=older[i-1];
        const beforeKeys=new Set((prior?.lines||[]).map(comparisonKey));
        const afterKeys=new Set(newer.lines.map(comparisonKey));
        const added=prior ? newer.lines.filter(x=>!beforeKeys.has(comparisonKey(x))) : [];
        const removed=prior ? prior.lines.filter(x=>!afterKeys.has(comparisonKey(x))) : [];
        const status=prior?"compared":"baseline";
        const classification=prior ? (
          added.length&&removed.length?"변경":added.length?"추가":removed.length?"삭제":"변경"
        ):"비교 기준";
        indexed.set(newer.changed_at,{
          item_seq:target.item_seq,product:target.product,company:target.company,
          ingredient:target.ingredient||"",changed_at:newer.changed_at,change_section:"효능·효과",
          classification,evidence_url:target.source_url,
          before_text:prior?.lines.join("\n")||null,
          after_text:newer.lines.join("\n"),added_lines:added,removed_lines:removed,
          diff_status:status,history_seq:newer.history_seq,
          prior_history_seq:prior?.history_seq||null,detail_checked_at:now,
          last_seen_at:now
        });
      }
      // Some MFDS history dates predate electronic document conversion and
      // have no version XML. Retain them as change dates, without inventing text.
      for(const day of officialDates) {
        if(!indexed.has(day)){
          indexed.set(day,{
            item_seq:target.item_seq,product:target.product,company:target.company,
            ingredient:target.ingredient||"",changed_at:day,change_section:"효능·효과",
            classification:"변경",evidence_url:target.source_url,
            before_text:null,after_text:null,
            added_lines:[],removed_lines:[],diff_status:"not_available",
            history_seq:null,prior_history_seq:null,detail_checked_at:now,last_seen_at:now
          });
        }
      }
      const records=[...indexed.values()];
      if(records.length)await db("POST","mfds_monitor_efficacy_history?on_conflict=item_seq,changed_at,change_section",
        records,"resolution=merge-duplicates,return=minimal");
      await db("PATCH","mfds_monitor_drug_targets?item_seq=eq."+target.item_seq,{
        last_checked_at:now,last_checked_status:"ok:"+records.length
      },"return=minimal");
      results.push({product:target.product,dates:records.length,comparable:records.filter(x=>x.diff_status==="compared").length,undigitized:records.filter(x=>x.diff_status==="not_available").length});
    }catch(error){
      const message=String(error).slice(0,250);
      await db("PATCH","mfds_monitor_drug_targets?item_seq=eq."+target.item_seq,{
        last_checked_at:new Date().toISOString(),last_checked_status:message
      },"return=minimal");
      results.push({product:target.product,error:message});
    }
  }
  return {mode:"efficacy_sync",target_count:targets.length,results};
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
  let route="mfds_monitor_items?select=id,source,source_id,source_url,title,category,company,product,ingredient,published_at,effective_at,approval_changed_at,change_type,change_summary,stage,attachment_names,classification,rationale,alert_state,first_seen_at"+
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



// Compare efficacy statements by therapeutic context, not by raw HTML
// paragraphs. Cosmetic differences never count as added/deleted indications.
type EffectEntry={text:string,context:string,heading:boolean};
type EffectDelta={kind:"added"|"removed"|"modified",context:string,text:string,before_text?:string,after_text?:string};
function normalizedEffectText(source:string):string{
 return source.normalize("NFKC").toLocaleLowerCase("ko-KR")
  .replace(/항암\s*화학\s*요법/g,"화학요법")
  .replace(/\s+/g,"").replace(/[().,;:·\-–—'"‘’“”/]/g,"");
}
function effectHeading(line:string):boolean {
 const s=line.trim();
 if(s.length>155||s.length<3)return false;
 if(/환자에서|환자의 치료|치료로서|투여|병용요법|단독요법|수술 전 보조요법|수술 후 보조요법|확인된 경우/.test(s))return false;
 return (/(?:세포암|편평세포암|선암|비인두암|림프종|백혈병|골수종|유방암|흑색종|식도암|폐암|위암|난소암|간암|직장암|당뇨병|비만|염증성 장질환).*\([^)]+\)\s*$/.test(s)
 || /^\d{1,2}[.)]\s*[^.]+(?:암|환자|환자에의|질환)\s*$/.test(s)
 || /^[가-힣\s/()-]+(?:암|질환|병)\s*$/.test(s));
}
function effectStatements(text:string):EffectEntry[]{
 let context="효능·효과";
 const result:EffectEntry[]=[];
 for(const raw of text.split(/\r?\n/)){
  const line=raw.replace(/\s+/g," ").trim();
  if(!line)continue;
  const heading=effectHeading(line);
  if(heading)context=line.replace(/\s*\([^)]*\)\s*$/,"").replace(/^\d{1,2}[.)]\s*/,"").trim();
  result.push({text:line,context,heading});
 }
 return result;
}
function effectDice(a:string,b:string):number{
 if(a===b)return 1;
 if(!a||!b)return 0;
 const gram=(s:string)=>{
  const map=new Map<string,number>();
  for(let i=0;i<s.length-1;i++){const g=s.slice(i,i+2);map.set(g,(map.get(g)||0)+1);}
  return map;
 };
 const x=gram(a),y=gram(b);let count=0;
 for(const [key,n] of x)count+=Math.min(n,y.get(key)||0);
 return 2*count/Math.max(1,a.length+b.length-2);
}
function importantTherapeuticChange(a:string,b:string):boolean{
 // Numeric/line-of-therapy, biomarker and regimen changes have clinical
 // meaning, even when just one character changed in a long paragraph.
 const signatures=[
  /\d+\s*차\s*(?:치료|이상|요법)?/g,
  /수술\s*전|수술\s*후|절제\s*가능|절제\s*불가능/g,
  /단독\s*요법|병용\s*요법|병용\s*투여/g,
  /양성|음성|변이|전이성|재발성|국소\s*진행성|확장\s*병기|제한\s*병기/g,
  /(?:pd-l1|her-?2|egfr|alk|braf|ras)[^\s,.;)]{0,18}/gi,
  /[≥≤<>]\s*\d+(?:\.\d+)?\s*%?/g,
  /(?:페메트렉시드|카보플라틴|시스플라틴|파클리탁셀|젬시타빈|에토포시드|엔코라페닙)/g
 ];
 for(const pattern of signatures){
  const sig=(s:string)=>[...new Set((s.match(pattern)||[]).map(normalizedEffectText))].sort().join("|");
  if(sig(a)!==sig(b))return true;
 }
 return false;
}

function sharedNamedRegimen(a:string,b:string):boolean{
 const extract=(s:string)=>{
  const matches=[...s.matchAll(/([가-힣A-Za-z0-9-]{4,})(?:과의|와의)\s*병용요법/g)];
  return matches.map(x=>x[1]).filter(x=>!/(?:화학요법|항암화학요법|방사선요법|기존요법|처치요법)$/.test(x));
 };
 const current=new Set(extract(b));
 return extract(a).some(x=>current.has(x));
}
function substantiveEffectDiff(before:string,after:string):{
 changes:EffectDelta[],editorial_changes:number,change_type:string,
 summary_lines:string[],added_count:number,removed_count:number,modified_count:number
}{
 const old=effectStatements(before),current=effectStatements(after);
 if(!before.trim()||!after.trim())return {changes:[],editorial_changes:0,change_type:"확인 필요",summary_lines:[],added_count:0,removed_count:0,modified_count:0};
 const used=new Set<number>(), unmatched:number[]=[];
 const changes:EffectDelta[]=[];let editorial=0;
 for(let currentIndex=0;currentIndex<current.length;currentIndex++){
  const fresh=current[currentIndex];
  const normalized=normalizedEffectText(fresh.text);
  let found=-1;
  for(let i=0;i<old.length;i++){
   if(used.has(i))continue;
   if(normalizedEffectText(old[i].text)===normalized){found=i;break;}
  }
  if(found>=0){used.add(found);if(old[found].text!==fresh.text)editorial++;continue;}
  unmatched.push(currentIndex);
 }
 // Mark new headings as context only. They are not full treatment indications.
 const toCompare=unmatched.filter(i=>!current[i].heading), usedAfter=new Set<number>();
 for(const currentIndex of toCompare){
  const next=current[currentIndex],newKey=normalizedEffectText(next.text);
  let bestIndex=-1,bestScore=0;
  for(let i=0;i<old.length;i++){
   if(used.has(i)||old[i].heading)continue;
   const previous=old[i];
   const sim=effectDice(newKey,normalizedEffectText(previous.text));
   const sameContext=normalizedEffectText(next.context)===normalizedEffectText(previous.context);
   // Cross-context matching is allowed for a heading being retitled, but
   // requires very high text similarity to avoid merging distinct indications.
   const strongRegimen=sharedNamedRegimen(previous.text,next.text);
   const limit=sameContext?0.72:(strongRegimen?0.48:0.90);
   if(sim>=limit&&sim>bestScore){bestScore=sim;bestIndex=i;}
  }
  if(bestIndex>=0){
   used.add(bestIndex);usedAfter.add(currentIndex);
   const previous=old[bestIndex];
   const meaningfulClinicalChange=importantTherapeuticChange(previous.text,next.context+" "+next.text);
   const sameExistingRegimen=sharedNamedRegimen(previous.text,next.text) && !meaningfulClinicalChange;
   if((bestScore>=0.94&&!importantTherapeuticChange(previous.text,next.text))||sameExistingRegimen){
    editorial++;
   }else{
    changes.push({kind:"modified",context:next.context,text:next.text,
      before_text:previous.text,after_text:next.text});
   }
  }
 }
 for(const currentIndex of toCompare){
  if(usedAfter.has(currentIndex))continue;
  const e=current[currentIndex];
  if(e.text.length>=18)changes.push({kind:"added",context:e.context,text:e.text,after_text:e.text});
  else editorial++;
 }
 for(let i=0;i<old.length;i++){
  const previous=old[i];if(used.has(i)||previous.heading)continue;
  if(previous.text.length>=18)changes.push({kind:"removed",context:previous.context,text:previous.text,before_text:previous.text});
  else editorial++;
 }
 const added=changes.filter(x=>x.kind==="added").length;
 const removed=changes.filter(x=>x.kind==="removed").length;
 const modified=changes.filter(x=>x.kind==="modified").length;
 let type="표현 수정";
 if(added&&removed)type="추가·삭제";
 else if(added&&modified)type="추가·변경";
 else if(added)type="추가";
 else if(removed&&modified)type="삭제·변경";
 else if(removed)type="삭제";
 else if(modified)type="변경";
 const grouped=new Map<string,EffectDelta[]>();
 for(const delta of changes){
  const context=delta.context||"효능·효과";
  if(!grouped.has(context))grouped.set(context,[]);
  grouped.get(context)!.push(delta);
 }
 const summary=[...grouped.entries()].flatMap(([context,items])=>{
  const adds=items.filter(x=>x.kind==="added"),rems=items.filter(x=>x.kind==="removed"),mods=items.filter(x=>x.kind==="modified");
  const short=context==="효능·효과"?"":context+" · ";
  const first=adds[0]||mods[0]||rems[0];
  return first?[short+first.text]:[];
 });
 return {changes,editorial_changes:editorial,change_type:type,
  summary_lines:summary.slice(0,4),added_count:added,removed_count:removed,modified_count:modified};
}

function editorialChangeKind(eventType:string):string {
  if(eventType==="addition")return "추가";
  if(eventType==="deletion"||eventType==="reduction")return "삭제";
  return "변경";
}
async function filteredEfficacyFeed(query:URLSearchParams):Promise<unknown> {
  // Dedicated efficacy-only read API. All dates are approval-change dates,
  // never the publication dates of delayed review reports.
  const [history,editorial]=await Promise.all([
    db("GET","mfds_monitor_efficacy_history?select=id,item_seq,product,company,ingredient,changed_at,classification,before_text,after_text,added_lines,removed_lines,diff_status,evidence_url&order=changed_at.desc,id.desc&limit=1000"),
    db("GET","mfds_monitor_events?select=id,product,company,ingredient,event_date,event_type,change_area,title,before_text,after_text,details,evidence_url,mfds_url,verification&verification=in.(reviewed,official_confirmed)&order=event_date.desc,id.desc&limit=500")
  ]);
  const editorialKey=(p:string,d:string)=>p.replace(/\s+/g,"").replace(/\([^)]*\)/g,"")+"@"+d;
  const reviewed=new Map<string,any>();
  for(const event of editorial||[]) reviewed.set(editorialKey(event.product,event.event_date),event);
  const included=new Set<string>();
  const merged:any[]=[];
  for(const row of history||[]){
    if(row.diff_status==="baseline")continue;
    const key=editorialKey(row.product,row.changed_at);
    const event=reviewed.get(key);
    if(event)included.add(key);
    const analyzed=substantiveEffectDiff(row.before_text||"",row.after_text||"");
    let kind=analyzed.change_type;
    if(event && ["addition","deletion","reduction"].includes(event.event_type) && kind!=="확인 필요"&&kind!=="표현 수정"){
      if(event.event_type==="addition"&&analyzed.added_count)kind="추가";
      else if(event.event_type!=="addition"&&analyzed.removed_count)kind="삭제";
    }
    merged.push({
      id:"official-"+row.id,changed_at:row.changed_at,product:row.product,
      company:row.company,ingredient:row.ingredient,change_type:kind,
      title:event?.title||null,summary:event?.details||"",
      before_text:row.before_text||"",after_text:row.after_text||"",
      added_lines:analyzed.changes.filter(x=>x.kind==="added").map(x=>x.text),
      removed_lines:analyzed.changes.filter(x=>x.kind==="removed").map(x=>x.text),
      change_details:analyzed.changes,editorial_changes:analyzed.editorial_changes,
      summary_lines:analyzed.summary_lines,added_count:analyzed.added_count,
      removed_count:analyzed.removed_count,modified_count:analyzed.modified_count,
      diff_status:row.diff_status,evidence_url:row.evidence_url,
      source_kind:"official",comparison_kind:"literal",verified_summary:!!event
    });
  }
  for(const event of editorial||[]){
    const key=editorialKey(event.product,event.event_date);
    if(included.has(key))continue;
    included.add(key);
    merged.push({
      id:"reviewed-"+event.id,changed_at:event.event_date,product:event.product,
      company:event.company,ingredient:event.ingredient,
      change_type:editorialChangeKind(event.event_type),
      title:event.title||"",summary:event.details||"",
      before_text:event.before_text||"",after_text:event.after_text||"",
      added_lines:[],removed_lines:[],change_details:[],
      editorial_changes:0,summary_lines:[event.title||event.after_text].filter(Boolean),
      added_count:event.event_type==="addition"?1:0,
      removed_count:event.event_type==="deletion"||event.event_type==="reduction"?1:0,modified_count:0,
      diff_status:"editorial_summary",
      evidence_url:event.mfds_url||event.evidence_url,
      supplementary_url:event.evidence_url,
      source_kind:"reviewed",comparison_kind:"summary",verified_summary:true
    });
  }
  const year=query.get("year")||"";
  const kind=query.get("type")||"all";
  const scope=query.get("scope")||"all";
  const needle=(query.get("q")||"").trim().toLocaleLowerCase("ko-KR").slice(0,80);
  const rows=merged.filter((row:any)=>{
    if(/^20\d{2}$/.test(year)&&!row.changed_at.startsWith(year))return false;
    if(["추가","삭제","변경"].includes(kind)){
      const contains=kind==="추가"?(row.added_count>0||row.change_type==="추가"):
        kind==="삭제"?(row.removed_count>0||row.change_type==="삭제"):
        (row.modified_count>0||row.change_type==="변경");
      if(!contains)return false;
    }
    if(scope==="compared"&&!["compared","editorial_summary"].includes(row.diff_status))return false;
    if(scope==="uncompared"&&["compared","editorial_summary"].includes(row.diff_status))return false;
    if(needle&&![row.product,row.company,row.ingredient].join(" ").toLocaleLowerCase("ko-KR").includes(needle))return false;
    return true;
  });
  rows.sort((a:any,b:any)=>b.changed_at.localeCompare(a.changed_at)||a.product.localeCompare(b.product,"ko-KR"));
  const total=rows.length,offset=Math.max(0,Math.min(20000,Number(query.get("offset")||0)||0));
  const period=total?{start:rows[total-1].changed_at,end:rows[0].changed_at}:null;
  const product_count=new Set(rows.map((x:any)=>x.product)).size;
  const limit=Math.max(10,Math.min(50,Number(query.get("limit")||20)||20));
  const countByType={
    added:rows.filter((x:any)=>x.added_count>0||x.change_type==="추가").length,
    changed:rows.filter((x:any)=>x.modified_count>0||x.change_type==="변경").length,
    deleted:rows.filter((x:any)=>x.removed_count>0||x.change_type==="삭제").length
  };
  return {items:rows.slice(offset,offset+limit),total,has_more:offset+limit<total,
    next_offset:offset+limit,counts:countByType,period,product_count,
    source_description:"효능·효과 변경일을 기준으로 정렬. 비교 가능한 버전은 식약처 공식 효능·효과 XML 원문을 대조합니다. 일부 구버전 원문 및 품목은 미수집."};
}


// Public, read-only lookup across the live MFDS product catalogue.
// No unauthenticated request inserts/updates monitoring or historical records.
type CatalogueItem={
 item_seq:string;product:string;company:string;ingredient:string;
 permit_date:string;status:string;source_url:string;
};
function parseDrugCatalogue(markup:string):CatalogueItem[]{
 const body=markup.match(/<tbody\b[^>]*>([\s\S]*?)<\/tbody>/i)?.[1]||"";
 const results:CatalogueItem[]=[];
 const seen=new Set<string>();
 for(const row of body.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)){
  const cells=[...row[1].matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/gi)].map(m=>plain(m[1]));
  if(cells.length<12)continue;
  const item_seq=row[1].match(/getItemDetail\?itemSeq=(\d{9})/)?.[1]||"";
  if(!item_seq||seen.has(item_seq))continue;
  seen.add(item_seq);
  const product=cells[1],company=cells[3],ingredient=cells[11];
  if(!product||!company)continue;
  results.push({
   item_seq,product,company,ingredient,
   permit_date:/^\d{4}-\d{2}-\d{2}$/.test(cells[7]||"")?cells[7]:"",
   status:cells[9]||"",
   source_url:ORIGIN+"/pbp/CCBBB01/getItemDetail?itemSeq="+item_seq
  });
 }
 return results;
}
async function lookupMFDSCatalogue(params:URLSearchParams):Promise<unknown>{
 const q=(params.get("q")||"").normalize("NFKC").trim().replace(/\s+/g," ");
 if(q.length<2||q.length>70)return {matches:[],has_more:false,total_at_least:0,page:1,message:"검색어는 2~70자로 입력해주세요."};
 const page=Math.max(1,Math.min(50,Number(params.get("page")||1)||1));
 const fields=["itemName","ingrName1","entpName"];
 const pageSize=15; // MFDS searchDrug's fixed actual page size; the 'limit' query string is ignored.
 const jobs=await Promise.allSettled(fields.map(async field=>{
  const url=new URL(ORIGIN+"/searchDrug");
  url.searchParams.set("searchYn","Y");
  url.searchParams.set("page",String(page));
  url.searchParams.set(field,q);
  const markup=await html(url.toString());
  const items=parseDrugCatalogue(markup);
  const countText=markup.match(/class=["']sch_info["'][\s\S]{0,280}?<strong>\s*([\d,]+)\s*<\/strong>/i)?.[1];
  const total=countText?Number(countText.replace(/,/g,"")):items.length;
  return {field,items,total,has_more:total>page*pageSize};
 }));
 const ok=jobs.filter((j):j is PromiseFulfilledResult<{field:string,items:CatalogueItem[],total:number,has_more:boolean}>=>j.status==="fulfilled");
 if(!ok.length)throw Error("식약처 품목 검색 서버에 연결하지 못했습니다.");
 const matches=new Map<string,CatalogueItem>();
 for(const part of ok)for(const item of part.value.items)matches.set(item.item_seq,item);
 const norm=q.toLocaleLowerCase("ko-KR").replace(/\s/g,"");
 const ranked=[...matches.values()].filter(item=>
  [item.product,item.company,item.ingredient].some(x=>x.toLocaleLowerCase("ko-KR").replace(/\s/g,"").includes(norm))
 ).sort((a,b)=>{
  const score=(x:CatalogueItem)=>{
   const product=x.product.toLocaleLowerCase("ko-KR");
   if(product===norm||product.replace(/\([^)]*\)/g,"").trim()===norm)return 0;
   if(product.startsWith(norm))return 1;
   if(product.includes(norm))return 2;
   if(x.ingredient.toLocaleLowerCase("ko-KR").includes(norm))return 3;
   return 4;
  };
  return score(a)-score(b)||a.product.localeCompare(b.product,"ko-KR");
 });
 const incomplete=jobs.some(j=>j.status==="rejected");
 const totalAtLeast=Math.max(0,...ok.map(x=>x.value.total));
 const byField=Object.fromEntries(ok.map(x=>[x.value.field,x.value.total]));
 return {matches:ranked,has_more:ok.some(j=>j.value.has_more),
  page,total_at_least:totalAtLeast,totals_by_field:byField,
  source:"MFDS 의약품등 정보검색",partial:incomplete,
  note:"식약처 실시간 품목검색 결과입니다. 뒤쪽 페이지가 있으면 더 보기를 통해 모두 검색할 수 있습니다."};
}
async function inspectMFDSItem(params:URLSearchParams):Promise<unknown>{
 const itemSeq=(params.get("item_seq")||"").trim();
 if(!/^\d{9}$/.test(itemSeq))throw Error("유효한 품목기준코드가 필요합니다.");
 const url=ORIGIN+"/pbp/CCBBB01/getItemChangeHistList?itemSeq="+itemSeq+"&docType=EE&page=1";
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),16000);
 let content="";
 try{
  const response=await fetch(url,{signal:controller.signal,headers:{"User-Agent":"Mozilla/5.0","Accept":"text/html"}});
  if(!response.ok)throw Error("식약처 이력 조회 HTTP "+response.status);
  content=await response.text();
  if(!content.includes('id="hist_list"'))throw Error("식약처 효능·효과 변경이력 응답이 올바르지 않습니다.");
 }finally{clearTimeout(timer);}
 const versions=parseOfficialHistoryVersions(content);
 // MFDS product-detail change table can list regulatory efficacy-change dates
 // newer than the last electronically archived XML revision.
 const officialDates=new Set<string>();
 let detailComplete=false;
 let officialChangeTotal:null|number=null;
 const detailedUrl=ORIGIN+"/pbp/CCBBB01/getItemDetailCache?cacheSeq="+itemSeq;
 let detailError="";
 let cachedSummary=false;
 let officialEfficacyCount:number|null=null;
 let latestSummaryDate:string|null=null;
 // The MFDS detail page can intermittently time out even though its
 // electronically stored efficacy XML remains available. Retry briefly.
 for(let attempt=0;attempt<2&&!detailComplete;attempt++){
  const detailController=new AbortController();
  const detailTimer=setTimeout(()=>detailController.abort(),attempt===0?10000:8500);
  try{
   const response=await fetch(detailedUrl,{signal:detailController.signal,headers:{"User-Agent":"Mozilla/5.0","Accept":"text/html"}});
   if(!response.ok)throw Error("MFDS detail HTTP "+response.status);
   const detail=await response.text();
   const tableIndex=detail.indexOf('id="tblChf"');
   if(tableIndex<0)throw Error("MFDS detail change table missing");
   const tbody=detail.slice(tableIndex).match(/<tbody\b[^>]*>([\s\S]*?)<\/tbody>/i)?.[1]||"";
   if(!tbody)throw Error("MFDS detail change rows missing");
   const officialRows=[...tbody.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)];
   officialChangeTotal=officialRows.length;
   for(const entry of officialRows){
    const cols=[...entry[1].matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/gi)].map(x=>plain(x[1]));
    const date=cols.find(x=>/^\d{4}-\d{2}-\d{2}$/.test(x));
    if(date&&/효능.?효과/.test(cols.at(-1)||""))officialDates.add(date);
   }
   detailComplete=true;
   officialEfficacyCount=officialDates.size;
  }catch(e){detailError=String(e).slice(0,130)}
  finally{clearTimeout(detailTimer)}
 }
 if(!detailComplete){
  // Read-only fallback to a previously verified official summary. Never
  // silently assert that the absence of a response means no older changes.
  try{
   const saved=await db("GET","mfds_monitor_history_summaries?select=official_change_total,official_efficacy_total,verified_at&item_seq=eq."+itemSeq+"&limit=1");
   if(saved?.length){
    officialChangeTotal=saved[0].official_change_total;
    officialEfficacyCount=saved[0].official_efficacy_total;
    latestSummaryDate=saved[0].verified_at;
    cachedSummary=true;
   }
   const old=await db("GET","mfds_monitor_efficacy_history?select=changed_at&item_seq=eq."+itemSeq+"&limit=300");
   // The earliest electronic snapshot is only a comparison baseline.
   // Do not mistake an original marketing authorisation for a new change
   // when reconstructing history from the local read-only cache.
   for(const row of old||[])if(row.changed_at&&row.changed_at!==versions[0]?.changed_at)officialDates.add(row.changed_at);
  }catch(_ignored){}
 }
 const items:any[]=[];
 for(let i=1;i<versions.length;i++){
  const prior=versions[i-1],next=versions[i];
  const before=new Set(prior.lines.map(comparisonKey)),after=new Set(next.lines.map(comparisonKey));
  const analyzed=substantiveEffectDiff(prior.lines.join("\n"),next.lines.join("\n"));
  items.push({
   id:"live-"+itemSeq+"-"+next.changed_at,
   changed_at:next.changed_at,change_type:analyzed.change_type,
   before_text:prior.lines.join("\n"),after_text:next.lines.join("\n"),
   added_lines:analyzed.changes.filter(x=>x.kind==="added").map(x=>x.text),
   removed_lines:analyzed.changes.filter(x=>x.kind==="removed").map(x=>x.text),
   change_details:analyzed.changes,editorial_changes:analyzed.editorial_changes,
   summary_lines:analyzed.summary_lines,added_count:analyzed.added_count,
   removed_count:analyzed.removed_count,modified_count:analyzed.modified_count,
   diff_status:"compared",
   evidence_url:ORIGIN+"/pbp/CCBBB01/getItemDetail?itemSeq="+itemSeq,
   source_kind:"official_live",comparison_kind:"literal"
  });
 }
 const baseline=versions[0]?.changed_at;
 const known=new Set(versions.map(x=>x.changed_at));
 for(const day of officialDates){
  if(known.has(day)&&day!==baseline)continue;
  items.push({
   id:"live-"+itemSeq+"-"+day,changed_at:day,change_type:"확인 필요",
   before_text:"",after_text:day===baseline ? (versions[0]?.lines.join("\n")||"") : "",
   added_lines:[],removed_lines:[],
   change_details:[],summary_lines:[],editorial_changes:0,added_count:0,removed_count:0,modified_count:0,
   diff_status:"not_available",evidence_url:ORIGIN+"/pbp/CCBBB01/getItemDetail?itemSeq="+itemSeq,
   source_kind:"official_live",comparison_kind:"unknown"
  });
 }
 items.sort((a,b)=>b.changed_at.localeCompare(a.changed_at));
 const current=versions.at(-1);
 const earliest=versions[0];
 return {item_seq:itemSeq,items,total:items.length,
  current_efficacy:current?.lines.join("\n")||"",official_history_complete:detailComplete,
  initial_version_date:earliest?.changed_at||null,
  initial_efficacy:earliest?.lines.join("\n")||"",
  official_change_total:officialChangeTotal,
  official_efficacy_total:officialEfficacyCount,
  official_other_total:officialChangeTotal===null||officialEfficacyCount===null?
    null:Math.max(0,officialChangeTotal-officialEfficacyCount),
  official_counts_from_cache:cachedSummary,
  official_summary_date:cachedSummary?latestSummaryDate:null,
  official_history_warning:detailComplete?null:"식약처 품목별 변경이력 상세 페이지의 실시간 조회가 지연돼 저장된 확인 자료를 우선 표시합니다.",
  official_uncompared_dates:items.filter(x=>x.diff_status==="not_available").map(x=>x.changed_at),
  all_history_dates_seen:officialDates.size,
  source:"식약처 효능·효과 변경이력",reviewed:false,
  note:"식약처가 전자화한 효능·효과 원문의 연속 버전을 비교했습니다. 전자화 이전 이력과 문구 변경의 의학적 의미는 별도 확인이 필요합니다."};
}


// Cross-product source discovery. The MFDS catalogue cannot be sorted by
// last indication-change date, so we resolve products from newly published
// change-review records, then obtain their *actual* regulatory change dates
// from each official product's history. Publication dates are never events.
function splitProductNames(input:string):string[]{
 const parts:string[]=[];let part="",depth=0;
 for(const char of String(input||"")){
  if(char==="("||char==="[")depth++;
  if(char===")"||char==="]")depth=Math.max(0,depth-1);
  if(char===","&&depth===0){if(part.trim())parts.push(part.trim());part="";continue;}
  part+=char;
 }
 if(part.trim())parts.push(part.trim());
 return parts;
}
function searchProductName(raw:string):string {
 return raw.replace(/^\s*(?:\[[^\]]*\]\s*)+/,"")
  .replace(/^\s*\([^)]*(?:주식회사|주|유)\)\s*,\s*/,"")
  .replace(/\([^)]*\)/g,"").replace(/\[[^\]]*\]/g,"")
  .replace(/\s*외\s*\d+\s*(?:품목|건).*$/,"")
  .replace(/\s+/g," ").trim().slice(0,95);
}
async function findChangeReviewProducts(source:any):Promise<CatalogueItem[]>{
 const inputs=splitProductNames(source.product||"").slice(0,3);
 const title=source.title?.replace(/^\s*(?:\[[^\]]*\]\s*)+/,"")||"";
 if(!inputs.length)inputs.push(title);
 if(inputs.length===1&&searchProductName(inputs[0])!==searchProductName(title))
  inputs.push(title);
 const seen=new Map<string,CatalogueItem>();
 for(const candidate of inputs.slice(0,3)){
  const q=searchProductName(candidate);
  if(q.length<2)continue;
  const url=new URL(ORIGIN+"/searchDrug");
  url.searchParams.set("searchYn","Y");
  url.searchParams.set("page","1");
  url.searchParams.set("itemName",q);
  const candidates=parseDrugCatalogue(await html(url.toString()));
  // Match the queried item, not unrelated similar formulations.
  const key=q.normalize("NFKC").replace(/[\s()[\]·,]/g,"").toLocaleLowerCase("ko-KR");
  const matched=candidates.filter(x=>{
   const n=x.product.normalize("NFKC").replace(/[\s()[\]·,]/g,"").toLocaleLowerCase("ko-KR");
   return n.includes(key);
  });
  for(const drug of matched.slice(0,2))seen.set(drug.item_seq,drug);
  if(seen.size>=4)break;
 }
 return [...seen.values()].slice(0,4);
}
async function globalEfficacyScan(maxSources:number=5):Promise<unknown>{
 const count=Math.max(1,Math.min(12,Math.floor(maxSources)||5));
 const [reviews,prior] = await Promise.all([
  db("GET","mfds_monitor_items?select=source_id,title,product,company,published_at&source=eq.review&order=published_at.desc,id.desc&limit=900"),
  db("GET","mfds_monitor_global_source_scans?select=source_id,status,attempted_at&limit=1500")
 ]);
 const scanned=new Map<string,any>((prior||[]).map((x:any)=>[x.source_id,x]));
 const deadline=Date.now()+105000;
 const now=Date.now();
 const fresh=(reviews||[]).filter((item:any)=>{
  if(!/변경/.test(item.title||"") || !item.source_id)return false;
  const existing=scanned.get(item.source_id);
  if(!existing)return true;
  if(existing.status==="done"||existing.status==="not_found"||existing.status==="skipped")return false;
  return now-new Date(existing.attempted_at).getTime()>6*3600000;
 }).slice(0,count);
 const results:any[]=[];
 let added=0;
 for(const item of fresh){
  if(Date.now()>deadline)break;
  const stamp=new Date().toISOString();
  let status="done",summary="",saved=0,first:any=null;
  try{
   const found=await findChangeReviewProducts(item);
   if(!found.length)status="not_found";
   for(const product of found){
    if(Date.now()>deadline)break;
    // Efficacy history has a foreign key to the shared official product
    // registry. Register newly discovered products without activating them
    // in the older manually curated four-product high-frequency cron.
    await db("POST","mfds_monitor_drug_targets?on_conflict=item_seq",{
      item_seq:product.item_seq,product:product.product,company:product.company,
      ingredient:product.ingredient||"",source_url:product.source_url,active:false,
      last_checked_status:"global-discovered"
    },"resolution=ignore-duplicates,return=minimal");
    const inspection:any=await inspectMFDSItem(new URLSearchParams({item_seq:product.item_seq}));
    if(!first)first=product;
    const original=inspection.initial_version_date||"";
    const today=new Date().toISOString().slice(0,10);
    const events=(inspection.items||[]).filter((x:any)=>
      /^\d{4}-\d{2}-\d{2}$/.test(x.changed_at||"") &&
      x.changed_at!==original && x.changed_at<=today &&
      ["compared","not_available"].includes(x.diff_status)
    );
    const rows=events.map((ev:any)=>({
      item_seq:product.item_seq,product:product.product,company:product.company,
      ingredient:product.ingredient||"",changed_at:ev.changed_at,
      change_section:"효능·효과",classification:ev.change_type||"확인 필요",
      evidence_url:product.source_url,
      before_text:ev.before_text||null,after_text:ev.after_text||null,
      added_lines:ev.added_lines||[],removed_lines:ev.removed_lines||[],
      diff_status:ev.diff_status,detail_checked_at:stamp,last_seen_at:stamp
    }));
    for(let i=0;i<rows.length;i+=25)await db("POST",
      "mfds_monitor_efficacy_history?on_conflict=item_seq,changed_at,change_section",
      rows.slice(i,i+25),"resolution=merge-duplicates,return=minimal");
    if(inspection.official_change_total!=null&&inspection.official_efficacy_total!=null)
      await db("POST","mfds_monitor_history_summaries?on_conflict=item_seq",{
        item_seq:product.item_seq,
        official_change_total:inspection.official_change_total,
        official_efficacy_total:inspection.official_efficacy_total,
        verified_at:stamp
      },"resolution=merge-duplicates,return=minimal");
    saved+=rows.length;
   }
  }catch(e){status="error";summary=String(e).slice(0,220)}
  await db("POST","mfds_monitor_global_source_scans?on_conflict=source_id",{
    source_id:item.source_id,source_title:(item.title||"").slice(0,350),
    product_hint:(item.product||"").slice(0,450),item_seq:first?.item_seq||null,
    product:first?.product||null,company:first?.company||null,
    status,changed_records:saved,attempted_at:stamp,error_text:summary||null
  },"resolution=merge-duplicates,return=minimal");
  results.push({source:item.title,item_seq:first?.item_seq||null,status,saved,error:summary||undefined});
  added+=saved;
 }
 return {mode:"global_efficacy_scan",processed:results.length,saved_records:added,
  source_review_count:(reviews||[]).length,results,
  coverage:"식약처 변경심사 공개자료에서 품목을 찾고 실제 품목별 효능·효과 변경일만 수집. 전체 의약품 정밀 전수조사 완료 아님."};
}


// Official-original master. Keep evidence, match confidence and surveillance
// scope distinct so a generic reference standard is never silently called an
// original. The 2025 annual designation is a cumulative MFDS list (810 rows).
const MFDS_NEW_DRUG_NOTICES={
  2025:{seq:16201,label:"2025년도 신약 지정 목록(누적)"},
  2024:{seq:15931,label:"2024년도 신약 지정 목록(누적)"}
} as const;
const cleanMFDSKey=(x:string)=>String(x||"").normalize("NFKC").toLocaleLowerCase("ko-KR")
 .replace(/\([^)]*\)/g,"").replace(/\[[^\]]*\]/g,"").replace(/[（）（）㈜\s.,·"'‘’\-]/g,"");
const companyKey=(x:string)=>String(x||"").normalize("NFKC").toLocaleLowerCase("ko-KR")
 .replace(/(?:주식회사|유한회사|\(주\)|\(유\)|㈜|주\)|유\))/g,"")
 .replace(/[()（）\s,.\-]/g,"");
const seedBaseName=(x:string)=>String(x||"").split(/\r?\n/)[0].trim().replace(/\s*[\[\(][^\])]*(?:\]|\))\s*$/,"").trim();
function parseMFDSExcelDate(value:unknown):string|null{
 if(typeof value==="number"){
  const parts=XLSX.SSF.parse_date_code(value);
  if(!parts||parts.y<1900||parts.y>2100)return null;
  return [String(parts.y).padStart(4,"0"),String(parts.m).padStart(2,"0"),String(parts.d).padStart(2,"0")].join("-");
 }
 const v=String(value||"").replace(/\./g,"-").trim();
 return /^\d{4}-\d{2}-\d{2}$/.test(v)?v:null;
}
async function importMFDSNewDrugDesignation(year:number):Promise<unknown>{
 if(!Number.isInteger(year)||!(year in MFDS_NEW_DRUG_NOTICES))throw Error("Unsupported verified MFDS new-drug year");
 const entry=MFDS_NEW_DRUG_NOTICES[year as keyof typeof MFDS_NEW_DRUG_NOTICES];
 const url="https://www.mfds.go.kr/brd/m_76/down.do?brd_id=ntc0004&seq="+entry.seq+"&data_tp=A&file_seq=1";
 const response=await fetch(url,{headers:{"Accept":"application/octet-stream,*/*"}});
 if(!response.ok)throw Error("Official MFDS spreadsheet unavailable: "+response.status);
 const workbook=XLSX.read(await response.arrayBuffer(),{type:"array"});
 const main=workbook.Sheets[workbook.SheetNames[0]];
 if(!main)throw Error("MFDS spreadsheet did not contain the original designation list");
 const all:any[][]=XLSX.utils.sheet_to_json(main,{header:1,defval:"",blankrows:false});
 const rows=all.filter(x=>typeof x[0]==="number"&&
  typeof x[1]==="string"&&String(x[1]).trim()&&String(x[2]||"").trim());
 // Refuse malformed attachments rather than silently inserting wrong data.
 if(rows.length<100)throw Error("Unusually small MFDS original designation list: "+rows.length);
 const body=rows.map(row=>({
  seed_key:"newdrug-"+year+"-"+String(row[0]).padStart(4,"0"),
  source_year:year,ordinal:row[0],
  product:String(row[1]).trim().slice(0,450),
  company:String(row[2]).trim().slice(0,240),
  ingredient:String(row[3]||"").trim().slice(0,600),
  permit_date:parseMFDSExcelDate(year===2025?row[4]:row[5]),
  source_type:"mfds_new_drug_designation",
  source_url:"https://www.mfds.go.kr/brd/m_76/view.do?seq="+entry.seq,
  match_status:"pending"
 }));
 for(let i=0;i<body.length;i+=100){
  await db("POST","mfds_monitor_master_seeds?on_conflict=seed_key",
   body.slice(i,i+100),"resolution=ignore-duplicates,return=minimal");
 }
 return {mode:"master_import",year,official_items:rows.length,seed_rows:body.length,
  source:entry.label,source_url:body[0].source_url,
  note:"신약 지정 공식 엑셀의 명단을 가져왔습니다. 품목기준코드 연결은 별도 검증 단계입니다."};
}
function seedResolutionScore(seed:any,drug:CatalogueItem):number{
 const s=cleanMFDSKey(seedBaseName(seed.product).replace(/\([^)]*\)/g,""));
 const d=cleanMFDSKey(seedBaseName(drug.product).replace(/\([^)]*\)/g,""));
 if(!s||!d)return -100;
 let score=s===d?60:(s.length>=5&&d.length>=5&&(s.startsWith(d)||d.startsWith(s))?27:0);
 if(!score)return -100;
 const companyMatch=companyKey(seed.company)===companyKey(drug.company);
 if(companyMatch)score+=23;
 // Date is crucial to disambiguate different strength-specific licenses.
 if(seed.permit_date&&drug.permit_date&&seed.permit_date===drug.permit_date)score+=25;
 else if(seed.permit_date&&drug.permit_date)score-=40;
 const searchIngredient=String(seed.ingredient||"").replace(/\([^)]*\)/g,"").split(/[\/,]/)[0];
 if(searchIngredient.length>=3&&drug.ingredient.includes(searchIngredient))score+=10;
 if(!companyMatch)score-=30;
 if(drug.status&&!/정상/.test(drug.status))score-=5;
 return score;
}
async function resolveMFDSOriginalSeeds(maxItems:number=12):Promise<unknown>{
 const n=Math.max(1,Math.min(40,Math.floor(maxItems)||12));
 const seeds=await db("GET","mfds_monitor_master_seeds?select=seed_key,source_year,product,company,ingredient,permit_date,source_url,source_type,match_status,last_attempt_at&match_status=in.(pending,error,not_found,ambiguous)&limit=1100");
 const prioritized=["키트루다","임핀지","테빔브라","파센라","엔허투","옵디보","오젬픽","레켐비","트렘피어","듀피젠트","가다실","티쎈트릭","레켐비"];
 const priority=(row:any)=>{const i=prioritized.findIndex(x=>row.product.includes(x));return i<0?100:i;};
 const now=Date.now();
 const pending=(seeds||[]).filter((x:any)=>x.match_status==="pending"||
  !x.last_attempt_at||now-new Date(x.last_attempt_at).getTime()>24*3600000)
  .sort((a:any,b:any)=>priority(a)-priority(b)||
   String(b.permit_date||"").localeCompare(String(a.permit_date||""))||
   a.seed_key.localeCompare(b.seed_key))
  .slice(0,n);
 const results:any[]=[];
 async function process(seed:any):Promise<void>{
  let state="not_found",code:string|null=null,score:number|null=null,note="";
  let result:CatalogueItem|null=null;
  try{
   const query=seedBaseName(seed.product).replace(/\([^)]*\)/g,"").trim();
   const url=new URL(ORIGIN+"/searchDrug");
   url.searchParams.set("searchYn","Y");url.searchParams.set("page","1");url.searchParams.set("itemName",query);
   let candidates=parseDrugCatalogue(await html(url.toString()));
   // For officially renamed products try a shortened brand name, but only
   // trust the result if company and permit date still match.
   if(!candidates.length&&query.length>9){
    url.searchParams.set("itemName",query.slice(0,Math.min(7,query.length)));
    candidates=parseDrugCatalogue(await html(url.toString()));
   }
   const sorted=candidates.map(c=>({c,score:seedResolutionScore(seed,c)})).sort((a,b)=>b.score-a.score);
   if(sorted.length&&sorted[0].score>=70&&
      (!sorted[1]||sorted[0].score-sorted[1].score>=10)){
     result=sorted[0].c;
     score=sorted[0].score;state="matched";code=result.item_seq;
     await db("POST","mfds_monitor_product_roles?on_conflict=item_seq",{
       item_seq:result.item_seq,product:result.product,company:result.company,
       ingredient:result.ingredient,product_role:"new_drug",watch_scope:"primary",
       evidence_source:"mfds_new_drug_designation",evidence_url:seed.source_url,
       evidence_note:"식약처 "+seed.source_year+"년 신약 지정 공고 원문과 제품명·업체명·허가일자 대조",
       evidence_year:seed.source_year,classification_confidence:"official_list"
     },"resolution=ignore-duplicates,return=minimal");
     await db("POST","mfds_monitor_drug_targets?on_conflict=item_seq",{
       item_seq:result.item_seq,product:result.product,company:result.company,
       ingredient:result.ingredient,source_url:result.source_url,
       active:false,last_checked_status:"original-master"
     },"resolution=ignore-duplicates,return=minimal");
   }else if(sorted.length){
     state="ambiguous";note="최적 적합점수 "+sorted[0].score+"; 후보 "+sorted.slice(0,3).map(x=>x.c.product+"("+x.score+")").join(", ");
   }else note="식약처 검색 결과 0건; 이관·취하·품목명 변경 여부 확인 필요";
  }catch(e){state="error";note=String(e).slice(0,240)}
  await db("PATCH","mfds_monitor_master_seeds?seed_key=eq."+encodeURIComponent(seed.seed_key),{
    match_status:state,item_seq:code,match_score:score,
    match_note:note||null,last_attempt_at:new Date().toISOString()
  },"return=minimal");
  results.push({seed:seed.product.slice(0,90),status:state,item_seq:code,score,
   note:note.slice(0,160)});
 }
 for(let i=0;i<pending.length;i+=4)await Promise.all(pending.slice(i,i+4).map(process));
 const resolved=results.filter(x=>x.status==="matched").length;
 return {mode:"master_resolve",attempted:results.length,matched:resolved,results};
}
async function originalMasterStatus():Promise<unknown>{
 const [seeds,roles,unresolved]=await Promise.all([
  db("GET","mfds_monitor_master_seeds?select=match_status,source_year&limit=2000"),
  db("GET","mfds_monitor_product_roles?select=product_role,watch_scope,classification_confidence&limit=3000"),
  db("GET","mfds_monitor_master_seeds?select=seed_key,product,company,match_status,match_note&match_status=eq.ambiguous&limit=12")
 ]);
 const aggregate=(input:any[],field:string)=>{
  const map:Record<string,number>={};
  for(const x of input||[])map[x[field]]=(map[x[field]]||0)+1;
  return map;
 };
 return {source:"식약처 연도별 신약 지정 목록 및 검증된 허가정보",
  seeds:(seeds||[]).length,seed_status:aggregate(seeds,"match_status"),
  classified:(roles||[]).length,watch_scopes:aggregate(roles,"watch_scope"),
  classes:aggregate(roles,"product_role"),needs_review:unresolved||[],
  selection_complete:false,
  note:"신약 공고를 품목기준코드로 연결하는 중이며 대조약·바이오·희귀·개량신약·자료제출의약품은 공식 증거 확인 시 각각 별도로 편입합니다."};
}

async function feed(): Promise<unknown> {
  const [events, leads, recent, runs, stats, efficacy, targets] = await Promise.all([
    db("GET", "mfds_monitor_events?select=id,product,company,ingredient,event_date,event_type,change_area,title,before_text,after_text,details,evidence_url,mfds_url,verification,alert_state&verification=in.(reviewed,official_confirmed)&order=event_date.desc,id.desc&limit=300"),
    db("GET", "mfds_monitor_items?select=id,source,source_id,source_url,title,company,product,ingredient,published_at,attachment_names,classification,rationale,alert_state&source=eq.review&classification=eq.clinical_lead&order=published_at.desc,id.desc&limit=150"),
    db("GET", "mfds_monitor_items?select=id,source,source_id,source_url,title,category,company,product,ingredient,published_at,effective_at,stage,attachment_names,classification,rationale,alert_state,approval_changed_at,change_type,change_summary,first_seen_at&order=published_at.desc.nullslast,id.desc&limit=200"),
    db("GET", "mfds_monitor_runs?select=id,started_at,finished_at,status,reviews_checked,changes_checked,errors&order=id.desc&limit=5"),
    db("GET", "rpc/mfds_monitor_archive_stats"),
    db("GET", "mfds_monitor_efficacy_history?select=id,item_seq,product,company,changed_at,change_section,classification,evidence_url,first_seen_at&order=changed_at.desc,id.desc&limit=300"),
    db("GET", "mfds_monitor_drug_targets?select=item_seq,product,company,last_checked_at,last_checked_status&active=eq.true&limit=100")
  ]);
  return {
    events,leads,items:recent,runs,efficacy,targets,
    counts:{verified_events:stats.verified,leads:(leads||[]).length,efficacy:(efficacy||[]).length,review_records:stats.review_changes,orders_records:stats.orders_total,review_total:stats.review_total},
    archive:stats.cursors,
    description:"실제 허가변경일을 확인한 이벤트와 변경심사자료/변경명령의 공개이력을 별도 구분합니다. 미확인 자료는 확정 변경으로 분류하지 않습니다."
  };
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response(null,{status:204,headers:HEADERS});
  try {
    if (req.method === "GET") {
      const url=new URL(req.url);
      const view=url.searchParams.get("view");
      if(view==="master")return reply(await originalMasterStatus());
      if(view==="lookup")return reply(await lookupMFDSCatalogue(url.searchParams));
      if(view==="inspect")return reply(await inspectMFDSItem(url.searchParams));
      return reply(view==="efficacy"
        ? await filteredEfficacyFeed(url.searchParams)
        : view==="archive" ? await archiveFeed(url.searchParams) : await feed());
    }
    if (req.method !== "POST") return reply({error:"Unsupported method"},405);
    if (!await validToken(req.headers.get("x-monitor-token") || "")) return reply({error:"Unauthorized"},401);
    const input=await req.json().catch(()=>({}));
    if(input?.mode==="backfill") return reply(await backfill());
    if(input?.mode==="repair_order_dates") return reply(await repairOrderHistory());
    if(input?.mode==="efficacy_sync") return reply(await syncOfficialEfficacyHistory());
    if(input?.mode==="master_import")return reply(await importMFDSNewDrugDesignation(Number(input?.year)||2025));
    if(input?.mode==="master_resolve")return reply(await resolveMFDSOriginalSeeds(Number(input?.limit)||12));
    if(input?.mode==="global_efficacy_scan") return reply(await globalEfficacyScan(input?.max_sources));
    return reply(await collect());
  } catch (e) {
    return reply({error:String(e).slice(0,420)},500);
  }
});