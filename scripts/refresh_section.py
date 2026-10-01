import json, os, sys, urllib.parse, urllib.request, re, html
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SUPABASE_URL="https://mqkhtnryxyntrrfrfing.supabase.co"
SUPABASE_KEY="sb_publishable_GLp72jjAPgHWqUEpqtnw5Q_rY3lfcB8"
MODEL=os.getenv("OPENAI_MODEL","gpt-6.1-sol")
SECTIONS=("domestic","global","patent")

def get_json(url, headers=None, data=None, timeout=900):
    req=urllib.request.Request(url,data=data,headers=headers or {})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.load(r)

def supabase_get(path):
    return get_json(SUPABASE_URL+path,{"apikey":SUPABASE_KEY,"Authorization":f"Bearer {SUPABASE_KEY}"})

def call_openai(prompt):
    key=os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    payload={
      "model":MODEL,
      "reasoning":{"effort":"medium"},
      "tools":[{"type":"web_search","search_context_size":"high"}],
      "tool_choice":"required",
      "input":prompt,
      "text":{"format":{"type":"json_object"}},
      "max_output_tokens":18000
    }
    res=get_json("https://api.openai.com/v1/responses",
      {"Authorization":f"Bearer {key}","Content-Type":"application/json"},
      json.dumps(payload).encode(),900)
    chunks=[]
    for item in res.get("output",[]):
        if item.get("type")=="message":
            for c in item.get("content",[]):
                if c.get("type")=="output_text":
                    chunks.append(c.get("text",""))
    if not chunks:
        raise RuntimeError("OpenAI response contained no output_text")
    return json.loads("".join(chunks))


def clean_text(v):
    return re.sub(r"\\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",str(v or "")))).strip()

def rss_items(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req,timeout=20) as r:
            root=ET.fromstring(r.read())
    except Exception as e:
        print("rss failed",url,e,file=sys.stderr); return []
    out=[]
    for item in root.findall(".//item"):
        title=clean_text(item.findtext("title"))
        link=clean_text(item.findtext("link"))
        desc=clean_text(item.findtext("description"))
        pub=clean_text(item.findtext("pubDate"))
        src=item.find("source")
        source=clean_text(src.text if src is not None else "")
        if title and link:
            out.append({"title":title,"source":link,"description":desc[:900],"published_at":pub,"source_name":source})
    return out

def search_candidates(section, settings):
    if section=="domestic":
        queries=[
          '제약 바이오 임상 허가 투자 인수 합병 단독',
          '"단독" 제약 바이오',
          '제약 약가 급여 식약처 심평원',
          '바이오 임상 2상 3상 기술수출'
        ]
        domains=(settings.get("priority_sources",{}).get("domestic") or [])[:12]
        queries += [f"site:{d} 제약 바이오" for d in domains if "." in d]
        market="ko-KR"
    elif section=="global":
        queries=[
          'pharma biotech phase 2 phase 3 FDA approval deal acquisition',
          'biotech topline pivotal trial safety licensing',
          'pharma M&A licensing FDA EMA'
        ]
        domains=(settings.get("priority_sources",{}).get("global") or [])[:10]
        queries += [f"site:{d} pharma biotech" for d in domains if "." in d]
        market="en-US"
    else:
        queries=[
          '제약 특허 소송 특허심판 제네릭 우선판매',
          '바이오 특허 침해 영업비밀 소송',
          'pharma patent lawsuit generic PTAB'
        ]
        domains=(settings.get("priority_sources",{}).get("patent") or [])[:10]
        queries += [f"site:{d} 제약 특허" for d in domains if "." in d]
        market="ko-KR"
    rows=[]
    for q in queries:
        enc=urllib.parse.quote(q)
        urls=[
          f"https://www.bing.com/news/search?q={enc}&format=rss&mkt={market}",
          f"https://news.google.com/rss/search?q={enc}&hl={'ko' if market=='ko-KR' else 'en-US'}&gl={'KR' if market=='ko-KR' else 'US'}&ceid={'KR:ko' if market=='ko-KR' else 'US:en'}"
        ]
        for u in urls:
            rows.extend(rss_items(u))
    seen=set(); out=[]
    for x in rows:
        k=re.sub(r"[^0-9A-Za-z가-힣]+","",x["title"]).lower()
        if not k or k in seen: continue
        seen.add(k); out.append(x)
    return out[:100]

