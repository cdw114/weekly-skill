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
import glob
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
from output_contract import contract_errors, evidence_errors, project_case_fields


def _log(msg: str) -> None:
    sys.stdout.write(f"[run_case] {msg}\n")
    sys.stdout.flush()


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8-sig") as f:   # tolerate a BOM (platform-generated files)
        return json.load(f)


def _norm(s: str) -> str:
    return "".join(ch.lower() for ch in s if ch.isalnum())


def find_pdf(case: dict, case_path: str, extra_dirs: List[str]) -> Optional[str]:
    """Locate the input PDF. If the case names a PDF explicitly and that file is missing, return None
    (never silently fall back to another PDF nearby); otherwise look for any PDF near case.json / under /input."""
    cands: List[str] = []
    for key in ("pdf", "pdf_path", "file", "file_path", "input", "input_path", "document", "path", "source"):
        v = case.get(key)
        if isinstance(v, str) and v.lower().endswith(".pdf"):
            cands.append(v)
        elif isinstance(v, dict):
            for k2 in ("path", "file", "url", "local_path"):
                if isinstance(v.get(k2), str) and v[k2].lower().endswith(".pdf"):
                    cands.append(v[k2])
    for key in ("files", "inputs", "materials", "attachments", "artifacts"):
        v = case.get(key)
        if isinstance(v, list):
            for it in v:
                if isinstance(it, str) and it.lower().endswith(".pdf"):
                    cands.append(it)
                elif isinstance(it, dict):
                    for k2 in ("path", "file", "local_path", "name"):
                        if isinstance(it.get(k2), str) and it[k2].lower().endswith(".pdf"):
                            cands.append(it[k2])
    for c in cands:
        if os.path.isfile(c):
            return c
        if not os.path.isabs(c):
            for d in extra_dirs:
                p2 = os.path.join(d, c)
                if os.path.isfile(p2):
                    return p2
    if cands:
        find_pdf.alternates = []
        find_pdf.missing_explicit = cands   # the case named a PDF that does not exist: do not guess
        return None
    find_pdf.missing_explicit = []  # type: ignore[attr-defined]
    # fall back to any PDF near the case file / under /input
    search = list(extra_dirs) + [os.path.dirname(case_path), "/input", "/app/input", "/data"]
    seen = set()
    hits: List[str] = []
    for d in search:
        if d and os.path.isdir(d) and d not in seen:
            seen.add(d)
            hits.extend(sorted(glob.glob(os.path.join(d, "**", "*.pdf"), recursive=True)))
    hits = list(dict.fromkeys(hits))
    if hits:
        # prefer a name that matches the case id / title; among the rest prefer a PDF that actually has a text layer
        # (a scanned supplement is usually larger than the paper, so size is a poor signal), then more pages
        key = _norm(str(case.get("case_id") or case.get("id") or "") + " " + str(case.get("title") or ""))

        def probe(h: str):
            try:
                import fitz
                d = fitz.open(h)
                n = len(d)
                chars = sum(len(d[i].get_text()) for i in range(min(3, n)))
                d.close()
                return n, chars
            except Exception:
                return 0, 0

        def rank(h: str):
            name = _norm(os.path.basename(h))
            name_hit = 0 if key and (name in key or key[:12] in name) else 1
            n, chars = probe(h)
            return (name_hit, 0 if chars > 100 else 1, -n)
        hits.sort(key=rank)
        find_pdf.alternates = hits[1:]
        return hits[0]
    find_pdf.alternates = []
    return None
find_pdf.alternates = []  # type: ignore[attr-defined]


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


def build_result(case: dict, case_path: str, parsed: dict, out_dir: str,
                 started: float, extra: Dict[str, Any]) -> dict:
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
    result.update(extra)
    return project_case_fields(case, result, parsed, out_dir)


def _validate(case, out_dir):
    result = _read_json(os.path.join(out_dir, "result.json"))
    if not isinstance(result, dict):
        raise ValueError("result.json must be an object")
    errors = contract_errors(case, result, out_dir) + evidence_errors(case, result)
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=True))
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
    pdf = args.pdf or find_pdf(case, args.case, [os.path.dirname(args.case), "/input", "/app/input"])
    if not pdf or not os.path.isfile(pdf):
        missing = [args.pdf] if args.pdf else getattr(find_pdf, "missing_explicit", [])
        raise FileNotFoundError(f"input PDF not found (case={args.case}, requested={missing})")
    _log(f"PDF: {pdf}")
    import pdfparse as parser

    if parser.fitz is None:
        raise RuntimeError("PyMuPDF is required. Install it with python -m pip install -r requirements.txt.")
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
    extra = {}
    alts = getattr(find_pdf, "alternates", []) if not args.pdf else []
    if alts:
        extra["input_candidates"] = {"chosen": pdf, "alternates": alts}
        parsed["status"]["notes"].append(f"{len(alts)} other PDF(s) were not parsed. Verify the selected source or re-run with --pdf.")
    result = build_result(case, args.case, parsed, args.out, started, extra)
    write_result(args.out, result)
    st = result["status"]
    _log(f"state={st['state']} pages={st['pages_parsed']}/{st['pages_total']} unreadable={st['pages_unreadable']}")
    return int(st["state"] == "failed")


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
    ap.add_argument("--validate-result", action="store_true", help="Check the completed result against the case contract")
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
        elif args.validate_result or not args.pdf:
            raise FileNotFoundError(f"case file not found: {args.case}")
        if args.validate_result:
            return _validate(case, args.out)
        os.makedirs(args.work, exist_ok=True)
        write_result(args.out, fallback_result(case, args.case, args.out, "partial", "PDF analysis started", start))
        return _run_case(args, case, start)
    except Exception as exc:
        if args.validate_result:
            print(json.dumps({"valid": False, "errors": [str(exc)]}, ensure_ascii=True))
            return 1
        reason = f"{type(exc).__name__}: {exc}"
        _log(reason)
        write_result(args.out, fallback_result(case, args.case, args.out, "failed", reason, start))
        return 2


if __name__ == "__main__":
    sys.exit(main())
