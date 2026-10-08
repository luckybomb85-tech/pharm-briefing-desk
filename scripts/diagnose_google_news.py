"""Inspect a live Google News RSS token and its article page without exposing page contents."""
import base64,re,urllib.request,urllib.parse,xml.etree.ElementTree as ET
rss='https://news.google.com/rss/search?q=pharma+FDA&hl=en-US&gl=US&ceid=US:en'
req=urllib.request.Request(rss,headers={'User-Agent':'Mozilla/5.0'})
with urllib.request.urlopen(req,timeout=20) as r:root=ET.fromstring(r.read())
link=root.findtext('.//item/link')
print('RSS_URL_HOST',urllib.parse.urlparse(link).hostname)
token=urllib.parse.urlparse(link).path.split('/')[-1]
raw=base64.urlsafe_b64decode(token+'='*(-len(token)%4))
print('TOKEN_LENGTH',len(token),'DECODED_BYTES',len(raw),'CONTAINS_HTTP',b'http' in raw)
req=urllib.request.Request('https://news.google.com/rss/articles/'+token,headers={'User-Agent':'Mozilla/5.0'})
with urllib.request.urlopen(req,timeout=20) as r:page=r.read(2500000).decode('utf-8','replace');final=r.geturl()
print('ARTICLE_FINAL_HOST',urllib.parse.urlparse(final).hostname)
for attr in ('data-n-a-id','data-n-a-ts','data-n-a-sg'):
 m=re.search(attr+r'=[\"\']([^\"\']+)',page)
 print('ATTR',attr,'FOUND',bool(m),'VALUE_LENGTH',len(m.group(1)) if m else 0)
print('META_MARKERS',[(x,x in page) for x in ('Fbv4je','garturlreq','data-n-a-id')])

print('PAGE_LENGTH',len(page),'PAGE_START',repr(page[:350]))
print('FINAL_PATH',urllib.parse.urlparse(final).path[:100])

for marker in ('data-n-a-','garturlreq','Fbv4je','https://www.','https://news.google.com'):
 print('MARKER',marker,page.find(marker))

from verify_originals import resolve_google_news
resolved=resolve_google_news(link)
print('RESOLVED_HOST',urllib.parse.urlparse(resolved or '').hostname,'SUCCESS',bool(resolved))
