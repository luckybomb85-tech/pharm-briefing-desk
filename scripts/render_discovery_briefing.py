"""Produce a readable discovery briefing; never label index hits fact-verified."""
import argparse,json
from pathlib import Path
def render(day,stage4,global_shortlist):
    lines=[f"# 제약바이오 브리핑 후보 | {day}","","> 자동 수집·선별 결과입니다. 제목·발행 시각·본문의 사실관계는 원문 확인 전까지 미검증입니다.",""]
    domestic=stage4.get("domestic",[])
    global_rows=global_shortlist.get("shortlist",[])
    for heading,rows in (("국내 기사 후보",domestic[:20]),("글로벌 기사 후보",global_rows[:10])):
        lines.extend([f"## {heading}",""])
        if not rows:lines.extend(["후보 없음(수집 범위 완전성 확인 필요).",""]);continue
        for i,row in enumerate(rows,1):
            title=str(row.get("title") or row.get("representative",{}).get("title") or "제목 미확인").replace("\n"," ").strip()
            url=row.get("url") or row.get("source") or row.get("original_url") or ""
            if not url and isinstance(row.get("representative"),dict):url=row["representative"].get("url","")
            level=row.get("priority",row.get("score",""))
            lines.append(f"{i}. **{title}**"+(f" · {level}" if level!="" else ""))
            if str(url).startswith(("https://","http://")):lines.append(f"   - 발견 링크: {url}")
            lines.append("   - 상태: 수집 후보 / 원문 사실관계 미검증")
        lines.append("")
    lines.append("자동 기사 발행: 비활성화. 검색 누락 여부 및 기사 사실관계는 별도 확인 필요.")
    return "\n".join(lines)+"\n"
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--date",required=True);ap.add_argument("--domestic",required=True);ap.add_argument("--global-shortlist",required=True);ap.add_argument("--output",required=True)
    a=ap.parse_args()
    d=json.loads(Path(a.domestic).read_text(encoding="utf-8"));g=json.loads(Path(a.global_shortlist).read_text(encoding="utf-8"))
    Path(a.output).write_text(render(a.date,d,g),encoding="utf-8")
