import json, os, sys, urllib.parse, urllib.request, re, html
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime

SUPABASE_URL="https://mqkhtnryxyntrrfrfing.supabase.co"
SUPABASE_KEY="sb_publishable_GLp72jjAPgHWqUEpqtnw5Q_rY3lfcB8"
MODEL=os.getenv("OPENAI_MODEL","gpt-6.1-sol")
SECTIONS=("domestic","global","patent")

# Hard editorial gates are code, not prompt-only policy. This keeps fallback and AI paths consistent.
PHARMA_TERMS=("제약","바이오","의약","신약","치료제","백신","임상","허가","식약처","복지부","심평원","약가","급여","특허","제네릭","의료","pharma","biotech","drug","clinical","fda","ema")
HIGH_VALUE_TERMS=("단독","exclusive","3상","phase 3","pivotal","2상","phase 2","fda","ema","식약처","허가","승인","급여","약가","기술수출","라이선스","license","인수","합병","m&a","acquisition","투자","임상 중단","safety","안전성","판결","소송","특허","patent","lawsuit","영업비밀","우선판매","공시")
LOW_VALUE_TERMS=("채용","부고","봉사","기부","행사 참가","세미나 참가","홍보대사","수상","전시회 참가","부스 참가","주가 급등","주가 급락")
STOPWORDS={"단독","제약","바이오","산업","관련","대한","위한","통해","참가","진행","발표","확대","글로벌","국내","해외","뉴스","기자","올해","이번","기업","회사","업계"}

def get_json(url, headers=None, data=None, timeout=900):
    req=urllib.request.Request(url,data=data,headers=headers or {})
    with urllib.request.urlopen(req,timeout=timeout) as r: return json.load(r)

def supabase_get(path):
    return get_json(SUPABASE_URL+path,{"apikey":SUPABASE_KEY,"Authorization":f"Bearer {SUPABASE_KEY}"})

def clean_text(v):
    return re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",str(v or "")))).strip()

def rss_items(url):
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req,timeout=20) as r: root=ET.fromstring(r.read())
    except Exception as e:
        print("rss failed",url,e,file=sys.stderr); return []
    out=[]
    for item in root.findall(".//item"):
        title=clean_text(item.findtext("title")); link=clean_text(item.findtext("link"))
        if not title or not link: continue
        src=item.find("source")
        out.append({"title":title,"source":link,"description":clean_text(item.findtext("description"))[:900],"published_at":clean_text(item.findtext("pubDate")),"source_name":clean_text(src.text if src is not None else "")})
    return out

def title_tokens(t):
    return {x for x in re.findall(r"[0-9A-Za-z가-힣]{2,}",str(t or "").lower()) if x not in STOPWORDS}

def similarity(a,b):
    x,y=title_tokens(a),title_tokens(b)
    if not x or not y: return 0.0
    return len(x&y)/max(1,min(len(x),len(y)))

def event_key(title):
    """Event fingerprint: company/entity + distinctive subject terms, independent of outlet wording."""
    toks=list(title_tokens(title))
    # Numeric amounts/trial phases/product/event names are highly discriminative.
    strong=[t for t in toks if re.search(r"\d",t) or len(t)>=4]
    return set(strong or toks)

def same_event(a,b):
    if similarity(a,b)>=0.48: return True
    x,y=event_key(a),event_key(b)
    common=x&y
    # Two distinctive shared terms catches e.g. 유한양행 + CPHI despite rewritten headlines.
    if len(common)>=2: return True
    # A shared named entity plus a shared deal/clinical/regulatory concept is enough.
    concepts=("임상","허가","승인","급여","약가","특허","소송","판결","투자","인수","합병","기술수출","라이선스","cphi","cdmo","fda","ema")
    al=a.lower(); bl=b.lower()
    shared_concept=any(k in al and k in bl for k in concepts)
    named=[t for t in common if len(t)>=3 and t not in concepts]
    return shared_concept and bool(named)

def pharma_relevant(x,section):
    if section in ("global","patent"): return True
    text=(x.get("title","")+" "+x.get("description","")+" "+x.get("source_name","")).lower()
    return any(k in text for k in PHARMA_TERMS)

