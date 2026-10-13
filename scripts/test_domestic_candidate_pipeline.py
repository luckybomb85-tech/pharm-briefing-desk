"""Offline stage-4 tests. No live search, network or Pages publication."""
import unittest
from domestic_candidate_pipeline import build_domestic_stage4, canon_url

DAY="2026-10-12"
IN_WINDOW="2026-10-12T07:12:00+09:00"
EARLY="2026-10-11T09:12:00+09:00"

def config(budget=12):
    return {"domestic":{"event_validation":{
        "scope":"domestic_only", "publish_allowed":False,
        "max_new_original_verifications":budget
    }}}

def original(title,url,group="A",priority="P2",**more):
    return {"title":title,"url":url,"group":group,"priority":priority,
            "verified_original":True,"published_at":IN_WINDOW,
            "timestamp_unverified":False,**more}

def unverified(title,url,group="WEB",priority="P2",**more):
    return {"title":title,"url":url,"group":group,"priority":priority,
            "verified_original":False,"published_at":"",
            "timestamp_unverified":True,**more}

def success(item):
    return {"verified_original":True,"resolved_url":item["url"],
            "original_title":item["title"],"published_at_verified":IN_WINDOW}

class Stage4Tests(unittest.TestCase):
    def test_reuse_verified_fixed_and_do_not_fetch_duplicate_web_title(self):
        calls=[]
        def verify(c):
            calls.append(c)
            return success(c)
        rows=[
            original("한미약품 3상 결과 발표", "https://a.example.kr/news/articleView.html?idxno=22",priority="P0"),
            unverified("한미약품 3상 결과 발표", "https://news.google.com/rss/articles/AA",priority="P0")
        ]
        result=build_domestic_stage4(DAY,rows,config(),verifier=verify)
        self.assertEqual(len(result["domestic"]),1)
        self.assertEqual(result["statistics"]["new_original_verifier_calls"],0)
        self.assertEqual(result["statistics"]["reused_preverified_originals"],1)
        self.assertEqual(len(calls),0)
        self.assertEqual(result["statistics"]["duplicates_suppressed"],1)
        self.assertEqual(set(result["domestic"][0]["discovery_groups"]),{"A","WEB"})
        self.assertTrue(result["domestic"][0]["core_fact_check_required"])

    def test_tracking_query_urls_are_same_article(self):
        rows=[original("급여 협상 이슈", "https://example.com/news/11?utm_source=foo&x=1"),
              unverified("급여 협상 후속", "https://example.com/news/11?x=1&utm_medium=social")]
        result=build_domestic_stage4(DAY,rows,config(),verifier=lambda c:
                                      self.fail("should not open"))
        self.assertEqual(len(result["domestic"]),1)
        self.assertEqual(result["statistics"]["new_original_verifier_calls"],0)
        self.assertEqual(result["statistics"]["duplicates_suppressed"],1)

    def test_distinct_milestones_same_company_are_not_merged(self):
        rows=[
            original("한미 에페글레나타이드 허가", "https://example.com/approval",event_id="HANMI-EPHE",priority="P1"),
            original("한미 에페글레나타이드 급여", "https://example.com/benefit",event_id="HANMI-EPHE",priority="P1"),
            original("한미 에페글레나타이드 임상 결과", "https://example.com/clinical",event_id="HANMI-EPHE",priority="P1")
        ]
        result=build_domestic_stage4(DAY,rows,config(),verifier=lambda c:
                                      self.fail("already confirmed"))
        self.assertEqual(len(result["domestic"]),3)
        self.assertEqual({x["milestone"] for x in result["domestic"]},
                         {"approval","reimbursement","clinical"})
        self.assertEqual(result["statistics"]["new_original_verifier_calls"],0)

    def test_same_event_same_milestone_deduplicated_by_id(self):
        rows=[
            original("케이캡 미국 3상 결과 발표", "https://a.example.kr/x",event_id="KCAP-PHASE3"),
            unverified("HK이노엔 테고프라잔 미국 임상 3상 상세", "https://news.google.com/rss/articles/BB",
                       event_id="KCAP-PHASE3")
        ]
        result=build_domestic_stage4(DAY,rows,config(),verifier=lambda c:
                                      self.fail("must reuse confirmed"))
        self.assertEqual(len(result["domestic"]),1)
        self.assertEqual(result["statistics"]["duplicates_suppressed"],1)

    def test_priority_order_and_budget(self):
        titles=[
            unverified("바이오 신규 소식 일반", "https://news.google.com/rss/articles/P3",priority="P3"),
            unverified("단독 신약 급여", "https://news.google.com/rss/articles/P1",priority="P1"),
            unverified("임상 3상 실패", "https://news.google.com/rss/articles/P0",priority="P0"),
        ]
        calls=[]
        def verify(c):
            calls.append(c["title"])
            return {"verified_original":True, "resolved_url":
                    "https://publisher.example.kr/"+str(len(calls)),
                    "published_at_verified":IN_WINDOW}
        result=build_domestic_stage4(DAY,titles,config(2),verifier=verify)
        self.assertEqual(calls,["임상 3상 실패","단독 신약 급여"])
        self.assertEqual(result["statistics"]["new_original_verifier_calls"],2)
        self.assertEqual(result["statistics"]["deferred_for_budget"],1)
        p3=[x for x in result["domestic"] if x["priority"]=="P3"][0]
        self.assertEqual(p3["original_verification_method"],"DEFERRED_NOT_VERIFIED")
        self.assertTrue(p3["timestamp_unverified"])
        self.assertEqual(p3["published_at"],"")

    def test_p2_one_original_check_and_no_secondary(self):
        calls=[]
        def verify(c):
            calls.append(c)
            return {"verified_original":True,
                    "resolved_url":"https://publisher.example.kr/123",
                    "published_at_verified":IN_WINDOW}
        result=build_domestic_stage4(DAY,[unverified("바이오 투자 유치",
                                "https://news.google.com/rss/articles/BB")],
                                config(12),verifier=verify)
        self.assertEqual(len(calls),1)
        self.assertTrue(result["domestic"][0]["verified_original"])
        self.assertFalse(result["domestic"][0]["core_fact_check_required"])

    def test_p1_title_and_clock_do_not_verify_critical_fact(self):
        x=original("대법원 제약 소송 판결","https://publisher.example.kr/111",
                   priority="P1")
        result=build_domestic_stage4(DAY,[x],config(),verifier=lambda c:
                                      self.fail("already checked"))
        self.assertTrue(result["domestic"][0]["core_fact_check_required"])
        self.assertEqual(result["domestic"][0]["verification_status"],
                         "EDITORIAL_CORE_FACT_PENDING")

    def test_core_fact_primary_evidence_can_be_reused(self):
        x=original("대법원 제약 소송 판결","https://publisher.example.kr/111",
                   priority="P1",core_fact_verified=True,
                   verification_status="PRIMARY_CONFIRMED",
                   primary_source_url="https://www.scourt.go.kr/case/1")
        result=build_domestic_stage4(DAY,[x],config())
        self.assertFalse(result["domestic"][0]["core_fact_check_required"])

    def test_failed_publisher_resolution_never_becomes_verified(self):
        result=build_domestic_stage4(DAY,[unverified("신약 개발 임상",
                   "https://news.google.com/rss/articles/X")],config(1),
                   verifier=lambda c:{"verified_original":False,
                                      "reason":"AGGREGATOR_UNRESOLVED"})
        item=result["domestic"][0]
        self.assertFalse(item["verified_original"])
        self.assertTrue(item["timestamp_unverified"])
        self.assertEqual(item["published_at"],"")
        self.assertFalse(result["publish_allowed"])

    def test_out_of_window_original_excluded(self):
        result=build_domestic_stage4(DAY,[unverified("제약 생산시설 건설",
                     "https://news.google.com/rss/articles/OLD")],config(1),
                     verifier=lambda c:{"verified_original":True,
                         "resolved_url":"https://publisher.example.kr/old",
                         "published_at_verified":EARLY})
        self.assertEqual(result["domestic"],[])
        self.assertEqual(result["statistics"]["out_of_window_removed"],1)

    def test_discovery_rss_pubdate_never_counts_as_verified(self):
        x=unverified("국내 신약 개발","https://news.google.com/rss/articles/T",
                     index_pub_date="Mon, 12 Oct 2026 01:00:00 GMT")
        result=build_domestic_stage4(DAY,[x],config(0),
                                     verifier=lambda c:self.fail("no budget"))
        self.assertTrue(result["domestic"][0]["timestamp_unverified"])
        self.assertEqual(result["statistics"]["new_original_verifier_calls"],0)

    def test_global_and_patent_candidates_not_processed(self):
        candidates=[
            unverified("글로벌 신약 뉴스", "https://x.com/global",group="GLOBAL"),
            unverified("특허심판원 심결", "https://x.com/patent",group="PATENT"),
            original("국내 제약 신약 뉴스", "https://x.com/domestic",group="B")
        ]
        result=build_domestic_stage4(DAY,candidates,config(1),verifier=lambda c:
                                      self.fail("already verified"))
        self.assertEqual(result["statistics"]["input_domestic_candidates"],1)
        self.assertEqual(len(result["domestic"]),1)

    def test_same_company_different_news_do_not_merge(self):
        rows=[
            original("삼성바이오로직스 수주 계약", "https://a.example.kr/1"),
            original("삼성바이오로직스 공장 증설", "https://b.example.kr/2")
        ]
        result=build_domestic_stage4(DAY,rows,config(),verifier=lambda c:
                                      self.fail("no extra checks"))
        self.assertEqual(len(result["domestic"]),2)

    def test_update_status_preserved(self):
        row=original("한미 에페글레나타이드 약가 후속",
                     "https://a.example.kr/1",event_status="UPDATE")
        result=build_domestic_stage4(DAY,[row],config())
        self.assertEqual(result["domestic"][0]["event_status"],"UPDATE")

    def test_outlet_suffix_only_dedup(self):
        rows=[
            original("한미 에페글레나타이드 허가 - 메디파나뉴스",
                     "https://a.example.kr/1",priority="P1"),
            unverified("한미 에페글레나타이드 허가",
                       "https://news.google.com/rss/articles/77",priority="P1")
        ]
        result=build_domestic_stage4(DAY,rows,config(),verifier=lambda c:
                                     self.fail("no repeated original"))
        self.assertEqual(len(result["domestic"]),1)

    def test_significant_dash_clauses_not_stripped_or_merged(self):
        rows=[
            original("한미 에페글레나타이드 - 허가",
                     "https://a.example.kr/1",priority="P1"),
            original("한미 에페글레나타이드 - 급여",
                     "https://a.example.kr/2",priority="P1")
        ]
        result=build_domestic_stage4(DAY,rows,config(),verifier=lambda c:
                                     self.fail("no repeated original"))
        self.assertEqual(len(result["domestic"]),2)
        self.assertEqual({x["milestone"] for x in result["domestic"]},
                         {"approval","reimbursement"})

    def test_large_discovery_pool_has_bounded_balanced_review_queue(self):
        cfg=config(0)
        cfg["domestic"]["event_validation"]["max_editorial_candidates"]=40
        cfg["domestic"]["event_validation"]["max_editorial_candidates_per_source"]=6
        rows=[]
        for src in range(10):
            for index in range(15):
                item=unverified(
                    "제약 임상 개발 소식 %d %d" % (src,index),
                    "https://example%d.kr/news/%d" % (src,index),
                    priority="P2")
                item["source_name"]="source%d" % src
                rows.append(item)
        result=build_domestic_stage4(DAY,rows,cfg,verifier=lambda _:self.fail("no verification budget"))
        self.assertEqual(result["statistics"]["input_domestic_candidates"],150)
        self.assertEqual(result["statistics"]["events_output"],40)
        self.assertEqual(len(result["domestic"]),40)
        self.assertEqual(result["statistics"]["not_in_review_queue_preserved_in_raw_audit"],110)
        from collections import Counter
        counts=Counter(x["source_name"] for x in result["domestic"])
        self.assertLessEqual(max(counts.values()),6)
        self.assertFalse(result["publish_allowed"])

    def test_invalid_config_fails_closed(self):
        cfg=config()
        cfg["domestic"]["event_validation"]["publish_allowed"]=True
        with self.assertRaises(ValueError):
            build_domestic_stage4(DAY,[],cfg)
        cfg=config(31)
        with self.assertRaises(ValueError):
            build_domestic_stage4(DAY,[],cfg)

    def test_canonical_url_keeps_real_query_while_discarding_trackers(self):
        self.assertEqual(canon_url("https://www.example.kr/news?a=1&utm_source=hi&fbclid=aa"),
                         "https://example.kr/news?a=1")

