from __future__ import annotations

from pathlib import Path

from ges.errors import MANAGED_CONTENT_MODIFIED, GesError
from ges.io import sha256_bytes
from ges.paths import AGENTS_BEGIN, AGENTS_END

STACK_BODY = """
## AI Engineering Stack

Discovery / requirement grilling:
grill-with-docs
grilling
domain-modeling

Architecture / codebase design:
codebase-design

Work decomposition:
to-tickets

Project principles / constitution:
speckit-constitution

Feature specification:
speckit-specify

Requirement clarification:
speckit-clarify

Technical intent planning:
speckit-plan

Implementation plan methodology:
writing-plans

Execution:
subagent-driven-development

TDD:
test-driven-development

Debug:
systematic-debugging

Review:
requesting-code-review
receiving-code-review

Completion:
verification-before-completion
finishing-a-development-branch

GES manages composition and governance metadata.
GES does not generate Specs, implementation plans or code.
""".strip()


def marker_block() -> str:
    return f"{AGENTS_BEGIN}\n\n{STACK_BODY}\n\n{AGENTS_END}"


def section_hash(text: str) -> str:
    return sha256_bytes(extract_section(text).encode("utf-8"))


def extract_section(text: str) -> str:
    start = text.find(AGENTS_BEGIN)
    end = text.find(AGENTS_END)
    if start < 0 or end < 0 or end < start:
        return ""
    return text[start : end + len(AGENTS_END)]


def count_markers(text: str) -> int:
    return text.count(AGENTS_BEGIN)


def apply_marker(current: str, *, last_applied_hash: str | None) -> str:
    desired = marker_block()
    if AGENTS_BEGIN not in current:
        return current + desired
    existing = extract_section(current)
    if not existing:
        raise GesError(MANAGED_CONTENT_MODIFIED, "AGENTS.md marker pair is malformed")
    existing_hash = sha256_bytes(existing.encode("utf-8"))
    if last_applied_hash and existing_hash != last_applied_hash and existing != desired:
        raise GesError(
            MANAGED_CONTENT_MODIFIED,
            "AGENTS.md GES-managed section was modified by the user",
        )
    return current[: current.find(AGENTS_BEGIN)] + desired + current[current.find(AGENTS_END) + len(AGENTS_END) :]


def remove_marker(current: str) -> str:
    start = current.find(AGENTS_BEGIN)
    end = current.find(AGENTS_END)
    if start < 0 or end < 0:
        return current
    before = current[:start].rstrip("\n")
    after = current[end + len(AGENTS_END) :].lstrip("\n")
    if before and after:
        return before + "\n\n" + after
    return (before + "\n" + after).strip("\n") + ("\n" if before or after else "")


def outside_bytes(text: str) -> bytes:
    start = text.find(AGENTS_BEGIN)
    end = text.find(AGENTS_END)
    if start < 0 or end < 0:
        return text.encode("utf-8")
    return (text[:start] + text[end + len(AGENTS_END) :]).encode("utf-8")


def read_agents(repo: Path) -> str:
    path = repo / "AGENTS.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")
