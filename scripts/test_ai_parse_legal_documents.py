import unittest

from scripts.ai_parse_legal_documents import (
    DOCUMENTS,
    MODEL,
    amendment_source_map,
    merge_act_chunks,
    merge_legal_text,
    normalize_section_titles,
)


def section(number, text, clause_text=""):
    clauses = [{"clause_number": "(a)", "text": clause_text}] if clause_text else []
    return {
        "section_number": number,
        "title": f"{number}. Sample title",
        "status": "active",
        "subsections": [
            {
                "subsection_number": "(1)",
                "text": text,
                "status": "active",
                "clauses": clauses,
                "amendments": [],
            }
        ],
        "amendments": [],
    }


class AiLegalParserTests(unittest.TestCase):
    def test_document_manifest_excludes_ordinances(self):
        self.assertEqual(len(DOCUMENTS), 6)
        self.assertFalse(any("ordinance" in name.lower() for name in DOCUMENTS))
        self.assertTrue(MODEL.startswith("gemini-"))

    def test_merge_legal_text_uses_overlap(self):
        self.assertEqual(
            merge_legal_text(
                "The company shall keep a registered office at all times",
                "registered office at all times capable of receiving notices",
            ),
            "The company shall keep a registered office at all times capable of receiving notices",
        )

    def test_chunk_merge_deduplicates_and_joins_sections(self):
        chunks = [
            {
                "act_title": "THE COMPANIES ACT, 2013",
                "doc_type": "current_act",
                "chapters": [
                    {
                        "chapter_number": "CHAPTER I",
                        "chapter_title": "PRELIMINARY",
                        "sections": [section("1", "first visible fragment")],
                    }
                ],
            },
            {
                "act_title": "THE COMPANIES ACT, 2013",
                "doc_type": "current_act",
                "chapters": [
                    {
                        "chapter_number": "CHAPTER I",
                        "chapter_title": "PRELIMINARY",
                        "sections": [section("1", "visible fragment continued")],
                    }
                ],
            },
        ]

        import scripts.ai_parse_legal_documents as module

        original = module.validate_act
        module.validate_act = lambda *_: None
        try:
            merged = merge_act_chunks(chunks, "current_act")
        finally:
            module.validate_act = original

        self.assertEqual(len(merged["chapters"]), 1)
        self.assertEqual(len(merged["chapters"][0]["sections"]), 1)
        self.assertEqual(merged["chapters"][0]["sections"][0]["title"], "Sample title")
        self.assertIn(
            "continued",
            merged["chapters"][0]["sections"][0]["subsections"][0]["text"],
        )

    def test_title_normalization_removes_section_prefix(self):
        document = {"chapters": [{"sections": [section("23", "text")]}]}
        normalize_section_titles(document)
        self.assertEqual(document["chapters"][0]["sections"][0]["title"], "Sample title")

    def test_amendment_source_map_is_specific(self):
        sources = amendment_source_map(
            [
                {
                    "document_title": "Companies (Amendment) Act, 2019",
                    "act_number": "22 of 2019",
                    "amendments": [
                        {
                            "principal_section": "10A",
                            "operation": "inserted",
                            "target": "section 10A",
                            "page_reference": "page 2",
                        }
                    ],
                }
            ]
        )
        record = sources["10A"][0]
        self.assertEqual(record["target"], "section 10A")
        self.assertEqual(record["operation"], "inserted")
        self.assertIn("Companies (Amendment) Act, 2019", record["citation"])
        self.assertIn("Act 22 of 2019", record["citation"])
        self.assertIn("PDF page 2", record["citation"])


if __name__ == "__main__":
    unittest.main()
