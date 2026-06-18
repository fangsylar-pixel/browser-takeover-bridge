#!/usr/bin/env python3
"""Benchmark readonly snapshots against already-open extension tabs."""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
import time
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SERVER_PATH = SCRIPT_DIR / "browser_takeover_mcp.py"


def load_server():
    spec = importlib.util.spec_from_file_location("browser_takeover_benchmark_server", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url-contains", action="append", default=[])
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--max-text", type=int, default=20000)
    parser.add_argument("--max-controls", type=int, default=500)
    parser.add_argument("--active-only", action="store_true")
    parser.add_argument("--max-tabs", type=int, default=0)
    args = parser.parse_args()

    server = load_server()
    server.start_extension_bridge()
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        diagnostics = server.BRIDGE_STATE.diagnostics()
        tabs = server.BRIDGE_STATE.all_tabs()
        healthy = [client for client in diagnostics["clients"] if client["health"]["polling"]]
        if healthy and tabs:
            break
        time.sleep(0.25)
    else:
        raise RuntimeError("No healthy extension client connected")

    client = max(healthy, key=lambda item: sum(bool(value) for value in item["health"].values()))
    client_id = client["clientId"]
    patterns = args.url_contains or [""]
    targets = [
        tab
        for tab in tabs
        if tab.get("clientId") == client_id
        and any(pattern in (tab.get("url") or "") for pattern in patterns)
        and (tab.get("url") or "").startswith(("http://", "https://"))
        and (not args.active_only or tab.get("active"))
    ]
    if args.max_tabs > 0:
        targets = targets[: args.max_tabs]
    if not targets:
        raise RuntimeError("No matching open tabs")

    report = {
        "client": client,
        "iterations": args.iterations,
        "targets": [],
    }
    for tab in targets:
        claim = server.BRIDGE_STATE.claim_tab(client_id, tab["id"], "benchmark", "readonly", 120)
        samples = []
        try:
            for _ in range(max(1, args.iterations)):
                started = time.perf_counter()
                command_id = server.BRIDGE_STATE.enqueue(
                    client_id,
                    {
                        "type": "action",
                        "tabId": tab["id"],
                        "action": {
                            "type": "snapshot",
                            "maxText": args.max_text,
                            "maxControls": args.max_controls,
                        },
                    },
                )
                try:
                    response = server.BRIDGE_STATE.wait_result(client_id, command_id, args.timeout)
                    elapsed = round((time.perf_counter() - started) * 1000, 3)
                    payload = response.get("result") or {}
                    value = payload.get("value") or {}
                    samples.append(
                        {
                            "ok": bool(response.get("ok") and payload.get("ok")),
                            "elapsedMs": elapsed,
                            "textLength": len(value.get("text") or ""),
                            "controlCount": len(value.get("controls") or []),
                            **({"error": response.get("error")} if response.get("error") else {}),
                        }
                    )
                except Exception as exc:
                    samples.append(
                        {
                            "ok": False,
                            "elapsedMs": round((time.perf_counter() - started) * 1000, 3),
                            "textLength": 0,
                            "controlCount": 0,
                            "error": str(exc),
                        }
                    )
        finally:
            server.BRIDGE_STATE.release_claim(claim["claimId"])
        elapsed_values = [sample["elapsedMs"] for sample in samples]
        report["targets"].append(
            {
                "tab": tab,
                "samples": samples,
                "successCount": sum(1 for sample in samples if sample["ok"]),
                "failureCount": sum(1 for sample in samples if not sample["ok"]),
                "medianMs": statistics.median(elapsed_values),
                "minMs": min(elapsed_values),
                "maxMs": max(elapsed_values),
            }
        )

    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
