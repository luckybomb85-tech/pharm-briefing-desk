"""Verify original URLs and publication dates. Unverified is never PASS."""
import argparse,html,json,urllib.parse,urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo
class Metadata(HTMLParser):
    def __init__(self):
        super().__init__();self.meta={};self.title="";self.in_title=False;self.in_ld=False;self.ld=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="meta":
            key=(a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and a.get("content"):self.meta.setdefault(key,[]).append(a["content"])
        if tag=="title":self.in_title=True
        if tag=="script" and a.get("type","").lower()=="application/ld+json":self.in_ld=True
    def handle_endtag(self,tag):
        if tag=="title":self.in_title=False
        if tag=="script":self.in_ld=False
    def handle_data(self,data):
        if self.in_title:self.title+=data
        if self.in_ld:self.ld.append(data)
def date_iso(value):
    try:
        dt=datetime.fromisoformat(str(value).strip().replace("Z","+00:00"))
        return dt.astimezone(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds") if dt.tzinfo else None
    except (ValueError,TypeError):return None
def verify(item,opener=None):
    url=item.get("url","");p=urllib.parse.urlparse(url)
    result={"url":url,"verified_original":False,"status":"UNVERIFIED"}
    if p.scheme not in ("http","https") or not p.hostname:return {**result,"reason":"INVALID_URL"}
    if p.hostname.endswith(("google.com","google.co.kr","bing.com")):return {**result,"reason":"AGGREGATOR_URL"}
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        with (opener or urllib.request.urlopen)(req,timeout=12) as resp:
            final=resp.geturl()
            if "html" not in resp.headers.get("Content-Type","").lower():return {**result,"reason":"NOT_HTML"}
            body=resp.read(350000).decode("utf-8","replace")
        if (urllib.parse.urlparse(final).hostname or "").endswith(("google.com","bing.com")):return {**result,"reason":"AGGREGATOR_REDIRECT"}
        m=Metadata();m.feed(body)
        title=html.unescape((m.meta.get("og:title") or [m.title])[0]).strip()
        if not title:return {**result,"reason":"NO_TITLE"}
        dates=[]
        for key in ("article:published_time","datepublished","datecreated","pubdate","publishdate","parsely-pub-date","dc.date.issued"):
            dates.extend((v,key) for v in m.meta.get(key,[]))
        for raw in m.ld:
            try:obj=json.loads(raw)
            except (ValueError,TypeError):continue
            nodes=[obj]
            while nodes:
                n=nodes.pop()
                if isinstance(n,list):nodes.extend(n)
                if isinstance(n,dict):
                    if n.get("datePublished"):dates.append((n["datePublished"],"jsonld.datePublished"))
                    nodes.extend(v for v in n.values() if isinstance(v,(dict,list)))
        for value,source in dates:
            date=date_iso(value)
            if date:return {**result,"verified_original":True,"status":"VERIFIED","resolved_url":final,"original_title":title,"published_at_verified":date,"date_source":source}
        return {**result,"reason":"NO_VERIFIABLE_PUBLICATION_DATE","original_title":title}
    except Exception as exc:return {**result,"reason":"FETCH_FAILED","error":str(exc)[:200]}
def process(data,limit=100):
    cache={};counts={"VERIFIED":0,"UNVERIFIED":0,"NOT_CHECKED":0}
    for i,item in enumerate(data.get("candidates",[])):
        url=item.get("url","")
        if i>=limit:r={"status":"NOT_CHECKED","verified_original":False,"reason":"LIMIT"}
        else:
            if url not in cache:cache[url]=verify(item)
            r=cache[url]
        item["original_verification"]=r;item["verified_original"]=r["verified_original"]
        counts[r["status"]]+=1
    data["original_verification_summary"]=counts
    return data
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--input",required=True);ap.add_argument("--output",required=True);ap.add_argument("--limit",type=int,default=100);args=ap.parse_args()
    d=process(json.loads(Path(args.input).read_text(encoding="utf-8")),args.limit)
    Path(args.output).write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("ORIGINAL_VERIFICATION",d["original_verification_summary"])
