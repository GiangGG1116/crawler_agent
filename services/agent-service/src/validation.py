"""Validation gates for LLM-generated crawler code and records."""


import ast
import json
from typing import Any

_BANNED_IMPORT_ROOTS = {
    "builtins",
    "ctypes",
    "importlib",
    "multiprocessing",
    "os",
    "pathlib",
    "playwright",
    "resource",
    "shutil",
    "socket",
    "subprocess",
    "sys",
    "tempfile",
}
_BANNED_CALLS = {
    "__import__",
    "breakpoint",
    "compile",
    "delattr",
    "dir",
    "eval",
    "exec",
    "getattr",
    "globals",
    "help",
    "input",
    "locals",
    "open",
    "setattr",
    "vars",
}


def validate_generated_code(code: str) -> list[str]:
    """Return policy violations found in generated crawler code."""
    if not code.strip():
        return ["Generated code is empty"]

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"Generated code has invalid syntax: {exc.msg}"]

    violations: list[str] = []
    has_scrape = False

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "scrape":
            has_scrape = True
        if not isinstance(
            node,
            (
                ast.Import,
                ast.ImportFrom,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.Assign,
                ast.AnnAssign,
            ),
        ):
            if not (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                violations.append(f"Top-level statement is not allowed: {type(node).__name__}")
        if isinstance(node, ast.Expr) and not (
            isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        ):
            violations.append("Top-level executable expressions are not allowed")
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)):
            violations.append("Top-level executable control flow is not allowed")
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if value is not None:
                try:
                    ast.literal_eval(value)
                except (ValueError, TypeError):
                    violations.append("Top-level assignments must contain literal values only")

    if not has_scrape:
        violations.append("Generated code must define a scrape function")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] in _BANNED_IMPORT_ROOTS:
                    violations.append(f"Import is not allowed: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root in _BANNED_IMPORT_ROOTS:
                violations.append(f"Import is not allowed: {node.module}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _BANNED_CALLS:
            violations.append(f"Call is not allowed: {node.func.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            violations.append(f"Dunder attribute access is not allowed: {node.attr}")

    return list(dict.fromkeys(violations))


def validate_records(
    records: Any,
    required_fields: list[str],
    *,
    max_records: int,
    min_field_completeness: float,
) -> dict[str, Any]:
    """Validate, deduplicate, and cap records returned by generated code."""
    if not isinstance(records, list):
        return {
            "status": "error",
            "error": "Crawler output must be a list",
            "records": [],
        }

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    rejected = 0

    for record in records[:max_records]:
        if not isinstance(record, dict) or not record:
            rejected += 1
            continue
        fingerprint = json.dumps(record, sort_keys=True, default=str)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        normalized.append(record)

    if not normalized:
        return {
            "status": "error",
            "error": "Crawler returned no valid records",
            "records": [],
            "metrics": {"rejected_records": rejected},
        }

    total_checks = len(normalized) * len(required_fields)
    present = sum(
        1
        for record in normalized
        for field in required_fields
        if record.get(field) is not None and record.get(field) != ""
    )
    completeness = present / total_checks if total_checks else 1.0

    metrics = {
        "record_count": len(normalized),
        "rejected_records": rejected,
        "required_field_completeness": round(completeness, 4),
    }
    if completeness < min_field_completeness:
        return {
            "status": "error",
            "error": (
                f"Required field completeness {completeness:.1%} is below the {min_field_completeness:.1%} threshold"
            ),
            "records": [],
            "metrics": metrics,
        }

    return {"status": "success", "records": normalized, "metrics": metrics}