class EditorialGateTests(unittest.TestCase):
    def test_unrelated_web_and_sports_promo_removed_before_verification(self):
        rows=[
            unverified("단독 부동산 중개사고, 보상까지 600일", "https://news.google.com/rss/articles/OFFTOPIC", priority="P1"),
            original("셀메드 후원 유현조, 시즌 2승 달성", "https://publisher.example.kr/sports", priority="P1"),
            original("동아에스티 신약 임상 3상 성공", "https://publisher.example.kr/trial", priority="P0")
        ]
        result=build_domestic_stage4(DAY,rows,config(0),verifier=lambda _:self.fail("budget zero"))
        self.assertEqual(result["statistics"]["off_topic_web_excluded_before_verification"],1)
        self.assertEqual(result["statistics"]["non_editorial_excluded_before_verification"],1)
        self.assertEqual(len(result["domestic"]),1)
        self.assertIn("동아에스티",result["domestic"][0]["title"])

    def test_high_priority_web_checked_before_lower_priority_publisher(self):
        rows=[
            unverified("제약 사업전략 해설", "https://publisher.example.kr/low",group="A",priority="P2"),
            unverified("임상 3상 실패 제약 바이오", "https://news.google.com/rss/articles/HIGH",priority="P0")
        ]
        calls=[]
        def verify(c):
            calls.append(c["title"])
            return {"verified_original":True,"resolved_url":"https://publisher.example.kr/high",
                    "published_at_verified":IN_WINDOW}
        result=build_domestic_stage4(DAY,rows,config(1),verifier=verify)
        self.assertEqual(calls,["임상 3상 실패 제약 바이오"])
        self.assertEqual(result["statistics"]["new_original_verifier_calls"],1)
        self.assertEqual(result["statistics"]["deferred_for_budget"],1)


if __name__=="__main__":
    unittest.main()