def candidate_score(x,section,priority):
    text=(x.get("title","")+" "+x.get("description","")).lower(); score=0
    for k in HIGH_VALUE_TERMS:
        if k in text: score+=2
    if "단독" in text or "exclusive" in text: score+=3
    for k in LOW_VALUE_TERMS:
        if k in text: score-=7
    src=(x.get("source_name","")+" "+x.get("source","")).lower()
    if any(str(d).lower() in src for d in priority): score+=2
    if section=="patent" and any(k in text for k in ("판결","소송","침해","무효","심판","우선판매","patent","lawsuit","ptab")): score+=3
    return score

def candidate_day(x):
    try: return parsedate_to_datetime(str(x.get("published_at",""))).date()
    except Exception: return None

def search_candidates(section,settings):
    if section=="domestic":
        queries=['제약 바이오 임상 허가 투자 인수 합병','"단독" 제약 바이오','제약 약가 급여 식약처 심평원','바이오 임상 2상 3상 기술수출']; market="ko-KR"
    elif section=="global":
        queries=[
          'pharma biotech phase 3 topline pivotal FDA approval CRL acquisition licensing',
          'biotech phase 2 phase 3 clinical trial results safety halt',
          'FDA drug approval priority review complete response letter pharma',
          'EMA CHMP medicine approval pharma biotech',
          'pharma biotech M&A licensing deal upfront milestone'
        ]; market="en-US"
    else:
        queries=[
          '제약 특허심판 청구 무효 소극적 권리범위확인',
          '제약 특허심판원 심결 특허법원 판결',
          '제약 우선판매품목허가 우판권 통지의약품',
          '의약품 특허 만료 우판기간 만료',
          '제약 특허법 개정 허가특허연계 법안',
          '국내 제약사 해외 특허 소송 판결',
          'pharma patent lawsuit generic exclusivity court'
        ]; market="ko-KR"
    domains=[]
    if section=="domestic":
        domains=[d for grp in settings.get("domestic",{}).get("collectors",{}).values() for d in grp if "." in d]
        queries += [f"site:{d} 제약 바이오" for d in domains]
    elif section=="global":
        domains=[d for d in settings.get("global",{}).get("sources",[]) if "." in d]
    else:
        domains=[d for d in settings.get("patent",{}).get("sources",[]) if "." in d]
    rows=[]
    for q in queries:
        q += (' when:3d' if section=='patent' else ' when:1d'); enc=urllib.parse.quote(q)
        for u in [f"https://www.bing.com/news/search?q={enc}&format=rss&mkt={market}",f"https://news.google.com/rss/search?q={enc}&hl={'ko' if market=='ko-KR' else 'en-US'}&gl={'KR' if market=='ko-KR' else 'US'}&ceid={'KR:ko' if market=='ko-KR' else 'US:en'}"]:
            rows.extend(rss_items(u))
    out=[]
    for x in rows:
        if not pharma_relevant(x,section): continue
        if any(same_event(x.get("title",""),y.get("title","")) for y in out): continue
        out.append(x)
    return out[:150]

def infer_tag(title,section):
    t=title.lower()
    if section=="patent": return "특허·소송" if any(k in t for k in ("소송","침해","법원","판결","lawsuit","court")) else "특허·IP"
    if any(k in t for k in ("3상","phase 3","pivotal")): return "임상 3상"
    if any(k in t for k in ("2상","phase 2")): return "임상 2상"
    if any(k in t for k in ("허가","승인","fda","ema")): return "허가·규제"
    if any(k in t for k in ("인수","합병","m&a","acquisition")): return "M&A"
    if any(k in t for k in ("투자","기술수출","라이선스","license","deal")): return "투자·기술거래"
    if any(k in t for k in ("급여","약가","보험")): return "약가·급여"
    return "산업"

def load_json(path,default):
    try: return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception: return default

def latest_requests(day):
    qs=urllib.parse.urlencode({"briefing_date":f"eq.{day}","select":"id,briefing_date,section,requested_at","order":"requested_at.desc"})
    rows=supabase_get("/rest/v1/briefing_refresh_requests?"+qs); out={}
    for r in rows:
        s=r.get("section")
        if s in SECTIONS and s not in out: out[s]=r
    return out

