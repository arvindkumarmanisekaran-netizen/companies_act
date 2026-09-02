import unittest

from scripts.pdftojson import deduplicate_chapters, merge_bare_act_history, parse_sections_robust


class ParserMergeTests(unittest.TestCase):
    def test_section_number_is_not_repeated_in_title(self):
        sections = parse_sections_robust(
            "\n23. Public offer and placement.—The provision text.", {}
        )

        self.assertEqual(sections[0]["section_number"], "23")
        self.assertEqual(sections[0]["title"], "Public offer and placement.")

    def test_duplicate_chapters_keep_the_richer_body_copy(self):
        chapters = [
            {"chapter_number": "CHAPTER I", "sections": []},
            {
                "chapter_number": "CHAPTER I",
                "sections": [
                    {
                        "section_number": "1",
                        "title": "Short title",
                        "subsections": [{"text": "Current text", "clauses": []}],
                    }
                ],
            },
        ]

        result = deduplicate_chapters(chapters)

        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["sections"]), 1)

    def test_bare_clauses_are_retained_as_substituted_or_omitted(self):
        bare = {
            "chapters": [
                {
                    "chapter_number": "CHAPTER I",
                    "sections": [
                        {
                            "section_number": "1",
                            "amendments": [],
                            "subsections": [
                                {
                                    "subsection_number": "(1)",
                                    "text": "Original",
                                    "amendments": [],
                                    "clauses": [
                                        {"clause_number": "(a)", "text": "original clause A"},
                                        {"clause_number": "(b)", "text": "original clause B"},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        current = {
            "chapters": [
                {
                    "chapter_number": "CHAPTER I",
                    "sections": [
                        {
                            "section_number": "1",
                            "amendments": [{"note": "Subs. by Act 1 of 2020"}],
                            "subsections": [
                                {
                                    "subsection_number": "(1)",
                                    "text": "Current",
                                    "amendments": [],
                                    "clauses": [
                                        {"clause_number": "(a)", "text": "replacement clause A"}
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }

        merged = merge_bare_act_history(current, bare, {})
        history = merged["chapters"][0]["sections"][0]["subsections"][0][
            "historical_clauses"
        ]

        self.assertEqual([item["change_type"] for item in history], ["substituted", "omitted"])
        self.assertTrue(all("Act 1 of 2020" in item["source_note"] for item in history))


if __name__ == "__main__":
    unittest.main()
