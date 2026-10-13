"""Verify at most ten ranked global articles without rerunning source discovery."""
from urllib.parse import urlsplit
try:
    from .verify_originals import verify
    from .global_source_collector import PUBLISHERS
except ImportError:
    from verify_originals import verify
    from global_source_collector import PUBLISHERS
ALLOWED=set(PUBLISHERS.values())|{"fda.gov","ema.europa.eu"}
def allowed(url):
    p=urlsplit(url)
    host=(p.hostname or "").lower()
    return p.scheme=="https" and any(host==d or host.endswith("."+d) for d in ALLOWED)
def verify_shortlist(shortlist,limit=10,verifier=None):
    verifier=verifier or verify
    rows=[dict(x) for x in shortlist.get("shortlist",[])];results=[];attempts=0
    for row in rows:
        if attempts>=limit:
            row["original_verification"]={"status":"NOT_CHECKED","verified_original":False,"reason":"BUDGET"}
            continue
        attempts+=1
        try:
            r=verifier(row)
            if r.get("status")=="VERIFIED" and r.get("verified_original") and r.get("published_at_verified") and allowed(r.get("resolved_url","")):
                row["original_verification"]=r
                row["verified_original"]=True
                row["editorial_status"]="ORIGINAL_METADATA_VERIFIED"
            else:
                row["original_verification"]={**r,"status":"UNVERIFIED","verified_original":False,"reason":r.get("reason","UNTRUSTED_SOURCE_OR_MISSING_EVIDENCE")}
                row["verified_original"]=False
        except Exception as exc:
            row["original_verification"]={"status":"UNVERIFIED","verified_original":False,"reason":"VERIFIER_ERROR","error":str(exc)[:120]}
        results.append(row["original_verification"]["status"])
    return {**shortlist,"shortlist":rows,"verification":{"attempted":attempts,"verified":results.count("VERIFIED"),"unverified":results.count("UNVERIFIED"),"not_checked":len(rows)-attempts,"max_articles":limit,"publish_allowed":False,"note":"Metadata checks only, not independent fact-checking. Never auto-publish."}}
