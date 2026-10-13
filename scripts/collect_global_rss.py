#!/usr/bin/env python3
"""Collect dated global pharmaceutical news candidates for the existing desk."""
import datetime as dt
import email.utils
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime.now(KST)
DAY = NOW.date().isoformat()
START = dt.datetime.combine(NOW.date()-dt.timedelta(days=1), dt.time(12), KST)
SOURCES = [
 ("Fierce Pharma","fiercepharma.com"), ("Fierce Biotech","fiercebiotech.com"),
 ("BioPharma Dive","biopharmadive.com"), ("BioSpace","biospace.com"),
 ("STAT","statnews.com"), ("Endpoints News","endpts.com"),
 ("FirstWord Pharma","firstwordpharma.com"), ("Pharmaceutical Technology","pharmaceutical-technology.com"),
 ("GEN","genengnews.com"), ("Reuters","reuters.com"),
 ("Evaluate","evaluate.com"), ("Scrip","citeline.com"), ("Labiotech","labiotech.eu"),
]
TERMS = re.compile(r"trial|phase [123]|FDA|EMA|approval|drug|biotech|pharma|clinical|patent|license|acquisition|therapy|vaccine|regulator|cancer|biosimilar",re.I)

def read_feed(domain):
    q = urllib.parse.quote(f"site:{domain} (pharma OR biotech OR clinical OR FDA OR trial) when:2d")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; PharmBriefing/1.0)"})
    with urllib.request.urlopen(req,timeout=18) as response:
        return ET.fromstring(response.read(1500000))

def collect():
    items=[]; errors={}; seen=set(); successes=0
    for name,domain in SOURCES:
        try:
            root=read_feed(domain)
            successes+=1
            for entry in root.findall("./channel/item"):
                title=(entry.findtext("title") or "").strip()
                link=(entry.findtext("link") or "").strip()
                date=entry.findtext("pubDate") or ""
                if not title or not link or not TERMS.search(title):continue
                try:published=email.utils.parsedate_to_datetime(date).astimezone(KST)
                except (TypeError,ValueError):continue
                if not START<=published<=NOW:continue
                original=title.rsplit(" - ",1)[0].strip()
                key=re.sub(r"[^a-z0-9]+","",original.lower())[:110]
                if key in seen:continue
                seen.add(key)
                items.append({"title":original,"original_title":original,"source":link,
                              "source_name":name,"published_at":published.isoformat(),
                              "tag":"GLOBAL","summary":"해외 전문매체 검색으로 발견한 취재 후보. 원문 사실관계는 별도 확인이 필요합니다.",
                              "discovery_only":True})
        except Exception as exc:
            errors[name]=str(exc)[:240]
    items.sort(key=lambda x:x["published_at"],reverse=True)
    return {"date":DAY,"status":"discovery-only" if successes else "collection-failed",
            "updated_at":NOW.isoformat(),"items":items[:60],
            "source_count":len(SOURCES),"sources_succeeded":successes,"source_errors":errors}

def main():
    result=collect()
    out=Path("global")/(DAY+".json")
    out.parent.mkdir(parents=True,exist_ok=True)
    temp=out.with_suffix(".tmp")
    temp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    os.replace(temp,out)
    print(f"global_candidates={len(result['items'])} feeds_ok={result['sources_succeeded']}/{len(SOURCES)} output={out}")
    if result["sources_succeeded"]==0:raise SystemExit("All global feeds failed")

if __name__=="__main__":main()
