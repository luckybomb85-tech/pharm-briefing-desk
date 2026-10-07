import json, os, urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

MODEL=os.getenv("OPENAI_MODEL","gpt-5.6")
URL="https://mqkhtnryxyntrrfrfing.supabase.co"
KEY="sb_publishable_GLp72jjAPgHWqUEpqtnw5Q_rY3lfcB8"

def req(url, headers=None, data=None, timeout=900):
    r=urllib.request.Request(url,data=data,headers=headers or {})
    with urllib.request.urlopen(r,timeout=timeout) as x: return json.load(x)

def public_cases():
    try:
        return req(URL+"/rest/v1/tracked_cases?visibility=eq.public&select=court,case_number,party,note,status",
          {"apikey":KEY,"Authorization":f"Bearer {KEY}"})
    except Exception: return []

def call(prompt):
    key=os.environ.get("OPENAI_API_KEY")
    if not key: raise SystemExit("OPENAI_API_KEY is not configured")
    body={"model":MODEL,"reasoning":{"effort":"low"},"tools":[{"type":"web_search","search_context_size":"high"}],
          "tool_choice":"required","input":prompt,"text":{"format":{"type":"json_object"}},"max_output_tokens":20000}
    out=req("https://api.openai.com/v1/responses",{"Authorization":f"Bearer {key}","Content-Type":"application/json"},json.dumps(body).encode())
    text="".join(c.get("text","") for i in out.get("output",[]) if i.get("type")=="message" for c in i.get("content",[]) if c.get("type")=="output_text")
    return json.loads(text)

def write_health(status, now, detail, event_count=None):
    p=Path("status/schedule-health.json"); p.parent.mkdir(parents=True,exist_ok=True)
    payload={"status":status,"checked_at":now.isoformat(timespec="seconds"),"timezone":"Asia/Seoul","detail":detail}
    if event_count is not None: payload["event_count"]=event_count
    p.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")

def main():
    p=Path("schedule/events.json"); old=json.loads(p.read_text(encoding="utf-8"))
    now=datetime.now(ZoneInfo("Asia/Seoul")); today=now.strftime("%Y-%m-%d")
    existing=[x for x in old.get("events",[]) if x.get("date","")>=today]
    cases=public_cases()
    prompt=f"""한국 제약바이오 전문기자의 미래 취재일정 수집기다. 오늘은 {today}.
live web search를 사용해 앞으로 180일 내 취재 가치가 있는 일정 중 새로 공개되거나 변경된 내용을 찾고, 아래 기존 자동일정과 병합한 전체 JSON을 반환하라.
우선 복지부, 식약처, 심평원, 건보공단, 보건산업진흥원, 국회, DART/KRX, 법원/특허법원, 특허청/KIPRIS, 제약바이오 기업 뉴스룸/IR, 학회·세미나 공식 공지를 검색한다. 최근 90일 기사·보도자료 속 미래 날짜도 역검색한다.
범주: 기자간담회, 정부·위원회, 법원·소송, 특허·심판, 학회·세미나, IR·주총, 허가·규제, 제품출시, 기타.
기존 일정과 같은 사건이면 중복 생성하지 말고 더 정확한 시간·장소·상태·출처로 보완한다. 날짜가 지난 일정은 제외한다. 시간·장소·사건번호를 모르면 빈 문자열. 추정 금지. 허가 예상일은 공식기관/회사가 날짜를 명시한 경우만.
관심소송은 공개 확인 가능한 변론·선고기일 또는 기일변경이 있을 때만 일정으로 추가한다.
기존 일정={json.dumps(existing,ensure_ascii=False)}
공개 관심소송={json.dumps(cases,ensure_ascii=False)}
최상위 JSON은 {{"events":[...]}}만. 각 event는 id,date,end_date,time,end_time,title,category,confidence,place,organization,case_number,memo,source,source_name,first_seen,last_checked,entry_type 필드를 모두 가진다. confidence는 공식확정/주최측확인/보도예정/미확정 중 하나. entry_type='auto'. JSON만 출력."""
    try:
        d=call(prompt)
    except Exception as e:
        write_health("FAIL",now,f"schedule collector failed: {type(e).__name__}: {e}")
        raise
    events=d.get("events")
    if not isinstance(events,list): raise SystemExit("invalid events output")
    seen=set()
    for e in events:
        if not e.get("id") or not e.get("date") or not e.get("title") or not e.get("source"): raise SystemExit("event missing required fields")
        if e["id"] in seen: raise SystemExit("duplicate event id")
        seen.add(e["id"])
    out={"version":1,"updated_at":now.isoformat(timespec="seconds"),"timezone":"Asia/Seoul","events":events,"tracked_cases":[],"notes":old.get("notes","Shared schedule database.")}
    p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    write_health("PASS",now,"same-day schedule collection completed",len(events))
    print(f"schedule updated: {len(events)} future events")

if __name__=="__main__": main()
