import unittest

from apply_review_v83 import assemble_final_post, normalize_variant
from draft_generator_v83 import validate_draft_shape


class DraftReviewV83Tests(unittest.TestCase):
    def test_validate_draft_shape_requires_unapproved_review_state(self):
        draft = {
            "publish_id": "e1",
            "approved": False,
            "caption_a": "Caption A",
            "caption_b": "Caption B",
            "summary_a": "Summary A",
            "summary_b": "Summary B",
            "source_comment": "Nguồn: Example https://example.com/a",
            "selected_variant": "",
            "main_post": "",
            "comments": [],
            "source_note": "Nguồn: Example https://example.com/a",
        }
        validate_draft_shape(draft, "e1")

    def test_validate_draft_shape_blocks_model_auto_approval(self):
        draft = {
            "publish_id": "e1",
            "approved": True,
            "caption_a": "Caption A",
            "caption_b": "Caption B",
            "summary_a": "Summary A",
            "summary_b": "Summary B",
            "source_comment": "Nguồn: Example https://example.com/a",
            "selected_variant": "",
            "main_post": "",
            "comments": [],
            "source_note": "Nguồn: Example https://example.com/a",
        }
        with self.assertRaises(ValueError):
            validate_draft_shape(draft, "e1")

    def test_review_assembles_selected_variant(self):
        draft = {
            "caption_a": "Caption trực diện",
            "caption_b": "Caption gợi tò mò",
            "summary_a": "Tóm tắt A",
            "summary_b": "Tóm tắt B",
            "source_comment": "Nguồn: Example\nĐọc bài báo gốc tại đây: https://example.com/a",
        }
        main_post, comments, source_note = assemble_final_post(draft, "B")
        self.assertIn("Caption gợi tò mò", main_post)
        self.assertIn("Tóm tắt B", main_post)
        self.assertEqual(comments, [source_note])

    def test_variant_must_be_a_or_b(self):
        with self.assertRaises(ValueError):
            normalize_variant("C")


if __name__ == "__main__":
    unittest.main()
