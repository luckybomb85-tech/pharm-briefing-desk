"""Export bounded domestic editorial candidates for the existing public desk.

Discovery-only: article titles are not assertions of verified underlying facts.
Do not overwrite a prior valid desk file with an empty or malformed result.
"""
import json
import sys
from pathlib import Path

def publish(day):
    source=Path(f"staging/{day}-domestic-stage4.json")
    data=json.loads(source.read_text(encoding="utf-8"))
    if data.get("date") != day or not isinstance(data.get("domestic"),list):
        raise ValueError("INVALID_DOMESTIC_STAGE4")
    items=[]
    for row in data["domestic"]:
        title=str(row.get("title") or row.get("representative",{}).get("title") or "").strip()
        url=str(row.get("source") or row.get("url") or row.get("original_url") or "").strip()
        if not url and isinstance(row.get("representative"),dict):
            url=str(row["representative"].get("url") or "")
        if not title or not url.startswith("https://"):
            continue
        items.append({"title":title,"source":url,"source_name":row.get("source_name",""),
                      "published_at":row.get("published_at",""),"tag":row.get("priority","국내"),
                      "summary":"국내 기사 취재 후보입니다. 제목과 기사 내용의 사실관계는 원문 확인이 필요합니다.",
                      "discovery_only":True,"priority":row.get("priority","P3"),
                      "event_status":row.get("event_status","NEW")})
    if not items:
        raise ValueError("DOMESTIC_NO_VALID_CANDIDATES: previous data preserved")
    output=Path("domestic")/f"{day}.json"
    output.parent.mkdir(parents=True,exist_ok=True)
    payload={"date":day,"status":"discovery-only","items":items,
             "note":"자동 수집된 취재 후보. 원문 및 핵심 사실은 별도 검증 필요."}
    output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"Domestic desk export: {len(items)} candidates -> {output}")

if __name__=="__main__":
    publish(sys.argv[1])
