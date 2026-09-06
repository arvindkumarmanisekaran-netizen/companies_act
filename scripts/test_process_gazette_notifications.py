import tempfile
import unittest
from pathlib import Path

from scripts.process_gazette_notifications import (
    build_index,
    has_sufficient_text,
    mentions_companies_act_2013,
    safe_name,
    screening_decision,
)


class GazetteScreeningTests(unittest.TestCase):
    def test_detects_companies_act_2013(self):
        text = (
            "powers conferred by section 454 read with section 469 "
            "of the Companies Act, 2013 (18 of 2013)"
        )
        self.assertTrue(mentions_companies_act_2013(text))
        self.assertEqual(screening_decision(text, 1)[0], "candidate")

    def test_company_law_board_is_not_false_positive(self):
        text = "Company Law Board Group B Recruitment Rules, 2013. " * 80
        self.assertFalse(mentions_companies_act_2013(text))
        self.assertEqual(screening_decision(text, 1)[0], "irrelevant")

    def test_companies_act_1956_is_not_false_positive(self):
        text = "Companies Act, 1956 section 642 accounting standards. " * 80
        self.assertFalse(mentions_companies_act_2013(text))
        self.assertEqual(screening_decision(text, 2)[0], "irrelevant")

    def test_short_text_is_uncertain(self):
        self.assertFalse(has_sufficient_text("scanned cover", 5))
        self.assertEqual(screening_decision("scanned cover", 5)[0], "uncertain")

    def test_safe_name_is_stable(self):
        result = safe_name(Path("43 - Establishment of ROCs … (267173).pdf"), "a" * 64)
        self.assertNotIn(" ", result)
        self.assertTrue(result.endswith("-aaaaaaaaaaaa"))

    def test_index_counts_notifications(self):
        records = [
            {
                "source_file": "a.pdf", "sha256": "a", "page_count": 2,
                "status": "relevant", "screening_decision": "candidate",
                "document_relevant_to_companies_act_2013": True,
                "text_file": "text/a.txt",
                "gazette": {"notifications": [
                    {"relevant_to_companies_act_2013": True},
                    {"relevant_to_companies_act_2013": False},
                ]},
            },
            {
                "source_file": "b.pdf", "sha256": "b", "page_count": 1,
                "status": "irrelevant_local_screen", "screening_decision": "irrelevant",
                "document_relevant_to_companies_act_2013": False,
                "text_file": "text/b.txt", "gazette": None,
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            index = build_index(records, output, Path("input"))
            self.assertEqual(index["document_count"], 2)
            self.assertEqual(index["relevant_document_count"], 1)
            self.assertEqual(index["relevant_notification_count"], 1)
            self.assertEqual(index["screening_counts"], {"candidate": 1, "irrelevant": 1})
            self.assertEqual(index["gemini_review_document_count"], 1)
            self.assertTrue((output / "index.json").exists())


if __name__ == "__main__":
    unittest.main()
