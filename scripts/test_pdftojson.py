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
                            "amendments": [],
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

        amendment_sources = {
            "1": [
                {
                    "operation": "substituted",
                    "target": "section 1, clause (a)",
                    "citation": "Substituted by Act 1 of 2020, section 1, clause (a).",
                },
                {
                    "operation": "omitted",
                    "target": "section 1, clause (b)",
                    "citation": "Omitted by Act 1 of 2020, section 1, clause (b).",
                },
            ]
        }
        merged = merge_bare_act_history(current, bare, amendment_sources)
        history = merged["chapters"][0]["sections"][0]["subsections"][0][
            "historical_clauses"
        ]

        self.assertEqual([item["change_type"] for item in history], ["substituted", "omitted"])
        self.assertTrue(all("Act 1 of 2020" in item["source_note"] for item in history))

    def test_clause_citations_are_exact_and_unamended_clauses_are_restored(self):
        bare = {
            "chapters": [
                {
                    "chapter_number": "CHAPTER I",
                    "sections": [
                        {
                            "section_number": "2",
                            "amendments": [],
                            "subsections": [
                                {
                                    "subsection_number": "N/A",
                                    "text": "Definitions",
                                    "amendments": [],
                                    "clauses": [
                                        {"clause_number": "(6)", "text": "old associate company"},
                                        {"clause_number": "(38)", "text": "expert definition"},
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
                            "section_number": "2",
                            "amendments": [],
                            "subsections": [
                                {
                                    "subsection_number": "N/A",
                                    "text": "Definitions",
                                    "amendments": [],
                                    "clauses": [
                                        {"clause_number": "(6)", "text": "new associate company"}
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        sources = {
            "2": [
                {
                    "operation": "substituted",
                    "target": "section 2, clause (6), Explanation",
                    "citation": "Substituted by the 2017 Act, section 2, clause (6).",
                },
                {
                    "operation": "substituted",
                    "target": "section 2, clause (28)",
                    "citation": "Unrelated clause 28 citation.",
                },
            ]
        }

        merged = merge_bare_act_history(current, bare, sources)
        subsection = merged["chapters"][0]["sections"][0]["subsections"][0]
        history = subsection["historical_clauses"]

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["clause_number"], "(6)")
        self.assertIn("clause (6)", history[0]["source_note"])
        self.assertNotIn("clause 28", history[0]["source_note"])
        restored = {item["clause_number"]: item for item in subsection["clauses"]}
        self.assertEqual(restored["(38)"]["text"], "expert definition")
        self.assertFalse(restored["(38)"].get("historical", False))


if __name__ == "__main__":
    unittest.main()
