import unittest
from email.message import Message
from verify_originals import verify,date_iso,process
class Response:
    def __init__(self,body):
        self.body=body;self.headers=Message();self.headers["Content-Type"]="text/html"
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def geturl(self):return "https://publisher.example/news/1"
    def read(self,n):return self.body.encode()
def opener(body):return lambda req,timeout:Response(body)
class TestOriginals(unittest.TestCase):
    def test_verified(self):
        r=verify({"url":"https://publisher.example/news/1"},opener('<title>Real article</title><meta property="article:published_time" content="2026-10-08T09:00:00+09:00">'))
        self.assertTrue(r["verified_original"]);self.assertEqual(r["published_at_verified"],"2026-10-08T09:00:00+09:00")
    def test_no_date(self):
        self.assertEqual(verify({"url":"https://publisher.example/news/1"},opener("<title>Article</title>"))["reason"],"NO_VERIFIABLE_PUBLICATION_DATE")
    def test_aggregator(self):
        self.assertEqual(verify({"url":"https://news.google.com/rss/articles/abc"},opener=lambda req,timeout:Response("<title>Google News</title>"))["reason"],"NO_VERIFIABLE_PUBLICATION_DATE")
    def test_naive_date(self):self.assertIsNone(date_iso("2026-10-08T09:00:00"))
    def test_limit(self):
        x=process({"candidates":[{"url":"bad"},{"url":"bad"}]},1)
        self.assertEqual(x["original_verification_summary"]["NOT_CHECKED"],1)
if __name__=="__main__":unittest.main()
