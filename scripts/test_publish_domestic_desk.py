"""Offline domestic publishing tests: never promote unverified indexed hits."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from publish_domestic_desk import curate, headline, publish

DAY = "2026-10-13"


def confirmed(title="신약 3상 성공", source="https://example.com/news/1",
              published_at="2026-10-13T07:10:00+09:00", **overrides):
    item = {"title":title,"source":source,"source_name":"dailypharm.com",
            "priority":"P1","verified_original":True,
            "timestamp_unverified":False,"published_at":published_at}
    item.update(overrides)
    return item


class DomesticPublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        Path("staging").mkdir()
        Path("domestic").mkdir()

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def fixture(self, rows, day=DAY):
        Path(f"staging/{day}-domestic-stage4.json").write_text(
            json.dumps({"date":day,"domestic":rows}), encoding="utf-8")

    def test_publishes_verified_publisher_with_explicit_discovery_disclaimer(self):
        self.fixture([confirmed()])
        publish(DAY)
        data = json.loads(Path(f"domestic/{DAY}.json").read_text(encoding="utf-8"))
        self.assertEqual(len(data["items"]),1)
        self.assertEqual(data["items"][0]["source_name"],"데일리팜")
        self.assertTrue(data["items"][0]["discovery_only"])
        self.assertIn("CORE_FACT_PENDING",data["items"][0]["verification_status"])

    def test_empty_or_unverified_does_not_overwrite_prior_desk(self):
        target=Path(f"domestic/{DAY}.json")
        target.write_text('{"old":true}', encoding="utf-8")
        self.fixture([confirmed(verified_original=False)])
        with self.assertRaisesRegex(ValueError,"DOMESTIC_NO_VERIFIED_CANDIDATES"):
            publish(DAY)
        self.assertEqual(target.read_text(encoding="utf-8"),'{"old":true}')

    def test_index_links_and_missing_timestamps_never_published(self):
        rows = [
            confirmed(source="https://news.google.com/rss/articles/ABC"),
            confirmed(source="javascript:alert(1)"),
            confirmed(published_at=""),
            confirmed(published_at="2026-10-12T11:59:59+09:00"),
            confirmed(source="https://example.com/news/real",published_at="2026-10-12T12:00:00+09:00"),
        ]
        items,stat=curate(DAY,rows)
        self.assertEqual(len(items),1)
        self.assertEqual(stat["skipped_unverified"],4)

    def test_sports_sponsorship_and_ir_promo_do_not_bury_news(self):
        rows=[
            confirmed("셀메드 후원 유현조, 시즌 2승 달성…영양·컨디션 관리 지원",source="https://example.com/sport"),
            confirmed("HLB그룹, 15일 IR데이…10개 상장사 성장 전략 공유 [데일리팜=최다은 기자] 신약이 기대된다",source="https://example.com/ir"),
            confirmed("동아에스티 '슈가논' 기반 3제 병용요법 3상 성공",source="https://example.com/trial"),
            confirmed("후원 선수 관련 임상 3상 성공",source="https://example.com/material"),
        ]
        items,stat=curate(DAY,rows)
        self.assertEqual(len(items),2)
        self.assertEqual(stat["skipped_non_editorial"],2)

    def test_native_article_body_removed_from_display_title(self):
        title="오페브 후발 신약 '자스케이드', 식약처 최종 승인 임박 [데일리팜=어윤호 기자] 관련 업계에 따르면 내용이 계속"
        self.assertEqual(headline(title),"오페브 후발 신약 '자스케이드', 식약처 최종 승인 임박")
        self.assertEqual(headline("[데일리팜]삼진제약, 용량 신설"),"삼진제약, 용량 신설")

    def test_duplicate_original_link_suppressed(self):
        items,stats=curate(DAY,[confirmed(),confirmed("같은 원문을 재수집")])
        self.assertEqual(len(items),1)
        self.assertEqual(stats["skipped_duplicate"],1)


if __name__=="__main__":
    unittest.main()
