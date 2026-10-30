from __future__ import annotations

from pathlib import Path
from typing import Any

from ges.governance.artifacts import artifact_status
from ges.governance.evidence import collect_evidence
from ges.governance.storage import load_work
from ges.reconciler.state import validate_payload
from ges.stagelog import TRACE_BUILD, emit

REQUIRED_EDGES = (
    "WORK_HAS_SPEC",
    "WORK_HAS_PLAN",
    "PR_DECLARES_WORK",
    "PR_HEAD_IS_COMMIT",
    "CHECK_VERIFIES_COMMIT",
    "REVIEW_GOVERNS_PR",
)


def build_trace(repo: Path, work_id: str, pr_number: int) -> dict[str, Any]:
    emit(TRACE_BUILD, "start", work_id=work_id, pr=pr_number)
    work = load_work(repo, work_id)
    snapshot = collect_evidence(repo, work_id, pr_number)
    spec, spec_state = artifact_status(repo, work, "SPEC")
    plan, plan_state = artifact_status(repo, work, "PLAN")
    subject = snapshot["subject_sha"]
    nodes = [
        {"id": f"work:{work_id}", "kind": "WORK", "status": "PRESENT", "ref": work_id},
        {"id": "spec", "kind": "SPEC", "status": _node_status(spec_state), "ref": (spec or {}).get("pointer", "")},
        {"id": "plan", "kind": "PLAN", "status": _node_status(plan_state), "ref": (plan or {}).get("pointer", "")},
        {"id": f"pr:{pr_number}", "kind": "PR", "status": "PRESENT", "ref": str(pr_number)},
        {"id": f"commit:{subject}", "kind": "COMMIT", "status": "PRESENT" if subject else "MISSING", "ref": subject},
        {
            "id": "review",
            "kind": "REVIEW_DECISION",
            "status": "MISSING" if snapshot["review"]["status"] == "MISSING" else snapshot["review"]["status"],
            "ref": str(snapshot["review"].get("decision") or ""),
        },
    ]
    edges = [
        {"type": "WORK_HAS_SPEC", "from": f"work:{work_id}", "to": "spec"},
        {"type": "WORK_HAS_PLAN", "from": f"work:{work_id}", "to": "plan"},
        {"type": "PR_DECLARES_WORK", "from": f"pr:{pr_number}", "to": f"work:{work_id}"},
        {"type": "PR_HEAD_IS_COMMIT", "from": f"pr:{pr_number}", "to": f"commit:{subject}"},
        {"type": "REVIEW_GOVERNS_PR", "from": "review", "to": f"pr:{pr_number}"},
    ]
    if snapshot["checks"]:
        for index, check in enumerate(snapshot["checks"]):
            node_id = f"check:{index}"
            nodes.append({"id": node_id, "kind": "CI_CHECK", "status": check["status"] if check["status"] != "SKIPPED" else "FAIL", "ref": check["name"]})
            edges.append({"type": "CHECK_VERIFIES_COMMIT", "from": node_id, "to": f"commit:{subject}"})
    else:
        nodes.append({"id": "check:missing", "kind": "CI_CHECK", "status": "MISSING", "ref": ""})
        edges.append({"type": "CHECK_VERIFIES_COMMIT", "from": "check:missing", "to": f"commit:{subject}"})
    graph = {"schema": "ges.trace.v1", "work_id": work_id, "subject_sha": subject, "nodes": nodes, "edges": edges}
    validate_payload("ges.trace.v1.json", graph)
    emit(TRACE_BUILD, "complete", nodes=len(nodes))
    return graph


def _node_status(state: str) -> str:
    if state == "CURRENT":
        return "CURRENT"
    if state == "MISSING":
        return "MISSING"
    return "STALE"
