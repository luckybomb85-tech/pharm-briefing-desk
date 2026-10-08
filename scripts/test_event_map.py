import unittest
from build_event_map import build

class TestEventMap(unittest.TestCase):
    def test_exact_duplicate(self):
        a={'title':'기사 1','url':'https://example.com/a'}
        b={'title':'기사 1','url':'https://example.com/a?utm_source=x'}
        d=build({'candidates':[a,b]})
        self.assertEqual(d['deduplication']['duplicates'],1)
    def test_distinct_followups(self):
        a={'title':'한미 에페글레나타이드 허가','url':'https://example.com/a','verified_original':True}
        b={'title':'에페글레나타이드 약가 급여 협상','url':'https://example.com/b','verified_original':True}
        d=build({'candidates':[a,b]})
        self.assertEqual(d['deduplication']['unique'],2)
        self.assertIn('approval',d['event_map']['HANMI-EPHE-APPROVAL']['milestones'])
        self.assertIn('reimbursement',d['event_map']['HANMI-EPHE-APPROVAL']['milestones'])
    def test_distinct_bing_links(self):
        a={'title':'First','url':'https://www.bing.com/news/apiclick.aspx?url=https%3A%2F%2Fone.example%2F1'}
        b={'title':'Second','url':'https://www.bing.com/news/apiclick.aspx?url=https%3A%2F%2Ftwo.example%2F2'}
        self.assertEqual(build({'candidates':[a,b]})['deduplication']['unique'],2)
    def test_followup_cap(self):
        titles=['에페글레나타이드 허가','에페글레나타이드 급여','에페글레나타이드 출시','에페글레나타이드 경쟁']
        items=[{'title':t,'url':'https://example.com/'+str(i),'verified_original':True} for i,t in enumerate(titles)]
        d=build({'candidates':items})
        self.assertEqual(len(d['unique_candidates']),4)
        self.assertEqual(len(d['event_recommendations']['HANMI-EPHE-APPROVAL']),2)
    def test_bing_same_target_dedup(self):
        a={'title':'A','url':'https://www.bing.com/news/apiclick.aspx?url=https%3A%2F%2Fexample.com%2Fa'}
        b={'title':'A','url':'https://example.com/a?utm_source=bing'}
        self.assertEqual(build({'candidates':[a,b]})['deduplication']['duplicates'],1)
    def test_unverified_not_recommended(self):
        d=build({'candidates':[{'title':'에페오토 허가','url':'https://example.com/a'}]})
        self.assertEqual(d['event_recommendations']['HANMI-EPHE-APPROVAL'],[])
        self.assertEqual(d['event_watch_status']['HANMI-EPHE-APPROVAL'],'UNVERIFIED_ONLY')
    def test_absent_not_success(self):
        d=build({'candidates':[]})
        self.assertEqual(d['event_watch_status']['HANMI-EPHE-APPROVAL'],'NOT_FOUND_IN_SCAN')
    def test_unverified_flag(self):
        d=build({'candidates':[{'title':'에페오토 출시','url':'https://example.com/c'}]})
        self.assertFalse(d['event_map']['HANMI-EPHE-APPROVAL']['articles'][0]['verified_original'])

if __name__=='__main__':unittest.main()
