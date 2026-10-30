from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from ges import __product_version__

ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "ges-setup"
SKILL_MD = SKILL_ROOT / "SKILL.md"
LOCK_PATH = SKILL_ROOT / "engine.lock.json"
SCRIPTS = SKILL_ROOT / "scripts"
NAME_RE = re.compile(r"^[a-z0-9-]+$")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def acquire_mod():
    return _load("acquire_ges_cli", SCRIPTS / "acquire_ges_cli.py")


@pytest.fixture(scope="module")
def setup_mod():
    return _load("ges_setup", SCRIPTS / "ges_setup.py")


def _frontmatter(text: str) -> dict[str, object]:
    assert text.startswith("---"), "SKILL.md must start with YAML frontmatter"
    end = text.find("\n---", 3)
    assert end > 0, "SKILL.md frontmatter is not closed"
    block = text[3:end]
    data: dict[str, object] = {}
    key = None
    folded: list[str] = []
    for line in block.splitlines():
        if key and (line.startswith("  ") or line.startswith("\t")):
            folded.append(line.strip())
            continue
        if key:
            data[key] = " ".join(folded).strip()
            key = None
            folded = []
        if ":" not in line:
            continue
        raw_key, value = line.split(":", 1)
        raw_key = raw_key.strip()
        value = value.strip()
        if value in {">", ">-", "|", "|-"}:
            key = raw_key
            folded = []
            continue
        if value.lower() in {"true", "false"}:
            data[raw_key] = value.lower() == "true"
        else:
            data[raw_key] = value.strip('"').strip("'")
    if key:
        data[key] = " ".join(folded).strip()
    return data


def test_skill_frontmatter_is_cursor_valid():
    meta = _frontmatter(SKILL_MD.read_text(encoding="utf-8"))
    assert meta.get("name") == "ges-setup"
    assert SKILL_ROOT.name == "ges-setup"
    assert NAME_RE.fullmatch(str(meta["name"]))
    description = str(meta.get("description") or "")
    assert description
    assert "ges-setup" in description
    assert "/ges-setup" in description
    assert meta.get("disable-model-invocation") is True


def test_skill_documents_skills_path_only_install():
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "npx skills@latest add smc-copilot/ges -a cursor --path skills" in text
    assert "pip install" in text
    assert "governance init" in text
    assert "BOOTSTRAP_PENDING" in text
    assert "engine.lock.json" in text
    assert "tag-1.0" in text


def test_readme_leads_with_cursor_product_path():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    install = "npx skills@latest add smc-copilot/ges -a cursor --path skills"
    assert text.index(install) < text.index("pip install -e")
    assert text.index("/ges-setup") < text.index("pip install -e")
    assert "Do not" in text or "do not" in text
    assert "Python tree" in text or "ges/` Python" in text
    assert "--path skills" in text
    assert "tag-1.0" in text
    assert "Current locked release" in text
    assert "6.0.0-alpha.5" in text
    assert "git+https://github.com/smc-copilot/ges.git@tag-1.0" in text
    assert "ges governance init" in text
    assert "v1.0.0" in text  # forbidden-name warning, not the public tag


def test_packaging_keeps_skills_out_of_the_engine_tree():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'include = ["ges*"]' in pyproject
    assert not (ROOT / "SKILL.md").exists()
    assert (ROOT / "skills.sh.json").is_file()
    manifest = json.loads((ROOT / "skills.sh.json").read_text(encoding="utf-8"))
    assert manifest["paths"] == ["./skills"]
    assert list((ROOT / "skills").glob("*/SKILL.md")) == [SKILL_MD]


def _write_pin(tmp_path: Path, **overrides) -> Path:
    pin = {
        "schema": "ges.engine-pin.v1",
        "package": "ges",
        "product_version": "6.0.0-alpha.5",
        "repository": "https://github.com/smc-copilot/ges.git",
        "ref": "tag-1.0",
        "ref_kind": "tag",
        "requirement": "ges @ git+https://github.com/smc-copilot/ges.git@tag-1.0",
    }
    pin.update(overrides)
    path = tmp_path / "engine.lock.json"
    path.write_text(json.dumps(pin), encoding="utf-8")
    return tmp_path


def test_engine_pin_is_scheme_a_tag_1_0(acquire_mod):
    pin = acquire_mod.load_pin(SKILL_ROOT)
    assert pin["schema"] == "ges.engine-pin.v1"
    assert pin["package"] == "ges"
    assert pin["product_version"] == __product_version__
    assert pin["ref_kind"] == "tag"
    assert pin["ref"] == "tag-1.0"
    assert pin["requirement"] == "ges @ git+https://github.com/smc-copilot/ges.git@tag-1.0"
    assert pin["ref"] in pin["requirement"]
    assert pin["repository"] in pin["requirement"]
    assert not re.fullmatch(r"[0-9a-f]{40}", pin["ref"])
    assert LOCK_PATH.is_file()
    assert acquire_mod.default_wheel_name(pin) == "ges-6.0.0a5-py3-none-any.whl"
    assert acquire_mod.default_wheel_url(pin) == (
        "https://github.com/smc-copilot/ges/releases/download/tag-1.0/"
        "ges-6.0.0a5-py3-none-any.whl"
    )


