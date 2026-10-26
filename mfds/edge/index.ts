import "jsr:@supabase/functions-js/edge-runtime.d.ts";

// MFDS indication-change monitor, v1. Public GET is read-only.
// POST collection requires an independent secret stored in Supabase Vault;
// no drug-approval claim is made without verification of changed indications.
const ORIGIN = "https://nedrug.mfds.go.kr";
const BASE = Deno.env.get("SUPABASE_URL") || "";
const KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
const HEADERS = {
  "Access-Control-Allow-Origin": "*",
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
  published_at: string | null; stage: string; attachment_names: string[];
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
    const published = source === "review" ? plain(cells[8]) : (dates[0] || null);
    const isChange = source === "review" && /변경/.test(title);
    const promising = /적응증|효능.{0,2}효과|치료대상|치료\s*범위|대상환자|허가\s*확대/i.test(title);
    const classification = source === "review"
      ? (isChange ? (promising ? "high_candidate" : "change_candidate") : "other")
      : (promising ? "change_candidate" : "monitor_only");
    items.push({
      source, source_id: key, source_url: linkUrl, title, category,
      company: source === "review" ? plain(cells[3]) : "",
      product: source === "review" ? plain(cells[4]) : "",
      ingredient: source === "review" ? plain(cells[5]) : "",
      published_at: /^\d{4}-\d\d-\d\d$/.test(published || "") ? published : null,
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
    if (/적응증|효능.{0,2}효과|치료.{0,7}추가|질환.{0,8}추가|암.{0,18}추가|확대/i.test(joined)) {
      item.classification = "high_candidate";
      item.rationale = "첨부 보고서 파일명에 적응증·치료영역 추가 관련 표현 발견. 원문 확인 필요.";
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
        fresh.filter(x => x.classification === "high_candidate" ||
          x.classification === "change_candidate").length;
    } catch (e) {
      report.errors.push(source + ": " + String(e).slice(0, 220));
    }
  }
  report.status = report.errors.length ? "partial" : "success";
  await db("PATCH", "mfds_monitor_runs?id=eq." + run.id,
    { ...report, finished_at: new Date().toISOString() }, "return=minimal");
  return { ...report, run_id: run.id };
}
async function feed() {
  // Critical: the review-publication date is NOT the date an indication
  // changed. Raw source-list entries are retained as internal leads only.
  // Never publish those as clinical approval events or push notifications.
  const [events, runs] = await Promise.all([
    db("GET", "mfds_monitor_events?select=id,product,company,ingredient,event_date,event_type,change_area,title,before_text,after_text,details,evidence_url,mfds_url,verification,alert_state&verification=in.(reviewed,official_confirmed)&order=event_date.desc,id.desc&limit=250"),
    db("GET", "mfds_monitor_runs?select=id,started_at,finished_at,status,reviews_checked,changes_checked,errors&order=id.desc&limit=5"),
  ]);
  return { events, runs, description:"허가사항 실제 변경일과 전후 내용을 확인한 사건만 표시. 공개일만 있는 심사보고서는 제외.", count:events.length };
}
Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response(null,{status:204,headers:HEADERS});
  try {
    if (req.method === "GET") return reply(await feed());
    if (req.method !== "POST") return reply({error:"Unsupported method"},405);
    if (!await validToken(req.headers.get("x-monitor-token") || "")) return reply({error:"Unauthorized"},401);
    return reply(await collect());
  } catch (e) {
    return reply({error:String(e).slice(0,420)},500);
  }
});