"""No-network regression tests for production strict-ready domestic 14+6 metric."""
import copy
import unittest
from pathlib import Path

from validate_briefing import validate_v1
from domestic_coverage_gate import score_operational_coverage

def settings():
    import json
    return json.loads(Path("config/briefing-settings.json").read_text(encoding="utf-8"))

def ready_case():
    conf=settings()
    names=conf["domestic"]["collectors"]
    audit={}
    groups={}
    for group in ("A","B","C","D"):
        audit[group]={}
        rows=[]
        for src in names[group]:
            state={"status":"PARTIAL","routes":[{
                "method":"DIRECT_LIST","status":"PARTIAL","hits":10}]}
            audit[group][src]=state
            rows.append({"source":src,**state})
        groups[group]={"checked_at":"2026-10-12T11:30:00+09:00",
                       "status":"PARTIAL","routes":rows}
    axes=conf["domestic"]["web_unified_search"]["selected_terms_by_axis"]
    groups["WEB"]={"checked_at":"2026-10-12T11:30:00+09:00",
                   "status":"PARTIAL","routes":[{"axis":x,"status":"PARTIAL","hits":0}
                                               for x in axes]}
    evidence={"source_health":audit,"domestic_groups":groups,
              "web_gap_scan":{"checked_at":"2026-10-12T11:30:00+09:00",
                              "reuses_unified_web_scan":True},
              "global":{"status":"PASS","checked_at":"2026-10-12T06:00:00+09:00",
                        "routes":[{"status":"PASS"}]},
              "patent":{"status":"PASS","checked_at":"2026-10-12T06:00:00+09:00",
                        "routes":[{"status":"PASS"}]},
              "p0_followups":[]}
    d={"schema_version":"briefing-final-v1.0","date":"2026-10-12",
       "timezone":"Asia/Seoul","status":"ready",
       "search_window":{"from":"2026-10-11T12:00:00+09:00"},
       "collector_status":{k:"PARTIAL" for k in ("A","B","C","D","WEB")},
       "completeness_status":"ready",
       "collection_evidence":evidence,
       "domestic":[],"global":[],"patent":[],
       "section_health":{k:"PASS" for k in ("domestic","global","patent","schedule")}}
    return d

class ReadyValidationTests(unittest.TestCase):
    def test_twenty_route_tasks_can_pass_even_when_web_index_publishers_not_pass(self):
        d=ready_case()
        self.assertIs(validate_v1(d,Path("2026-10-12.json")),d)

    def test_below_ninety_percent_blocks_ready(self):
        d=ready_case()
        for group,source in (("A",list(d["collection_evidence"]["source_health"]["A"])[0]),
                             ("B",list(d["collection_evidence"]["source_health"]["B"])[0]),
                             ("C",list(d["collection_evidence"]["source_health"]["C"])[0])):
            d["collection_evidence"]["source_health"][group][source]["routes"][0]["status"]="FAIL"
        with self.assertRaisesRegex(ValueError,"below 90pct"):
            validate_v1(d,Path("2026-10-12.json"))

    def test_p1_unverified_core_fact_still_blocks_ready(self):
        d=ready_case()
        d["domestic"]=[{
            "tag":"기업지배구조","title":"제약사 경영권 판결 발표","summary":"회사 지배구조",
            "source":"https://example.org/news/1","source_name":"매체",
            "published_at":"2026-10-12T08:10:00+09:00","timestamp_unverified":False,
            "priority":"P1","core_fact_check_required":True,
            "article_preview":{
                "quick":{"title":"제약사 판결","lead":"관련 판결 발표"},
                "diff":{"title":"후속 취재","direction":"판결문 검토"}}
        }]
        with self.assertRaisesRegex(ValueError,"core fact not verified"):
            validate_v1(d,Path("2026-10-12.json"))

    def test_global_patent_validation_not_bypassed(self):
        d=ready_case()
        d["collection_evidence"]["patent"]["status"]="PARTIAL"
        with self.assertRaisesRegex(ValueError,"missing actual collection evidence"):
            validate_v1(d,Path("2026-10-12.json"))

if __name__=="__main__":
    unittest.main()
