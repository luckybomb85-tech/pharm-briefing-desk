"""Safely expose domestically collected original articles as *discovery* candidates.

Only verified publisher URLs with publisher publication timestamps are exported.
A WEB search index hit, however highly ranked, is never silently promoted.
The independent underlying article facts remain editorially unverified.
"""
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
OUTLETS = {
    "dailypharm.com": "데일리팜",
    "medipana.com": "메디파나뉴스",
    "hitnews.co.kr": "히트뉴스",
    "thebionews.net": "더바이오",
    "newsthevoice.com": "뉴스더보이스",
    "apsk.co.kr": "메디팜스투데이",
    "biospectator.com": "바이오스펙테이터",
    "biotimes.co.kr": "바이오타임즈",
    "dealsite.co.kr": "딜사이트",
    "businesspost.co.kr": "비즈니스포스트",
    "newspim.com": "뉴스핌",
    "newdaily.co.kr": "뉴데일리",
    "hankyung.com": "한국경제",
    "pharm.edaily.co.kr": "이데일리",
}
OUTLET_SUFFIX = re.compile(
    r"\\s+[-|]\\s+(?:데일리팜|메디파나뉴스|히트뉴스|뉴스더보이스|"
    r"메디팜스투데이|바이오스펙테이터|바이오타임즈|딜사이트|"
    r"비즈니스포스트|뉴스핌|뉴데일리|한국경제|이데일리)$"
)
NON_EDITORIAL = re.compile(
    r"(?:KLPGA|프로골프|(?:후원|협찬).{0,35}(?:선수|프로|우승|시즌\\s*\\d+승)|"
    r"광고[·\\s&/]*PR.{0,25}(?:대상|공모)|"
    r"봉사활동|체육대회|임직원 워크숍|사내 행사|"
    r"창립기념식|기부금 전달|(?:통합 )?IR데이)"
)
MATERIAL = re.compile(
    r"(?:임상\\s*[123]상|[123]상\\s*(?:결과|성공|실패)|"
    r"FDA\\s*(?:허가|승인)|"
    r"기술수출|기술이전|지분변동|최대주주 변경|"
    r"경영권|약가|급여|특허|판결|소송|실적 발표)"
)


def headline(raw):
    value = str(raw or "").strip()
    value = re.sub(r"^\\s*\\[데일리팜\\]\\s*", "", value)
    # Some publisher native-list extractors concatenate the article body.
    value = re.split(r"\\s*\\[데일리팜\\s*[=·]\\s*[^\\]]*기자\\]", value, maxsplit=1)[0]
    value = OUTLET_SUFFIX.sub("", value)
    return " ".join(value.split())


def valid_original(row, day):
    if row.get("verified_original") is not True or row.get("timestamp_unverified") is True:
        return False
    url = str(row.get("source") or "")
    split = urlsplit(url)
    if split.scheme != "https" or not split.hostname or split.hostname.lower() in ("news.google.com", "news.google.co.kr"):
        return False
    try:
        moment = datetime.fromisoformat(str(row.get("published_at") or ""))
        if moment.tzinfo is None:
            return False
        local = moment.astimezone(KST)
        start = datetime.fromisoformat(day + "T00:00:00").replace(tzinfo=KST) - timedelta(hours=12)
        end = datetime.fromisoformat(day + "T00:00:00").replace(tzinfo=KST) + timedelta(days=1)
        return start <= local < end
    except (ValueError, TypeError, OverflowError):
        return False


def curate(day, rows):
    if not isinstance(rows, list):
        raise ValueError("INVALID_DOMESTIC_ROWS")
    items = []
    seen = set()
    counts = {"input":len(rows),"skipped_unverified":0,"skipped_non_editorial":0,
              "skipped_duplicate":0,"selected":0}
    for row in rows:
        if not isinstance(row, dict) or not valid_original(row, day):
            counts["skipped_unverified"] += 1
            continue
        title = headline(row.get("title"))
        if not title or len(title) < 7:
            counts["skipped_non_editorial"] += 1
            continue
        if NON_EDITORIAL.search(title) and not MATERIAL.search(title):
            counts["skipped_non_editorial"] += 1
            continue
        url = str(row["source"]).strip()
        if url in seen:
            counts["skipped_duplicate"] += 1
            continue
        seen.add(url)
        host = urlsplit(url).hostname.lower().removeprefix("www.")
        raw_source = str(row.get("source_name") or "").strip()
        display_source = OUTLETS.get(raw_source, OUTLETS.get(host, raw_source or host))
        items.append({
            "title":title, "source":url,"source_name":display_source,
            "published_at":row["published_at"], "tag":row.get("tag") or row.get("priority") or "국내",
            "summary":"국내 매체의 원문 주소와 발행시각이 확인된 취재 후보입니다. 본문 핵심 사실은 별도 검증이 필요합니다.",
            "discovery_only":True,
            "verification_status":"PUBLISHER_ORIGINAL_TIME_CHECKED_CORE_FACT_PENDING",
            "priority":row.get("priority","P3"),
            "event_status":row.get("event_status","NEW"),
        })
    counts["selected"] = len(items)
    return items, counts


def publish(day):
    path = Path("staging") / (day + "-domestic-stage4.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("date") != day or not isinstance(data.get("domestic"), list):
        raise ValueError("INVALID_DOMESTIC_STAGE4")
    items, counts = curate(day, data["domestic"])
    if not items:
        raise ValueError("DOMESTIC_NO_VERIFIED_CANDIDATES: previous data preserved")
    target = Path("domestic") / (day + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"date":day,"status":"discovery-only","items":items,
               "statistics":counts,
               "note":"발행일·원문 주소 확인 후 선별된 국내 기사. 기사의 핵심 사실은 독립 검증 전."}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    print(f"Domestic desk export: {counts} -> {target}")


if __name__ == "__main__":
    publish(sys.argv[1])