def test_load_pin_accepts_scheme_a_tag(acquire_mod, tmp_path):
    root = _write_pin(tmp_path)
    pin = acquire_mod.load_pin(root)
    assert pin["ref_kind"] == "tag"
    assert pin["ref"] == "tag-1.0"


def test_load_pin_rejects_tag_missing_from_requirement(acquire_mod, tmp_path):
    root = _write_pin(
        tmp_path,
        requirement="ges @ git+https://github.com/smc-copilot/ges.git@deadbeef",
    )
    with pytest.raises(acquire_mod.AcquireError) as captured:
        acquire_mod.load_pin(root)
    assert captured.value.code == "GES_ENGINE_PIN_INVALID"
    assert "requirement" in captured.value.message


def test_load_pin_rejects_forbidden_tag_names(acquire_mod, tmp_path):
    for name in ("v1.0", "v1.0.0", "tag-1.0.0", "1.0", ""):
        root = _write_pin(
            tmp_path,
            ref=name,
            requirement=f"ges @ git+https://github.com/smc-copilot/ges.git@{name}",
        )
        with pytest.raises(acquire_mod.AcquireError) as captured:
            acquire_mod.load_pin(root)
        assert captured.value.code == "GES_ENGINE_PIN_INVALID"


def test_load_pin_still_validates_commit_sha(acquire_mod, tmp_path):
    sha = "a7490a9c617bf0a0fba0bab259b24792384e7f76"
    root = _write_pin(
        tmp_path,
        ref=sha,
        ref_kind="commit",
        requirement=f"ges @ git+https://github.com/smc-copilot/ges.git@{sha}",
    )
    pin = acquire_mod.load_pin(root)
    assert pin["ref_kind"] == "commit"
    assert pin["ref"] == sha

    bad = _write_pin(
        tmp_path,
        ref="abc123",
        ref_kind="commit",
        requirement="ges @ git+https://github.com/smc-copilot/ges.git@abc123",
    )
    with pytest.raises(acquire_mod.AcquireError) as captured:
        acquire_mod.load_pin(bad)
    assert captured.value.code == "GES_ENGINE_PIN_INVALID"


def test_pep440_public_version_matches_wheel_token(acquire_mod):
    assert acquire_mod.pep440_public_version("6.0.0-alpha.5") == "6.0.0a5"
    assert acquire_mod.pep440_public_version("1.2.3") == "1.2.3"


def test_product_repo_guard_rejects_this_checkout(setup_mod):
    assert setup_mod.looks_like_ges_product_repo(ROOT)
    with pytest.raises(setup_mod.SetupError) as captured:
        setup_mod.assert_business_target(ROOT)
    assert captured.value.code == setup_mod.PRODUCT_REPO


def test_product_repo_guard_allows_explicit_override(setup_mod):
    setup_mod.assert_business_target(ROOT, allow_product_repo=True)


def test_business_repo_is_not_the_product(setup_mod, tmp_path):
    (tmp_path / "README.md").write_text("app\n", encoding="utf-8")
    assert not setup_mod.looks_like_ges_product_repo(tmp_path)
    setup_mod.assert_business_target(tmp_path)


def test_whole_repo_dumped_into_cursor_is_blocked(setup_mod, tmp_path):
    dumped = tmp_path / ".cursor" / "ges" / "cli"
    dumped.mkdir(parents=True)
    (dumped / "main.py").write_text("# dumped engine\n", encoding="utf-8")
    with pytest.raises(setup_mod.SetupError) as captured:
        setup_mod.assert_business_target(tmp_path)
    assert captured.value.code == setup_mod.WHOLE_REPO_IN_CURSOR


def test_acquire_cache_hit_skips_pip(acquire_mod, tmp_path, monkeypatch):
    pin = acquire_mod.load_pin(SKILL_ROOT)
    home = tmp_path / "engines"
    venv = acquire_mod.venv_dir(pin, home)
    exe = acquire_mod.ges_executable(venv)
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(0o755)

    def fake_version(_exe):
        return f"{pin['product_version']} (distribution 1.2.1)"

    monkeypatch.setattr(acquire_mod, "cli_version", fake_version)
    payload = acquire_mod.acquire(skill_root=SKILL_ROOT, home=home)
    assert payload["ok"] is True
    assert payload["cache"] == "hit"
    assert payload["ges_cli"] == str(exe)
    assert payload["product_version"] == __product_version__


def test_acquire_falls_back_to_target_when_venv_unavailable(acquire_mod, tmp_path, monkeypatch):
    pin = acquire_mod.load_pin(SKILL_ROOT)
    home = tmp_path / "engines"
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(acquire_mod, "venv_available", lambda _python: False)
    monkeypatch.setattr(acquire_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        acquire_mod,
        "cli_version",
        lambda _exe: f"{pin['product_version']} (distribution 1.2.1)",
    )
    source = tmp_path / "src"
    source.mkdir()
    payload = acquire_mod.acquire(skill_root=SKILL_ROOT, home=home, source=source)
    assert payload["cache"] == "miss"
    assert any("--target" in argv for argv in calls)
    launcher = Path(payload["ges_cli"])
    assert launcher.is_file()
    assert "PYTHONPATH=" in launcher.read_text(encoding="utf-8")
    assert "-m ges" in launcher.read_text(encoding="utf-8")


