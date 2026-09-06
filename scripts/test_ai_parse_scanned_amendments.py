import unittest

from scripts.ai_parse_scanned_amendments import (
    merge_ai_sources,
    normalize_section_titles,
)


class AiParserMergeTests(unittest.TestCase):
    def test_normalizes_duplicate_section_number(self):
        master = {
            "chapters": [
                {
                    "sections": [
                        {"section_number": "23", "title": "23. Public offer and placement."}
                    ]
                }
            ]
        }

        normalize_section_titles(master)

        self.assertEqual(
            master["chapters"][0]["sections"][0]["title"],
            "Public offer and placement.",
        )

    def test_ai_source_replaces_only_unresolved_note(self):
        unresolved = "Amendment source was not identified in the parsed footnotes."
        master = {
            "chapters": [
                {
                    "sections": [
                        {
                            "section_number": "11",
                            "historical": True,
                            "source_note": unresolved,
                            "subsections": [],
                        }
                    ]
                }
            ]
        }
        parsed_documents = [
            {
                "parsed": {
                    "document_title": "Companies (Amendment) Ordinance, 2018",
                    "ordinance_number": "9 of 2018",
                    "publication_date": "2018",
                    "amendments": [
                        {
                            "principal_section": "11",
                            "operation": "omitted",
                            "target": "section 11",
                            "enacted_text": "",
                            "source_excerpt": "Section 11 shall be omitted.",
                            "effective_date": "",
                            "page_reference": "PDF page 3",
                        }
                    ],
                }
            }
        ]

        merge_ai_sources(master, parsed_documents)

        note = master["chapters"][0]["sections"][0]["source_note"]
        self.assertIn("Companies (Amendment) Ordinance, 2018", note)
        self.assertIn("omitted", note)


if __name__ == "__main__":
    unittest.main()
