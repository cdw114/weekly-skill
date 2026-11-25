"""Regression tests for case outputs, deadlines, OCR fallback, and source-linked answers."""
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from dataclasses import asdict
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
        result = {"case_id": "demo", "status": {"state": "success", "pages_total": 2, "pages_parsed": 2}, "uncertainty": {},
                  "evidence": {"block_index": [hit]},
                  "result": {"questions": [{"question": "How many?", "answer": "3", "status": "verified",
                                             "answer_block": hit["id"], "evidence": [{**hit, "page": 1}]}]}}
        self.assertTrue(contract.evidence_errors({"case_id": "demo"}, result, "."))
        result["result"]["questions"][0]["evidence"] = [hit]
        self.assertFalse(contract.evidence_errors({"case_id": "demo"}, result, "."))

    def test_cli_rejects_partial_success_missing_files_and_stale_answers(self):
        hit = {"id": "p1-b01", "page": 1, "bbox": [10, 20, 30, 40]}
        verified = {"question": "What was recorded?", "answer": "315 K", "status": "verified",
                    "answer_block": hit["id"], "evidence": [hit]}
        case = {"case_id": "review", "output_contract": ["answers"]}
        result = {"case_id": "review", "status": {"state": "success", "pages_total": 3, "pages_parsed": 1,
                                                 "pages_unreadable": [1]},
                  "uncertainty": {}, "result": {"questions": [verified]},
                  "answers": [{**verified, "status": "candidate"}],
                  "evidence": {"block_index": [hit], "artifacts": {"document_md": "missing.md"}}}
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(StringIO()) as output:
            root = Path(temp)
            case_path = root/"case.json"
            case_path.write_text(json.dumps(case), encoding="utf-8")
            run_case.write_result(root, result)
            args = ["--case", str(case_path), "--out", temp, "--validate-result"]
            self.assertEqual(run_case.main(args), 1)
            errors = json.loads(output.getvalue())["errors"]
        for expected in ("pages_parsed", "unreadable", "missing.md", "differs from result.questions"):
            self.assertTrue(any(expected in error for error in errors), errors)

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
    def test_native_worker_logs_do_not_interfere_with_ocr_results(self):
        line = parser.Line("扫描文字", (10, 20, 200, 50), 12, "ocr:tesseract", False, False, 0)

        def worker(*args, **kwargs):
            request = json.loads(kwargs["input"])
            Path(request["output"]).write_text(json.dumps([asdict(line)]), encoding="utf-8")
            return subprocess.CompletedProcess(args[0], 0, "Native library progress\n", "")

        with patch.object(subprocess, "run", side_effect=worker):
            result = parser._run_ocr_attempt("scan.pdf", 1, "tesseract", "chi_sim", 200, None, 5)
        self.assertEqual(result[0].text, line.text)
        self.assertEqual(tuple(result[0].bbox), line.bbox)

    def test_primary_pdf_overrides_earlier_supplement_and_missing_primary_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/"a-supplement.pdf").touch()
            paper = root/"z-main-paper.pdf"
            paper.touch()
            materials = [{"path": "a-supplement.pdf", "role": "supplement"},
                         {"path": "z-main-paper.pdf", "role": "paper"}]
            self.assertEqual(run_case.find_pdf({"materials": materials}, str(root/"case.json"), []), str(paper.resolve()))
            with self.assertRaisesRegex(ValueError, "multiple candidate PDFs"):
                run_case.find_pdf({}, str(root/"case.json"), [])
            paper.unlink()
            with self.assertRaisesRegex(FileNotFoundError, "z-main-paper.pdf"):
                run_case.find_pdf({"materials": materials}, str(root/"case.json"), [])

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
    def test_rendered_scan_can_be_encoded_without_pillow(self):
        with parser.fitz.open() as doc, patch.dict(sys.modules, {"PIL": None}):
            page = doc.new_page(width=200, height=100)
            image = parser.render_page(page, 72)
            self.assertIsInstance(image, parser.fitz.Pixmap)
            encoded = parser._img_to_png_bytes(image)
            decoded = parser.fitz.Pixmap(encoded)
            self.assertEqual((decoded.width, decoded.height), (200, 100))

    def test_ocr_uses_display_rotation_and_returns_unrotated_coordinates(self):
        fitz = parser.fitz
        with fitz.open() as doc:
            page = doc.new_page(width=440, height=700)
            page.set_rotation(270)
            native_box = fitz.Rect(40, 570, 200, 600)
            view_box = native_box * page.rotation_matrix
            line = parser.Line("315 K", tuple(view_box), 12, "ocr:tesseract", False, False, 0,
                               meta={"ocr_conf": 0.95})
            with patch.object(parser, "_run_tesseract_cli", return_value=[line]) as recognize, \
                patch.object(shutil, "which", return_value=sys.executable):
                lines, _ = parser.ocr_page(page, "tesseract", "eng", 72)
            self.assertEqual(recognize.call_args.args[0].width, 700)
            self.assertEqual(lines[0].bbox, tuple(native_box))

    def test_short_page_and_rotated_table_survive_full_run_and_finalize(self):
        fitz = parser.fitz
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(StringIO()) as output:
            root = Path(temp)
            pdf = root/"paper.pdf"
            with fitz.open() as doc:
                doc.new_page().insert_text((72, 92), "Materials Lab")
                for rotation in (90, 270):
                    page = doc.new_page(width=440, height=700)
                    page.insert_text((65, 605), "The measured temperature was 315 K under steady operation.")
                    for y in (480, 510, 540):
                        page.draw_line((50, y), (310, y))
                    for x in (50, 160, 310):
                        page.draw_line((x, 480), (x, 540))
                    for point, cell in [((60, 500), "Run"), ((175, 500), "Temperature"),
                                        ((60, 530), "Baseline"), ((175, 530), "315 K")]:
                        page.insert_text(point, cell)
                    page.set_rotation(rotation)
                doc.save(pdf)
            case = {"case_id": "rotated", "materials": [{"path": "paper.pdf", "role": "paper"}],
                    "questions": ["What was the measured temperature?"], "output_contract": ["answers"]}
            case_path = root/"case.json"
            case_path.write_text(json.dumps(case), encoding="utf-8")
            args = ["--case", str(case_path), "--out", str(root/"out"), "--work", str(root/"work"), "--ocr", "off"]
            self.assertEqual(run_case.main(args), 0)
            result = run_case._read_json(root/"out/result.json")
            self.assertEqual(result["status"]["pages_unreadable"], [])
            self.assertEqual(result["status"]["pages_parsed"], 3)
            self.assertEqual([p["rotation"] for p in result["evidence"]["pages"]], [0, 90, 270])
            self.assertTrue(any("Materials Lab" in b["text"] for b in result["evidence"]["block_index"]))
            self.assertEqual([t["page"] for t in result["result"]["tables"]], [2, 3])
            with fitz.open(pdf) as doc:
                for n in (2, 3):
                    block = next(b for b in result["evidence"]["block_index"]
                                 if b["page"] == n and "The measured temperature" in b["text"])
                    bbox = fitz.Rect(block["bbox"])
                    self.assertIn("315 K", doc[n - 1].get_textbox(bbox + (-0.1, -0.1, 0.1, 0.1)))
            answer = result["result"]["questions"][0]
            answer.update(answer="315 K under steady operation", answer_block=block["id"], status="verified")
            run_case.write_result(root/"out", result)
            self.assertEqual(run_case.main(args + ["--validate-result"]), 1)
            self.assertEqual(run_case.main(args + ["--finalize"]), 0)
            self.assertEqual(run_case.main(args + ["--finalize"]), 0)
            updated = run_case._read_json(root/"out/result.json")
            self.assertEqual(updated["status"]["state"], "success")
            self.assertEqual(updated["answers"], updated["result"]["questions"])
            self.assertEqual(updated["answers"][0]["evidence"][0]["page"], 3)
            self.assertEqual(len(updated["changes"]), 1)
            self.assertIn("Check: What was the measured temperature?", output.getvalue())

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
            self.assertIn(1, doc["status"]["pages_ocr"], doc["status"]["notes"])
            self.assertIn(phrase, "".join("".join(b["text"].split()) for b in doc["blocks"]), doc["status"]["notes"])
            self.assertTrue(any(b["bbox"] for b in doc["blocks"]))


if __name__ == "__main__":
    unittest.main()
