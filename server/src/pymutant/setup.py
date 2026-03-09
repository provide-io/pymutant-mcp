# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404
import tomllib
from pathlib import Path


def _project_root_or_cwd(project_root: Path | str | None) -> Path:
    if project_root is None:
        return Path(os.getcwd())
    return Path(project_root)


def _read_pyproject(root: Path) -> dict:
    pp = root / "pyproject.toml"
    if not pp.exists():
        return {}
    try:
        return tomllib.loads(pp.read_text())
    except tomllib.TOMLDecodeError:
        return {}


def _mutmut_version(root: Path) -> str | None:
    """Return installed mutmut version string, checking .venv first then PATH."""
    candidates = [
        str(root / ".venv" / "bin" / "mutmut"),
        shutil.which("mutmut") or "",
    ]
    for exe in candidates:
        if not exe or not Path(exe).exists():
            continue
        try:
            r = subprocess.run(  # noqa: S603,S607  # nosec
                [exe, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            out = r.stdout.strip() or r.stderr.strip()
            return out or "installed"
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def _find_test_dirs(root: Path) -> list[str]:
    return [
        c + "/"
        for c in ("tests", "test", "src/tests")
        if (root / c).is_dir()
    ]


def _normalize_to_list(value: object) -> tuple[list[str] | None, str | None]:
    if isinstance(value, list):
        return [str(v) for v in value], None
    if isinstance(value, str):
        return [value], "legacy string value detected; prefer TOML arrays"
    return None, f"got {type(value).__name__} — must be a TOML array or string"


def _detect_monorepo_src_paths(root: Path) -> list[str]:
    pkgs = root / "packages"
    if not pkgs.is_dir():
        return []
    return sorted(
        str(p.relative_to(root)) + "/"
        for p in pkgs.glob("*/src")
        if p.is_dir()
    )


_MONOREPO_KEY_MISMATCH_NOTE = (
    "MONOREPO KEY MISMATCH: mutmut derives mutant keys by stripping only a leading "
    "'src.' prefix from file paths. For 'packages/foo/src/mymod/bar.py' the key becomes "
    "'packages.foo.src.mymod.bar.*' but the trampoline records 'mymod.bar.*' via "
    "orig.__module__ — causing all mutants to report no_tests.\n"
    "FIX: create a symlink under src/ for each sub-package to mutate, then point "
    "paths_to_mutate at those symlinks:\n"
    "  ln -s ../../packages/foo/src/mymod src/mymod\n"
    "  paths_to_mutate = [\"src/mymod/\"]\n"
    "Also create a conftest.py at the repo root that prepends mutants/src to sys.path "
    "when MUTANT_UNDER_TEST is set — run pymutant_init with with_conftest=True."
)


def detect_layout(project_root: Path | None = None) -> dict:
    """Detect project layout and return a suggested mutmut configuration."""
    root = _project_root_or_cwd(project_root)
    test_dirs = _find_test_dirs(root)
    pyproject = _read_pyproject(root)
    has_mutmut = bool(pyproject.get("tool", {}).get("mutmut"))
    notes: list[str] = []
    also_copy: list[str] = []

    mono_paths = _detect_monorepo_src_paths(root)
    if mono_paths:
        layout = "monorepo"
        suggested_paths: list[str] = mono_paths
        notes.append(_MONOREPO_KEY_MISMATCH_NOTE)
    elif (root / "src").is_dir():
        layout = "flat_src"
        suggested_paths = ["src/"]
    else:
        layout = "flat"
        suggested_paths = [
            p.name + "/"
            for p in sorted(root.iterdir())
            if p.is_dir()
            and not p.name.startswith((".", "_"))
            and (p / "__init__.py").exists()
        ]

    if (root / "scripts").is_dir():
        also_copy.append("scripts/")
    if (root / "conftest.py").exists():
        also_copy.append("conftest.py")

    suggested: dict[str, object] = {
        "paths_to_mutate": suggested_paths,
        "tests_dir": test_dirs,
    }
    if also_copy:
        suggested["also_copy"] = also_copy

    return {
        "layout": layout,
        "src_paths": mono_paths or (["src/"] if (root / "src").is_dir() else suggested_paths),
        "test_dirs": test_dirs,
        "has_pyproject_toml": (root / "pyproject.toml").exists(),
        "has_mutmut_config": has_mutmut,
        "suggested_config": suggested,
        "notes": notes,
    }


def check_setup(project_root: Path | None = None) -> dict:
    """Run pre-flight checks for mutmut readiness on the project."""
    root = _project_root_or_cwd(project_root)
    pyproject = _read_pyproject(root)
    cfg = pyproject.get("tool", {}).get("mutmut", {})
    checks: list[dict] = []

    version = _mutmut_version(root)
    checks.append({
        "name": "mutmut_installed",
        "ok": version is not None,
        "detail": version or "not found — install: uv add --dev mutmut",
    })

    pp_exists = (root / "pyproject.toml").exists()
    checks.append({
        "name": "pyproject_toml_exists",
        "ok": pp_exists,
        "detail": "present" if pp_exists else "missing",
    })

    checks.append({
        "name": "mutmut_config_exists",
        "ok": bool(cfg),
        "detail": "present" if cfg else "missing — run pymutant_init to scaffold",
    })

    layout = detect_layout(root)["layout"]

    if cfg:
        paths, paths_note = _normalize_to_list(cfg.get("paths_to_mutate", []))
        tests, tests_note = _normalize_to_list(cfg.get("tests_dir", []))

        checks.append({
            "name": "paths_to_mutate_valid_type",
            "ok": paths is not None,
            "detail": paths_note or "ok",
        })
        checks.append({
            "name": "tests_dir_valid_type",
            "ok": tests is not None,
            "detail": tests_note or "ok",
        })

        if paths is not None:
            missing = [p for p in paths if not (root / p).exists()]
            checks.append({
                "name": "paths_to_mutate_exist",
                "ok": not missing,
                "detail": "all exist" if not missing else f"missing: {missing}",
            })
            has_packages_path = any("packages" in p for p in paths)
            if has_packages_path:
                checks.append({
                    "name": "no_monorepo_key_mismatch",
                    "ok": False,
                    "detail": (
                        "paths_to_mutate contains 'packages/' paths — mutmut key derivation "
                        "will not match trampoline module names. Use src/ symlinks instead. "
                        "Run pymutant_detect_layout for the full explanation."
                    ),
                })

        if tests is not None:
            missing_t = [t for t in tests if not (root / t).exists()]
            checks.append({
                "name": "tests_dir_exist",
                "ok": not missing_t,
                "detail": "all exist" if not missing_t else f"missing: {missing_t}",
            })

    conftest = root / "conftest.py"
    guard_required = layout == "monorepo"
    guard_ok = conftest.exists() and "MUTANT_UNDER_TEST" in conftest.read_text()
    checks.append({
        "name": "conftest_mutant_guard",
        "ok": (not guard_required) or guard_ok,
        "detail": (
            "not required for detected layout"
            if not guard_required else (
                "present" if guard_ok else (
                    "conftest.py missing or lacks MUTANT_UNDER_TEST sys.path guard "
                    "(needed for monorepo/editable-install projects — run pymutant_init with with_conftest=True)"
                )
            )
        ),
    })

    return {"ok": all(c["ok"] for c in checks), "checks": checks}
