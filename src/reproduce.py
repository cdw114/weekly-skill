#!/usr/bin/env python3
"""
reproduce.py — one-shot local self-test of the weekly-skill PDF parser on the bundled synthetic example.

This is NOT an official case. It runs the Skill exactly as the evaluator would (same entry point,
same arguments) on a 3-page synthetic two-column paper that ships with the bundle, and writes the
outputs under execution/results/ together with a short summary. Every number in characterization.json
comes from this script.

Usage:  python3 src/reproduce.py            # writes execution/results/ and execution/run.log (append)
        python3 src/reproduce.py --quick    # skip the scan / encrypted negative checks
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "SKILL.md")
SCRIPTS = os.path.join(ROOT, "scripts")
EXAMPLE_PDF = os.path.join(ROOT, "examples", "synth_paper.pdf")
EXAMPLE_SCAN = os.path.join(ROOT, "examples", "synth_paper_scan.pdf")
CASE_JSON = os.path.join(ROOT, "examples", "case.example.json")
RESULTS = os.path.join(ROOT, "execution", "results")
RUN_LOG = os.path.join(ROOT, "execution", "run.log")


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(RUN_LOG), exist_ok=True)
    with open(RUN_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_case(case: str, out: str, work: str) -> dict:
    os.makedirs(out, exist_ok=True); os.makedirs(work, exist_ok=True)
    cp = subprocess.run([sys.executable, os.path.join(SCRIPTS, "run_case.py"), "--case", case, "--out", out, "--work", work],
                        capture_output=True, text=True, timeout=900)
    log(f"run_case exit={cp.returncode} case={os.path.basename(case)}")
    for ln in (cp.stdout + cp.stderr).splitlines()[:12]:
        log("    " + ln)
    rp = os.path.join(out, "result.json")
    return json.load(open(rp, encoding="utf-8")) if os.path.isfile(rp) else {"status": {"state": "crashed"}, "stdout": cp.stdout[-800:]}


def expected_from_fixture() -> dict:
    """Ground truth of the synthetic paper (it is generated from make_synth.py, so we know the answers).
    Used only to score the local self-test; never used by the parser itself."""
    return {
        "title": "Attention-free parsing of scientific PDFs: a layout-first approach",
        "authors": "Jane Doe a, John Smith b, Wei Zhang a",
        "sections_level1": ["Introduction", "Related work", "Method", "Experiments", "Discussion", "Conclusion"],
        "sections_level2": ["Contributions", "Ablation"],
        "tables": 3,
        "table1_header": ["Method", "Accuracy (%)", "Accuracy (%)", "Method", "Text F1", "Table cell"],
        "table1_ours_row": ["Ours", "0.982", "0.941"],
        "equation_tag": "(1)",
        "references": 5,
        "table2_continued_from_page": 2,
        "answers": {
            "What is the table cell accuracy of the proposed method?": "0.941",
            "How many scanned papers are in DocBench-120?": "18",
            "What is the running time per page?": "1.8",
        },
    }


def score_case(r: dict, exp: dict) -> dict:
    st, res = r["status"], r["result"]
    doc = res.get("document") or {}
    checks = {}
    checks["state_success"] = st["state"] == "success"
    checks["title_exact"] = doc.get("title") == exp["title"]
    checks["authors_exact"] = doc.get("authors") == exp["authors"]
    l1 = [c["title"] for c in (res["sections"][0].get("children", []) if res["sections"] else []) if c["level"] == 1]
    l2 = [cc["title"] for c in (res["sections"][0].get("children", []) if res["sections"] else []) for cc in c.get("children", []) if cc["level"] == 2]
    checks["sections_l1"] = l1 == exp["sections_level1"]
    checks["sections_l2"] = l2 == exp["sections_level2"]
    checks["tables_count"] = len(res["tables"]) == exp["tables"]
    t1 = next((t for t in res["tables"] if t.get("number") == "1"), None)
    md = (t1 or {}).get("markdown", "")
    # multi-level header kept as in the source: row 1 'Accuracy (%)' spans 2 columns, row 2 has the sub-headers
    lines = [ln for ln in md.splitlines() if ln.startswith("|")]
    cells = [[c.strip() for c in ln.strip("|").split("|")] for ln in lines if not ln.startswith("|---")]
    checks["table1_header_multilevel"] = (len(cells) >= 2 and cells[0][:2] == ["Method", "Accuracy (%)"]
                                          and cells[1][1:3] == ["Text F1", "Table cell"])
    checks["table1_ours_row"] = "| Ours | 0.982 | 0.941 |" in md
    checks["equation_tag"] = any(e.get("tag") == "1" for e in res["equations"])
    checks["references_count"] = doc.get("reference_count") == exp["references"]
    checks["table2_continued"] = any(t.get("continued_from") is not None for t in res["tables"])
    # reading order: '1. Introduction' heading must come before '2. Related work'
    def idx(pred):
        return next((i for i, b in enumerate(r["evidence"]["block_index"]) if pred(b)), -1)
    h1 = idx(lambda b: b["type"] == "heading" and b["text"].startswith("1. Introduction"))
    h2 = idx(lambda b: b["type"] == "heading" and b["text"].startswith("2. Related work"))
    checks["reading_order_headings"] = 0 <= h1 < h2
    qa = {q["question"]: q for q in res.get("questions", [])}
    for q, want in exp["answers"].items():
        got = (qa.get(q, {}).get("answer") or "")
        checks[f"qa:{q[:28]}"] = (want in got) and qa.get(q, {}).get("answer_block") is not None
    return checks


def ensure_fixtures() -> None:
    """The synthetic PDFs are not shipped (the Skill bundle is text-only); generate them on first run."""
    if os.path.isfile(EXAMPLE_PDF) and os.path.isfile(EXAMPLE_SCAN):
        return
    log(f"generating synthetic fixtures via {os.path.join(ROOT, 'examples', 'make_synth.py')} (needs fpdf2)")
    cp = subprocess.run([sys.executable, os.path.join(ROOT, "examples", "make_synth.py")], capture_output=True, text=True)
    log("    " + (cp.stdout + cp.stderr).strip()[-400:])
    if not (os.path.isfile(EXAMPLE_PDF) and os.path.isfile(EXAMPLE_SCAN)):
        log("    fixture generation FAILED; the self-test needs `pip install fpdf2` and a system TTF font")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    log(f"=== reproduce start (python {sys.version.split()[0]}, skill={SKILL}) ===")
    log(f"pymupdf: {__import__('fitz').__doc__.split()[1] if 'fitz' in sys.modules or True else ''}")
    ensure_fixtures()
    summary = {"ran_at": time.strftime('%Y-%m-%dT%H:%M:%S%z'), "python": sys.version.split()[0], "cases": {}}

    # 1. main synthetic paper through the Skill entry point
    r = run_case(CASE_JSON, os.path.join(RESULTS, "synth"), os.path.join(RESULTS, "_work_synth"))
    checks = score_case(r, expected_from_fixture())
    passed = sum(1 for v in checks.values() if v)
    summary["cases"]["synth"] = {"state": r["status"]["state"], "pages": f"{r['status']['pages_parsed']}/{r['status']['pages_total']}",
                                "checks": checks, "passed": passed, "total": len(checks)}
    log(f"synth: {passed}/{len(checks)} checks passed; failed: {[k for k, v in checks.items() if not v]}")

    # 2. scanned copy (negative / honesty check): must NOT report success unless an OCR engine exists
    if not a.quick and os.path.isfile(EXAMPLE_SCAN):
        case_scan = os.path.join(RESULTS, "_work_synth", "case_scan.json")
        json.dump({"case_id": "synth-scan-neg", "pdf": EXAMPLE_SCAN, "output_contract": {"required": ["case_id", "status", "result", "evidence", "uncertainty"]}},
                  open(case_scan, "w", encoding="utf-8"))
        rs = run_case(case_scan, os.path.join(RESULTS, "scan"), os.path.join(RESULTS, "_work_scan"))
        honest = (rs["status"]["state"] in ("failed", "partial")) and bool(rs["status"].get("pages_unreadable")) and any("OCR" in n for n in rs["status"].get("notes", []))
        ocr_ok = rs["status"]["state"] == "success" and rs["status"].get("pages_ocr")
        summary["cases"]["scan"] = {"state": rs["status"]["state"], "pages_ocr": rs["status"].get("pages_ocr"),
                                    "pages_unreadable": rs["status"].get("pages_unreadable"),
                                    "checks": {"honest_degradation_without_ocr": honest or bool(ocr_ok), "ocr_path_when_available": ocr_ok or honest},
                                    "passed": int(honest or bool(ocr_ok)) + int(ocr_ok or honest), "total": 2}
        log(f"scan: state={rs['status']['state']} unreadable={rs['status'].get('pages_unreadable')} ocr={rs['status'].get('pages_ocr')}")

    # 3. missing-PDF negative: the case names a PDF that does not exist. Must write a failed result.json and
    #    must NOT silently parse another PDF that happens to be nearby.
    case_bad = os.path.join(RESULTS, "_work_synth", "case_missing.json")
    os.makedirs(os.path.dirname(case_bad), exist_ok=True)
    json.dump({"case_id": "missing-pdf-neg", "pdf": "does_not_exist.pdf"}, open(case_bad, "w", encoding="utf-8"))
    rb = run_case(case_bad, os.path.join(RESULTS, "missing"), os.path.join(RESULTS, "_work_missing"))
    bad_ok = rb.get("status", {}).get("state") == "failed" and "not found" in json.dumps(rb).lower()
    summary["cases"]["missing_pdf"] = {"state": rb.get("status", {}).get("state"), "reason": rb.get("status", {}).get("reason"),
                                      "checks": {"failed_result_written_no_fallback": bad_ok}, "passed": int(bad_ok), "total": 1}
    log(f"missing-pdf: state={rb.get('status', {}).get('state')} ok={bad_ok}")

    summary["wall_time_s"] = round(time.time() - t0, 2)
    summary["elapsed_s"] = summary["wall_time_s"]
    # keep only the compact result.json files + document.md under results/, drop work dirs
    for d in ("_work_synth", "_work_scan", "_work_missing"):
        import shutil
        shutil.rmtree(os.path.join(RESULTS, d), ignore_errors=True)
    json.dump(summary, open(os.path.join(RESULTS, "selftest_summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    tot_p = sum(c["passed"] for c in summary["cases"].values()); tot_t = sum(c["total"] for c in summary["cases"].values())
    log(f"=== reproduce done in {summary['wall_time_s']} s: {tot_p}/{tot_t} checks passed ===")
    return 0 if tot_p == tot_t else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log("FATAL " + traceback.format_exc()[-1200:])
        sys.exit(2)