def call_github_models(prompt):
    token=os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN unavailable for fallback ranking")
    payload={
      "model":"openai/gpt-4.1-mini",
      "messages":[{"role":"system","content":"Return only valid JSON. Never invent facts beyond supplied search results."},{"role":"user","content":prompt}],
      "temperature":0.1,
      "response_format":{"type":"json_object"}
    }
    return get_json("https://models.github.ai/inference/chat/completions",
      {"Authorization":f"Bearer {token}","Content-Type":"application/json"},
      json.dumps(payload).encode(),180)

def fallback_refresh(day, section, request_at, settings, base, live):
    candidates=search_candidates(section,settings)
    if not candidates:
        return {"items":[]}
    morning=[x.get("title","") for x in base.get(section,[])]
    existing=[x.get("title","") for x in live.get("items",[])]
    prompt=f"""Select only genuinely important NEW {section} pharma/biotech stories for {day} after the 07:20 KST morning edition.
There is no target count; zero is valid. Exclude duplicate events even when another outlet covers them.
Morning titles: {json.dumps(morning,ensure_ascii=False)}
Already-added live titles: {json.dumps(existing,ensure_ascii=False)}
Candidate search results: {json.dumps(candidates,ensure_ascii=False)}
Use only facts present in candidate titles/descriptions. Do not infer missing numbers or outcomes.
For each selected story output tag,title,summary,source,source_name,published_at,article_preview.
summary may be 1-3 concise factual sentences if the search snippet is limited.
article_preview.quick={{"title":"","lead":"","title_options":["",""]}}
article_preview.diff={{"title":"","direction":"","title_options":["",""]}}
Return {{"items":[]}} JSON only."""
    res=call_github_models(prompt)
    content=res.get("choices",[{}])[0].get("message",{}).get("content","{}")
    return json.loads(content)

def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default

def latest_requests(day):
    qs=urllib.parse.urlencode({
      "briefing_date":f"eq.{day}",
      "select":"id,briefing_date,section,requested_at",
      "order":"requested_at.desc"
    })
    rows=supabase_get("/rest/v1/briefing_refresh_requests?"+qs)
    out={}
    for r in rows:
        s=r.get("section")
        if s in SECTIONS and s not in out:
            out[s]=r
    return out

def section_instructions(section):
    if section=="domestic":
        return """국내 제약바이오 뉴스다. 국내 기업의 해외 임상·허가·투자도 포함한다. 우선매체 최신기사/섹션을 직접 훑고 단독·독자·확인 기사를 별도 탐색한다. DART/KRX/식약처/복지부/심평원/법원 등 1차자료를 교차검증한다. 단순 홍보·봉사·내부행사·제품소개·주가등락 자체는 제외한다. 다만 주가 변동 원인이 새로운 임상·공시·딜·규제·특허이면 그 원인 사건을 포함한다."""
    if section=="global":
        return """글로벌 제약바이오 뉴스다. FDA, EMA, ClinicalTrials.gov, SEC, 회사 공식 IR/Newsroom을 우선 확인하고 Reuters, STAT, Endpoints, BioPharma Dive, Fierce 등 전문매체와 전체 웹을 폭넓게 탐색한다. 주요 임상 2·3상 결과/실패, 허가·규제, 안전성, 대형 라이선스·M&A·투자, 중요한 R&D 전략변화를 우선한다. 한국 기업 직접 이슈는 제외한다."""
    return """제약바이오 특허·IP 뉴스다. 국내 사건을 최우선으로 KIPRIS, 특허심판원, 특허법원, 대법원/각급법원, 식약처 허가특허연계, IP-NAVI를 확인하고 부족하면 USPTO/PTAB, 미국 법원, Reuters Legal 등 해외로 확장한다. 등록·무효·권리범위확인·제네릭 도전·우판권·침해소송·영업비밀·특허기간연장을 포함한다. 단순 특허등록/PTE 행정기한은 시장·출시·독점기간 영향이 뚜렷하지 않으면 제외한다."""