def fallback_refresh(day,section,request_at,settings,base,live):
    candidates=search_candidates(section,settings); target=datetime.strptime(day,"%Y-%m-%d").date(); oldest=target-timedelta(days=2 if section=="patent" else 0)
    candidates=[x for x in candidates if candidate_day(x) and oldest<=candidate_day(x)<=target]
    known=[x.get("title","") for x in base.get(section,[])]+[x.get("title","") for x in live.get("items",[])]
    priority=(settings.get("global",{}).get("sources",[]) if section=="global" else settings.get("patent",{}).get("sources",[]) if section=="patent" else [d for grp in settings.get("domestic",{}).get("collectors",{}).values() for d in grp]); ranked=[]
    for x in candidates:
        if any(same_event(x.get("title",""),k) for k in known): continue
        sc=candidate_score(x,section,priority)
        if sc < (6 if section=="domestic" else 4 if section=="global" else 5): continue
        ranked.append((sc,x))
    ranked.sort(key=lambda z:z[0],reverse=True); selected=[]
    for sc,x in ranked:
        if any(same_event(x.get("title",""),y.get("title","")) for y in selected): continue
        title=x.get("title","").strip(); desc=clean_text(x.get("description","")) or title; src=x.get("source","").strip(); source_name=x.get("source_name","").strip() or urllib.parse.urlparse(src).netloc.replace("www.","")
        selected.append({"tag":infer_tag(title,section),"title":title,"summary":desc[:700],"source":src,"source_name":source_name,"published_at":x.get("published_at",""),"article_preview":{"quick":{"title":title,"lead":desc[:350],"title_options":[title,title]},"diff":{"title":title,"direction":"원문과 1차 자료를 추가 확인해 경쟁구도·수치·국내 업계 파급효과를 후속 취재한다.","title_options":[title,title]}}})
        if len(selected)>=8: break
    return {"items":selected}

def section_instructions(section):
    if section=="domestic": return "국내 제약바이오 뉴스. 단순 PR·봉사·행사·제품소개·주가등락은 제외. 동일 사건의 여러 매체 보도는 반드시 1건으로 묶고 가장 정보량과 원문성이 높은 출처만 남긴다. DART/KIND/식약처/복지부/심평원/법원 등 1차자료를 우선 검증한다."
    if section=="global": return "글로벌 제약바이오 뉴스. FDA/EMA/SEC/ClinicalTrials.gov/회사 원문을 우선하고 주요 임상·허가·안전성·대형 딜만 선별한다. 동일 사건 교차매체 보도는 1건만 남긴다."
    return "국내 제약바이오 특허·독점권 전용 뉴스. 최우선은 국내사의 특허심판 청구, 특허심판원 심결, 특허법원·각급법원 판결, 우선판매품목허가, 통지의약품, 특허기간·우판기간 만료, 제약바이오에 영향을 주는 특허법·허가특허연계 입법이다. 다음은 국내 제약바이오기업의 글로벌 특허 사건, 그 다음이 일반 글로벌 대형 특허 사건이다. domestic에 이미 실린 사건도 patent에는 다시 포함할 수 있다. patent 내부 동일 사건만 중복 제거한다."

def make_prompt(day,section,request_at,settings,base,live):
    known=[x.get("title","") for x in base.get(section,[])]+[x.get("title","") for x in live.get("items",[])]
    return f'''당신은 데일리팜 제약바이오 브리핑의 실시간 업데이트 편집자다. 한국 날짜 {day}, 요청시각 {request_at}, 섹션 {section}.
오늘 아침 이후 새로 발생/보도된 기사 중 기사화 가치가 높은 것만 찾는다. 개수 목표는 없으며 0건도 정상이다.
기존 제목: {json.dumps(known,ensure_ascii=False)}
{section_instructions(section)}
우선 출처: {json.dumps(settings.get("global",{}).get("sources",[]) if section=="global" else settings.get("patent",{}).get("sources",[]) if section=="patent" else settings.get("domestic",{}).get("collectors",{}),ensure_ascii=False)}
중요: 제목이 달라도 같은 회사·제품·행사·임상·딜·판결을 다루면 동일 사건이다. 동일 사건은 절대 복수 추가하지 말고 가장 원문성/정보량 높은 1건만 반환한다. 제약바이오와 직접 무관한 기사는 제외한다. 행사 참가·부스 운영·봉사·수상·단순 홍보는 중요한 신규 계약/수치/규제 변화가 없는 한 제외한다. 핵심 사실은 가능한 1차 자료로 검증한다.
각 item은 tag,title,summary,source,source_name,published_at,article_preview를 가진다. article_preview.quick={{title,lead,title_options:[2개]}}, diff={{title,direction,title_options:[2개]}}. 실제 확인 URL만 사용한다. 설명 없이 {{"items":[...]}} JSON만 반환하라.'''

