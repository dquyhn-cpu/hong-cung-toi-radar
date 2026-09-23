import unittest

from monetization_preflight import monetization_preflight


class MonetizationPreflightTests(unittest.TestCase):
    def test_death_crime_story_is_not_low_risk(self):
        event = {
            "title": "Một người tử vong sau vụ tai nạn, công an đang điều tra",
            "context": "",
            "articles": [
                {
                    "source": "VnExpress",
                    "source_tier": "TRUSTED_NEWS",
                    "url": "https://example.com/a",
                }
            ],
            "social_posts": [],
        }
        result = monetization_preflight(event)
        self.assertIn(result["monetization_risk"], {"MEDIUM", "HIGH"})
        self.assertEqual(result["recommended_publish_mode"], "POST_WITH_CAUTION")
        self.assertIn("ATTRIBUTION_REQUIRED", result["risk_flags"])

    def test_no_verified_source_is_blocked(self):
        event = {
            "title": "Tin lan truyền trên mạng",
            "context": "Chưa có nguồn báo hoặc cơ quan chính thức.",
            "articles": [],
            "social_posts": [{"text": "Tin đang lan truyền"}],
        }
        result = monetization_preflight(event)
        self.assertEqual(result["recommended_publish_mode"], "SKIP")
        self.assertIn("SOURCE_INTEGRITY_BLOCK", result["risk_flags"])

    def test_official_topic_requires_neutral_language(self):
        event = {
            "title": "Chính phủ công bố quyết định mới",
            "context": "",
            "articles": [
                {
                    "source": "Cổng TTĐT Chính phủ",
                    "source_tier": "OFFICIAL",
                    "url": "https://example.com/b",
                }
            ],
            "social_posts": [],
        }
        result = monetization_preflight(event)
        self.assertIn("NEUTRAL_LANGUAGE_REQUIRED", result["risk_flags"])
        self.assertIn(result["recommended_publish_mode"], {"POST", "POST_WITH_CAUTION"})


# Trigger CI after installing dedicated V8.2 workflow on main.

if __name__ == "__main__":
    unittest.main()
