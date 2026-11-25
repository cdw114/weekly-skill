"""Project parser results into the case contract and check the final deliverables."""
from __future__ import annotations

from pathlib import Path


BASE_FIELDS = {"case_id", "status", "result", "evidence", "uncertainty"}
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


def _artifact_exists(value, out_dir):
    try:
        root = Path(out_dir).resolve()
        path = (root / value).resolve()
        return path.is_relative_to(root) and path.is_file()
    except (OSError, ValueError):
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
    issues = contract_errors(case, result, out_dir)
    notes["contract_errors"] = issues
    if issues:
        result["status"]["notes"].append("Output contract needs completion: " + "; ".join(issues))
        if result["status"]["state"] == "success":
            result["status"]["state"] = "partial"
            result["status"]["reason"] = "output contract requires review"
    return result


def evidence_errors(case, result):
    expected = case.get("case_id", case.get("id"))
    errors = []
    if expected is not None and result.get("case_id") != expected:
        errors.append("case_id differs from the input")
    status = result.get("status")
    if not isinstance(status, dict) or status.get("state") not in ("success", "partial", "failed", "uncertain", "refused"):
        errors.append("status.state is missing or invalid")
        return errors
    body = result.get("result") or {}
    evidence = result.get("evidence") or {}
    if not isinstance(body, dict) or not isinstance(evidence, dict):
        return errors
    anchors = {b["id"]: b for b in evidence.get("block_index", []) if isinstance(b, dict) and isinstance(b.get("id"), str)}
    questions = body.get("questions") or []
    for q in questions:
        if not isinstance(q, dict) or q.get("status") not in ("found", "verified"):
            continue
        anchor = q.get("answer_block")
        candidates = q.get("evidence", [])
        source = anchors.get(anchor)
        if (q.get("requires_verification") is True or not q.get("answer") or not source or not any(
            isinstance(hit, dict) and hit.get("id") == anchor and hit.get("page") == source.get("page")
            and hit.get("bbox") == source.get("bbox") and bool(hit.get("bbox")) for hit in candidates
        )):
            errors.append(f"Question {q.get('question', '')!r}: confirm the answer and its source block")
    if status["state"] == "success":
        if (result.get("uncertainty") or {}).get("not_done"):
            errors.append("success cannot have unfinished pages")
        if any(isinstance(q, dict) and q.get("requires_verification") for q in questions):
            errors.append("Candidate answers still require source checks")
    return errors
