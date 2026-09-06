import json
import tempfile
import unittest
from pathlib import Path

from scripts.ai_parse_with_checkpoint import (
    atomic_write_json,
    checkpoint_key,
    is_transient_error,
    update_carry,
)


class AiCheckpointParserTests(unittest.TestCase):
    def test_checkpoint_key_is_stable(self):
        self.assertEqual(checkpoint_key(19, 28), "pages-0019-0028.json")

    def test_atomic_write_json_produces_valid_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "checkpoint.json"
            atomic_write_json(path, {"batch": 3, "ok": True})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"batch": 3, "ok": True},
            )
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_transient_gemini_errors_are_retryable(self):
        self.assertTrue(
            is_transient_error(
                RuntimeError("503 UNAVAILABLE: model is experiencing high demand")
            )
        )
        self.assertTrue(is_transient_error(RuntimeError("429 RESOURCE_EXHAUSTED")))
        self.assertFalse(is_transient_error(ValueError("invalid local configuration")))

    def test_update_carry_uses_last_visible_section(self):
        chunk = {
            "chapters": [
                {
                    "chapter_number": "CHAPTER III",
                    "chapter_title": "PROSPECTUS",
                    "sections": [
                        {"section_number": "23", "title": "Public offer"},
                        {"section_number": "24", "title": "Power of SEBI"},
                    ],
                }
            ]
        }
        chapter, section = update_carry(chunk, "old chapter", "old section")
        self.assertEqual(chapter, "CHAPTER III (PROSPECTUS)")
        self.assertEqual(section, "section 24 (Power of SEBI)")


if __name__ == "__main__":
    unittest.main()
