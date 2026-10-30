from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ges.errors import DESIRED_STATE_INVALID, GesError
from ges.io import read_yaml
from ges.paths import CATALOG_DIR

PROVIDERS_FILE = CATALOG_DIR / "providers.yaml"
RTK_ID = "command-output.rtk"


@dataclass(frozen=True)
class Provider:
    id: str
    category: str
    provider: str
    default_level: str
    incompatible: tuple[str, ...]
    health_checks: tuple[str, ...]


def load_providers(path: Path | None = None) -> dict[str, Provider]:
    payload = read_yaml(path or PROVIDERS_FILE) or {}
    out: dict[str, Provider] = {}
    for item in payload.get("providers") or []:
        cap_id = item["id"]
        if cap_id in out:
            raise GesError(DESIRED_STATE_INVALID, f"duplicate provider id: {cap_id}")
        provider = Provider(
            id=cap_id,
            category=item["category"],
            provider=item["provider"],
            default_level=item.get("default_level") or "optional",
            incompatible=tuple(item.get("incompatible") or []),
            health_checks=tuple(item.get("health_checks") or ()),
        )
        out[provider.id] = provider
    return out


def rtk_provider() -> Provider:
    return load_providers()[RTK_ID]
