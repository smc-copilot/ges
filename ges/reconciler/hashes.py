from __future__ import annotations

from pathlib import Path
from typing import Any

from ges.harness_adapters.agents_md import section_hash
from ges.io import sha256_bytes, sha256_file
from ges.source_adapters.base import ProjectedFile


def file_hash(content: bytes) -> str:
    return sha256_bytes(content)


def hash_record(item: ProjectedFile) -> dict[str, Any]:
    identity = desired_identity(item)
    return {
        "generated": identity,
        "last_applied": identity,
        "upstream_sha": item.source_sha,
        "kind": item.kind,
        "capability": item.capability,
        "ownership_type": item.ownership_type,
    }


def artifact_index(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in receipt.get("managed_artifacts") or []:
        path = item.get("path")
        if path:
            out[path] = item
    if out:
        return out
    for rel, meta in (receipt.get("content_hashes") or {}).items():
        out[rel] = {
            "path": rel,
            "ownership_type": "FILE",
            "last_applied_hash": meta.get("last_applied"),
            "producer": meta.get("capability"),
        }
    for section in receipt.get("managed_sections") or []:
        path = section.get("path")
        if path:
            out[path] = {
                "path": path,
                "ownership_type": "SECTION",
                "selector": section.get("id"),
                "last_applied_hash": section.get("last_applied"),
            }
    return out


def desired_identity(item: ProjectedFile) -> str:
    if item.ownership_type == "SECTION":
        return section_hash(item.content.decode("utf-8"))
    if item.ownership_type == "ENTRY" and item.selector:
        text = item.content.decode("utf-8")
        return sha256_bytes(item.selector.encode("utf-8") + b"\0" + text.encode("utf-8"))
    return sha256_bytes(item.content)


def current_identity(repo: Path, rel: str, item: ProjectedFile | None = None, *, ownership_type: str = "FILE") -> str | None:
    path = repo / rel
    if not path.is_file():
        return None
    kind = item.ownership_type if item is not None else ownership_type
    if kind == "SECTION":
        return section_hash(path.read_text(encoding="utf-8"))
    if kind == "ENTRY" and item is not None and item.selector:
        text = path.read_text(encoding="utf-8")
        return sha256_bytes(item.selector.encode("utf-8") + b"\0" + text.encode("utf-8"))
    return sha256_file(path)
