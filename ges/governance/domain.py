from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ArtifactRef:
    """Pointer-only artifact identity. GES never copies artifact body."""

    id: str
    type: str
    pointer: str
    digest: str


@dataclass
class Work:
    id: str
    kind: str = "FEATURE"
    title: str = ""
    status: str = "OPEN"
    owner: str = ""
    risk: str | None = None
    policy: str = "default-v1"
    artifacts: list[ArtifactRef] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Evidence:
    type: str
    status: str
    subject_sha: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Policy:
    id: str
    intake: dict[str, Any] = field(default_factory=dict)
    merge: dict[str, Any] = field(default_factory=dict)


@dataclass
class Risk:
    level: str


@dataclass
class Ownership:
    work_id: str
    owner: str


@dataclass
class Approval:
    id: str
    work_id: str
    actor: str
    verdict: str


@dataclass
class Release:
    id: str
    work_id: str
    commit: str | None = None


BACKPLANE_MODULES = (
    "01 Registry",
    "02 Policy",
    "03 Risk",
    "04 Ownership",
    "05 Evidence",
    "06 Approval",
    "07 Traceability",
    "08 Delivery",
    "09 Release",
    "10 Audit",
)
