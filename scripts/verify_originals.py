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

def resolve_google_news(url,opener=None):
    """Resolve Google News RSS token via its public article metadata endpoint."""
    import re
    parsed=urllib.parse.urlparse(url)
    if parsed.hostname not in ("news.google.com","news.google.co.kr"):
        return url
    token=parsed.path.rstrip("/").split("/")[-1]
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]+",token):
        return None
    open_fn=opener or urllib.request.urlopen
    # Google News RSS article IDs often embed the publisher URL in a
    # length-prefixed protobuf payload. Decode that before network requests.
    try:
        import base64
        raw=base64.urlsafe_b64decode(token+"="*(-len(token)%4))
        for match in re.finditer(rb"https?://[^\\x00-\\x20\\x7f]+",raw):
            candidate=match.group(0).decode("utf-8","ignore").rstrip('\\x00')
            host=urllib.parse.urlparse(candidate).hostname or ""
            if host and "google." not in host:
                return candidate
    except Exception:
        pass
    try:
        req=urllib.request.Request("https://news.google.com/rss/articles/"+token,headers={"User-Agent":"Mozilla/5.0"})
        with open_fn(req,timeout=12) as resp:
            page=resp.read(1200000).decode("utf-8","replace")
            final=resp.geturl()
        if urllib.parse.urlparse(final).hostname not in ("news.google.com","news.google.co.kr"):
            return final
        match=re.search(r'data-n-a-id="([^"]+)"[^>]*data-n-a-ts="([^"]+)"[^>]*data-n-a-sg="([^"]+)"',page)
        if not match:
            return None
        aid,ts,sig=match.groups()
        import urllib.parse as up
        payload=f'[[["Fbv4je","[\\\"garturlreq\\\",[[\\\"en-US\\\",\\\"US\\\",[\\\"FINANCE_TOP_INDICES\\\",\\\"WEB_TEST_1_0_0\\\"]],null,null,1,1,\\\"US:en\\\",null,180,null,null,null,null,null,0,null,null,[1608992183,723341000]],\\\"{aid}\\\",{ts},\\\"{sig}\\\"]",null,"generic"]]]'
        data=up.urlencode({"f.req":payload}).encode()
        req=urllib.request.Request("https://news.google.com/_/DotsSplashUi/data/batchexecute?rpcids=Fbv4je",data=data,headers={"User-Agent":"Mozilla/5.0","Content-Type":"application/x-www-form-urlencoded"})
        with open_fn(req,timeout=12) as resp:answer=resp.read(200000).decode("utf-8","replace")
        urls=re.findall(r'https?://[^\\\\\\\"\\s]+',answer)
        for candidate in urls:
            candidate=candidate.replace("\\\\/","/").replace("\\u003d","=")
            host=up.urlparse(candidate).hostname or ""
            if host and "google." not in host:return candidate
    except Exception:
        return None
    return None

def verify(item,opener=None):
    url=item.get("url","");p=urllib.parse.urlparse(url)
    result={"url":url,"verified_original":False,"status":"UNVERIFIED"}
    if p.scheme not in ("http","https") or not p.hostname:return {**result,"reason":"INVALID_URL"}
    if p.hostname.endswith(("google.com","google.co.kr","bing.com")):
        resolved=resolve_google_news(url,opener)
        if not resolved:return {**result,"reason":"AGGREGATOR_UNRESOLVED"}
        url=resolved
        result["resolved_from_aggregator"]=True
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        with (opener or urllib.request.urlopen)(req,timeout=12) as resp:
            final=resp.geturl()
            if "html" not in resp.headers.get("Content-Type","").lower():return {**result,"reason":"NOT_HTML"}
            body=resp.read(350000).decode("utf-8","replace")
        final_host=urllib.parse.urlparse(final).hostname or ""
        if final_host.endswith(("google.com","bing.com")) or final_host.startswith("www.bing."):
            return {**result,"reason":"AGGREGATOR_REDIRECT"}
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
    from collections import Counter
    data["original_verification_summary"]=counts
    data["original_verified_hosts"] = {}
    return data
if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--input",required=True);ap.add_argument("--output",required=True);ap.add_argument("--limit",type=int,default=100);args=ap.parse_args()
    d=process(json.loads(Path(args.input).read_text(encoding="utf-8")),args.limit)
    Path(args.output).write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    from collections import Counter
    print("ORIGINAL_VERIFICATION",d["original_verification_summary"])
    print("REJECTION_REASONS",dict(Counter(x.get("original_verification",{}).get("reason","OK") for x in d["candidates"][:args.limit])))
    print("SAMPLE_INPUT_HOSTS",dict(Counter(urllib.parse.urlparse(x.get("url","")).hostname for x in d["candidates"][:args.limit])))
