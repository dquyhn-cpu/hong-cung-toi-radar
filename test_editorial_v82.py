import unittest

from editorial_v82 import build_editorial_package, score_editorial_value


class EditorialV82Tests(unittest.TestCase):
    def test_verified_concrete_event_scores_above_unverified(self):
        verified = {
            "event_id": "e1",
            "title": "Phát hiện vụ cháy lớn, lực lượng cứu hộ đang xử lý",
            "context": "Vụ cháy xảy ra lúc 10 giờ, có hình ảnh hiện trường.",
            "articles": [
                {
                    "source": "VnExpress",
                    "source_tier": "TRUSTED_NEWS",
                    "url": "https://example.com/a",
                    "title": "Vụ cháy lớn",
                    "is_new": True,
                },
                {
                    "source": "Tuổi Trẻ",
                    "source_tier": "TRUSTED_NEWS",
                    "url": "https://example.com/b",
                    "title": "Cứu hộ vụ cháy",
                    "is_new": True,
                },
            ],
            "social_posts": [],
            "social_sources": ["BeatVN"],
            "specificity": {
                "proper_phrases": ["vu chay"],
                "numbers": ["10"],
                "concrete_action": True,
                "distinctive_count": 8,
            },
            "hot_rule": "MULTI_SOURCE_EVENT",
        }
        unverified = {
            **verified,
            "event_id": "e2",
            "articles": [],
            "social_sources": [],
        }

        self.assertGreater(
            score_editorial_value(verified)["score"],
            score_editorial_value(unverified)["score"],
        )

    def test_political_or_official_content_requires_neutral_language(self):
        event = {
            "event_id": "e3",
            "title": "Chính phủ công bố quyết định mới",
            "context": "",
            "articles": [
                {
                    "source": "Cổng TTĐT Chính phủ",
                    "source_tier": "OFFICIAL",
                    "url": "https://example.com/c",
                    "title": "Quyết định mới",
                    "is_new": True,
                }
            ],
            "social_posts": [],
            "social_sources": [],
            "specificity": {
                "proper_phrases": ["chinh phu"],
                "numbers": [],
                "concrete_action": True,
                "distinctive_count": 5,
            },
        }
        score = score_editorial_value(event)
        self.assertIn("NEUTRAL_LANGUAGE_REQUIRED", score["risk_flags"])

    def test_editorial_package_defaults_to_not_approved(self):
        event = {
            "event_id": "e4",
            "title": "Giá xăng thay đổi",
            "context": "",
            "articles": [],
            "social_posts": [],
            "social_sources": [],
            "specificity": {},
        }
        source = {
            "source": "VnExpress",
            "source_tier": "TRUSTED_NEWS",
            "url": "https://example.com/d",
            "title": "Giá xăng thay đổi",
        }
        package = build_editorial_package(event, source)
        self.assertFalse(package["output_schema"]["approved"])
        self.assertEqual(package["output_schema"]["main_post"], "")


if __name__ == "__main__":
    unittest.main()
