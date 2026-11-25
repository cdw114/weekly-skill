"""Regression tests for case outputs, deadlines, OCR fallback, and source-linked answers."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
import output_contract as contract
import pdfparse as parser
import run_case


class OutputContractTests(unittest.TestCase):
    def test_markdown_inline_and_unknown_required_field(self):
        case = {"output_contract": {"properties": {"markdown": {"type": "string"},
                                                    "translation": {"type": "object"}},
                                    "required": ["markdown", "translation"]}}
        result = {"case_id": "demo", "result": {"document": {"title": "Demo"}},
                  "status": {"state": "success", "notes": []}, "evidence": {}, "uncertainty": {}}
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp)/"document.md").write_text("# Demo\n", encoding="utf-8")
            contract.project_case_fields(case, result, {}, temp)
        self.assertEqual(result["markdown"], "# Demo\n")
        self.assertEqual(result["status"]["state"], "partial")
        self.assertEqual(result["uncertainty"]["contract_errors"], ["translation: missing"])

    def test_nested_types_and_file_path(self):
        case = {"output_contract": {"fields": [
            {"name": "markdown", "type": "file"},
            {"name": "metadata", "type": "object", "required": ["pages"],
             "properties": {"pages": {"type": "integer"}}},
        ], "artifacts": ["preview.png"]}}
        result = dict.fromkeys(contract.BASE_FIELDS)
        result.update(markdown="../outside.md", metadata={"pages": True})
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp)/"document.md").touch()
            self.assertEqual(len(contract.contract_errors(case, result, temp)), 3)
            (Path(temp)/"preview.png").touch()
            result.update(markdown="document.md", metadata={"pages": 3})
            self.assertFalse(contract.contract_errors(case, result, temp))

    def test_invalid_final_answer_source_is_rejected(self):
        box = [10, 20, 30, 40]
        hit = {"id": "p2-b01", "page": 2, "bbox": box}
        result = {"case_id": "demo", "status": {"state": "success"}, "uncertainty": {},
                  "evidence": {"block_index": [hit]},
                  "result": {"questions": [{"question": "How many?", "answer": "3", "status": "verified",
                                             "answer_block": hit["id"], "evidence": [{**hit, "page": 1}]}]}}
        self.assertTrue(contract.evidence_errors({"case_id": "demo"}, result))
        result["result"]["questions"][0]["evidence"] = [hit]
        self.assertFalse(contract.evidence_errors({"case_id": "demo"}, result))

    def test_missing_input_keeps_case_and_failed_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            case = root/"case.json"
            case.write_text(json.dumps({"case_id": "missing-demo", "pdf": "missing.pdf",
                                        "output_contract": ["translation"]}), encoding="utf-8")
            rc = run_case.main(["--case", str(case), "--out", str(root/"out"), "--work", str(root/"work")])
            result = json.loads((root/"out/result.json").read_text(encoding="utf-8"))
        self.assertEqual(rc, 2)
        self.assertEqual(result["case_id"], "missing-demo")
        self.assertEqual(result["status"]["state"], "failed")
        self.assertIn("missing.pdf", result["status"]["reason"])
        self.assertEqual(result["uncertainty"]["contract_errors"], ["translation: missing"])


class OCRAndEvidenceTests(unittest.TestCase):
    def test_ocr_crash_and_empty_output_fall_through(self):
        line = parser.Line("中文文献正文", (5, 8, 40, 12), 12, "ocr:tesseract", False, False, 0,
                           meta={"ocr_conf": 0.94})
        with patch.object(parser, "_run_ocr_attempt", side_effect=[RuntimeError("failed"), [], [line]]) as attempt:
            notes = []
            lines, source = parser.ocr_with_fallback("scan.pdf", 1, ["rapidocr", "paddleocr", "tesseract"],
                                                     "chi_sim+eng", 200, None, time.monotonic() + 10, notes)
        self.assertEqual(attempt.call_count, 3)
        self.assertEqual((lines, source), ([line], "tesseract"))
        self.assertIn("failed", notes[0])
        self.assertIn("returned no text", notes[1])

    def test_deadline_stops_before_engine(self):
        with patch.object(parser, "_run_ocr_attempt") as attempt:
            notes = []
            result = parser.ocr_with_fallback("scan.pdf", 2, ["rapidocr"], "eng", 200, None, 0, notes)
        attempt.assert_not_called()
        self.assertEqual(result, ([], ""))
        self.assertIn("page 2", notes[0])

    def test_page_range_is_bounded_and_ordered(self):
        self.assertEqual(parser.parse_page_range("8,2,2,1-3,3-99999999", 5), [1, 2, 3, 4, 5])

    def test_zero_budget_keeps_a_parse_result_without_touching_pages(self):
        class ThreePageDocument:
            needs_pass = False

            def __len__(self):
                return 3

            def __getitem__(self, _index):
                raise AssertionError("expired run tried to access a page")

            def close(self):
                pass

        fitz = types.SimpleNamespace(open=lambda _path: ThreePageDocument(), version=("test",))
        with tempfile.TemporaryDirectory() as temp, patch.object(parser, "fitz", fitz):
            root = Path(temp)
            (root/"dummy.pdf").touch()
            (root/"case.json").write_text('{"case_id":"cutoff","pdf":"dummy.pdf"}', encoding="utf-8")
            code = run_case.main(["--case", str(root/"case.json"), "--work", str(root/"work"), "--out", str(root/"out"),
                                  "--lang", "eng", "--ocr", "off", "--max-seconds", "0"])
            result = json.loads((root/"out/result.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(result["status"]["state"], "partial")
        self.assertEqual(result["status"]["pages_parsed"], 0)
        self.assertEqual(result["uncertainty"]["not_done"], [1, 2, 3])

    def test_encrypted_case_preserves_case_id(self):
        fixture = types.SimpleNamespace(needs_pass=True, authenticate=lambda _password: 0, close=lambda: None)
        with tempfile.TemporaryDirectory() as temp, patch.object(parser, "fitz", types.SimpleNamespace(open=lambda _p: fixture)):
            root = Path(temp)
            (root/"encrypted.pdf").touch()
            case = root/"case.json"
            case.write_text('{"case_id":"e1","pdf":"encrypted.pdf"}', encoding="utf-8")
            rc = run_case.main(["--case", str(case), "--lang", "eng", "--out", str(root/"out"), "--work", str(root/"work")])
            result = json.loads((root/"out/result.json").read_text(encoding="utf-8"))
        self.assertEqual(rc, 2)
        self.assertEqual(result["case_id"], "e1")
        self.assertIn("encrypted PDF", result["status"]["reason"])

    def test_candidate_cites_selected_block_and_stays_unverified(self):
        doc = {"tables": [], "blocks": [
            {"id": "p1-b01", "page": 1, "bbox": [1, 2, 3, 4], "flags": [], "type": "paragraph",
             "text": "The measured temperature was 315 K under steady operation."},
            {"id": "p1-b02", "page": 1, "bbox": [5, 6, 7, 8], "flags": [], "type": "paragraph",
             "text": "Pressure was measured after startup."},
        ]}
        answer = parser.answer_questions(doc, ["What was the measured temperature?"])[0]
        self.assertIn("315 K", answer["answer"])
        self.assertEqual(answer["answer_block"], "p1-b01")
        self.assertEqual(answer["status"], "candidate")
        self.assertTrue(answer["requires_verification"])
        self.assertTrue(answer["evidence"][0]["contains_answer"])

    def test_missing_geometry_is_not_emitted_as_a_location(self):
        line = parser.Line("有文字但缺少坐标", (0, 0, 100, 20), 10, "ocr:ocr-tool", False, False, 1,
                           meta={"geometry": "unknown", "uncertain": True})
        block = parser.make_block([line], "paragraph", 1).to_dict(include_lines=True)
        self.assertIsNone(block["bbox"])
        self.assertIsNone(block["lines"][0]["bbox"])
        self.assertIn("uncertain", block["flags"])


@unittest.skipIf(parser.fitz is None, "PyMuPDF unavailable")
class PDFIntegrationTests(unittest.TestCase):
    def test_page_subset_and_zero_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root/"source.pdf"
            with parser.fitz.open() as doc:
                for i in range(3):
                    doc.new_page().insert_text((70, 72), f"Page {i+1} contains enough text for native layout parsing.")
                doc.save(pdf)
            (root/"case.json").write_text('{"case_id":"pages","pdf":"source.pdf"}', encoding="utf-8")
            args = ["--case", str(root/"case.json"), "--out", str(root/"out"), "--work", str(root/"work"), "--ocr", "off"]
            for flags, pages, remaining in [(["--pages", "1"], 1, [2, 3]), (["--max-seconds", "0"], 0, [1, 2, 3])]:
                self.assertEqual(run_case.main(args + flags), 0)
                result = json.loads((root/"out/result.json").read_text(encoding="utf-8"))
                self.assertEqual(result["status"]["state"], "partial")
                self.assertEqual(result["status"]["pages_parsed"], pages)
                self.assertEqual(result["uncertainty"]["not_done"], remaining)

    def test_chinese_image_pdf_with_tesseract(self):
        tesseract = shutil.which("tesseract")
        if not tesseract:
            self.skipTest("Tesseract unavailable")
        langs = subprocess.run([tesseract, "--list-langs"], capture_output=True, text=True, check=True, timeout=10)
        if "chi_sim" not in langs.stdout.splitlines():
            self.skipTest("Chinese OCR language pack unavailable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root/"scan.pdf"
            with parser.fitz.open() as native, parser.fitz.open() as scan:
                page = native.new_page()
                phrase = "中国科学文献"
                page.insert_text((50, 92), phrase, fontname="china-s", fontsize=34)
                scan.new_page().insert_image(page.rect, pixmap=page.get_pixmap(dpi=250))
                scan.save(pdf)
            doc = parser.parse_document(str(pdf), str(root/"out"), lang="chi_sim", ocr="tesseract", dpi=250, quiet=True)
            self.assertIn(1, doc["status"]["pages_ocr"])
            self.assertIn(phrase, "".join("".join(b["text"].split()) for b in doc["blocks"]))
            self.assertTrue(any(b["bbox"] for b in doc["blocks"]))


if __name__ == "__main__":
    unittest.main()