def make_prompt(day, section, request_at, settings, base, live):
    morning_titles=[x.get("title","") for x in base.get(section,[])]
    live_titles=[x.get("title","") for x in live.get("items",[])]
    sources=settings.get("priority_sources",{}).get(section,[])
    policy=settings.get("source_policy",{})
    return f"""당신은 데일리팜 제약바이오 브리핑의 실시간 업데이트 편집자다.
한국 날짜 {day}, 사용자가 {request_at}에 '{section}' 탭 업데이트를 눌렀다.
live web search를 충분히 사용해 오늘 아침 07:20 KST 이후 지금까지 새로 발생하거나 새로 보도된 '추가할 가치가 있는 중요한 기사'만 찾는다.

중요: 개수 목표는 없다. 0건도 정상이다. 중요하지 않은 기사로 숫자를 채우지 마라.
아침판은 절대 교체하지 않는다. 아래 아침판 및 기존 라이브 항목과 같은 사건은 다른 매체 기사여도 중복 추가하지 않는다.
아침판 제목: {json.dumps(morning_titles,ensure_ascii=False)}
이미 추가된 라이브 제목: {json.dumps(live_titles,ensure_ascii=False)}

섹션 지침:
{section_instructions(section)}

운영 수집원칙: {json.dumps(policy,ensure_ascii=False)}
우선 출처: {json.dumps(sources,ensure_ascii=False)}

선정 기준은 객관적 중요도, 새 정보의 크기, 데일리팜 기사화·후속취재 가치, 출처 신뢰도/원문 확인 가능성, 단독·독자취재 여부다.
우선매체는 검색엔진 결과만 기다리지 말고 최신기사/섹션을 확인하고, 등록되지 않은 매체·공식자료도 전체 웹에서 보완 탐색한다.
핵심 수치·임상·투자액·지분·허가·급여·판결·특허는 가능한 한 1차 출처로 검증한다.
published_at은 확인된 경우만 한국시간 'M. D. 오전/오후 HH:MM' 형식, 아니면 빈 문자열.
각 item은 tag,title,summary,source,source_name,published_at,article_preview를 가진다.
summary는 사실 중심 3~5문장.
article_preview.quick={{title,lead,title_options:[2개]}}
article_preview.diff={{title,direction,title_options:[2개]}}
출처 URL은 실제 확인한 URL만 사용한다. 확인되지 않은 사실은 추정하지 않는다.
출력은 설명 없이 {{"items":[...]}} JSON 하나만 반환하라."""

def normalize_item(x, completed_at, batch_id):
    return {
      "tag":x.get("tag",""),
      "title":x.get("title","").strip(),
      "summary":x.get("summary","").strip(),
      "source":x.get("source","").strip(),
      "source_name":x.get("source_name","").strip(),
      "published_at":x.get("published_at",""),
      "article_preview":x.get("article_preview") or {},
      "live_added_at":completed_at,
      "update_batch":batch_id,
      "is_live":True
    }

def process_section(day, section, req, settings, base):
    path=Path("live")/f"{day}-{section}.json"
    live=load_json(path,{"date":day,"section":section,"morning_count":len(base.get(section,[])),"updated_at":"","last_request_at":"","batches":[],"items":[]})
    request_at=req["requested_at"]
    if live.get("last_request_at","") >= request_at:
        print(section,"already processed",request_at)
        return False
    result=call_openai(make_prompt(day,section,request_at,settings,base,live)) if os.environ.get('OPENAI_API_KEY') else fallback_refresh(day,section,request_at,settings,base,live)
    now=datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    batch_id=req["id"]
    existing_urls={str(x.get("source","")).strip() for x in base.get(section,[])+live.get("items",[]) if x.get("source")}
    existing_titles={str(x.get("title","")).strip() for x in base.get(section,[])+live.get("items",[]) if x.get("title")}
    added=[]
    for raw in result.get("items",[]):
        x=normalize_item(raw,now,batch_id)
        if not x["title"] or not x["source"].startswith("http"):
            continue
        if x["source"] in existing_urls or x["title"] in existing_titles:
            continue
        existing_urls.add(x["source"]); existing_titles.add(x["title"]); added.append(x)
    live["date"]=day
    live["section"]=section
    live["morning_count"]=len(base.get(section,[]))
    live["updated_at"]=now
    live["last_request_at"]=request_at
    live.setdefault("items",[]).extend(added)
    live.setdefault("batches",[]).append({"request_id":batch_id,"requested_at":request_at,"completed_at":now,"added_count":len(added)})
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(live,ensure_ascii=False,indent=2),encoding="utf-8")
    print(section,":",len(added),"new; total live",len(live["items"]))
    return True

def main():
    day=datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    reqs=latest_requests(day)
    if not reqs:
        print("no refresh requests for",day)
        return
    base=load_json(Path("data")/f"{day}.json",{})
    if not base:
        raise SystemExit("morning briefing is missing")
    try:
        rows=supabase_get("/rest/v1/app_settings?key=eq.main&select=value")
        settings=rows[0]["value"] if rows else {}
    except Exception:
        settings=load_json("config/briefing-settings.json",{})
    changed=False
    for section,req in reqs.items():
        try:
            changed=process_section(day,section,req,settings,base) or changed
        except Exception as e:
            print(f"{section} refresh failed: {e}",file=sys.stderr)
    if not changed:
        print("no unprocessed refresh requests")

if __name__=="__main__":
    main()
