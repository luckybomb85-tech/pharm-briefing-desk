"""Operational 90% gate tests; never reinterpret Google RSS as per-outlet PASS."""
import unittest
from domestic_coverage_gate import score_operational_coverage

AXES=("rnd","bd","governance","court","market_risk","policy")
FIXED={"A":["a1","a2","a3","a4"],"B":["b1","b2","b3","b4"],
       "C":["c1","c2","c3","c4"],"D":["d1","d2"]}
def cfg():
    return {"domestic":{
        "collectors":{**FIXED,"WEB":["8 named publishers","기타 전체 웹"]},
        "web_unified_search":{"selected_terms_by_axis":{a:[a] for a in AXES}}
    },"readiness_gate":{"domestic":{"operational_coverage":{"goal":0.90}}}}

def evidence():
    health={}
    for group,names in FIXED.items():
        health[group]={name:{"status":"PARTIAL","routes":[{
            "method":"DIRECT_LIST","status":"PARTIAL","hits":10
        }]} for name in names}
    return {"source_health":health,"domestic_groups":{
        "WEB":{"routes":[{"axis":a,"status":"PARTIAL","hits":0}
                         for a in AXES]}
    }}

class MixedCoverageTests(unittest.TestCase):
    def test_all_routes_work_but_article_recall_remains_unmeasured(self):
        result=score_operational_coverage(cfg(),evidence())
        self.assertEqual(result["configured_search_tasks"],20)
        self.assertEqual(result["verified_usable_search_tasks"],20)
        self.assertTrue(result["target_met"])
        self.assertEqual(result["article_recall_status"],"UNMEASURED")
        self.assertFalse(result["article_recall_claimed"])
        self.assertTrue(result["publisher_completeness_not_inferred"])

    def test_eighteen_of_twenty_meets_90pct_target(self):
        e=evidence()
        e["source_health"]["A"]["a1"]["routes"][0]["status"]="FAIL"
        e["domestic_groups"]["WEB"]["routes"][0]["status"]="FAIL"
        r=score_operational_coverage(cfg(),e)
        self.assertEqual(r["verified_usable_search_tasks"],18)
        self.assertTrue(r["target_met"])

    def test_seventeen_of_twenty_fails(self):
        e=evidence()
        for name in ("a1","a2","a3"):
            e["source_health"]["A"][name]["routes"][0]["status"]="FAIL"
        r=score_operational_coverage(cfg(),e)
        self.assertEqual(r["verified_usable_search_tasks"],17)
        self.assertFalse(r["target_met"])

    def test_web_rss_zero_is_operational_but_not_article_zero(self):
        r=score_operational_coverage(cfg(),evidence())
        for x in r["units"]:
            if x["kind"]=="WEB_SHARED_TOPIC_QUERY":
                self.assertEqual(x["publisher_completeness"],"NOT_APPLICABLE_INDEX")
                self.assertFalse(x["original_article_time_proven"])
        self.assertEqual(sum(x["kind"]=="WEB_SHARED_TOPIC_QUERY" for x in r["units"]),6)

    def test_malformed_or_missing_native_source_does_not_pass(self):
        e=evidence()
        del e["source_health"]["B"]["b1"]
        e["source_health"]["A"]["a2"]["routes"][0]["hits"]=0
        r=score_operational_coverage(cfg(),e)
        self.assertEqual(r["verified_usable_search_tasks"],18)
        self.assertIn("B/b1",r["unusable_tasks"])
        self.assertIn("A/a2",r["unusable_tasks"])

    def test_completeness_pass_zero_keeps_zero_with_proof(self):
        e=evidence()
        e["source_health"]["B"]["b1"]={"status":"PASS_ZERO","routes":[{
            "method":"DIRECT_LIST","status":"PASS_ZERO","hits":0}]}
        r=score_operational_coverage(cfg(),e)
        self.assertTrue(r["target_met"])
        self.assertEqual(r["verified_usable_search_tasks"],20)

if __name__=="__main__":
    unittest.main()
