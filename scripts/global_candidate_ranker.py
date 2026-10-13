"""Conservative ranking of global discovery candidates; never claims original verification."""
import re
from urllib.parse import urlsplit,parse_qs
from difflib import SequenceMatcher
SIGNALS=[
 (r"phase (?:2|3|ii|iii)|pivotal|topline|primary endpoint|trial (?:met|failed)|clinical trial",4,"CLINICAL"),
 (r"fda (?:approv|reject)|ema (?:approv|recommend)|chmp|complete response letter|drug approv",4,"REGULATORY"),
 (r"licens|acqui|merger|buyout|deal worth|billion|partnership",3,"DEAL"),
 (r"patent|biosimilar|generic|exclusivity|lawsuit|litigation",3,"IP"),
 (r"safety|recall|adverse event|warning",3,"SAFETY")]
LOW=r"webinar|conference attendance|investor presentation|sponsored|job opening|stock price|shares rise|analyst rating"
def normalize(title):
    title=re.sub(r"\s+[-|]\s+[^-|]{2,60}$","",title or "")
    return re.sub(r"[^a-z0-9가-힣]+"," ",title.lower()).strip()
def select(candidates,limit=30):
    selected=[];seen_urls=set();seen_titles=[]
    for item in candidates:
        title=item.get("title","");url=item.get("url","");key=normalize(title)
        if not url.startswith(("https://","http://")) or len(key)<18:continue
        # Google News redirects are index links, not original URLs.
        url_key=urlsplit(url)._replace(query="",fragment="").geturl()
        if url_key in seen_urls or any(SequenceMatcher(None,key,prev).ratio()>=0.88 for prev in seen_titles):continue
        seen_urls.add(url_key);seen_titles.append(key)
        tags=[tag for pattern,score,tag in SIGNALS if re.search(pattern,key)]
        score=sum(score for pattern,score,tag in SIGNALS if re.search(pattern,key))
        if re.search(LOW,key):score-=5
        if not tags or score<=0:continue
        selected.append({**item,"score":score,"signals":tags,"verified_original":False,"editorial_status":"CANDIDATE_ONLY","original_url_verified":False})
    selected.sort(key=lambda x:(-x["score"],x.get("title","")))
    return {"total_input":len(candidates),"ranked_count":len(selected),"shortlist":selected[:limit],"note":"Keyword ranking only; manual or separate original-source verification required."}
