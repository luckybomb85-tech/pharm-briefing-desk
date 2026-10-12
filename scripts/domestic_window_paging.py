"""Publisher listing timeline and bounded native-page discovery.

Dates next to article anchors are listing evidence, NOT proof of original
publication. Supports 2026-10-12 09:15, 10.12 09:15, 10-12 09:15.
Does not trust dates in page headers, JSON-LD scripts, or unrelated sidebar.
"""
import html
import re
import urllib.parse
from datetime import datetime, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ARTICLE_PATH = re.compile(
    r"(articleview|article_view|newsid=|idxno=|/news/read|/news/view|/news/\d|"
    r"/user/news/\d|/\d{4}/\d{2}/\d{2}/|/article/|/news/\w+-\d+)", re.I
)
DATE_RE = re.compile(
    r"(?<!\d)(?:(20\d{2})[./-])?(\d{1,2})[./-](\d{1,2})"
    r"\s+([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?(?!\d)"
)

def _article_url(url):
    p = urllib.parse.urlsplit(url)
    return p.scheme == "https" and bool(ARTICLE_PATH.search(p.path + "?" + p.query))

def _safe_page2(base, other, anchor_title, rel):
    """Require a literal page=2 or an explicit next link, same hostname/path."""
    a, b = urllib.parse.urlsplit(base), urllib.parse.urlsplit(other)
    if (b.scheme != "https" or not a.hostname or not b.hostname
            or a.hostname.lower() != b.hostname.lower()
            or a.path != b.path):
        return False
    page = urllib.parse.parse_qs(b.query).get("page")
    is_two = page == ["2"] and anchor_title.strip() in ("2", "다음", "Next", "next", "›", "»")
    return is_two or ("next" in rel.split() and page == ["2"])

class ListingTimeline(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url=url
        self._parts=[]
        self._offset=0
        self._active=None
        self.articles=[]
        self.page2_url=None
        self._skip=0
        self._block_tags={"script", "style", "noscript", "svg"}
    def _add(self, value):
        if self._skip:
            return
        self._parts.append(value)
        self._offset+=len(value)
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag in self._block_tags:
            self._skip+=1
            return
        if self._skip:
            return
        if tag == "a":
            self._active={"href":a.get("href",""),"title":a.get("title",""),
                          "rel":a.get("rel",""),"start":self._offset,"text":[]}
        elif tag == "time" and a.get("datetime"):
            self._add(" " + a["datetime"] + " ")
    def handle_data(self, value):
        if self._skip:
            return
        if self._active is not None:
            self._active["text"].append(value)
        self._add(value + " ")
    def handle_endtag(self, tag):
        if tag in self._block_tags:
            self._skip=max(0,self._skip-1)
            return
        if self._skip:
            return
        if tag=="a" and self._active is not None:
            a=self._active
            self._active=None
            url=urllib.parse.urljoin(self.url, a["href"])
            title=html.unescape(" ".join(" ".join(a["text"]).split()) or a["title"])
            if _article_url(url) and len(title)>=7:
                self.articles.append({"url":url,"title":title,
                                      "_at":a["start"],"_end":self._offset})
            if self.articles and not self.page2_url and _safe_page2(
                    self.url,url,title,a["rel"]):
                self.page2_url=url
    @property
    def text(self):
        return "".join(self._parts)

def _date_near(text, day):
    m=DATE_RE.search(text)
    if not m:
        return None
    year, month, day_of_month, hour, minute, sec=m.groups()
    target=datetime.strptime(day,"%Y-%m-%d").date()
    years=[int(year)] if year else [target.year, target.year-1, target.year+1]
    possibilities=[]
    for yy in years:
        try:
            dt=datetime(yy,int(month),int(day_of_month),int(hour),
                        int(minute),int(sec or 0),tzinfo=KST)
            if abs((dt.date()-target).days)<=32:
                possibilities.append(dt)
        except ValueError:
            pass
    return min(possibilities,key=lambda d:abs((d.date()-target).days)) if possibilities else None

def parse_publisher_page(data, url, day, max_links=100):
    doc=ListingTimeline(url)
    doc.feed(data.decode("utf-8","replace"))
    full_text=doc.text
    all_links=doc.articles
    seen=set()
    links=[]
    for i, entry in enumerate(all_links):
        if entry["url"] in seen:
            continue
        seen.add(entry["url"])
        after=entry["_end"]
        until=(all_links[i+1]["_at"] if i+1<len(all_links) else len(full_text))
        # The listing metadata is located near the article, usually AFTER its
        # headline, not in a <time datetime>. Do not borrow the next article date.
        snippet=full_text[after:min(until,after+2200)]
        listed=_date_near(snippet,day)
        item={"url":entry["url"],"title":entry["title"],"listing_date_evidence":bool(listed),
              "listing_published_at":listed.isoformat(timespec="seconds") if listed else "",
              "source_page":url}
        links.append(item)
        if len(links)>=max_links:
            break
    dated=[datetime.fromisoformat(x["listing_published_at"]) for x in links
           if x["listing_published_at"]]
    return {"links":links,"dates":dated,"page2_url":doc.page2_url,
            "dated_article_count":len(dated),
            "listing_article_count":len(links)}
