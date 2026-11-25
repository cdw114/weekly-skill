#!/usr/bin/env python3
"""
run_case.py — Skill entry point for the Playground challenge "阅读01｜文献文档解析".

Reads the platform case (/input/case.json + task.md), parses the actual PDF with the co-located
pdfparse.py, and writes /app/output/result.json (+ document.json / document.md / tables / pages)
satisfying the case's output_contract. Everything the result says is grounded in block ids and page
bounding boxes; anything the parser could not read is reported, never guessed.

Usage (inside the Skill directory):
    python run_case.py                      # defaults: /input/case.json -> /app/output
    python run_case.py --case X.json --out DIR [--work /app/work] [--dpi 200] [--ocr auto|off|...]
    python run_case.py --pdf paper.pdf --out DIR [--task task.md] [--questions q.json]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from output_contract import complete_verified_answers, contract_errors, evidence_errors, project_case_fields, unfinished_questions

REVIEW_REASONS = ("candidate answers need source verification", "output contract requires review")


def _log(msg: str) -> None:
    sys.stdout.write(f"[run_case] {msg}\n")
    sys.stdout.flush()


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8-sig") as f:   # tolerate a BOM (platform-generated files)
        return json.load(f)


def _norm(s: str) -> str:
    return "".join(ch.lower() for ch in s if ch.isalnum())


def find_pdf(case: dict, case_path: str, extra_dirs: List[str]) -> Optional[str]:
    """Use the explicit PDF or the single unambiguous case material."""
    roots = list(dict.fromkeys([os.path.dirname(os.path.abspath(case_path)), *extra_dirs]))
    roots = [Path(root) for root in roots if root]
    explicit = []
    materials = {}
    primary_roles = {"paper", "main", "mainpaper", "primary", "primarypaper", "article", "mainarticle",
                     "maindocument", "sourcedocument", "正文", "论文", "原文"}
    secondary_roles = {"appendix", "attachment", "supplement", "supplementary", "supplementarymaterial",
                       "supplementarymaterials", "supportinginformation", "附件", "补充材料", "附录"}

    def pdf_path(item):
        names = (item,) if isinstance(item, str) else (
            item.get(key) for key in ("local_path", "path", "file", "name", "url")
        ) if isinstance(item, dict) else ()
        return next((name for name in names if isinstance(name, str) and name.lower().endswith(".pdf")), None)

    for key in ("pdf", "pdf_path", "file", "file_path", "input", "input_path", "document", "path", "source"):
        if path := pdf_path(case.get(key)):
            explicit.append(path)
    for key in ("files", "inputs", "materials", "attachments", "artifacts"):
        v = case.get(key)
        if isinstance(v, list):
            for item in v:
                path = pdf_path(item)
                if not path:
                    continue
                role = _norm(str(item.get("role") or "")) if isinstance(item, dict) else ""
                materials.setdefault(path, set()).add(role or ("attachment" if key == "attachments" else ""))

    def locate(path):
        if "://" in path:
            return None
        candidate = Path(path)
        for local in ([candidate] if candidate.is_absolute() else [root/candidate for root in roots]):
            if local.is_file():
                return str(local.resolve())
        return None

    def choose(paths):
        choices = {}
        for path in paths:
            resolved = locate(path)
            choices[resolved or path] = resolved
        if len(choices) > 1:
            raise ValueError(f"multiple candidate PDFs: {', '.join(list(choices)[:8])}. Select the source with --pdf.")
        if choices:
            path, resolved = next(iter(choices.items()))
            if not resolved:
                raise FileNotFoundError(f"input PDF not found: {path}. Supply the local path with --pdf.")
            return resolved
        return None

    if explicit:
        return choose(explicit)
    primary = [path for path, roles in materials.items() if roles & primary_roles]
    ordinary = [path for path, roles in materials.items() if not roles & secondary_roles]
    if primary or ordinary:
        return choose(primary or ordinary)

    attachments = {locate(path) for path in materials}
    hits = sorted({str(path.resolve()) for root in roots if root.is_dir()
                   for path in root.rglob("*") if path.suffix.lower() == ".pdf" and path.is_file()} - attachments)
    if hits:
        return choose(hits)
    if materials:
        raise ValueError("only supplements or attachments were listed. Select the requested source with --pdf.")
    return None


def find_task_md(case_path: str) -> Optional[str]:
    for c in (os.path.join(os.path.dirname(case_path), "task.md"), "/input/task.md"):
        if os.path.isfile(c):
            return c
    return None


def collect_questions(case: dict, task_md: Optional[str], explicit: Optional[str]) -> List[str]:
    qs: List[str] = []
    if explicit:
        if os.path.isfile(explicit):
            v = _read_json(explicit)
            qs.extend(v if isinstance(v, list) else v.get("questions", []))
        else:
            qs.extend(q.strip() for q in explicit.split(";") if q.strip())
    for key in ("questions", "queries", "tasks", "asks"):
        v = case.get(key)
        if isinstance(v, list):
            for it in v:
                if isinstance(it, str):
                    qs.append(it)
                elif isinstance(it, dict):
                    for k2 in ("question", "query", "text", "prompt", "id"):
                        if isinstance(it.get(k2), str):
                            qs.append(it[k2]); break
        elif isinstance(v, dict) and isinstance(v.get("questions"), list):
            qs.extend(q for q in v["questions"] if isinstance(q, str))
    if task_md and os.path.isfile(task_md):
        txt = open(task_md, "r", encoding="utf-8", errors="replace").read()
        # questions listed as numbered / bulleted lines ending with '?' or '？'
        for line in txt.splitlines():
            s = line.strip()
            if (s[:2] in ("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.") or s[:2] in ("- ", "* ")) \
                    and (s.endswith("?") or s.endswith("？")) and 8 < len(s) < 400:
                qs.append(s.lstrip("-*0123456789. ").strip())
    # de-dup, keep order
    seen, out = set(), []
    for q in qs:
        k = _norm(q)
        if k and k not in seen:
            seen.add(k); out.append(q)
    return out


def grounded_evidence(doc: dict) -> List[dict]:
    """One compact evidence record per content block (id, page, bbox, type, short text) so a reader can jump back."""
    ev = []
    for b in doc.get("blocks", []):
        if b.get("type") in ("header", "footer", "page_number"):
            continue
        ev.append({"id": b["id"], "page": b["page"], "type": b["type"], "bbox": b["bbox"],
                   "flags": b.get("flags", []), "text": (b.get("text") or "")[:160]})
    return ev


def case_identifier(case, case_path):
    for field in ("case_id", "id", "name"):
        if case.get(field) is not None:
            return case[field]
    return Path(case_path).stem


def write_result(out_dir, value):
    tmp = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=out_dir, delete=False)
    path = Path(tmp.name)
    try:
        with tmp:
            json.dump(value, tmp, ensure_ascii=False, indent=2)
        os.replace(path, Path(out_dir)/"result.json")
    finally:
        path.unlink(missing_ok=True)


def fallback_result(case, case_path, out_dir, state, reason, started):
    result = {
        "case_id": case_identifier(case, case_path),
        "status": {"state": state, "reason": reason, "pages_total": None, "pages_parsed": 0,
                   "pages_unreadable": [], "pages_ocr": [], "uncertain_blocks": 0,
                   "elapsed_s": round(time.monotonic() - started, 2), "notes": [reason], "limits": []},
        "result": None,
        "evidence": {"block_index": [], "pages": [], "artifacts": {}},
        "uncertainty": {"not_done": ["parse"], "unreadable_pages": [], "notes": [reason]},
        "changes": [],
        "sources": [],
    }
    return project_case_fields(case, result, {}, out_dir)


def build_result(case: dict, case_path: str, parsed: dict, out_dir: str, started: float) -> dict:
    case_id = case_identifier(case, case_path)
    st = parsed["status"]
    questions_out = []
    for a in parsed.get("answers", []):
        questions_out.append({
            "question": a["question"], "answer": a.get("answer"), "status": a["status"],
            "confidence": a.get("confidence"), "answer_block": a.get("answer_block"),
            "requires_verification": a.get("requires_verification", False),
            "evidence": a.get("evidence", []),
            "evidence_text": [e["text"] for e in a.get("evidence", [])][:2],
        })
    pending_answers = [q["question"] for q in questions_out if q["requires_verification"]]
    pending = st["state"] == "success" and bool(pending_answers)
    result: Dict[str, Any] = {
        "case_id": case_id,
        "schema": "pdfparse-case/v1",
        "input": parsed["input"],
        "status": {
            "state": "partial" if pending else st["state"],
            "reason": "candidate answers need source verification" if pending else st["reason"],
            "pages_total": st["pages_total"],
            "pages_parsed": st["pages_parsed"],
            "pages_unreadable": st["pages_unreadable"],
            "pages_ocr": st["pages_ocr"],
            "uncertain_blocks": st["uncertain_blocks"],
            "elapsed_s": round(time.monotonic() - started, 2),
            "notes": list(st["notes"]),
            "limits": ["Candidate answers need verification against the original page",
                       "No LaTeX reconstruction or OCR of regions on a page with a usable text layer",
                       "Layout heuristics target single and double columns"],
        },
        "result": {
            "document": parsed["document"],
            "sections": parsed["sections"],
            "reading_order": [b["id"] for b in parsed["blocks"]],
            "tables": [{"id": t["id"], "number": t.get("number"), "page": t["page"], "caption": t.get("caption"),
                        "rows": t["row_count"], "cols": t["col_count"], "markdown": t.get("markdown"),
                        "continued_from": t.get("continued_from"), "continued_by": t.get("continued_by")} for t in parsed["tables"]],
            "figures": parsed["figures"],
            "equations": parsed["equations"],
            "references": parsed["references"],
            "footnotes": parsed["footnotes"],
            "questions": questions_out,
        },
        "evidence": {
            "block_index": grounded_evidence(parsed),
            "pages": [{"page": p["page"], "width": p["width"], "height": p["height"], "text_source": p["text_source"],
                       "coordinate_space": p["coordinate_space"], "rotation": p["rotation"],
                       "ocr_mean_conf": p.get("ocr_mean_conf"), "columns": (p.get("layout") or {}).get("columns")} for p in parsed["pages"]],
            "artifacts": {
                "document_json": "document.json",
                "document_md": "document.md",
                "tables_dir": "tables" if parsed["tables"] else None,
                "pages_dir": "pages",
            },
        },
        "uncertainty": {
            "unreadable_pages": st["pages_unreadable"],
            "ocr_pages": st["pages_ocr"],
            "low_confidence_blocks": [b["id"] for b in parsed["blocks"] if "uncertain" in (b.get("flags") or [])],
            "notes": st["notes"],
            "not_done": st["not_done"],
            "questions_to_verify": pending_answers,
        },
        "changes": [],
        "sources": [{"type": "file", "path": parsed["input"]["path"], "sha256": parsed["input"].get("sha256"), "pages": st["pages_total"]}],
        "tools": parsed["parser"],
        "runtime": {"python": sys.version.split()[0], "pdfparse": parsed["parser"]["version"]},
    }
    return project_case_fields(case, result, parsed, out_dir)


def _review_summary(result, out_dir):
    status = result["status"]
    uncertainty = result["uncertainty"]
    print(f"{Path(out_dir)/'result.json'} | {status['state']} | pages {status['pages_parsed']}/{status['pages_total']}")
    if status["reason"]:
        print(f"Reason: {status['reason']}")
    for key in ("unreadable_pages", "not_done"):
        if pages := uncertainty.get(key):
            print(f"{key}: {pages[:12]} ({len(pages)} total)")
    for message in uncertainty.get("contract_errors", [])[:8]:
        print(f"Required output: {message[:240]}")
    questions = (result.get("result") or {}).get("questions", [])
    pending = unfinished_questions(questions)
    for q in pending[:8]:
        hits = q.get("evidence", [])
        regions = ", ".join(f"page {hit['page']} {hit['id']}" for hit in hits if hit.get("id"))
        print(f"Check: {q['question'][:200]} | {regions or 'search the source PDF'}")
        if q.get("answer"):
            print(f"  Candidate: {q['answer'][:220]}")
    if len(pending) > 8:
        print(f"See result.questions for all {len(pending)} questions.")


def _validate(case, args):
    out_dir = args.out
    result = _read_json(os.path.join(out_dir, "result.json"))
    if not isinstance(result, dict):
        raise ValueError("result.json must be an object")
    body = result.get("result")
    questions = body.get("questions", []) if isinstance(body, dict) else []
    status = result.get("status")
    if (args.finalize and isinstance(body, dict) and isinstance(status, dict)
        and isinstance(questions, list) and isinstance(result.get("uncertainty"), dict)):
        complete_verified_answers(result, questions)
        result["uncertainty"]["questions_to_verify"] = [q["question"] for q in unfinished_questions(questions)
                                                        if isinstance(q.get("question"), str)]
        result["uncertainty"]["contract_errors"] = contract_errors(case, result, out_dir)
        status["notes"] = [note for note in status.get("notes", [])
                           if not note.startswith("Output contract needs completion: ")]
        if (status.get("state") == "partial" and status.get("reason") in REVIEW_REASONS
            and not unfinished_questions(questions)):
            status["state"] = "success"
    errors = contract_errors(case, result, out_dir) + evidence_errors(case, result, out_dir)
    if isinstance(body, dict) and isinstance(questions, list):
        expected = collect_questions(case, args.task or find_task_md(args.case), args.questions)
        present = {q["question"] for q in questions if isinstance(q, dict) and isinstance(q.get("question"), str)}
        errors.extend(f"result.questions: missing question {q!r}" for q in expected if q not in present)
    if args.finalize and isinstance(status, dict):
        if status.get("state") == "success" and errors:
            status.update(state="partial", reason="output contract requires review")
        elif status.get("state") == "success":
            status["reason"] = None
        write_result(out_dir, result)
    print(json.dumps({"valid": not errors, "state": status.get("state") if isinstance(status, dict) else None,
                      "errors": errors[:20], "error_count": len(errors)}, ensure_ascii=True))
    return int(bool(errors))


def _copy_artifacts(stage, out_dir):
    for name in ("document.json", "document.md", "tables", "pages"):
        src, dst = stage/name, Path(out_dir)/name
        if src.is_file():
            shutil.copy2(src, dst)
        elif name in ("tables", "pages"):
            if dst.is_dir():
                shutil.rmtree(dst)
            if src.is_dir():
                shutil.copytree(src, dst)


def _run_case(args, case, started):
    args.task = args.task or find_task_md(args.case)
    pdf = args.pdf or find_pdf(case, args.case, ["/input", "/app/input", "/data"])
    if not pdf or not os.path.isfile(pdf):
        raise FileNotFoundError(f"input PDF not found (case={args.case}, requested={args.pdf}). Supply it with --pdf.")
    import pdfparse as parser

    if parser.fitz is None:
        requirements = Path(HERE).parent/"requirements.txt"
        raise RuntimeError(f'PyMuPDF is required. Try python3 -m pip install -r "{requirements}" and rerun.')
    lang = args.lang or case.get("ocr_language") or case.get("language")
    if lang in ("zh", "zh-CN", "Chinese", "中文"):
        lang = "chi_sim+eng"
    elif lang in ("en", "en-US", "English"):
        lang = "eng"
    if not lang:
        # Chinese scans have no text to sample. Prefer a bilingual run when those language files are installed.
        with parser.fitz.open(pdf) as sample_pdf:
            sample = "".join(sample_pdf[i].get_text() for i in range(min(3, len(sample_pdf)))) if not sample_pdf.needs_pass else ""
        if len(sample.strip()) < 30:
            lang = "chi_sim+eng"
        else:
            lang = "chi_sim+eng" if any("\u4e00" <= char <= "\u9fff" for char in sample) else "eng"
    questions = collect_questions(case, args.task, args.questions)
    with tempfile.TemporaryDirectory(dir=args.work, prefix="parse-") as temp:
        parsed = parser.parse_document(pdf, temp, lang=lang, ocr=args.ocr, pages=args.pages, dpi=args.dpi,
                                      password=args.password, questions=questions or None, quiet=True,
                                      deadline=started + args.max_seconds)
        _copy_artifacts(Path(temp), args.out)
    result = build_result(case, args.case, parsed, args.out, started)
    write_result(args.out, result)
    _log(f"PDF: {pdf}")
    _review_summary(result, args.out)
    return int(result["status"]["state"] == "failed")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Parse the case PDF into a grounded structured result.")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--pdf", help="Override the PDF path")
    ap.add_argument("--task", help="Path to task.md")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--questions")
    ap.add_argument("--lang", help="OCR language, for example chi_sim+eng")
    ap.add_argument("--ocr", default="auto", choices=["auto", "off", "tesseract", "rapidocr", "paddleocr", "ocr-tool"])
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--pages", help="One-based page range, for example 1-3,5")
    ap.add_argument("--password")
    ap.add_argument("--max-seconds", type=float, default=800.0, help="Case time budget including OCR and layout")
    final = ap.add_mutually_exclusive_group()
    final.add_argument("--validate-result", action="store_true", help="Check the result without modifying it")
    final.add_argument("--finalize", action="store_true", help="Refresh projected answers, then validate the result")
    args = ap.parse_args(argv)
    if not math.isfinite(args.max_seconds) or args.max_seconds < 0:
        ap.error("--max-seconds must be finite and nonnegative")
    start = time.monotonic()
    os.makedirs(args.out, exist_ok=True)
    case: dict = {}
    try:
        if os.path.isfile(args.case):
            loaded = _read_json(args.case)
            if not isinstance(loaded, dict):
                raise ValueError("case.json must be an object")
            case = loaded
        elif args.validate_result or args.finalize or not args.pdf:
            raise FileNotFoundError(f"case file not found: {args.case}")
        if args.validate_result or args.finalize:
            return _validate(case, args)
        os.makedirs(args.work, exist_ok=True)
        write_result(args.out, fallback_result(case, args.case, args.out, "partial", "PDF analysis started", start))
        return _run_case(args, case, start)
    except Exception as exc:
        if args.validate_result or args.finalize:
            print(json.dumps({"valid": False, "errors": [str(exc)]}, ensure_ascii=True))
            return 1
        reason = f"{type(exc).__name__}: {exc}"
        _log(reason)
        write_result(args.out, fallback_result(case, args.case, args.out, "failed", reason, start))
        return 2


if __name__ == "__main__":
    sys.exit(main())
