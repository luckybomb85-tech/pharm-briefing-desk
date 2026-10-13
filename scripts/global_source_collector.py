"""Bounded global news discovery; no index hit is treated as original verification."""
from datetime import datetime,timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo
KST=ZoneInfo("Asia/Seoul")
FEEDS={"FDA Press Releases":"https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml","FDA Drugs":"https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/drugs/rss.xml","EMA News":"https://www.ema.europa.eu/en/news.xml","EMA New Human Medicines":"https://www.ema.europa.eu/en/new-human-medicine-new.xml"}
PUBLISHERS={"Reuters":"reuters.com","STAT":"statnews.com","Endpoints News":"endpts.com","BioPharma Dive":"biopharmadive.com","Fierce Pharma":"fiercepharma.com","Fierce Biotech":"fiercebiotech.com","BioSpace":"biospace.com","FirstWord Pharma":"firstwordpharma.com","Scrip/Pink Sheet":"citeline.com","Evaluate":"evaluate.com","Pharmaceutical Technology":"pharmaceutical-technology.com","Labiotech":"labiotech.eu","GEN":"genengnews.com"}
def rss(url):
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 (BriefingAudit/1.0)"})
    with urlopen(req,timeout=12) as res: root=ET.fromstring(res.read(2000000))
    items=[]
    for x in root.findall(".//item"):
        items.append({"title":(x.findtext("title") or "").strip(),"url":(x.findtext("link") or "").strip(),"published_at":(x.findtext("pubDate") or "").strip()})
    if not items:
        ns={"a":"http://www.w3.org/2005/Atom"}
        for x in root.findall(".//a:entry",ns):
            link=x.find("a:link",ns)
            items.append({"title":x.findtext("a:title","",ns).strip(),"url":link.get("href","") if link is not None else "","published_at":x.findtext("a:updated","",ns)})
    return items
def news(query):
    return rss("https://news.google.com/rss/search?"+urlencode({"q":query,"hl":"en-US","gl":"US","ceid":"US:en"}))
def in_window(value,start,end):
    try: dt=parsedate_to_datetime(value)
    except (ValueError,TypeError,IndexError):
        try: dt=datetime.fromisoformat(value.replace("Z","+00:00"))
        except (ValueError,TypeError,AttributeError): return False
    return dt.tzinfo is not None and start<=dt.astimezone(KST)<=end
def scan_global_sources(day,settings,now,news_fetch=None,feed_fetch=None):
    news_fetch=news_fetch or news;feed_fetch=feed_fetch or rss
    start=datetime.fromisoformat(day+"T00:00:00+09:00")-timedelta(hours=12)
    end=min(datetime.fromisoformat(day+"T23:59:59+09:00"),datetime.now(KST))
    routes=[];candidates=[];seen=set()
    def collect(source,group,method,target,fn):
        state={"source":source,"group":group,"method":method,"target":target,"checked_at":now(),"status":"FAIL","hits":0,"in_window_index_hits":0,"original_verified":False,"coverage_proven":False}
        try:
            hits=fn(target);state["hits"]=len(hits);state["status"]="PARTIAL"
            for hit in hits:
                if not in_window(hit.get("published_at"),start,end):continue
                state["in_window_index_hits"]+=1
                url=hit.get("url","")
                if not url or url in seen:continue
                seen.add(url);candidates.append({**hit,"source":source,"group":"GLOBAL","verified_original":False,"timestamp_origin":"feed_or_index"})
        except Exception as exc:state["error"]=str(exc)[:240]
        routes.append(state)
    for name,url in FEEDS.items():
        if name.startswith("FDA "):
            collect(name,"PRIMARY_REGULATORY","GOOGLE_NEWS_SITE_DISCOVERY_FALLBACK",f"site:fda.gov {'press announcement' if name == 'FDA Press Releases' else 'drug approval'} after:{start.date()} before:{end.date()+timedelta(days=1)}",news_fetch)
        else:
            collect(name,"PRIMARY_REGULATORY","OFFICIAL_RSS",url,feed_fetch)
    for name,domain in PUBLISHERS.items():collect(name,"TRADE_AND_WIRE","GOOGLE_NEWS_SITE_DISCOVERY",f"site:{domain} after:{start.date()} before:{end.date()+timedelta(days=1)}",news_fetch)
    pooled={"Global gap recovery":"pharmaceutical biotech clinical results drug approval acquisition"}
    for name,query in pooled.items():collect(name,"WHOLE_WEB_RECOVERY","SHARED_GOOGLE_NEWS_DISCOVERY",f"{query} after:{start.date()} before:{end.date()+timedelta(days=1)}",news_fetch)
    groups={}
    for group in ("PRIMARY_REGULATORY","TRADE_AND_WIRE","WHOLE_WEB_RECOVERY"):
        subset=[r for r in routes if r["group"]==group];groups[group]="PARTIAL" if any(r["status"]=="PARTIAL" for r in subset) else "FAIL"
    return {"checked_at":now(),"status":"PARTIAL" if "PARTIAL" in groups.values() else "FAIL","source_groups":groups,"routes":routes,"candidates":candidates,"request_budget":{"official_feeds":2,"fda_fallback_queries":2,"publisher_queries":13,"pooled_queries":1,"total_max":18},"note":"Index discovery only; source coverage and original publication times are not verified."}
