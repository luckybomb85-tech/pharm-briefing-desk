import json, os, sys, urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SUPABASE_URL="https://mqkhtnryxyntrrfrfing.supabase.co"
SUPABASE_KEY="sb_publishable_GLp72jjAPgHWqUEpqtnw5Q_rY3lfcB8"
MODEL=os.getenv("OPENAI_MODEL","gpt-6.1-sol")

def get_json(url, headers=None, data=None):
    req=urllib.request.Request(url,data=data,headers=headers or {})
    with urllib.request.urlopen(req,timeout=900) as r:
        return json.load(r)

def supabase(path, method="GET", body=None):
    headers={"apikey":SUPABASE_KEY,"Authorization":f"Bearer {SUPABASE_KEY}","Content-Type":"application/json"}
    data=None if body is None else json.dumps(body).encode()
    return get_json(SUPABASE_URL+path,headers,data)

def settings_and_feedback():
    try:
        rows=supabase("/rest/v1/app_settings?key=eq.main&select=value")
        settings=rows[0]["value"] if rows else {}
    except Exception as e:
        print("settings fallback:",e,file=sys.stderr)
        settings=json.loads(Path("config/briefing-settings.json").read_text(encoding="utf-8"))
    try:
        feedback=supabase("/rest/v1/rpc/get_feedback_learning_profile",method="POST",body={})
    except Exception as e:
        print("feedback unavailable:",e,file=sys.stderr); feedback=[]
    return settings,feedback

def prompt(day, settings, feedback, retry=""):
    counts=settings.get("target_counts",{"domestic":10,"global":10,"patent":5})
    sources=settings.get("priority_sources",{})
    principles=settings.get("briefing_principles","")
    return f"""당신은 한국 제약바이오 전문매체 데일리팜의 아침 뉴스 편집자다. 현재 한국 날짜는 {day}다.
반드시 live web search를 적극 사용해 오늘 아침 브리핑을 JSON 하나로 작성하라.

완료조건은 domestic 정확히 {counts.get('domestic',10)}개, global 정확히 {counts.get('global',10)}개, patent 정확히 {counts.get('patent',5)}개다. 이는 최대치가 아니라 완료조건이다.
국내·글로벌은 원칙적으로 직전 24시간에서 찾고 부족하면 검색어·회사·기관·전문매체를 넓힌다. 특허는 직전 24시간에서 부족하면 72시간까지 확장하고 summary에서 날짜를 분명히 밝힌다. 봉사활동·단순 내부행사·제품 홍보성 문구로 숫자를 채우지 않는다.
국내: 국내 기업 직접 해외 임상/허가/투자 포함. DART, KRX, 식약처, 복지부, 심평원, 법원, 특허기관, 데일리팜 등 전문매체 우선.
글로벌: FDA, EMA, SEC, ClinicalTrials.gov, 회사 공식자료, Reuters, STAT, Fierce Pharma/Biotech 등 우선. 한국 기업 직접 이슈는 국내로 보낸다.
특허: KIPRIS, 특허법원/대법원/특허심판원, 식약처 허가특허연계, USPTO/PTAB/미국 법원 원문 우선. 특허등록, 무효/권리범위확인, 제네릭 도전, 침해소송, 영업비밀/IP, 특허기간연장까지 포함한다.
객관적 중요뉴스(FDA/EMA/식약처 허가, 주요 2·3상 결과·중단·안전성, 약가·급여·정책, 대형 기술거래/M&A, 중요 특허·판결, 중대한 실적/재무)는 피드백과 무관하게 반드시 독립 평가한다.

운영 원칙: {principles}
우선 출처 설정: {json.dumps(sources,ensure_ascii=False)}
최근 30일 편집 피드백 집계(후보 간 가중치 보정에만 사용): {json.dumps(feedback,ensure_ascii=False)}

각 항목 필드:
tag, title, summary, source, source_name, published_at, article_preview.
summary는 사실 중심 3~5문장으로 핵심 수치·이전 대비 변화·기사 가치를 포함한다.
source는 반드시 실제 확인한 원문 또는 신뢰할 수 있는 기사 URL 전체 문자열이어야 한다. source_name은 사람이 읽는 기관/매체명이다.
published_at은 원문 게시시각을 확인한 경우만 한국시간 'M. D. 오전/오후 HH:MM', 아니면 빈 문자열.
article_preview.quick={{title,lead,title_options:[대안2개]}}. lead는 실제 스트레이트 기사 첫 문단 1~2문장.
article_preview.diff={{title,direction,title_options:[대안2개]}}. direction은 차별화 후속취재 방향 2~3문장.
같은 사건을 중복으로 세지 않는다. 확인되지 않은 사실은 추정하지 않는다.

최상위 JSON은 반드시:
{{"date":"{day}","timezone":"Asia/Seoul","status":"published","domestic":[...10개...],"global":[...10개...],"patent":[...5개...]}}
설명이나 마크다운 없이 JSON만 출력하라.
{retry}
"""

def call_openai(text):
    key=os.environ.get("OPENAI_API_KEY")
    if not key: raise SystemExit("OPENAI_API_KEY is not configured")
    payload={
      "model":MODEL,
      "reasoning":{"effort":"medium"},
      "tools":[{"type":"web_search","search_context_size":"high"}],
      "tool_choice":"required",
      "input":text,
      "text":{"format":{"type":"json_object"}},
      "max_output_tokens":30000
    }
    res=get_json("https://api.openai.com/v1/responses",
        {"Authorization":f"Bearer {key}","Content-Type":"application/json"},
        json.dumps(payload).encode())
    chunks=[]
    for item in res.get("output",[]):
        if item.get("type")=="message":
            for c in item.get("content",[]):
                if c.get("type")=="output_text": chunks.append(c.get("text",""))
    if not chunks: raise RuntimeError("OpenAI response contained no output_text")
    return json.loads("".join(chunks))

def basic_validate(d, day):
    errs=[]
    if d.get("date")!=day: errs.append("date")
    if d.get("status")!="published": errs.append("status")
    for k,n in (("domestic",10),("global",10),("patent",5)):
        a=d.get(k)
        if not isinstance(a,list) or len(a)!=n: errs.append(f"{k} count={len(a) if isinstance(a,list) else 'invalid'}")
        elif len({x.get("title","").strip() for x in a})!=n: errs.append(f"{k} duplicate titles")
    return errs

def main():
    day=datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    settings,feedback=settings_and_feedback()
    retry=""
    for attempt in range(2):
        d=call_openai(prompt(day,settings,feedback,retry))
        errs=basic_validate(d,day)
        if not errs:
            p=Path("data")/f"{day}.json"
            p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
            print(f"generated {p}: 10/10/5 using {MODEL}")
            return
        retry="이전 생성은 검증 실패했다: "+", ".join(errs)+". 부족한 항목을 추가 검색해 반드시 정확한 10/10/5 JSON으로 다시 생성하라."
        print(retry,file=sys.stderr)
    raise SystemExit("generation failed hard validation after retry")

if __name__=="__main__":
    main()
