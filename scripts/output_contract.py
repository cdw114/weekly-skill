"""Project parser results into the case contract and check the final deliverables."""
from __future__ import annotations

import math
from pathlib import Path


BASE_FIELDS = {"case_id", "status", "result", "evidence", "uncertainty"}
ANSWER_ALIASES = ("answers", "qa")
_METADATA = {"$schema", "$id", "$defs", "definitions", "type", "properties", "required",
             "fields", "description", "title", "additionalProperties", "artifacts"}
_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float),
          "boolean": bool, "null": type(None)}
_FILE_TYPES = {"file", "path", "file-path", "filepath", "artifact"}


def _spec(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        name = value.lower()
        if name in _TYPES or name in _FILE_TYPES:
            return {"type": name}
        return {"description": value}
    return {}


def field_specs(case):
    """Accept a name list, field descriptors, or an object schema."""
    contract = case.get("output_contract")
    specs = {name: {} for name in sorted(BASE_FIELDS)}
    if isinstance(contract, list):
        entries = contract
    elif isinstance(contract, dict):
        for name, schema in contract.items():
            if name not in _METADATA:
                specs[name] = _spec(schema)
        fields = contract.get("fields", [])
        properties = contract.get("properties")
        if isinstance(properties, dict):
            required = contract.get("required")
            for name, spec in properties.items():
                if name in BASE_FIELDS or not isinstance(required, list) or name in required:
                    specs[name] = _spec(spec)
        if isinstance(fields, dict):
            specs.update((name, _spec(schema)) for name, schema in fields.items())
        entries = list(fields) if isinstance(fields, list) else []
        required = contract.get("required", [])
        if isinstance(required, list):
            entries += required
    else:
        entries = []
    for entry in entries:
        if isinstance(entry, str):
            specs.setdefault(entry, {})
        elif isinstance(entry, dict):
            name = entry.get("name")
            if isinstance(name, str) and entry.get("required", True):
                specs[name] = {**specs.get(name, {}), **entry}
    return specs


def _is_file(spec):
    return any(isinstance(spec.get(key), str) and spec[key] in _FILE_TYPES for key in ("type", "format"))


def _matches_type(value, name):
    if name in _FILE_TYPES:
        return isinstance(value, str)
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    return name not in _TYPES or isinstance(value, _TYPES[name])


def _field_errors(value, spec, field, out_dir):
    errors = []
    types = spec.get("type")
    if isinstance(types, str):
        types = [types]
    if isinstance(types, list) and types and not any(_matches_type(value, t) for t in types if isinstance(t, str)):
        return [f"{field}: expected {' or '.join(map(str, types))}"]
    if isinstance(spec.get("enum"), list) and value not in spec["enum"]:
        errors.append(f"{field}: value outside the permitted choices")
    if "const" in spec and value != spec["const"]:
        errors.append(f"{field}: value differs from the required constant")
    if _is_file(spec) and value is not None:
        if not isinstance(value, str) or not _artifact_exists(value, out_dir):
            errors.append(f"{field}: expected an existing file under the output directory")
    if isinstance(value, dict):
        fields = spec.get("properties", {})
        required = spec.get("required", [])
        if isinstance(required, list):
            errors.extend(f"{field}.{key}: missing" for key in required if isinstance(key, str) and key not in value)
        if isinstance(fields, dict):
            for key, sub in fields.items():
                if key in value:
                    errors.extend(_field_errors(value[key], _spec(sub), f"{field}.{key}", out_dir))
    if isinstance(value, list) and isinstance(spec.get("items"), dict):
        for i, item in enumerate(value):
            errors.extend(_field_errors(item, spec["items"], f"{field}[{i}]", out_dir))
    if isinstance(value, (str, list)):
        unit = "Length" if isinstance(value, str) else "Items"
        for key, violates in ((f"min{unit}", lambda n: len(value) < n), (f"max{unit}", lambda n: len(value) > n)):
            if isinstance(spec.get(key), int) and violates(spec[key]):
                errors.append(f"{field}: violates {key}={spec[key]}")
    return errors


def _artifact_exists(value, out_dir, directory=False):
    try:
        root = Path(out_dir).resolve()
        path = (root / value).resolve()
        return path != root and path.is_relative_to(root) and (path.is_dir() if directory else path.is_file())
    except (OSError, ValueError, RuntimeError):
        return False


def contract_errors(case, result, out_dir):
    errors = []
    for name, spec in field_specs(case).items():
        if name not in result:
            errors.append(f"{name}: missing")
        elif result[name] is None and "type" not in spec and name not in BASE_FIELDS:
            errors.append(f"{name}: unresolved")
        else:
            errors.extend(_field_errors(result[name], spec, name, out_dir))
    contract = case.get("output_contract")
    if isinstance(contract, dict) and isinstance(contract.get("artifacts"), list):
        for item in contract["artifacts"]:
            path = item.get("path") if isinstance(item, dict) and item.get("required", True) else item
            if isinstance(path, str) and not _artifact_exists(path, out_dir):
                errors.append(f"artifact {path!r}: missing or outside the output directory")
    return errors


def project_case_fields(case, result, parsed, out_dir):
    """Expose supported fields using real parser data. Flag fields that require Agent work."""
    specs = field_specs(case)
    body = result.get("result") or {}
    doc = body.get("document") or {}
    sections = body.get("sections", [])
    refs = body.get("references", [])
    qa = body.get("questions", [])
    notes = result["uncertainty"]
    aliases = {
        **doc,
        "reading_order": body.get("reading_order", []),
        "outline": sections, "sections": sections, "structure": sections,
        "metadata": doc, "document": doc, "tables": body.get("tables", []),
        "figures": body.get("figures", []), "equations": body.get("equations", []),
        "footnotes": body.get("footnotes", []), "citations": refs, "references": refs,
        "answers": qa, "qa": qa, "pages": result.get("evidence", {}).get("pages", []),
        "blocks": parsed.get("blocks", []),
    }
    markdown = Path(out_dir)/"document.md"
    if markdown.is_file() and body and any(name in specs and not _is_file(specs[name]) for name in ("markdown", "content_markdown")):
        content = markdown.read_text(encoding="utf-8")
        aliases.update(markdown=content, content_markdown=content)
    known_files = {"document": "document.json", "markdown": "document.md"}
    for name, spec in specs.items():
        if name in result or not body:
            continue
        value = known_files.get(name) if _is_file(spec) else aliases.get(name)
        if value is not None and not _field_errors(value, spec, name, out_dir):
            result[name] = value
            if name in ANSWER_ALIASES and value is qa:
                notes.setdefault("projected_answer_fields", []).append(name)
    issues = contract_errors(case, result, out_dir)
    notes["contract_errors"] = issues
    if issues:
        result["status"]["notes"].append("Output contract needs completion: " + "; ".join(issues))
        if result["status"]["state"] == "success":
            result["status"]["state"] = "partial"
            result["status"]["reason"] = "output contract requires review"
    return result


def unfinished_questions(questions):
    return [q for q in questions if isinstance(q, dict) and (
        q.get("requires_verification") or q.get("status") not in ("found", "verified", "not_found")
    )]


def _valid_box(box):
    return (isinstance(box, list) and len(box) == 4
            and all(type(v) in (int, float) and math.isfinite(v) for v in box)
            and box[0] < box[2] and box[1] < box[3])


def complete_verified_answers(result, questions):
    """Resolve a reviewer-selected block to a verifiable source and synchronize projected answers."""
    evidence = result.get("evidence")
    blocks = evidence.get("block_index", []) if isinstance(evidence, dict) else []
    anchors = {b["id"]: b for b in blocks if isinstance(b, dict) and isinstance(b.get("id"), str)}
    for q in questions:
        if not isinstance(q, dict) or q.get("status") != "verified":
            continue
        anchor = q.get("answer_block")
        source = anchors.get(anchor) if isinstance(anchor, str) else None
        if not source or not _valid_box(source.get("bbox")) or not str(q.get("answer") or "").strip():
            continue
        if q.get("requires_verification"):
            result.setdefault("changes", []).append({"what": f"Verified answer: {q.get('question', '')}",
                                                     "why": "Reviewer selected an original PDF source block",
                                                     "source_blocks": [anchor], "file": "result.json"})
        q.update(requires_verification=False, confidence="high", evidence=[{**source, "contains_answer": True}],
                 evidence_text=[source.get("text", "")])
    for name in result["uncertainty"].get("projected_answer_fields", []):
        if name in ANSWER_ALIASES:
            result[name] = questions


def evidence_errors(case, result, out_dir):
    expected = next((case[key] for key in ("case_id", "id", "name") if case.get(key) is not None), None)
    errors = []
    if expected is not None and result.get("case_id") != expected:
        errors.append("case_id differs from the input")
    status = result.get("status")
    if not isinstance(status, dict) or status.get("state") not in ("success", "partial", "failed", "uncertain", "refused"):
        errors.append("status.state is missing or invalid")
        return errors
    body = result.get("result")
    evidence = result.get("evidence")
    uncertainty = result.get("uncertainty")
    if not isinstance(evidence, dict) or not isinstance(uncertainty, dict):
        return errors + ["evidence and uncertainty must be objects"]
    if body is None and status["state"] in ("failed", "partial", "refused"):
        body = {}
    if not isinstance(body, dict):
        return errors + ["result must be an object for a completed parse"]
    artifacts = evidence.get("artifacts", {})
    if not isinstance(artifacts, dict):
        return errors + ["evidence.artifacts must be an object"]
    for name, path in artifacts.items():
        if path is not None and (not isinstance(path, str) or not _artifact_exists(path, out_dir, name.endswith("_dir"))):
            errors.append(f"evidence.artifacts.{name}: missing or outside the output directory ({path!r})")
    pages_dir = artifacts.get("pages_dir")
    pages = evidence.get("pages", [])
    if isinstance(pages_dir, str) and isinstance(pages, list) and _artifact_exists(pages_dir, out_dir, directory=True):
        for page in pages:
            number = page.get("page") if isinstance(page, dict) else None
            if type(number) is int and not _artifact_exists(str(Path(pages_dir)/f"page_{number:03d}.txt"), out_dir):
                errors.append(f"evidence.pages: missing page_{number:03d}.txt in {pages_dir}")
    blocks = evidence.get("block_index", [])
    questions = body.get("questions", [])
    if not isinstance(blocks, list) or not isinstance(questions, list):
        return errors + ["evidence.block_index and result.questions must be arrays"]
    anchors = {b["id"]: b for b in blocks if isinstance(b, dict) and isinstance(b.get("id"), str)}
    specs = field_specs(case)
    for name in ANSWER_ALIASES:
        alias = result.get(name)
        if isinstance(alias, list) and (name in uncertainty.get("projected_answer_fields", [])
                                       or not _field_errors(questions, specs.get(name, {}), name, out_dir)):
            if alias != questions and (name in specs or name in uncertainty.get("projected_answer_fields", [])):
                errors.append(f"{name}: differs from result.questions (use --finalize to refresh a projected answer list)")
    for q in questions:
        if not isinstance(q, dict) or not isinstance(q.get("question"), str):
            errors.append("result.questions: each answer needs its question text")
            continue
        if q.get("status") not in ("found", "verified"):
            continue
        anchor = q.get("answer_block")
        candidates = q.get("evidence", [])
        source = anchors.get(anchor) if isinstance(anchor, str) else None
        if (q.get("requires_verification") or not str(q.get("answer") or "").strip() or not source
            or not isinstance(candidates, list) or not any(
            isinstance(hit, dict) and hit.get("id") == anchor and hit.get("page") == source.get("page")
            and type(hit.get("page")) is int and hit["page"] > 0
            and hit.get("bbox") == source.get("bbox") and _valid_box(hit["bbox"]) for hit in candidates
        )):
            errors.append(f"Question {q.get('question', '')!r}: confirm the answer and its source block")
    if status["state"] == "success":
        total, parsed = status.get("pages_total"), status.get("pages_parsed")
        if type(total) is not int or total < 1 or type(parsed) is not int or parsed != total:
            errors.append("status: success requires pages_parsed == pages_total > 0")
        elif "pages" in evidence:
            numbers = [p.get("page") for p in pages if isinstance(p, dict)] if isinstance(pages, list) else []
            if len(numbers) != total or any(type(n) is not int for n in numbers) or sorted(numbers) != list(range(1, total + 1)):
                errors.append("evidence.pages: success requires one evidence record per input page")
        if uncertainty.get("not_done") or status.get("pages_unreadable") or uncertainty.get("unreadable_pages"):
            errors.append("status: success cannot have unreadable or unfinished pages")
        if unfinished_questions(questions):
            errors.append("result.questions: unfinished answers still need source checks")
    return errors
