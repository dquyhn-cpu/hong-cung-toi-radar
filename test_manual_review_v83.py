import unittest

from build_manual_review_v83 import build_candidates, build_markdown


class ManualReviewV83Tests(unittest.TestCase):
    def test_only_ready_for_draft_candidates_are_included(self):
        context = {
            "items": [
                {
                    "event_id": "e1",
                    "status": "READY_FOR_DRAFT",
                    "working_title": "Tin đủ điều kiện",
                    "editorial_score": {"score": 80, "tier": "PRIORITY"},
                    "recommended_angle": "TIN_MOI_CAN_BIET",
                    "monetization_preflight": {
                        "monetization_risk": "LOW",
                        "recommended_publish_mode": "POST",
                        "risk_flags": [],
                    },
                    "source_bundle": [
                        {
                            "status": "READ_OK",
                            "source": "Example",
                            "tier": "TRUSTED_NEWS",
                            "article": {
                                "title": "Bài nguồn",
                                "canonical_url": "https://example.com/a",
                            },
                        }
                    ],
                },
                {
                    "event_id": "e2",
                    "status": "SOURCE_READ_REQUIRED",
                    "working_title": "Tin chưa đọc được nguồn",
                    "editorial_score": {"score": 90, "tier": "PRIORITY"},
                },
            ]
        }
        packets = {
            "items": [
                {"event_id": "e1", "prompt": "draft e1"},
                {"event_id": "e2", "prompt": "draft e2"},
            ]
        }

        candidates = build_candidates(context, packets, 5)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["event_id"], "e1")
        self.assertEqual(candidates[0]["source"]["url"], "https://example.com/a")

    def test_markdown_states_no_api_and_no_autopost(self):
        markdown = build_markdown([])
        self.assertIn("Không có API AI", markdown)
        self.assertIn("Không có bài nào được tự động đăng Facebook", markdown)


if __name__ == "__main__":
    unittest.main()
