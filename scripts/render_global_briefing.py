"""Render an editorial global discovery briefing from an existing shortlist. No network."""
import argparse,json
from pathlib import Path
def render(day,shortlist,limit=10):
    rows=shortlist.get("shortlist",[])[:limit]
    lines=[f"# 글로벌 제약바이오 브리핑 | {day}","","> 자동 발견·선별된 취재 후보입니다. 원문 및 핵심 사실은 기사 작성 전 확인해야 합니다.",""]
    if not rows:lines.extend(["선별 후보 없음. 검색 누락 또는 수집 경로 장애 가능성을 별도로 확인해야 합니다.",""])
    for i,row in enumerate(rows,1):
        title=" ".join(str(row.get("title","제목 미확인")).split())
        lines.append(f"### {i}. {title}")
        lines.append(f"- 매체: {row.get('source','미확인')} | 중요도 점수: {row.get('score',0)}")
        lines.append(f"- 분류: {', '.join(row.get('signals',[])) or '기타'}")
        url=str(row.get("url",""))
        if url.startswith(("https://","http://")):lines.append(f"- 발견 링크: {url}")
        lines.append("- 확인 수준: 검색 색인 후보 (원문 사실관계 미검증)")
        lines.append("")
    lines.extend([f"선별 대상 {shortlist.get('total_input',0)}건 중 중요도 기준 통과 {shortlist.get('ranked_count',0)}건. 상위 {len(rows)}건 표시.","","자동 기사 발행 없음. 원문 검증 실패는 브리핑 후보 제외 사유가 아닙니다.",""])
    return "\n".join(lines)
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--date",required=True);ap.add_argument("--input",required=True);ap.add_argument("--output",required=True);args=ap.parse_args()
    data=json.loads(Path(args.input).read_text(encoding="utf-8"))
    Path(args.output).write_text(render(args.date,data),encoding="utf-8")
