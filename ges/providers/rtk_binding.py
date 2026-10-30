from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ges.catalog.providers import RTK_ID
from ges.providers.rtk import probe_rtk
from ges.reconciler.state import validate_payload

PASS = "PASS"
FAIL = "FAIL"


def probe_binding(capability_id: str, host: str) -> dict[str, Any]:
    if capability_id != RTK_ID:
        return _payload(capability_id, host, "UNSUPPORTED", "missing", [])
    provider = probe_rtk()
    if host == "cursor":
        status, observations = _cursor_binding()
    elif host == "codex":
        status, observations = _codex_binding()
    elif host == "hermes":
        status, observations = _hermes_binding()
    else:
        status, observations = "UNSUPPORTED", []
    if provider["status"] != "READY" and status == "BOUND":
        status = "UNPROVEN"
    return _payload(capability_id, host, status, provider["status"], observations)


def binding_identity(payload: dict[str, Any]) -> str:
    rows = sorted(
        (str(item.get("source") or ""), str(item.get("digest") or ""))
        for item in payload.get("observations") or []
    )
    raw = json.dumps({"host": payload.get("host"), "rows": rows}, sort_keys=True)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cursor_binding() -> tuple[str, list[dict[str, str]]]:
    path = Path.home() / ".cursor" / "hooks.json"
    return _hooks_file_binding(path, name="host_registration")


def _codex_binding() -> tuple[str, list[dict[str, str]]]:
    candidates = [Path.cwd() / ".codex" / "hooks.json"]
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        candidates.append(Path(codex_home) / "hooks.json")
    existing = [path for path in candidates if path.is_file()]
    if not existing:
        return "UNPROVEN", [_obs("host_registration", FAIL, str(candidates[0]), "")]
    if len(existing) > 1:
        # Prefer project hooks when both exist.
        path = existing[0]
    else:
        path = existing[0]
    status, observations = _hooks_file_binding(path, name="host_registration")
    if _uses_markdown_linkage(Path.cwd()):
        agents = Path.cwd() / "AGENTS.md"
        rtk_md = Path.cwd() / "RTK.md"
        if not (agents.is_file() and rtk_md.is_file() and "rtk" in agents.read_text(encoding="utf-8", errors="replace").lower()):
            return "UNPROVEN", observations + [_obs("markdown_linkage", FAIL, str(agents), "")]
        observations.append(_obs("markdown_linkage", PASS, str(agents), _digest(agents)))
    return status, observations


def _hermes_binding() -> tuple[str, list[dict[str, str]]]:
    roots = _hermes_plugin_roots()
    if not roots:
        local = Path(os.environ.get("LOCALAPPDATA") or "") / "SMC" / "Hermes" / "plugins"
        return "UNPROVEN", [_obs("plugin_root", FAIL, str(local), "")]
    if len(roots) > 1:
        return "UNPROVEN", [_obs("plugin_root", FAIL, ",".join(str(p) for p in roots), "")]
    root = roots[0]
    plugin = _find_rtk_plugin(root)
    if plugin is None:
        return "UNBOUND", [_obs("plugin_root", FAIL, str(root), _digest_dir_marker(root))]
    config = root.parent / "config.json"
    if not config.is_file():
        config = root / "config.json"
    enabled = False
    if config.is_file():
        text = config.read_text(encoding="utf-8", errors="replace").lower()
        enabled = "rtk" in text and ("enable" in text or "enabled" in text or "true" in text)
    if not enabled:
        return "UNBOUND", [
            _obs("plugin_root", PASS, str(plugin), _digest(plugin) if plugin.is_file() else ""),
            _obs("plugin_enabled", FAIL, str(config), _digest(config) if config.is_file() else ""),
        ]
    return "BOUND", [
        _obs("plugin_root", PASS, str(plugin), _digest(plugin) if plugin.is_file() else _digest_dir_marker(plugin)),
        _obs("plugin_enabled", PASS, str(config), _digest(config)),
    ]


def _hermes_plugin_roots() -> list[Path]:
    roots: list[Path] = []
    home = os.environ.get("HERMES_HOME")
    if home:
        candidate = Path(home) / "plugins"
        if candidate.is_dir():
            roots.append(candidate.resolve())
    local = Path(os.environ.get("LOCALAPPDATA") or "") / "SMC" / "Hermes" / "plugins"
    if local.is_dir():
        resolved = local.resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _find_rtk_plugin(root: Path) -> Path | None:
    for path in root.rglob("*"):
        name = path.name.lower()
        if "rtk" in name and (path.is_dir() or path.suffix in {".js", ".mjs", ".json", ".py"}):
            return path
    return None


def _hooks_file_binding(path: Path, *, name: str) -> tuple[str, list[dict[str, str]]]:
    if not path.is_file():
        return "UNPROVEN", [_obs(name, FAIL, str(path), "")]
    text = path.read_text(encoding="utf-8", errors="replace")
    digest = _digest(path)
    lowered = text.lower()
    has_rtk = "rtk" in lowered
    has_rewrite = "rewrite" in lowered or "pretooluse" in lowered or "pre_tool_use" in lowered
    if has_rtk and has_rewrite and _rtk_resolvable(text):
        return "BOUND", [_obs(name, PASS, str(path), digest)]
    if path.is_file() and not (has_rtk and has_rewrite):
        return "UNBOUND", [_obs(name, FAIL, str(path), digest)]
    return "UNPROVEN", [_obs(name, FAIL, str(path), digest)]


def _rtk_resolvable(text: str) -> bool:
    lowered = text.lower()
    if "rtk.exe" in lowered or "/rtk" in lowered or "\\rtk" in lowered or '"rtk"' in lowered or "'rtk'" in lowered:
        return True
    return "rtk" in lowered


def _uses_markdown_linkage(repo: Path) -> bool:
    return (repo / "RTK.md").is_file() or (
        (repo / "AGENTS.md").is_file()
        and "rtk" in (repo / "AGENTS.md").read_text(encoding="utf-8", errors="replace").lower()
    )


def _digest(path: Path) -> str:
    data = path.read_bytes()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _digest_dir_marker(path: Path) -> str:
    return "sha256:" + hashlib.sha256(str(path).encode("utf-8")).hexdigest()


def _obs(name: str, status: str, source: str, digest: str) -> dict[str, str]:
    return {"name": name, "status": status, "source": source, "digest": digest}


def _payload(
    capability_id: str,
    host: str,
    status: str,
    provider_status: str,
    observations: list[dict[str, str]],
) -> dict[str, Any]:
    payload = {
        "schema": "ges.capability-binding-status.v1",
        "capability_id": capability_id,
        "provider": "rtk",
        "host": host,
        "status": status,
        "provider_status": provider_status,
        "observations": observations,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
    validate_payload("ges.capability-binding-status.v1.json", payload)
    return payload
