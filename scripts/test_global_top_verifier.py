import unittest
from global_top_verifier import verify_shortlist
class GlobalTopVerifierTests(unittest.TestCase):
    def test_budget_and_trusted_host(self):
        calls=[]
        def fake(row):
            calls.append(row["url"])
            return {"status":"VERIFIED","verified_original":True,"resolved_url":"https://www.reuters.com/article/123","published_at_verified":"2026-10-13T08:00:00+09:00"}
        rows={"shortlist":[{"title":"trial","url":f"https://news.google.com/rss/articles/{i}","verified_original":False} for i in range(12)]}
        out=verify_shortlist(rows,10,fake)
        self.assertEqual(len(calls),10)
        self.assertEqual(out["verification"]["verified"],10)
        self.assertEqual(out["verification"]["not_checked"],2)
        self.assertFalse(out["verification"]["publish_allowed"])
    def test_untrusted_host_rejected(self):
        row={"shortlist":[{"title":"trial","url":"https://news.google.com/rss/articles/x"}]}
        out=verify_shortlist(row,1,lambda x:{"status":"VERIFIED","verified_original":True,"resolved_url":"https://example.com/"})
        self.assertEqual(out["verification"]["verified"],0)
        self.assertFalse(out["shortlist"][0]["verified_original"])
if __name__=="__main__":unittest.main()
