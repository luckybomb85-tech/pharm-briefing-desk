import datetime as dt
import importlib.util
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

p = Path(__file__).with_name("collect.py")
spec = importlib.util.spec_from_file_location("collector", p)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class CollectorTests(unittest.TestCase):
    def test_url_rejects_google_intermediary(self):
        self.assertIsNone(mod.canonical_url("https://news.google.com/rss/articles/ABC"))
        self.assertEqual(mod.canonical_url("https://www.hkn24.com/news/articleView.html?idxno=123&utm_source=x"), "https://www.hkn24.com/news/articleView.html?idxno=123")

    def test_feed_and_source_priority(self):
        now = dt.datetime(2026, 10, 14, 7, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        stamp = dt.datetime(2026, 10, 14, 6, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        xml = ('<rss><channel><item><title>제약 신약 임상</title><link>https://news.google.com/rss/articles/ABC</link>'
               '<pubDate>' + stamp.strftime("%a, %d %b %Y %H:%M:%S %z") + '</pubDate>'
               '<source url="https://www.hkn24.com">헬스코리아뉴스</source></item></channel></rss>').encode()
        cfg={"priority_sites":[["헬스코리아뉴스","hkn24.com"]],"search_terms":["제약"],"discovery":{"timeout_seconds":1,"max_per_site":10}}
        result=mod.collect(now,cfg,lambda url,timeout:xml)
        self.assertEqual(len(result["items"]),0)
        self.assertEqual(len(result["unresolved"]),1)
        self.assertEqual(result["unresolved"][0]["verification_status"],"original_url_unresolved")
        self.assertEqual(result["window_start"],"2026-10-13T12:00:00+09:00")

if __name__ == "__main__":
    unittest.main()
