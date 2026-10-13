import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import os
from publish_domestic_desk import publish

class PublishDomesticDeskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=os.getcwd()
        os.chdir(self.tmp.name)
        Path("staging").mkdir()
        Path("domestic").mkdir()
    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()
    def fixture(self, rows):
        Path("staging/2026-10-14-domestic-stage4.json").write_text(
            json.dumps({"date":"2026-10-14","domestic":rows}),encoding="utf-8")
    def test_export_valid_candidate(self):
        self.fixture([{"title":"제약사 임상 결과","source":"https://example.com/article","priority":"P1"}])
        publish("2026-10-14")
        data=json.loads(Path("domestic/2026-10-14.json").read_text(encoding="utf-8"))
        self.assertEqual(len(data["items"]),1)
        self.assertTrue(data["items"][0]["discovery_only"])
    def test_empty_does_not_overwrite(self):
        target=Path("domestic/2026-10-14.json")
        target.write_text('{"old":true}',encoding="utf-8")
        self.fixture([])
        with self.assertRaisesRegex(ValueError,"DOMESTIC_NO_VALID_CANDIDATES"):
            publish("2026-10-14")
        self.assertEqual(target.read_text(encoding="utf-8"),'{"old":true}')
    def test_invalid_link_rejected(self):
        self.fixture([{"title":"잘못된 링크","source":"javascript:alert(1)"}])
        with self.assertRaises(ValueError):
            publish("2026-10-14")

if __name__=="__main__":
    unittest.main()