def call_openai(prompt):
    key=os.environ.get("OPENAI_API_KEY")
    if not key: raise RuntimeError("OPENAI_API_KEY is not configured")
    payload={"model":MODEL,"reasoning":{"effort":"medium"},"tools":[{"type":"web_search","search_context_size":"high"}],"tool_choice":"required","input":prompt,"text":{"format":{"type":"json_object"}},"max_output_tokens":18000}
    res=get_json("https://api.openai.com/v1/responses",{"Authorization":f"Bearer {key}","Content-Type":"application/json"},json.dumps(payload).encode(),900); chunks=[]
    for item in res.get("output",[]):
        if item.get("type")=="message":
            for c in item.get("content",[]):
                if c.get("type")=="output_text": chunks.append(c.get("text",""))
    if not chunks: raise RuntimeError("OpenAI response contained no output_text")
    return json.loads("".join(chunks))

def normalize_item(x,completed_at,batch_id):
    return {"tag":x.get("tag",""),"title":x.get("title","").strip(),"summary":x.get("summary","").strip(),"source":x.get("source","").strip(),"source_name":x.get("source_name","").strip(),"published_at":x.get("published_at",""),"article_preview":x.get("article_preview") or {},"live_added_at":completed_at,"update_batch":batch_id,"is_live":True}

def process_section(day,section,req,settings,base):
    path=Path("live")/f"{day}-{section}.json"; live=load_json(path,{"date":day,"section":section,"morning_count":len(base.get(section,[])),"updated_at":"","last_request_at":"","batches":[],"items":[]})
    request_at=req["requested_at"]
    if live.get("last_request_at","")>=request_at: print(section,"already processed",request_at); return False
    try:
        result=call_openai(make_prompt(day,section,request_at,settings,base,live))
    except Exception as e:
        print("AI refresh unavailable; using deterministic fallback:",e,file=sys.stderr)
        result=fallback_refresh(day,section,request_at,settings,base,live)
    now=datetime.now(ZoneInfo("Asia/Seoul")).isoformat(); batch_id=req["id"]
    existing=base.get(section,[])+live.get("items",[]); added=[]
    for raw in result.get("items",[]):
        x=normalize_item(raw,now,batch_id)
        if not x["title"] or not x["source"].startswith("http"): continue
        if not pharma_relevant(x,section): continue
        if section=="domestic" and any(k in (x["title"]+" "+x["summary"]).lower() for k in LOW_VALUE_TERMS) and not any(k in (x["title"]+" "+x["summary"]).lower() for k in ("계약","수주","허가","임상","투자","공시","판결","특허")): continue
        if any(x["source"]==str(y.get("source","")) or same_event(x["title"],str(y.get("title",""))) for y in existing+added): continue
        added.append(x)
    live.update({"date":day,"section":section,"morning_count":len(base.get(section,[])),"updated_at":now,"last_request_at":request_at})
    live.setdefault("items",[]).extend(added); live.setdefault("batches",[]).append({"request_id":batch_id,"requested_at":request_at,"completed_at":now,"added_count":len(added)})
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(live,ensure_ascii=False,indent=2),encoding="utf-8")
    print(section,":",len(added),"new; total live",len(live["items"])); return True

def main():
    day=datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d"); reqs=latest_requests(day)
    if not reqs: print("no refresh requests for",day); return
    base=load_json(Path("data")/f"{day}.json",{})
    if not base: raise SystemExit("morning briefing is missing")
    try:
        rows=supabase_get("/rest/v1/app_settings?key=eq.main&select=value"); settings=rows[0]["value"] if rows else {}
    except Exception: settings=load_json("config/briefing-settings.json",{})
    changed=False; failures=[]
    for section,req in reqs.items():
        try: changed=process_section(day,section,req,settings,base) or changed
        except Exception as e: failures.append(section); print(f"{section} refresh failed: {e}",file=sys.stderr)
    if failures: raise SystemExit("refresh failed for: "+", ".join(failures))
    if not changed: print("no unprocessed refresh requests")

if __name__=="__main__": main()
