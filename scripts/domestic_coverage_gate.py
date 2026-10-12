"""Measure configured domestic ROUTE execution (not article recall).

14 native/site source tasks + 6 shared WEB topic queries normally yields 20
tasks. Do NOT treat one Google RSS query as nine independent publisher checks.
"""
from collections import Counter

def score_operational_coverage(settings, evidence):
    domestic=settings.get("domestic",{})
    fixed=domestic.get("collectors",{})
    web=domestic.get("web_unified_search",{})
    axes=web.get("selected_terms_by_axis",{})
    goal=float(settings.get("readiness_gate",{}).get("domestic",{})
               .get("operational_coverage",{}).get("goal",0.9))
    if not 0<goal<=1:
        raise ValueError("INVALID_DOMESTIC_OPERATIONAL_TARGET")
    health=evidence.get("source_health",{})
    groups=evidence.get("domestic_groups",{})
    units=[]
    for group in ("A","B","C","D"):
        for name in fixed.get(group,[]):
            item=health.get(group,{}).get(name,{})
            routes=item.get("routes",[])
            if not routes:
                node=next((x for x in groups.get(group,{}).get("routes",[])
                           if x.get("source")==name),{})
                routes=node.get("routes",[])
            parsable=any(r.get("method") not in ("CONFIG",None)
                         and r.get("status") in ("PASS","PASS_ZERO","PARTIAL")
                         and (r.get("hits",0)>0 or r.get("status")=="PASS_ZERO")
                         for r in routes)
            units.append({"unit":group+"/"+name,"kind":"FIXED_PUBLISHER_ROUTE",
                          "operational_ok":parsable,
                          "publisher_completeness":item.get("status","MISSING"),
                          "original_article_time_proven":item.get("status") in ("PASS","PASS_ZERO")})
    webroutes=groups.get("WEB",{}).get("routes",[])
    for axis in axes:
        matching=next((r for r in webroutes if r.get("axis")==axis),{})
        ok=matching.get("status") in ("PASS","PASS_ZERO","PARTIAL")
        units.append({"unit":"WEB/"+axis,"kind":"WEB_SHARED_TOPIC_QUERY",
                      "operational_ok":ok,
                      "publisher_completeness":"NOT_APPLICABLE_INDEX",
                      "original_article_time_proven":False})
    passed=sum(x["operational_ok"] for x in units)
    total=len(units)
    return {"version":"domestic-operational-coverage-v1.0",
            "verified_usable_search_tasks":passed,
            "configured_search_tasks":total,
            "ratio":round(passed/total,4) if total else 0,
            "goal_ratio":goal,
            "target_met":total>0 and passed/total>=goal,
            "required_success_tasks":__import__("math").ceil(total*goal),
            "units":units,
            "article_recall_status":"UNMEASURED",
            "article_recall_claimed":False,
            "publisher_completeness_not_inferred":True,
            "unusable_tasks":[x["unit"] for x in units if not x["operational_ok"]],
            "note":"90% denotes configured search-task execution; never a measured percentage of all relevant articles recovered."}
