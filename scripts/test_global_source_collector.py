import unittest
from global_source_collector import scan_global_sources,FEEDS,PUBLISHERS,COMPANIES
class GlobalSourceTests(unittest.TestCase):
    def test_budget_window_and_dedup(self):
        calls=[]
        def fake(q):
            calls.append(q)
            return [{"title":"Pfizer trial result","url":"https://example.com/new","published_at":"Mon, 12 Oct 2026 05:00:00 GMT"},{"title":"old","url":"https://example.com/old","published_at":"Sun, 11 Oct 2026 05:00:00 GMT"}]
        out=scan_global_sources("2026-10-13",{},lambda:"now",fake,fake)
        self.assertEqual(len(calls),21)
        self.assertEqual(len(out["routes"]),21)
        self.assertEqual(len(out["candidates"]),1)
        self.assertEqual(len(out["company_checks"]),20)
        self.assertEqual(out["status"],"PARTIAL")
    def test_failures_are_isolated(self):
        def fail(_):raise OSError("blocked")
        out=scan_global_sources("2026-10-13",{},lambda:"now",fail,fail)
        self.assertEqual(len(out["routes"]),21)
        self.assertEqual(out["status"],"FAIL")
if __name__=="__main__":unittest.main()
