"""Resolve Google News RSS URLs; never treat an intermediary as a verified original."""
import json
import re
import urllib.parse
import urllib.request
from html import unescape

UA = "Mozilla/5.0 (compatible; BriefingDesk/2.0)"
RPC = "https://news.google.com/_/DotsSplashUi/data/batchexecute"

def request(url, data=None, timeout=12):
    headers = {"User-Agent": UA, "Cookie": "CONSENT=PENDING+987", "Accept-Language": "ko-KR,ko;q=0.9"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8"
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=timeout) as response:
        return response.read(1_500_000).decode("utf-8", "replace")

def safe_publisher_url(url, domain):
    try:
        p = urllib.parse.urlsplit(url.strip())
        host = (p.hostname or "").lower()
        if p.scheme not in ("http", "https") or p.username or p.password or not host:
            return None
        if host != domain and not host.endswith("." + domain):
            return None
        if p.port not in (None, 80, 443):
            return None
        query = [(k,v) for k,v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
        return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), p.path, urllib.parse.urlencode(query), ""))
    except (ValueError, AttributeError):
        return None

def resolve(google_url, domain, transport=request):
    direct = safe_publisher_url(google_url, domain)
    if direct:
        return direct
    parsed = urllib.parse.urlsplit(google_url)
    if parsed.hostname != "news.google.com" or not re.fullmatch(r"/(?:rss/)?articles/[A-Za-z0-9_-]+", parsed.path):
        return None
    article_id = parsed.path.rsplit("/", 1)[-1]
    try:
        html = transport("https://news.google.com/rss/articles/" + article_id)
        sg = re.search(r'data-n-a-sg="([^"]+)"', html)
        ts = re.search(r'data-n-a-ts="([0-9]+)"', html)
        if not sg or not ts:
            return None
        inner = ["garturlreq", [["X","X",["X","X"],None,None,1,1,"US:en",None,1,None,None,None,None,None,0,1],"X","X",1,[1,1,1],1,1,None,0,0,None,0],article_id,int(ts.group(1)),unescape(sg.group(1))]
        payload = urllib.parse.urlencode({"f.req": json.dumps([[["Fbv4je",json.dumps(inner,separators=(",",":")),None,"generic"]]],separators=(",",":"))}).encode()
        response = transport(RPC, data=payload)
        # Google's RPC response starts with an anti-XSSI prefix.
        match = re.search(r'\[\["wrb\.fr","Fbv4je","((?:\\.|[^"\\])*)"', response)
        if match:
            embedded = json.loads('"' + match.group(1) + '"')
            url = json.loads(embedded)[1]
            return safe_publisher_url(url, domain)
        for line in response.splitlines():
            try:
                batch = json.loads(line)
                for row in batch:
                    if isinstance(row,list) and len(row)>2 and row[1]=="Fbv4je":
                        return safe_publisher_url(json.loads(row[2])[1], domain)
            except (ValueError, TypeError, IndexError, KeyError):
                continue
    except (ValueError, TypeError, IndexError, OSError):
        return None
    return None
