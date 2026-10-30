from __future__ import annotations

from typing import Any


def reason(code: str, scope: str, expected: Any, actual: Any, source: str, remediation_hint: str) -> dict[str, Any]:
    return {
        "code": code,
        "scope": scope,
        "expected": expected,
        "actual": actual,
        "source": source,
        "remediation_hint": remediation_hint,
    }


def sort_reasons(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (item["code"], item["scope"], str(item["expected"]), str(item["actual"])))
