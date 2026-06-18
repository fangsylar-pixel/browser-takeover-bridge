#!/usr/bin/env python3
"""Run the complete local release verification workflow."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def executable(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise OSError(f"Required executable not found: {name}")
    return resolved


def run(label: str, command: list[str], cwd: Path = PROJECT_ROOT) -> None:
    print(f"\n== {label} ==", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-website", action="store_true")
    parser.add_argument("--no-package", action="store_true")
    args = parser.parse_args()
    python = sys.executable
    node = executable("node")
    npm = executable("npm")

    try:
        run("Release validation", [python, "browser-takeover/scripts/release_tools.py", "validate"])
        run(
            "Python syntax",
            [
                python,
                "-m",
                "py_compile",
                "browser-takeover/scripts/browser_takeover_mcp.py",
                "browser-takeover/scripts/benchmark_extension.py",
                "browser-takeover/scripts/release_tools.py",
                "browser-takeover/scripts/verify_release.py",
                "browser-takeover/tests/test_bridge.py",
                "browser-takeover/tests/test_release_tools.py",
            ],
        )
        run(
            "Python tests",
            [python, "-m", "unittest", "discover", "-s", "browser-takeover/tests", "-v"],
        )
        run("Extension background syntax", [node, "--check", "browser-takeover/extension/background.js"])
        run("Extension popup syntax", [node, "--check", "browser-takeover/extension/popup.js"])
        run(
            "Extension runtime smoke test",
            [node, "browser-takeover/tests/test_background_runtime.mjs"],
        )
        if not args.skip_website:
            run("Website dependencies", [npm, "ci"], PROJECT_ROOT / "website")
            run("Website build", [npm, "run", "build"], PROJECT_ROOT / "website")
        if not args.no_package:
            run("Release packages", [python, "browser-takeover/scripts/release_tools.py", "package"])
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"\nVerification failed: {exc}", file=sys.stderr)
        return 1

    print("\nAll release checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
