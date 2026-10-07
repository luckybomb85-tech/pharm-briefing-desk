import json, os, urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

MODEL=os.getenv("OPENAI_MODEL","gpt-5.6")
URL="https://mqkhtnryxyntrrfrfing.supabase.co"
KEY="sb_publishable_GLp72jjAPgHWqUEpqtnw5Q_rY3lfcB8"

def req(url,headers=None,data=None,timeout=900):
    r=urllib.request.Request(url,data=data,headers=headers or {})
    with urllib.request.urlopen(r,timeout=timeout) as x: return json.load(x)

def public_cases():
    try:
        rows=req(URL+"/rest/v1/tracked_cases?visibility=eq.public&select=court,case_number,party,note,status",{"apikey":KEY,"Authorization":f"Bearer {KEY}"})
        return rows, "PASS"
    except Exception as e:
        return [], f"PARTIAL:{type(e).__name__}"

def call(prompt):
    key=os.environ.get("OPENAI_API_KEY")
    if not key: raise RuntimeError("OPENAI_API_KEY is not configured")
    body={"model":MODEL,"reasoning":{"effort":"low"},"tools":[{"type":"web_search","search_context_size":"high"}],"tool_choice":"required","input":prompt,"text":{"format":{"type":"json_object"}},"max_output_tokens":16000}
    out=req("https://api.openai.com/v1/responses",{"Authorization":f"Bearer {key}","Content-Type":"application/json"},json.dumps(body).encode())
    text="".join(c.get("text","") for i in out.get("output",[]) if i.get("type")=="message" for c in i.get("content",[]) if c.get("type")=="output_text")
    if not text: raise RuntimeError("empty model output")
    return json.loads(text)

def write_health(status,now,detail,event_count=None,case_source_status=None):
    p=Path("status/schedule-health.json"); p.parent.mkdir(parents=True,exist_ok=True)
    x={"status":status,"checked_at":now.isoformat(timespec="seconds"),"timezone":"Asia/Seoul","detail":detail}
    if event_count is not None: x["event_count"]=event_count
    if case_source_status is not None: x["tracked_cases_source_status"]=case_source_status
    p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding="utf-8")

def valid_event(e):
    return isinstance(e,dict) and bool(e.get("id")) and bool(e.get("date")) and bool(e.get("title")) and str(e.get("source","")).startswith(("http://","https://"))

def merge(existing,candidates,today):
    by_id={str(e["id"]):dict(e) for e in existing if valid_event(e) and e.get("date","")>=today}
    for n in candidates:
        if not valid_event(n) or n.get("date","")<today: continue
        eid=str(n["id"])
        if eid in by_id:
            old=by_id[eid]
            for k,v in n.items():
                if v not in ("",None,[]): old[k]=v
            old["last_checked"]=n.get("last_checked") or old.get("last_checked","")
            by_id[eid]=old
        else:
            n=dict(n); n["entry_type"]="auto"; by_id[eid]=n
    return sorted(by_id.values(),key=lambda x:(x.get("date",""),x.get("time",""),x.get("title","")))

def main():
    now=datetime.now(ZoneInfo("Asia/Seoul")); today=now.strftime("%Y-%m-%d")
    try:
        p=Path("schedule/events.json"); old=json.loads(p.read_text(encoding="utf-8"))
        existing=[x for x in old.get("events",[]) if x.get("date","")>=today]
        cases,case_status=public_cases()
        prompt=f"""한국 제약바이오 전문기자의 미래 취재일정 수집기다. 오늘은 {today}.
live web search로 앞으로 180일 내 새로 공개되거나 기존 정보가 변경된 취재일정 후보만 반환하라. 기존 일정 전체를 다시 작성하지 말라.
우선 복지부, 식약처, 심평원, 건보공단, 보건산업진흥원, 국회, DART/KRX, 법원/특허법원, 특허청/KIPRIS, 제약바이오 기업 뉴스룸/IR, 학회·세미나 공식 공지를 검색한다. 최근 기사·보도자료 속 미래 날짜도 확인한다.
범주: 기자간담회, 정부·위원회, 법원·소송, 특허·심판, 학회·세미나, IR·주총, 허가·규제, 제품출시, 기타.
기존 일정과 같은 사건의 날짜·시간·장소·상태가 변경됐다면 같은 id로 변경된 필드를 포함해 반환한다. 새 정보가 없으면 반환하지 않는다. 시간·장소·사건번호 추정 금지.
기존 일정={json.dumps(existing,ensure_ascii=False)}
공개 관심소송={json.dumps(cases,ensure_ascii=False)}
최상위 JSON은 {{"events":[...]}}. 각 event는 id,date,end_date,time,end_time,title,category,confidence,place,organization,case_number,memo,source,source_name,first_seen,last_checked,entry_type 필드를 가진다. source는 실제 확인한 http/https 원문 URL. confidence는 공식확정/주최측확인/보도예정/미확정. JSON만 출력."""
        d=call(prompt); candidates=d.get("events")
        if not isinstance(candidates,list): raise RuntimeError("invalid events output")
        bad=[e for e in candidates if not valid_event(e)]
        if bad: raise RuntimeError(f"invalid candidate events: {len(bad)}")
        events=merge(existing,candidates,today)
        if len(events)<len(existing):
            raise RuntimeError("merge would drop existing future events")
        out={"version":1,"updated_at":now.isoformat(timespec="seconds"),"timezone":"Asia/Seoul","events":events,"tracked_cases":[],"notes":old.get("notes","Shared schedule database.")}
        p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
        health="PASS" if case_status=="PASS" else "PARTIAL"
        write_health(health,now,f"schedule collection completed; {len(candidates)} candidate updates; existing future events preserved",len(events),case_status)
        print(f"schedule updated: {len(events)} future events; candidates {len(candidates)}; health {health}")
    except Exception as e:
        write_health("FAIL",now,f"schedule collector failed: {type(e).__name__}: {e}")
        raise

if __name__=="__main__": main()
