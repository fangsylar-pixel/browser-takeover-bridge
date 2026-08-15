"""Persistent webpage monitoring state and comparison helpers."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path


RULE_TYPES = {
    "changed",
    "contains",
    "not_contains",
    "equals",
    "regex",
    "number_above",
    "number_below",
}


def default_store_path():
    override = os.environ.get("BROWSER_TAKEOVER_MONITOR_FILE")
    if override:
        return Path(override).expanduser().resolve()
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) / "BrowserTakeover" if base else Path.home() / ".browser-takeover"
    return root / "monitors.json"


def normalize_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return re.sub(r"\s+", " ", text).strip()


def content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_rule(rule):
    rule = dict(rule or {"type": "changed"})
    rule_type = rule.get("type", "changed")
    if rule_type not in RULE_TYPES:
        raise RuntimeError(f"Unsupported monitor rule type: {rule_type}")
    if rule_type in {"contains", "not_contains", "equals", "regex"} and rule.get("value") is None:
        raise RuntimeError(f"Monitor rule {rule_type} requires value")
    if rule_type in {"number_above", "number_below"}:
        try:
            rule["value"] = float(rule["value"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Monitor rule {rule_type} requires a numeric value") from exc
    rule["type"] = rule_type
    return rule


def extract_number(text, pattern=None):
    match = re.search(pattern or r"[-+]?\d[\d,]*(?:\.\d+)?", text)
    if not match:
        return None
    candidate = match.group(1) if match.lastindex else match.group(0)
    try:
        return float(candidate.replace(",", ""))
    except ValueError:
        return None


def evaluate_rule(rule, current, previous=None):
    rule = validate_rule(rule)
    rule_type = rule["type"]
    case_sensitive = bool(rule.get("caseSensitive", False))
    current_cmp = current if case_sensitive else current.casefold()
    expected = str(rule.get("value", ""))
    expected_cmp = expected if case_sensitive else expected.casefold()
    details = {}
    if rule_type == "changed":
        matched = previous is not None and current != previous
    elif rule_type == "contains":
        matched = expected_cmp in current_cmp
    elif rule_type == "not_contains":
        matched = expected_cmp not in current_cmp
    elif rule_type == "equals":
        matched = current_cmp == expected_cmp
    elif rule_type == "regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            match = re.search(expected, current, flags)
        except re.error as exc:
            raise RuntimeError(f"Invalid monitor regex: {exc}") from exc
        matched = bool(match)
        details["match"] = match.group(0) if match else None
    else:
        number = extract_number(current, rule.get("numberPattern"))
        threshold = float(rule["value"])
        matched = number is not None and (number > threshold if rule_type == "number_above" else number < threshold)
        details.update({"number": number, "threshold": threshold})
    return {"matched": matched, "type": rule_type, **details}


def compact_diff(previous, current, max_chars=6000):
    if previous is None:
        return ""
    lines = list(
        difflib.unified_diff(
            previous.splitlines(),
            current.splitlines(),
            fromfile="previous",
            tofile="current",
            lineterm="",
        )
    )
    return "\n".join(lines)[:max_chars]


class MonitorStore:
    def __init__(self, file_path=None, history_limit=100):
        self.path = Path(file_path or default_store_path()).expanduser().resolve()
        self.history_limit = max(2, min(int(history_limit), 1000))
        self.lock = threading.RLock()

    def _read_locked(self):
        if not self.path.exists():
            return {"version": 1, "monitors": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read monitor store: {exc}") from exc
        if not isinstance(data.get("monitors"), dict):
            raise RuntimeError("Monitor store is invalid")
        return data

    def _write_locked(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def create(self, name, url_pattern, target=None, rule=None, metadata=None):
        if not str(name or "").strip():
            raise RuntimeError("name is required")
        if not str(url_pattern or "").strip():
            raise RuntimeError("urlPattern is required")
        now = time.time()
        monitor_id = f"monitor_{secrets.token_urlsafe(12)}"
        monitor = {
            "monitorId": monitor_id,
            "name": str(name).strip(),
            "urlPattern": str(url_pattern).strip(),
            "target": dict(target or {}),
            "rule": validate_rule(rule),
            "status": "active",
            "metadata": dict(metadata or {}),
            "createdAt": now,
            "updatedAt": now,
            "lastCheckedAt": None,
            "lastChangedAt": None,
            "lastMatched": False,
            "history": [],
        }
        with self.lock:
            data = self._read_locked()
            data["monitors"][monitor_id] = monitor
            self._write_locked(data)
        return self._summary(monitor)

    def _get_locked(self, data, monitor_id):
        monitor = data["monitors"].get(monitor_id)
        if not monitor:
            raise RuntimeError("Monitor not found")
        return monitor

    def get(self, monitor_id, include_history=False):
        with self.lock:
            monitor = self._get_locked(self._read_locked(), monitor_id)
            return json.loads(json.dumps(monitor if include_history else self._summary(monitor)))

    def list(self, status=None):
        with self.lock:
            monitors = self._read_locked()["monitors"].values()
            return [self._summary(item) for item in monitors if not status or item.get("status") == status]

    def update(self, monitor_id, status=None, rule=None, name=None):
        with self.lock:
            data = self._read_locked()
            monitor = self._get_locked(data, monitor_id)
            if status is not None:
                if status not in {"active", "paused"}:
                    raise RuntimeError("status must be active or paused")
                monitor["status"] = status
            if rule is not None:
                monitor["rule"] = validate_rule(rule)
                monitor["lastMatched"] = False
            if name is not None:
                if not str(name).strip():
                    raise RuntimeError("name cannot be empty")
                monitor["name"] = str(name).strip()
            monitor["updatedAt"] = time.time()
            self._write_locked(data)
            return self._summary(monitor)

    def delete(self, monitor_id):
        with self.lock:
            data = self._read_locked()
            monitor = self._get_locked(data, monitor_id)
            data["monitors"].pop(monitor_id)
            self._write_locked(data)
            return {"deleted": True, "monitor": self._summary(monitor)}

    def record(self, monitor_id, content, source=None):
        current = normalize_text(content)
        if not current:
            raise RuntimeError("Monitored content is empty")
        with self.lock:
            data = self._read_locked()
            monitor = self._get_locked(data, monitor_id)
            if monitor.get("status") != "active":
                raise RuntimeError("Monitor is paused")
            history = monitor.setdefault("history", [])
            previous_entry = history[-1] if history else None
            previous = previous_entry.get("content") if previous_entry else None
            digest = content_hash(current)
            changed = previous_entry is not None and digest != previous_entry.get("hash")
            evaluation = evaluate_rule(monitor.get("rule"), current, previous)
            previously_matched = bool(monitor.get("lastMatched", False))
            checked_at = time.time()
            entry = {
                "checkedAt": checked_at,
                "hash": digest,
                "changed": changed,
                "matched": evaluation["matched"],
                "newlyTriggered": evaluation["matched"] and not previously_matched,
                "content": current,
                "source": dict(source or {}),
            }
            history.append(entry)
            monitor["history"] = history[-self.history_limit :]
            monitor["lastCheckedAt"] = checked_at
            monitor["lastChangedAt"] = checked_at if changed else monitor.get("lastChangedAt")
            monitor["lastMatched"] = evaluation["matched"]
            monitor["updatedAt"] = checked_at
            self._write_locked(data)
            return {
                "monitor": self._summary(monitor),
                "baselineCreated": previous_entry is None,
                "changed": changed,
                "condition": evaluation,
                "triggered": evaluation["matched"],
                "newlyTriggered": entry["newlyTriggered"],
                "previousHash": previous_entry.get("hash") if previous_entry else None,
                "currentHash": digest,
                "diff": compact_diff(previous, current),
                "currentPreview": current[:1000],
                "source": entry["source"],
            }

    def history(self, monitor_id, limit=20, include_content=False):
        limit = max(1, min(int(limit), self.history_limit))
        with self.lock:
            monitor = self._get_locked(self._read_locked(), monitor_id)
            rows = list(reversed(monitor.get("history", [])[-limit:]))
            if not include_content:
                rows = [{key: value for key, value in row.items() if key != "content"} for row in rows]
            return {"monitor": self._summary(monitor), "history": rows}

    @staticmethod
    def _summary(monitor):
        return {key: value for key, value in monitor.items() if key != "history"} | {
            "historyCount": len(monitor.get("history", []))
        }
