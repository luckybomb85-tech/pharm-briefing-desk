import unittest
from global_candidate_ranker import select
class RankerTests(unittest.TestCase):
    def test_dedup_and_no_false_verification(self):
        rows=[{"title":"Drug phase 3 trial meets primary endpoint","url":"https://example.com/a","source":"Reuters"},{"title":"Drug phase 3 trial meets primary endpoint","url":"https://example.com/b","source":"Other"},{"title":"Webinar attendance notice","url":"https://example.com/c"}]
        out=select(rows)
        self.assertEqual(out["ranked_count"],1)
        self.assertEqual(out["shortlist"][0]["editorial_status"],"CANDIDATE_ONLY")
        self.assertFalse(out["shortlist"][0]["verified_original"])
    def test_invalid_and_low_value(self):
        out=select([{"title":"Stock price rises on analyst rating","url":"https://example.com/stock"},{"title":"Phase 3 trial","url":"javascript:bad"}])
        self.assertEqual(out["ranked_count"],0)
if __name__=="__main__":unittest.main()
