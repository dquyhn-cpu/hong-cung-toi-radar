import unittest

from draft_validator import validate_editorial_output
from source_reader import extract_article_html
from editorial_pipeline import should_include_event


class SourceReaderTests(unittest.TestCase):
    def test_extracts_article_body_and_metadata(self):
        html = """
        <html>
          <head>
            <title>Bản tin thử nghiệm</title>
            <meta property="og:title" content="Tiêu đề OG">
            <meta name="description" content="Mô tả thử nghiệm">
            <link rel="canonical" href="https://example.com/canonical">
          </head>
          <body>
            <article>
              <p>Đây là đoạn nội dung đầu tiên đủ dài để hệ thống nhận diện phần bài báo và không nhầm với menu.</p>
              <p>Đây là đoạn nội dung thứ hai bổ sung thêm dữ kiện cho bài viết thử nghiệm trong bộ kiểm tra.</p>
              <p>Đây là đoạn nội dung thứ ba nhằm bảo đảm tổng chiều dài vượt ngưỡng tối thiểu của bộ đọc nguồn.</p>
              <p>Đây là đoạn nội dung thứ tư để hoàn thiện bài kiểm thử cho chức năng trích xuất nội dung gốc.</p>
            </article>
          </body>
        </html>
        """
        result = extract_article_html(html, "https://example.com/a")
        self.assertEqual(result["title"], "Tiêu đề OG")
        self.assertEqual(result["canonical_url"], "https://example.com/canonical")
        self.assertTrue(result["readable"])
        self.assertIn("đoạn nội dung đầu tiên", result["text"])

    def test_draft_validator_blocks_engagement_bait(self):
        item = {
            "event_id": "e1",
            "sources": [{"url": "https://example.com/source"}],
            "editorial_score": {"risk_flags": []},
            "output_schema": {
                "approved": True,
                "main_post": (
                    "Đây là một bản tin đã có đủ nội dung cốt lõi và dữ kiện chính "
                    "để người đọc hiểu sự việc mà không cần mở bình luận."
                ),
                "comments": ["Bình luận từ khóa OK để xem tiếp chi tiết."],
                "source_note": "Nguồn: Example https://example.com/source",
            },
        }
        result = validate_editorial_output(item)
        self.assertFalse(result["ok"])
        self.assertIn("ENGAGEMENT_BAIT", result["errors"])

    def test_draft_validator_requires_source_url(self):
        item = {
            "event_id": "e2",
            "sources": [{"url": "https://example.com/source"}],
            "editorial_score": {"risk_flags": []},
            "output_schema": {
                "approved": True,
                "main_post": (
                    "Đây là một bản tin thử nghiệm có đủ độ dài để vượt ngưỡng "
                    "và không chứa bất kỳ lời kêu gọi tương tác nào."
                ),
                "comments": [],
                "source_note": "Nguồn: Example",
            },
        }
        result = validate_editorial_output(item)
        self.assertFalse(result["ok"])
        self.assertIn("SOURCE_NOTE_MISSING_URL", result["errors"])


class EditorialPipelineSelectionTests(unittest.TestCase):
    def test_watch_event_can_reach_v82_review(self):
        event = {"decision": "THEO_DOI"}
        package = {"editorial_score": {"score": 48, "tier": "REVIEW"}}
        self.assertTrue(should_include_event(event, package))

    def test_low_watch_event_stays_out(self):
        event = {"decision": "THEO_DOI"}
        package = {"editorial_score": {"score": 38, "tier": "LOW"}}
        self.assertFalse(should_include_event(event, package))

    def test_direct_editorial_event_is_always_included(self):
        event = {"decision": "CHUYEN_BAN_BIEN_TAP"}
        package = {"editorial_score": {"score": 20, "tier": "LOW"}}
        self.assertTrue(should_include_event(event, package))


if __name__ == "__main__":
    unittest.main()
