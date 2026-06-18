#!/usr/bin/env python3
"""Validate and package Browser Takeover releases using only the Python standard library."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = PROJECT_ROOT / "browser-takeover"
DIST_ROOT = PROJECT_ROOT / "dist"
EXTENSION_MANIFEST = PLUGIN_ROOT / "extension" / "manifest.json"
PLUGIN_MANIFEST = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def release_version() -> str:
    extension_version = read_json(EXTENSION_MANIFEST)["version"]
    plugin_version = read_json(PLUGIN_MANIFEST)["version"].split("+", 1)[0]
    if not VERSION_PATTERN.fullmatch(extension_version):
        raise ValueError(f"Invalid extension version: {extension_version}")
    if extension_version != plugin_version:
        raise ValueError(
            f"Version mismatch: extension={extension_version}, plugin={plugin_version}"
        )
    return extension_version


def validate_release() -> list[str]:
    version = release_version()
    required = [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "LICENSE",
        PROJECT_ROOT / "PRIVACY.md",
        PROJECT_ROOT / "SECURITY.md",
        PROJECT_ROOT / "CHANGELOG.md",
        PLUGIN_ROOT / ".mcp.json",
        PLUGIN_ROOT / "README.md",
        PLUGIN_ROOT / "extension" / "background.js",
        PLUGIN_ROOT / "extension" / "popup.html",
        PLUGIN_ROOT / "extension" / "popup.css",
        PLUGIN_ROOT / "extension" / "popup.js",
        PLUGIN_ROOT / "skills" / "browser-takeover" / "SKILL.md",
        PLUGIN_ROOT / "scripts" / "browser_takeover_mcp.py",
    ]
    missing = [str(path.relative_to(PROJECT_ROOT)) for path in required if not path.is_file()]
    if missing:
        raise ValueError("Missing required release files: " + ", ".join(missing))

    for path in [EXTENSION_MANIFEST, PLUGIN_MANIFEST, PLUGIN_ROOT / ".mcp.json"]:
        read_json(path)

    manifest = read_json(EXTENSION_MANIFEST)
    if manifest.get("manifest_version") != 3:
        raise ValueError("The extension must use Manifest V3")
    if manifest.get("host_permissions") != ["<all_urls>"]:
        raise ValueError("Unexpected host permission configuration")

    placeholders = []
    placeholder_marker = "[" + "TODO:"
    for path in PROJECT_ROOT.rglob("*"):
        if (
            path.is_file()
            and ".git" not in path.parts
            and "node_modules" not in path.parts
            and path.suffix.lower() in {".md", ".json", ".js", ".py", ".html", ".css", ".yml"}
        ):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if placeholder_marker in text:
                placeholders.append(str(path.relative_to(PROJECT_ROOT)))
    if placeholders:
        raise ValueError("Release placeholders remain in: " + ", ".join(placeholders))

    return [
        f"version {version}",
        f"{len(required)} required files",
        "Manifest V3",
        "version consistency",
        "no release placeholders",
    ]


def iter_files(root: Path):
    ignored_parts = {"__pycache__", "node_modules", ".pytest_cache"}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not ignored_parts.intersection(path.parts) and path.suffix != ".pyc":
            yield path


def write_zip(output: Path, root: Path, files, prefix: str = "") -> None:
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(f"{prefix}{relative}", FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())


def package_release(clean: bool = True) -> list[Path]:
    version = release_version()
    if clean and DIST_ROOT.exists():
        shutil.rmtree(DIST_ROOT)
    DIST_ROOT.mkdir(parents=True, exist_ok=True)

    extension_zip = DIST_ROOT / f"browser-takeover-extension-{version}.zip"
    plugin_zip = DIST_ROOT / f"browser-takeover-plugin-{version}.zip"
    extension_root = PLUGIN_ROOT / "extension"
    write_zip(extension_zip, extension_root, iter_files(extension_root))
    write_zip(plugin_zip, PLUGIN_ROOT, iter_files(PLUGIN_ROOT), prefix="browser-takeover/")

    artifacts = [extension_zip, plugin_zip]
    checksum_path = DIST_ROOT / "SHA256SUMS.txt"
    checksum_lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}" for path in artifacts
    ]
    checksum_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    artifacts.append(checksum_path)
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["validate", "package", "all"], nargs="?", default="all")
    args = parser.parse_args()
    try:
        checks = validate_release()
        for check in checks:
            print(f"PASS {check}")
        if args.command in {"package", "all"}:
            for artifact in package_release():
                print(f"CREATED {artifact.relative_to(PROJECT_ROOT)}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
