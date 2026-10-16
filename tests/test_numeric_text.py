import unittest

from kspo_ingest.clean.numeric_text import numeric_to_words
from kspo_ingest.clean.rag import document_content, normalize_text


class NumericTextTests(unittest.TestCase):
    def test_supported_notations(self):
        cases = {
            "연령 10~15세": "연령 10세부터 15세까지",
            "만 10세 - 15세": "만 10세부터 15세까지",
            "기간 3–6개월": "기간 3개월부터 6개월까지",
            "2026-10-12": "2026년 10월 12일",
            "2026.10.12.": "2026년 10월 12일",
            "2026/10/12": "2026년 10월 12일",
            "2026-10-12~2026-11-30": "2026년 10월 12일부터 2026년 11월 30일까지",
            "2026.10.12. ~ 11월 30일": "2026년 10월 12일부터 11월 30일까지",
            "09:30~18:00": "9시 30분부터 18시 0분까지",
            "10~20%": "10퍼센트부터 20퍼센트까지",
            "요금 1,000~2,000원": "요금 1000원부터 2000원까지",
            "길이 1.5~2.0미터": "길이 1점5미터부터 2점0미터까지",
            "≥10명": "10명 이상",
            "≤20회": "20회 이하",
            "1-3": "1부터 3까지",
        }
        for original, expected in cases.items():
            with self.subTest(original=original):
                actual = numeric_to_words(original)
                self.assertEqual(actual, expected)
                self.assertEqual(numeric_to_words(actual), actual)

    def test_identifiers_and_invalid_dates_preserved(self):
        for original in [
            "https://soma.kspo.or.kr/a/2026-10-12?age=10~15",
            "연락처 02-1234-5678",
            "전화 1588-1234",
            "art-10-15@example.com",
            "첨부 2026-10-12.pdf",
            "2026-02-30",
            "온도 -5도",
            "작품 A-123-B",
        ]:
            self.assertEqual(numeric_to_words(original), original)

    def test_pipeline_and_metadata(self):
        body = normalize_text("연령 10~15세\n접수 2026-10-12~2026-11-30")
        self.assertNotIn("~", body)
        self.assertNotIn("-", body)
        source = "https://soma.kspo.or.kr/a-1"
        result = document_content(
            title="10~15세", source_url=source, body=body, summary="접수 2026-10-12"
        )
        self.assertIn("출처: " + source, result)
        self.assertIn("요약: 접수 2026년 10월 12일", result)
