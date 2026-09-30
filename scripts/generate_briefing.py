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

목표 출력은 domestic 정확히 {counts.get('domestic',10)}개, global 정확히 {counts.get('global',10)}개, patent 정확히 {counts.get('patent',5)}개다. 그러나 숫자를 먼저 채우지 말고 반드시 넓은 후보군을 만든 뒤 기사 가치를 비교해 선별한다. 국내 최소 30건, 글로벌 최소 30건, 특허 최소 15건의 서로 다른 사건을 탐색하는 것을 목표로 하고, 검색 결과가 부족하면 검색어·회사·기관·매체를 바꿔 추가 탐색한다. 봉사활동·단순 내부행사·단순 제품홍보·반복 보도·의미 없는 행정기한으로 숫자를 채우지 않는다.
국내·글로벌은 원칙적으로 직전 24시간, 특허는 직전 24시간 우선이며 국내 특허가 부족할 때만 72시간까지 넓힌다.

[국내 뉴스 탐색]
국내 기업의 해외 임상·허가·투자도 domestic으로 분류한다. 먼저 DART, KRX, 식약처, 복지부, 심평원, 건보공단, 법원 등 1차자료를 확인한다.
그 다음 아래 국내 매체를 특정 매체에 편중되지 않도록 폭넓게 각각 탐색하고 후보를 합친 뒤 중요도를 비교한다:
데일리팜, 히트뉴스, 메디파나뉴스, 바이오스펙테이터, 한경 바이오인사이트, 팜이데일리, 더벨, 시사저널e, 바이오타임즈, 헬스코리아뉴스, 메디컬옵저버, 더바이오, 메디팜스투데이, 뉴스더보이스헬스케어, 딜사이트, 비즈니스포스트, 뉴스핌, 뉴데일리경제, 코메디닷컴 산업/제약바이오, 뉴스1, 연합뉴스, 뉴시스, 조선비즈, 서울경제, 머니투데이, 전자신문, 비즈워치, 아시아경제, 매일경제, 한국경제, 파이낸셜뉴스, 이투데이, 쿠키뉴스, 이코노미스트, 헤럴드경제, 아주경제.
의협신문, 메디게이트뉴스, 팜뉴스, 약업신문, 약사공론, 메디칼타임즈는 domestic 후보 출처에서 제외한다.
어느 한 매체에서 필요한 개수를 확보했더라도 검색을 종료하지 않는다. 단독/법원·특허/약가·급여/정책·규제/대형 계약·M&A/임상 결과·허가/기업 실적·재무 이상징후를 우선한다.

[글로벌 뉴스 탐색]
FDA, EMA, SEC, ClinicalTrials.gov와 회사 공식 IR/Newsroom을 1차자료로 우선 확인한다. Reuters, STAT, Endpoints News, BioPharma Dive, Fierce Pharma, Fierce Biotech, BioSpace, FirstWord Pharma, Scrip/Pink Sheet, Evaluate, Pharmaceutical Technology, Labiotech, GEN 등을 폭넓게 탐색한다. Fierce 등 한 매체에 후보가 편중되지 않도록 한다. 한국 기업 직접 이슈는 domestic으로 보낸다.

[특허·소송 탐색: 국내 최우선]
patent 5개는 국내 사건을 먼저 채운 뒤 국내에서 기사 가치 있는 사건이 부족한 경우에만 해외 사건으로 보충한다.
국내 1차 탐색 순서: KIPRIS 신규 심판/심결 → 특허심판원 → 특허법원 → 대법원/각급법원 → 식약처 의약품 특허목록·우선판매품목허가·허가특허연계 자료 → 지식재산처/IP-NAVI.
국내 특허 보도 탐색에는 데일리팜, 히트뉴스, 메디파나뉴스, 헬스코리아뉴스, 바이오스펙테이터, 한경 바이오인사이트, 팜이데일리, 더벨 등을 사용한다.
우선순위는 국내 제약사의 신규 특허도전 > 심결·판결 > 항소/소송 제기 > 우판권·출시일 변화 > 국내사가 당사자인 해외소송 > 글로벌 대형 제약 특허판결 > 중요한 신규특허 > 단순 PTE·행정절차 순이다.
해외 보충 시 Reuters Legal, Law360 Life Sciences, Bloomberg Law, IAM, STAT, Endpoints, Fierce 및 USPTO/PTAB, 미국 연방법원, FDA Orange Book/Purple Book, EPO/UPC를 탐색한다.
단순 특허등록이나 PTE 기한은 시장·출시·독점기간에 실질 영향이 확인되지 않으면 5개를 채우기 위한 후보로 사용하지 않는다.

[선정]
설정의 priority_sources에 등록된 사이트는 다른 일반 출처보다 먼저 검색하고 후보 선정에서 우선 가중한다. 특히 priority_sources의 국내 사이트에서 제목·본문·메타데이터에 '단독', '[단독]', 'Exclusive', '특종' 등 독자취재 표시가 확인된 제약바이오 관련 기사는 반드시 후보군에 넣고, 동일 사건의 단순 보도자료 전재보다 우선 검토한다. 단독 표시는 출처가 실제로 표시한 경우에만 인정하며 임의로 추정하지 않는다. 광고성·비관련·사실 확인이 어려운 단독은 제외할 수 있다.
후보들을 ① 데일리팜 후속기사화 가능성 ② 새 정보·단독성 ③ 금액·임상수치·판결 등 구체성 ④ 국내 제약업계 파급력 ⑤ 기존 이슈와 연결되는 후속취재 가치로 비교한다. 객관적 중요뉴스(FDA/EMA/식약처 허가, 주요 2·3상 결과·중단·안전성, 약가·급여·정책, 대형 기술거래/M&A, 중요 특허·판결, 중대한 실적/재무)는 피드백과 무관하게 독립 평가한다.

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