def test_acquire_uses_local_source_when_uncached(acquire_mod, tmp_path, monkeypatch):
    pin = acquire_mod.load_pin(SKILL_ROOT)
    home = tmp_path / "engines"
    created: dict[str, object] = {}

    def fake_run(argv, **_kwargs):
        created.setdefault("argv", list(argv))
        if len(argv) >= 3 and argv[1:3] == ["-m", "venv"]:
            dest = Path(argv[3])
            created["dest"] = dest
            python = acquire_mod.venv_python(dest)
            python.parent.mkdir(parents=True)
            python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python.chmod(0o755)
            exe = acquire_mod.ges_executable(dest)
            exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            exe.chmod(0o755)
            created["argv"] = []
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        created["argv"] = list(argv)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(acquire_mod, "venv_available", lambda _python: True)
    monkeypatch.setattr(acquire_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        acquire_mod,
        "cli_version",
        lambda _exe: f"{pin['product_version']} (distribution 1.2.1)",
    )
    source = tmp_path / "src"
    source.mkdir()
    payload = acquire_mod.acquire(skill_root=SKILL_ROOT, home=home, source=source)
    assert payload["cache"] == "miss"
    assert created["argv"][:4] == [str(acquire_mod.venv_python(created["dest"])), "-m", "pip", "install"]
    assert "-e" in created["argv"]
    assert str(source) in created["argv"]
    assert pin["requirement"] not in created["argv"]


def test_acquire_prefers_release_wheel_then_falls_back_to_git(acquire_mod, tmp_path, monkeypatch):
    pin = acquire_mod.load_pin(SKILL_ROOT)
    home = tmp_path / "engines"
    calls: list[list[str]] = []
    wheel = acquire_mod.default_wheel_url(pin)
    assert wheel

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        if len(argv) >= 3 and argv[1:3] == ["-m", "venv"]:
            dest = Path(argv[3])
            python = acquire_mod.venv_python(dest)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python.chmod(0o755)
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if wheel in argv:
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": "404 wheel"})()
        dest = acquire_mod.venv_dir(pin, home)
        exe = acquire_mod.ges_executable(dest)
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        exe.chmod(0o755)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(acquire_mod, "venv_available", lambda _python: True)
    monkeypatch.setattr(acquire_mod, "wheel_url_available", lambda _url: True)
    monkeypatch.setattr(acquire_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        acquire_mod,
        "cli_version",
        lambda _exe: f"{pin['product_version']} (distribution 1.2.1)",
    )
    payload = acquire_mod.acquire(skill_root=SKILL_ROOT, home=home)
    assert payload["cache"] == "miss"
    pip_calls = [argv for argv in calls if "-m" in argv and "pip" in argv]
    assert pip_calls
    assert wheel in pip_calls[0]
    assert pin["requirement"] in pip_calls[-1]


def test_acquire_skips_missing_wheel_and_uses_git_pin(acquire_mod, tmp_path, monkeypatch):
    pin = acquire_mod.load_pin(SKILL_ROOT)
    home = tmp_path / "engines"
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        if len(argv) >= 3 and argv[1:3] == ["-m", "venv"]:
            dest = Path(argv[3])
            python = acquire_mod.venv_python(dest)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python.chmod(0o755)
            exe = acquire_mod.ges_executable(dest)
            exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            exe.chmod(0o755)
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(acquire_mod, "venv_available", lambda _python: True)
    monkeypatch.setattr(acquire_mod, "wheel_url_available", lambda _url: False)
    monkeypatch.setattr(acquire_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        acquire_mod,
        "cli_version",
        lambda _exe: f"{pin['product_version']} (distribution 1.2.1)",
    )
    payload = acquire_mod.acquire(skill_root=SKILL_ROOT, home=home)
    assert payload["cache"] == "miss"
    pip_calls = [argv for argv in calls if "-m" in argv and "pip" in argv]
    assert len(pip_calls) == 1
    assert pin["requirement"] in pip_calls[0]
    assert "releases/download" not in " ".join(pip_calls[0])


def test_bootstrap_pending_report_does_not_claim_ready(setup_mod, tmp_path):
    acquired = {"product_version": "6.0.0-alpha.5"}
    result = {
        "composer": "GES_APPLY_OK",
        "check": "GES_CHECK_PASS",
        "overall": "BOOTSTRAP_PENDING",
        "doctor": {
            "overall": "BOOTSTRAP_PENDING",
            "checks": {
                "ges_core": "PASS",
                "matt_project_bootstrap": "PENDING",
            },
            "warnings": [],
        },
    }
    report = setup_mod.render_report(tmp_path, acquired, result)
    assert "BOOTSTRAP_PENDING" in report
    assert "not READY" in report
    assert "setup-matt-pocock-skills" in report
    assert "governance init" in report
    assert "Composer first-install readiness: READY." not in report
