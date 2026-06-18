#!/usr/bin/env python3
"""Minimal MCP server for attaching to local Chromium via CDP."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import random
import secrets
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def windows_system_input(action, viewport):
    if os.name != "nt":
        raise RuntimeError("System input is currently implemented on Windows only")
    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

    ratio = float(viewport.get("devicePixelRatio") or 1)
    origin_x = float(viewport.get("contentScreenX") or 0)
    origin_y = float(viewport.get("contentScreenY") or 0)

    def point(x, y):
        return round((origin_x + float(x)) * ratio), round((origin_y + float(y)) * ratio)

    window_title = str(viewport.get("title") or "")
    matched_windows = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def enum_window(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value
        if window_title and window_title in title:
            matched_windows.append((hwnd, title))
        return True

    user32.EnumWindows(WNDENUMPROC(enum_window), 0)
    root_hwnd = matched_windows[0][0] if matched_windows else 0
    if root_hwnd:
        user32.ShowWindow(root_hwnd, 9)
        foreground = user32.GetForegroundWindow()
        current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        target_thread = user32.GetWindowThreadProcessId(root_hwnd, None)
        if foreground_thread and target_thread and foreground_thread != target_thread:
            user32.AttachThreadInput(current_thread, foreground_thread, True)
            user32.AttachThreadInput(current_thread, target_thread, True)
        user32.SetForegroundWindow(root_hwnd)
        user32.BringWindowToTop(root_hwnd)
        if foreground_thread and target_thread and foreground_thread != target_thread:
            user32.AttachThreadInput(current_thread, target_thread, False)
            user32.AttachThreadInput(current_thread, foreground_thread, False)
        time.sleep(0.1)
    else:
        raise RuntimeError(f"Could not find browser window for page title: {window_title!r}")

    def move_cursor(x, y):
        user32.SetCursorPos(x, y)
        user32.mouse_event(0x0001, 0, 0, 0, 0)

    mouse_flags = {
        "left": (0x0002, 0x0004),
        "right": (0x0008, 0x0010),
        "middle": (0x0020, 0x0040),
    }

    action_type = action.get("type")
    if action_type == "nativeClick":
        x, y = point(action.get("x", 0), action.get("y", 0))
        button = action.get("button", "left")
        down, up = mouse_flags[button]
        move_cursor(x, y)
        for _ in range(max(1, min(int(action.get("clickCount", 1)), 3))):
            user32.mouse_event(down, 0, 0, 0, 0)
            user32.mouse_event(up, 0, 0, 0, 0)
        return {"ok": True, "type": action_type, "method": "windows-sendinput", "screenX": x, "screenY": y}
    if action_type == "nativeWheel":
        x, y = point(action.get("x", 0), action.get("y", 0))
        move_cursor(x, y)
        delta_y = int(action.get("deltaY", 0))
        delta_x = int(action.get("deltaX", 0))
        if delta_y:
            user32.mouse_event(0x0800, 0, 0, -delta_y, 0)
        if delta_x:
            user32.mouse_event(0x01000, 0, 0, delta_x, 0)
        return {"ok": True, "type": action_type, "method": "windows-sendinput", "screenX": x, "screenY": y}
    if action_type == "nativeDrag":
        points = action.get("points") or []
        if len(points) < 2:
            raise RuntimeError("nativeDrag requires at least two points")
        button = action.get("button", "left")
        down, up = mouse_flags[button]
        first = point(points[0]["x"], points[0]["y"])
        move_cursor(*first)
        user32.mouse_event(down, 0, 0, 0, 0)
        delay = max(0.005, min(float(action.get("stepDelay", 0.02)), 0.2))
        for item in points[1:]:
            move_cursor(*point(item["x"], item["y"]))
            time.sleep(delay)
        user32.mouse_event(up, 0, 0, 0, 0)
        last = point(points[-1]["x"], points[-1]["y"])
        return {"ok": True, "type": action_type, "method": "windows-sendinput", "screenX": last[0], "screenY": last[1]}
    if action_type == "nativeText":
        text = str(action.get("text", ""))
        INPUT_MOUSE = 0
        INPUT_KEYBOARD = 1
        INPUT_HARDWARE = 2
        KEYEVENTF_UNICODE = 0x0004
        KEYEVENTF_KEYUP = 0x0002
        ULONG_PTR = ctypes.c_size_t

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", ctypes.c_ulong),
                ("wParamL", ctypes.c_ushort),
                ("wParamH", ctypes.c_ushort),
            ]

        class INPUT_UNION(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]

        for char in text:
            code = ord(char)
            inputs = (INPUT * 2)(
                INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, 0))),
                INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0))),
            )
            sent = user32.SendInput(2, inputs, ctypes.sizeof(INPUT))
            if sent != 2:
                raise RuntimeError(f"SendInput wrote {sent} of 2 keyboard events")
        return {"ok": True, "type": action_type, "method": "windows-sendinput", "characters": len(text)}
    if action_type == "nativeKey":
        key_map = {
            "Enter": 0x0D,
            "Tab": 0x09,
            "Escape": 0x1B,
            "Backspace": 0x08,
            "Delete": 0x2E,
            "ArrowLeft": 0x25,
            "ArrowUp": 0x26,
            "ArrowRight": 0x27,
            "ArrowDown": 0x28,
            "Home": 0x24,
            "End": 0x23,
            "PageUp": 0x21,
            "PageDown": 0x22,
            "Space": 0x20,
        }
        key = str(action.get("key", "Enter"))
        vk = key_map.get(key, ord(key.upper()) if len(key) == 1 else None)
        if vk is None:
            raise RuntimeError(f"Unsupported native key: {key}")
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 0x0002, 0)
        return {"ok": True, "type": action_type, "method": "windows-sendinput", "key": key}
    raise RuntimeError(f"Unsupported system input action: {action_type}")


DEFAULT_PORTS = [9222, 9223, 9333]
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 17321
SERVER_NAME = "browser-takeover"


class ExtensionBridgeState:
    def __init__(self):
        self.lock = threading.Lock()
        self.clients = {}
        self.tabs = {}
        self.commands = {}
        self.results = {}
        self.claims = {}
        self.events = []
        self.next_event_id = 1
        self.next_command_id = 1

    def register(self, client_id, payload):
        now = time.time()
        with self.lock:
            existing = self.clients.get(client_id) or {}
            token = existing.get("token") or secrets.token_urlsafe(32)
            self.clients[client_id] = {
                "clientId": client_id,
                "browser": payload.get("browser"),
                "userAgent": payload.get("userAgent"),
                "protocolVersion": payload.get("protocolVersion", 1),
                "capabilities": payload.get("capabilities") or [],
                "token": token,
                "registeredAt": existing.get("registeredAt") or now,
                "lastRegisteredAt": now,
                "lastTabsAt": existing.get("lastTabsAt"),
                "lastPollAt": existing.get("lastPollAt"),
                "lastResultAt": existing.get("lastResultAt"),
                "lastSeen": now,
            }
            return token

    def authenticate(self, client_id, token):
        with self.lock:
            client = self.clients.get(client_id)
            if not client:
                return False
            if client.get("protocolVersion", 1) < 2:
                return True
            return bool(token and secrets.compare_digest(client.get("token", ""), token))

    def update_tabs(self, client_id, tabs):
        now = time.time()
        with self.lock:
            if client_id in self.clients:
                self.clients[client_id]["lastSeen"] = now
                self.clients[client_id]["lastTabsAt"] = now
            self.tabs[client_id] = tabs or []

    def status(self):
        with self.lock:
            now = time.time()
            clients = [
                {
                    **{key: value for key, value in client.items() if key != "token"},
                    "health": self._client_health_locked(client, now),
                }
                for client in self.clients.values()
            ]
            return {
                "bridge": {"host": BRIDGE_HOST, "port": BRIDGE_PORT},
                "clients": clients,
                "tabCount": sum(len(tabs) for tabs in self.tabs.values()),
                "claimCount": len(self._active_claims_locked()),
            }

    def _client_health_locked(self, client, now=None):
        now = now or time.time()
        last_poll = client.get("lastPollAt")
        last_tabs = client.get("lastTabsAt")
        return {
            "registered": bool(client.get("lastRegisteredAt") and now - client["lastRegisteredAt"] <= 15),
            "tabsFresh": bool(last_tabs and now - last_tabs <= 10),
            "polling": bool(last_poll and now - last_poll <= 5),
            "roundTrip": bool(client.get("lastResultAt")),
        }

    def all_tabs(self):
        with self.lock:
            rows = []
            for client_id, tabs in self.tabs.items():
                for tab in tabs:
                    item = dict(tab)
                    item["clientId"] = client_id
                    rows.append(item)
            return rows

    def latest_client_id(self):
        with self.lock:
            if not self.clients:
                return None
            return max(self.clients.values(), key=lambda client: client.get("lastSeen", 0)).get("clientId")

    def enqueue(self, client_id, command):
        with self.lock:
            command_id = str(self.next_command_id)
            self.next_command_id += 1
            command = dict(command)
            command["id"] = command_id
            self.commands.setdefault(client_id, []).append(command)
            return command_id

    def poll(self, client_id):
        now = time.time()
        with self.lock:
            if client_id in self.clients:
                self.clients[client_id]["lastSeen"] = now
                self.clients[client_id]["lastPollAt"] = now
            queue = self.commands.setdefault(client_id, [])
            if queue:
                return queue.pop(0)
            return None

    def complete(self, client_id, command_id, payload):
        with self.lock:
            if client_id in self.clients:
                now = time.time()
                self.clients[client_id]["lastSeen"] = now
                self.clients[client_id]["lastResultAt"] = now
            self.results[(client_id, command_id)] = payload

    def diagnostics(self):
        with self.lock:
            now = time.time()
            clients = []
            for client_id, client in self.clients.items():
                clients.append(
                    {
                        "clientId": client_id,
                        "protocolVersion": client.get("protocolVersion", 1),
                        "capabilities": list(client.get("capabilities") or []),
                        "tabCount": len(self.tabs.get(client_id) or []),
                        "queuedCommands": len(self.commands.get(client_id) or []),
                        "pendingResults": sum(1 for key in self.results if key[0] == client_id),
                        "health": self._client_health_locked(client, now),
                        "ages": {
                            "registrationSeconds": round(now - client["lastRegisteredAt"], 3) if client.get("lastRegisteredAt") else None,
                            "tabSyncSeconds": round(now - client["lastTabsAt"], 3) if client.get("lastTabsAt") else None,
                            "pollSeconds": round(now - client["lastPollAt"], 3) if client.get("lastPollAt") else None,
                            "resultSeconds": round(now - client["lastResultAt"], 3) if client.get("lastResultAt") else None,
                        },
                    }
                )
            return {
                "bridge": {"host": BRIDGE_HOST, "port": BRIDGE_PORT, "protocolVersion": 2},
                "clients": clients,
                "claims": [dict(claim) for claim in self._active_claims_locked().values()],
                "latestEventId": self.events[-1]["eventId"] if self.events else 0,
            }

    def record_events(self, client_id, events):
        now = time.time()
        with self.lock:
            if client_id in self.clients:
                self.clients[client_id]["lastSeen"] = now
            recorded = []
            for event in events or []:
                item = {
                    "eventId": self.next_event_id,
                    "clientId": client_id,
                    "type": event.get("type") or "unknown",
                    "timestamp": event.get("timestamp") or now,
                    "tabId": event.get("tabId"),
                    "details": event.get("details") or {},
                }
                self.next_event_id += 1
                self.events.append(item)
                recorded.append(dict(item))
            if len(self.events) > 1000:
                self.events = self.events[-1000:]
            return recorded

    def list_events(self, after_id=0, limit=100, client_id=None):
        limit = max(1, min(int(limit), 500))
        after_id = int(after_id or 0)
        with self.lock:
            rows = [
                dict(event)
                for event in self.events
                if event["eventId"] > after_id and (not client_id or event["clientId"] == client_id)
            ]
            return rows[:limit]

    def wait_event(self, after_id=0, event_type=None, client_id=None, tab_id=None, download_id=None, timeout=10):
        deadline = time.time() + max(0, float(timeout))
        while time.time() <= deadline:
            events = self.list_events(after_id=after_id, limit=500, client_id=client_id)
            for event in events:
                if event_type and event["type"] != event_type:
                    continue
                if tab_id is not None and str(event.get("tabId")) != str(tab_id):
                    continue
                if download_id is not None and str(event.get("details", {}).get("downloadId")) != str(download_id):
                    continue
                return event
            time.sleep(0.1)
        raise RuntimeError(f"Timed out waiting for browser event: {event_type or 'any'}")

    def wait_result(self, client_id, command_id, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                key = (client_id, command_id)
                if key in self.results:
                    return self.results.pop(key)
            time.sleep(0.1)
        raise RuntimeError(f"Timed out waiting for extension command {command_id}")

    def _active_claims_locked(self):
        now = time.time()
        expired = [claim_id for claim_id, claim in self.claims.items() if claim["expiresAt"] <= now]
        for claim_id in expired:
            self.claims.pop(claim_id, None)
        return self.claims

    def claim_tab(self, extension_client_id, tab_id, owner, mode="interactive", ttl=60):
        ttl = max(10, min(int(ttl), 3600))
        mode = mode if mode in ("readonly", "interactive") else "interactive"
        now = time.time()
        with self.lock:
            claims = self._active_claims_locked()
            for claim in claims.values():
                same_tab = claim["extensionClientId"] == extension_client_id and str(claim["tabId"]) == str(tab_id)
                write_conflict = mode == "interactive" or claim["mode"] == "interactive"
                if same_tab and write_conflict and claim["owner"] != owner:
                    raise RuntimeError("Tab is already claimed by another interactive owner")
            claim_id = f"claim_{secrets.token_urlsafe(18)}"
            claim = {
                "claimId": claim_id,
                "extensionClientId": extension_client_id,
                "tabId": tab_id,
                "owner": owner,
                "mode": mode,
                "createdAt": now,
                "expiresAt": now + ttl,
            }
            claims[claim_id] = claim
            return dict(claim)

    def require_claim(self, claim_id, write=False):
        with self.lock:
            claim = self._active_claims_locked().get(claim_id)
            if not claim:
                raise RuntimeError("Claim is missing or expired")
            if write and claim["mode"] != "interactive":
                raise RuntimeError("Readonly claim cannot perform write actions")
            return dict(claim)

    def renew_claim(self, claim_id, ttl=60):
        ttl = max(10, min(int(ttl), 3600))
        with self.lock:
            claim = self._active_claims_locked().get(claim_id)
            if not claim:
                raise RuntimeError("Claim is missing or expired")
            claim["expiresAt"] = time.time() + ttl
            return dict(claim)

    def release_claim(self, claim_id):
        with self.lock:
            return self.claims.pop(claim_id, None)

    def list_claims(self):
        with self.lock:
            return [dict(claim) for claim in self._active_claims_locked().values()]


BRIDGE_STATE = ExtensionBridgeState()
BRIDGE_SERVER = None


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.decode("ascii", errors="replace").strip()
        if line == "":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def write_message(message):
    body = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def result(request_id, payload):
    write_message({"jsonrpc": "2.0", "id": request_id, "result": payload})


def error(request_id, code, message):
    write_message({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def tool_text(payload):
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}]}


def http_json(url, timeout=1.5, method="GET"):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read().decode("utf-8")
    return json.loads(data) if data else None


def read_http_body(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw) if raw else {}


def write_http_json(handler, payload, status=200):
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    origin = handler.headers.get("Origin", "")
    if origin.startswith(("chrome-extension://", "edge-extension://")):
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Vary", "Origin")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, X-Browser-Takeover-Token")
    handler.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_OPTIONS(self):
        origin = self.headers.get("Origin", "")
        if origin and not origin.startswith(("chrome-extension://", "edge-extension://")):
            write_http_json(self, {"ok": False, "error": "origin not allowed"}, 403)
            return
        write_http_json(self, {"ok": True})

    def authenticated(self, client_id):
        token = self.headers.get("X-Browser-Takeover-Token", "")
        return BRIDGE_STATE.authenticate(client_id, token)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/bridge/status":
            write_http_json(self, {"ok": True, **BRIDGE_STATE.status()})
            return
        if parsed.path == "/extension/poll":
            client_id = (query.get("clientId") or [""])[0]
            if not client_id:
                write_http_json(self, {"ok": False, "error": "clientId is required"}, 400)
                return
            if not self.authenticated(client_id):
                write_http_json(self, {"ok": False, "error": "unauthorized"}, 401)
                return
            command = BRIDGE_STATE.poll(client_id)
            write_http_json(self, {"ok": True, "command": command})
            return
        write_http_json(self, {"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            payload = read_http_body(self)
            client_id = payload.get("clientId")
            if parsed.path == "/extension/register":
                if not client_id:
                    write_http_json(self, {"ok": False, "error": "clientId is required"}, 400)
                    return
                token = BRIDGE_STATE.register(client_id, payload)
                write_http_json(
                    self,
                    {
                        "ok": True,
                        "token": token,
                        "protocolVersion": 2,
                        "pollIntervalMs": 250,
                    },
                )
                return
            if parsed.path == "/extension/tabs":
                if not client_id:
                    write_http_json(self, {"ok": False, "error": "clientId is required"}, 400)
                    return
                if not self.authenticated(client_id):
                    write_http_json(self, {"ok": False, "error": "unauthorized"}, 401)
                    return
                BRIDGE_STATE.update_tabs(client_id, payload.get("tabs") or [])
                write_http_json(self, {"ok": True})
                return
            if parsed.path == "/extension/result":
                command_id = payload.get("commandId")
                if not client_id or not command_id:
                    write_http_json(self, {"ok": False, "error": "clientId and commandId are required"}, 400)
                    return
                if not self.authenticated(client_id):
                    write_http_json(self, {"ok": False, "error": "unauthorized"}, 401)
                    return
                BRIDGE_STATE.complete(client_id, command_id, payload)
                write_http_json(self, {"ok": True})
                return
            if parsed.path == "/extension/events":
                if not client_id:
                    write_http_json(self, {"ok": False, "error": "clientId is required"}, 400)
                    return
                if not self.authenticated(client_id):
                    write_http_json(self, {"ok": False, "error": "unauthorized"}, 401)
                    return
                recorded = BRIDGE_STATE.record_events(client_id, payload.get("events") or [])
                write_http_json(self, {"ok": True, "recorded": len(recorded)})
                return
            write_http_json(self, {"ok": False, "error": "not found"}, 404)
        except Exception as exc:
            write_http_json(self, {"ok": False, "error": str(exc)}, 500)


def start_extension_bridge():
    global BRIDGE_SERVER
    if BRIDGE_SERVER:
        return {"host": BRIDGE_HOST, "port": BRIDGE_PORT, "started": False, "alreadyRunning": True}
    try:
        BRIDGE_SERVER = ThreadingHTTPServer((BRIDGE_HOST, BRIDGE_PORT), BridgeHandler)
    except OSError as exc:
        return {"host": BRIDGE_HOST, "port": BRIDGE_PORT, "started": False, "error": str(exc)}
    thread = threading.Thread(target=BRIDGE_SERVER.serve_forever, daemon=True)
    thread.start()
    return {"host": BRIDGE_HOST, "port": BRIDGE_PORT, "started": True}


def cdp_base(host="127.0.0.1", port=9222):
    return f"http://{host}:{int(port)}"


def cdp_version(host="127.0.0.1", port=9222):
    return http_json(f"{cdp_base(host, port)}/json/version")


def cdp_pages(host="127.0.0.1", port=9222):
    pages = http_json(f"{cdp_base(host, port)}/json/list")
    return pages or []


def choose_page(host, port, page_id=None):
    pages = cdp_pages(host, port)
    if page_id:
        for page in pages:
            if page.get("id") == page_id:
                return page
        raise RuntimeError(f"No page with id {page_id!r} on {host}:{port}")
    for page in pages:
        if page.get("type") == "page" and page.get("webSocketDebuggerUrl"):
            return page
    raise RuntimeError(f"No attachable page found on {host}:{port}")


def discover_ports(host="127.0.0.1", ports=None):
    reachable = []
    for port in ports or DEFAULT_PORTS:
        try:
            version = cdp_version(host, port)
            pages = cdp_pages(host, port)
            reachable.append(
                {
                    "host": host,
                    "port": port,
                    "browser": version.get("Browser"),
                    "protocolVersion": version.get("Protocol-Version"),
                    "webSocketDebuggerUrl": version.get("webSocketDebuggerUrl"),
                    "pageCount": len(pages),
                }
            )
        except Exception as exc:
            reachable.append({"host": host, "port": port, "reachable": False, "error": str(exc)})
    return reachable


def browser_processes():
    if os.name != "nt":
        return []
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -in @('chrome.exe','msedge.exe') } | "
        "Select-Object Name,ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=4,
        )
        raw = completed.stdout.strip()
        if not raw:
            return []
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            parsed = [parsed]
        return parsed
    except Exception as exc:
        return [{"error": f"Could not inspect browser processes: {exc}"}]


def find_browser_exe(browser):
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = []
    if browser == "edge":
        candidates = [
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
            local / "Microsoft/Edge/Application/msedge.exe",
        ]
    elif browser == "chrome":
        candidates = [
            Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
            local / "Google/Chrome/Application/chrome.exe",
        ]
    else:
        raise RuntimeError("browser must be 'edge' or 'chrome'")
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise RuntimeError(f"Could not find {browser} executable")


def launch_browser(browser="edge", port=9222, url="about:blank", user_data_dir=None):
    exe = find_browser_exe(browser)
    if not user_data_dir:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "CodexBrowserTakeover"
        user_data_dir = str(base / f"{browser}-profile")
    Path(user_data_dir).mkdir(parents=True, exist_ok=True)
    args = [
        exe,
        f"--remote-debugging-port={int(port)}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        url or "about:blank",
    ]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 8
    last_error = None
    while time.time() < deadline:
        try:
            version = cdp_version("127.0.0.1", port)
            return {"launched": True, "browser": browser, "port": int(port), "userDataDir": user_data_dir, "version": version}
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.25)
    return {"launched": True, "browser": browser, "port": int(port), "userDataDir": user_data_dir, "cdpReady": False, "error": last_error}


class CdpWebSocket:
    def __init__(self, ws_url):
        parsed = urllib.parse.urlparse(ws_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        self.path = parsed.path
        if parsed.query:
            self.path += "?" + parsed.query
        raw_sock = socket.create_connection((self.host, self.port), timeout=5)
        if parsed.scheme == "wss":
            raw_sock = ssl.create_default_context().wrap_socket(raw_sock, server_hostname=self.host)
        self.sock = raw_sock
        self.next_id = 1
        self._handshake()

    def _handshake(self):
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            response += chunk
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError("WebSocket handshake failed")
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest())
        if accept not in response:
            raise RuntimeError("WebSocket accept header mismatch")

    def send_json(self, payload):
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = random.randbytes(4) if hasattr(random, "randbytes") else os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def recv_json(self):
        first = self.sock.recv(2)
        if len(first) < 2:
            raise RuntimeError("WebSocket closed")
        opcode = first[0] & 0x0F
        masked = bool(first[1] & 0x80)
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self.sock.recv(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self.sock.recv(8))[0]
        mask = self.sock.recv(4) if masked else b""
        data = b""
        while len(data) < length:
            data += self.sock.recv(length - len(data))
        if masked:
            data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        if opcode == 8:
            raise RuntimeError("WebSocket closed by browser")
        if opcode not in (1, 2):
            return self.recv_json()
        return json.loads(data.decode("utf-8"))

    def call(self, method, params=None, timeout=10):
        call_id = self.next_id
        self.next_id += 1
        self.sock.settimeout(timeout)
        self.send_json({"id": call_id, "method": method, "params": params or {}})
        while True:
            message = self.recv_json()
            if message.get("id") == call_id:
                if "error" in message:
                    raise RuntimeError(json.dumps(message["error"], ensure_ascii=False))
                return message.get("result", {})

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def cdp_call(host, port, method, params=None, page_id=None):
    page = choose_page(host, port, page_id)
    ws = CdpWebSocket(page["webSocketDebuggerUrl"])
    try:
        return {"page": {"id": page.get("id"), "title": page.get("title"), "url": page.get("url")}, "result": ws.call(method, params or {})}
    finally:
        ws.close()


def handle_tool(name, args):
    args = args or {}
    host = args.get("host", "127.0.0.1")
    port = int(args.get("port", 9222))
    if name == "browser_takeover_extension_bridge_status":
        bridge = start_extension_bridge()
        return {**BRIDGE_STATE.status(), "startup": bridge}
    if name == "browser_takeover_extension_diagnostics":
        bridge = start_extension_bridge()
        return {**BRIDGE_STATE.diagnostics(), "startup": bridge}
    if name == "browser_takeover_extension_events":
        start_extension_bridge()
        events = BRIDGE_STATE.list_events(
            after_id=args.get("afterId", 0),
            limit=args.get("limit", 100),
            client_id=args.get("clientId"),
        )
        return {
            "events": events,
            "latestEventId": events[-1]["eventId"] if events else int(args.get("afterId", 0) or 0),
        }
    if name == "browser_takeover_extension_wait_event":
        start_extension_bridge()
        event = BRIDGE_STATE.wait_event(
            after_id=args.get("afterId", 0),
            event_type=args.get("type"),
            client_id=args.get("clientId"),
            tab_id=args.get("tabId"),
            download_id=args.get("downloadId"),
            timeout=args.get("timeout", 10),
        )
        return {"event": event, "latestEventId": event["eventId"]}
    if name == "browser_takeover_extension_list_tabs":
        start_extension_bridge()
        return {"tabs": BRIDGE_STATE.all_tabs(), "claims": BRIDGE_STATE.list_claims(), "protocolVersion": 2}
    if name == "browser_takeover_claim_tab":
        start_extension_bridge()
        client_id = args.get("clientId")
        tab_id = args.get("tabId")
        if not client_id or tab_id is None:
            raise RuntimeError("clientId and tabId are required")
        known = any(
            tab.get("clientId") == client_id and str(tab.get("id")) == str(tab_id)
            for tab in BRIDGE_STATE.all_tabs()
        )
        if not known:
            raise RuntimeError("Tab is not currently reported by the extension")
        claim = BRIDGE_STATE.claim_tab(
            client_id,
            tab_id,
            owner=args.get("owner") or "mcp-client",
            mode=args.get("mode", "interactive"),
            ttl=args.get("ttl", 60),
        )
        return {"claim": claim}
    if name == "browser_takeover_renew_claim":
        return {"claim": BRIDGE_STATE.renew_claim(args.get("claimId"), args.get("ttl", 60))}
    if name == "browser_takeover_release_tab":
        claim_id = args.get("claimId")
        if not claim_id:
            raise RuntimeError("claimId is required")
        claim = BRIDGE_STATE.release_claim(claim_id)
        return {"released": bool(claim), "claim": claim}
    if name == "browser_takeover_extension_action":
        start_extension_bridge()
        claim = BRIDGE_STATE.require_claim(
            args.get("claimId"),
            write=(args.get("action") or {}).get("type") not in ("read", "snapshot", "wait"),
        )
        action = args.get("action") or {}
        if not action.get("type"):
            raise RuntimeError("action.type is required")
        command_id = BRIDGE_STATE.enqueue(
            claim["extensionClientId"],
            {"type": "action", "tabId": claim["tabId"], "action": action},
        )
        response = BRIDGE_STATE.wait_result(
            claim["extensionClientId"],
            command_id,
            float(args.get("timeout", 10)),
        )
        BRIDGE_STATE.renew_claim(claim["claimId"], args.get("renewTtl", 60))
        return response
    if name == "browser_takeover_extension_batch_snapshot":
        start_extension_bridge()
        targets = args.get("tabs") or []
        if not targets:
            raise RuntimeError("tabs is required")
        if len(targets) > 20:
            raise RuntimeError("At most 20 tabs can be snapshotted in one batch")
        known_tabs = {
            (tab.get("clientId"), str(tab.get("id"))): tab
            for tab in BRIDGE_STATE.all_tabs()
        }
        claims = []
        commands = []
        try:
            for target in targets:
                client_id = target.get("clientId")
                tab_id = target.get("tabId")
                if not client_id or tab_id is None:
                    raise RuntimeError("Each tab requires clientId and tabId")
                if (client_id, str(tab_id)) not in known_tabs:
                    raise RuntimeError(f"Tab is not currently reported: {client_id}/{tab_id}")
                claim = BRIDGE_STATE.claim_tab(
                    client_id,
                    tab_id,
                    owner=args.get("owner") or "batch-snapshot",
                    mode="readonly",
                    ttl=max(30, int(args.get("timeout", 10)) + 10),
                )
                claims.append(claim)
                command_id = BRIDGE_STATE.enqueue(
                    client_id,
                    {
                        "type": "action",
                        "tabId": tab_id,
                        "action": {
                            "type": "snapshot",
                            "maxText": args.get("maxText", 20000),
                            "maxControls": args.get("maxControls", 500),
                        },
                    },
                )
                commands.append((target, client_id, command_id))
            results = []
            for target, client_id, command_id in commands:
                try:
                    response = BRIDGE_STATE.wait_result(client_id, command_id, float(args.get("timeout", 10)))
                    results.append({"target": target, "ok": bool(response.get("ok")), "response": response})
                except Exception as exc:
                    results.append({"target": target, "ok": False, "error": str(exc)})
            return {
                "ok": all(result["ok"] for result in results),
                "count": len(results),
                "results": results,
            }
        finally:
            for claim in claims:
                BRIDGE_STATE.release_claim(claim["claimId"])
    if name == "browser_takeover_extension_upload":
        start_extension_bridge()
        claim = BRIDGE_STATE.require_claim(args.get("claimId"), write=True)
        file_path = Path(args.get("filePath") or "").expanduser().resolve()
        if not file_path.is_file():
            raise RuntimeError("filePath must point to an existing file")
        size = file_path.stat().st_size
        max_bytes = int(args.get("maxBytes", 25 * 1024 * 1024))
        if size > max_bytes:
            raise RuntimeError(f"File is too large ({size} bytes); maximum is {max_bytes}")
        mime_type = args.get("mimeType") or "application/octet-stream"
        data_url = f"data:{mime_type};base64,{base64.b64encode(file_path.read_bytes()).decode('ascii')}"
        action = {
            "type": "upload",
            "target": args.get("target") or {"css": 'input[type="file"]'},
            "dataUrl": data_url,
            "fileName": args.get("fileName") or file_path.name,
            "mimeType": mime_type,
        }
        if args.get("frameId") is not None:
            action["frameId"] = args.get("frameId")
        if args.get("frameScope"):
            action["frameScope"] = args.get("frameScope")
        if args.get("expect"):
            action["expect"] = args.get("expect")
        command_id = BRIDGE_STATE.enqueue(
            claim["extensionClientId"],
            {"type": "action", "tabId": claim["tabId"], "action": action},
        )
        response = BRIDGE_STATE.wait_result(
            claim["extensionClientId"],
            command_id,
            float(args.get("timeout", 20)),
        )
        BRIDGE_STATE.renew_claim(claim["claimId"], args.get("renewTtl", 60))
        return response
    if name == "browser_takeover_extension_workflow":
        start_extension_bridge()
        steps = args.get("steps") or []
        if not steps:
            raise RuntimeError("steps is required")
        if len(steps) > 100:
            raise RuntimeError("At most 100 workflow steps are allowed")
        readonly_types = {"read", "snapshot", "wait"}
        requires_write = any((step.get("action") or {}).get("type") not in readonly_types for step in steps)
        claim = BRIDGE_STATE.require_claim(args.get("claimId"), write=requires_write)
        workflow_started = time.time()
        results = []
        stopped = False
        for index, step in enumerate(steps):
            action = step.get("action") or {}
            if not action.get("type"):
                raise RuntimeError(f"steps[{index}].action.type is required")
            attempts = max(1, min(int(step.get("attempts", 1)), 5))
            delay = max(0, min(float(step.get("retryDelay", 0.25)), 10))
            step_result = None
            for attempt in range(1, attempts + 1):
                command_id = BRIDGE_STATE.enqueue(
                    claim["extensionClientId"],
                    {"type": "action", "tabId": claim["tabId"], "action": action},
                )
                try:
                    response = BRIDGE_STATE.wait_result(
                        claim["extensionClientId"],
                        command_id,
                        float(step.get("timeout", args.get("timeout", 15))),
                    )
                    ok = bool(response.get("ok") and (response.get("result") or {}).get("ok"))
                    step_result = {
                        "index": index,
                        "name": step.get("name") or f"step-{index + 1}",
                        "attempt": attempt,
                        "ok": ok,
                        "response": response,
                    }
                    if ok:
                        break
                except Exception as exc:
                    step_result = {
                        "index": index,
                        "name": step.get("name") or f"step-{index + 1}",
                        "attempt": attempt,
                        "ok": False,
                        "error": str(exc),
                    }
                if attempt < attempts:
                    time.sleep(delay)
            results.append(step_result)
            if not step_result["ok"] and step.get("onError", "stop") != "continue":
                stopped = True
                break
        BRIDGE_STATE.renew_claim(claim["claimId"], args.get("renewTtl", 60))
        return {
            "ok": all(result["ok"] for result in results) and len(results) == len(steps),
            "stopped": stopped,
            "completedSteps": len(results),
            "totalSteps": len(steps),
            "durationMs": round((time.time() - workflow_started) * 1000),
            "results": results,
        }
    if name == "browser_takeover_extension_download":
        start_extension_bridge()
        client_id = args.get("clientId") or BRIDGE_STATE.latest_client_id()
        if not client_id:
            raise RuntimeError("No connected extension client found")
        url = args.get("url")
        if not url:
            raise RuntimeError("url is required")
        command_id = BRIDGE_STATE.enqueue(
            client_id,
            {
                "type": "downloadUrl",
                "url": url,
                "filename": args.get("filename"),
                "saveAs": bool(args.get("saveAs", False)),
                "conflictAction": args.get("conflictAction", "uniquify"),
            },
        )
        return BRIDGE_STATE.wait_result(client_id, command_id, float(args.get("timeout", 20)))
    if name == "browser_takeover_extension_download_status":
        start_extension_bridge()
        client_id = args.get("clientId") or BRIDGE_STATE.latest_client_id()
        if not client_id:
            raise RuntimeError("No connected extension client found")
        command_id = BRIDGE_STATE.enqueue(
            client_id,
            {"type": "downloadStatus", "downloadId": args.get("downloadId")},
        )
        return BRIDGE_STATE.wait_result(client_id, command_id, float(args.get("timeout", 10)))
    if name == "browser_takeover_extension_full_screenshot":
        start_extension_bridge()
        claim = BRIDGE_STATE.require_claim(args.get("claimId"), write=False)
        command_id = BRIDGE_STATE.enqueue(
            claim["extensionClientId"],
            {
                "type": "fullPageScreenshot",
                "tabId": claim["tabId"],
                "format": args.get("format", "png"),
                "quality": args.get("quality", 90),
                "scale": args.get("scale", 1),
            },
        )
        capture = BRIDGE_STATE.wait_result(
            claim["extensionClientId"],
            command_id,
            float(args.get("timeout", 30)),
        )
        output_path = args.get("outputPath")
        data_url = capture.get("result", {}).get("dataUrl")
        if output_path and data_url:
            _, encoded = data_url.split(",", 1)
            path = Path(output_path).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(encoded))
            capture["outputPath"] = str(path)
            capture["result"].pop("dataUrl", None)
        return capture
    if name == "browser_takeover_extension_native_input":
        start_extension_bridge()
        claim = BRIDGE_STATE.require_claim(args.get("claimId"), write=True)
        action = args.get("action") or {}
        if action.get("type") not in {"nativeClick", "nativeWheel", "nativeDrag", "nativeText", "nativeKey"}:
            raise RuntimeError("Unsupported native input action type")
        command_id = BRIDGE_STATE.enqueue(
            claim["extensionClientId"],
            {"type": "prepareSystemInput", "tabId": claim["tabId"]},
        )
        prepared = BRIDGE_STATE.wait_result(
            claim["extensionClientId"],
            command_id,
            float(args.get("timeout", 10)),
        )
        if not prepared.get("ok") or not (prepared.get("result") or {}).get("ok"):
            return prepared
        time.sleep(max(0, min(float(args.get("focusDelay", 0.15)), 2)))
        result = windows_system_input(action, prepared["result"])
        BRIDGE_STATE.renew_claim(claim["claimId"], args.get("renewTtl", 60))
        return {
            "ok": True,
            "result": result,
            "viewport": prepared["result"],
        }
    if name == "browser_takeover_extension_handle_dialog":
        start_extension_bridge()
        claim = BRIDGE_STATE.require_claim(args.get("claimId"), write=True)
        command_id = BRIDGE_STATE.enqueue(
            claim["extensionClientId"],
            {
                "type": "handleDialog",
                "tabId": claim["tabId"],
                "accept": bool(args.get("accept", True)),
                "promptText": args.get("promptText", ""),
            },
        )
        return BRIDGE_STATE.wait_result(
            claim["extensionClientId"],
            command_id,
            float(args.get("timeout", 10)),
        )
    if name == "browser_takeover_extension_advanced_control":
        start_extension_bridge()
        client_id = args.get("clientId") or BRIDGE_STATE.latest_client_id()
        if not client_id:
            raise RuntimeError("No connected extension client found")
        command_id = BRIDGE_STATE.enqueue(
            client_id,
            {"type": "advancedControl", "enabled": bool(args.get("enabled", True))},
        )
        response = BRIDGE_STATE.wait_result(client_id, command_id, float(args.get("timeout", 10)))
        return {**response, "diagnostics": BRIDGE_STATE.diagnostics()}
    if name == "browser_takeover_extension_reload":
        start_extension_bridge()
        client_id = args.get("clientId") or BRIDGE_STATE.latest_client_id()
        if not client_id:
            raise RuntimeError("No connected extension client found")
        command_id = BRIDGE_STATE.enqueue(client_id, {"type": "reload"})
        return {
            "clientId": client_id,
            "commandId": command_id,
            "queued": True,
            "note": "The extension reloads itself and may not return a command result.",
        }
    if name == "browser_takeover_extension_evaluate":
        start_extension_bridge()
        client_id = args.get("clientId")
        tab_id = args.get("tabId")
        expression = args.get("expression")
        if not client_id or tab_id is None or not expression:
            raise RuntimeError("clientId, tabId, and expression are required")
        command_id = BRIDGE_STATE.enqueue(
            client_id,
            {"type": "evaluate", "tabId": tab_id, "expression": expression, "awaitPromise": bool(args.get("awaitPromise", True))},
        )
        return BRIDGE_STATE.wait_result(client_id, command_id, float(args.get("timeout", 10)))
    if name == "browser_takeover_extension_navigate":
        start_extension_bridge()
        client_id = args.get("clientId")
        tab_id = args.get("tabId")
        url = args.get("url")
        if not client_id or tab_id is None or not url:
            raise RuntimeError("clientId, tabId, and url are required")
        command_id = BRIDGE_STATE.enqueue(client_id, {"type": "navigate", "tabId": tab_id, "url": url})
        return BRIDGE_STATE.wait_result(client_id, command_id, float(args.get("timeout", 10)))
    if name == "browser_takeover_extension_screenshot":
        start_extension_bridge()
        client_id = args.get("clientId")
        tab_id = args.get("tabId")
        if not client_id or tab_id is None:
            raise RuntimeError("clientId and tabId are required")
        command_id = BRIDGE_STATE.enqueue(
            client_id,
            {
                "type": "screenshot",
                "tabId": tab_id,
                "format": args.get("format", "png"),
                "selector": args.get("selector"),
                "clip": args.get("clip"),
            },
        )
        capture = BRIDGE_STATE.wait_result(client_id, command_id, float(args.get("timeout", 10)))
        output_path = args.get("outputPath")
        data_url = capture.get("result", {}).get("dataUrl")
        if output_path and data_url:
            _, encoded = data_url.split(",", 1)
            path = Path(output_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(encoded))
            capture["outputPath"] = str(path)
            capture["result"].pop("dataUrl", None)
        return capture
    if name == "browser_takeover_status":
        bridge = start_extension_bridge()
        ports = args.get("ports") or DEFAULT_PORTS
        return {
            "processes": browser_processes(),
            "ports": discover_ports(host, ports),
            "extensionBridge": {**BRIDGE_STATE.status(), "startup": bridge},
            "note": "An existing browser is attachable only when it was launched with --remote-debugging-port.",
        }
    if name == "browser_takeover_list_pages":
        return {"host": host, "port": port, "pages": cdp_pages(host, port)}
    if name == "browser_takeover_launch":
        return launch_browser(
            browser=args.get("browser", "edge"),
            port=port,
            url=args.get("url", "about:blank"),
            user_data_dir=args.get("userDataDir"),
        )
    if name == "browser_takeover_navigate":
        url = args.get("url")
        if not url:
            raise RuntimeError("url is required")
        return cdp_call(host, port, "Page.navigate", {"url": url}, args.get("pageId"))
    if name == "browser_takeover_evaluate":
        expression = args.get("expression")
        if not expression:
            raise RuntimeError("expression is required")
        return cdp_call(
            host,
            port,
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": bool(args.get("awaitPromise", True)), "returnByValue": True},
            args.get("pageId"),
        )
    if name == "browser_takeover_screenshot":
        capture = cdp_call(
            host,
            port,
            "Page.captureScreenshot",
            {"format": args.get("format", "png"), "fromSurface": True},
            args.get("pageId"),
        )
        output_path = args.get("outputPath")
        if output_path:
            data = capture.get("result", {}).get("data")
            if data:
                path = Path(output_path).expanduser()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(base64.b64decode(data))
                capture["outputPath"] = str(path)
                capture["result"].pop("data", None)
        return capture
    raise RuntimeError(f"Unknown tool: {name}")


TOOLS = [
    {
        "name": "browser_takeover_status",
        "description": "Inspect running Chrome/Edge processes and common local CDP ports.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "127.0.0.1"},
                "ports": {"type": "array", "items": {"type": "integer"}, "default": DEFAULT_PORTS},
            },
        },
    },
    {
        "name": "browser_takeover_launch",
        "description": "Launch Chrome or Edge with a persistent Codex takeover profile and CDP enabled.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "browser": {"type": "string", "enum": ["edge", "chrome"], "default": "edge"},
                "port": {"type": "integer", "default": 9222},
                "url": {"type": "string", "default": "about:blank"},
                "userDataDir": {"type": "string"},
            },
        },
    },
    {
        "name": "browser_takeover_list_pages",
        "description": "List attachable tabs/pages from a local CDP endpoint.",
        "inputSchema": {"type": "object", "properties": {"host": {"type": "string", "default": "127.0.0.1"}, "port": {"type": "integer", "default": 9222}}},
    },
    {
        "name": "browser_takeover_navigate",
        "description": "Navigate an attachable page to a URL.",
        "inputSchema": {
            "type": "object",
            "required": ["url"],
            "properties": {
                "host": {"type": "string", "default": "127.0.0.1"},
                "port": {"type": "integer", "default": 9222},
                "pageId": {"type": "string"},
                "url": {"type": "string"},
            },
        },
    },
    {
        "name": "browser_takeover_evaluate",
        "description": "Evaluate JavaScript in an attachable page.",
        "inputSchema": {
            "type": "object",
            "required": ["expression"],
            "properties": {
                "host": {"type": "string", "default": "127.0.0.1"},
                "port": {"type": "integer", "default": 9222},
                "pageId": {"type": "string"},
                "expression": {"type": "string"},
                "awaitPromise": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "browser_takeover_screenshot",
        "description": "Capture a screenshot from an attachable page. Provide outputPath to save it locally.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "127.0.0.1"},
                "port": {"type": "integer", "default": 9222},
                "pageId": {"type": "string"},
                "format": {"type": "string", "enum": ["png", "jpeg"], "default": "png"},
                "selector": {"type": "string"},
                "clip": {
                    "type": "object",
                    "required": ["x", "y", "width", "height"],
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "width": {"type": "number"},
                        "height": {"type": "number"},
                        "devicePixelRatio": {"type": "number"},
                    },
                },
                "outputPath": {"type": "string"},
            },
        },
    },
    {
        "name": "browser_takeover_extension_bridge_status",
        "description": "Start/check the localhost bridge used by the companion browser extension for already-open authenticated tabs.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "browser_takeover_extension_diagnostics",
        "description": "Inspect extension registration, tab-sync freshness, command polling, round-trip results, queues, and active claims.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "browser_takeover_extension_events",
        "description": "Read browser tab lifecycle events reported by the extension, with an incremental event cursor.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "afterId": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
                "clientId": {"type": "string"},
            },
        },
    },
    {
        "name": "browser_takeover_extension_wait_event",
        "description": "Wait for a matching tab or download lifecycle event after an event cursor.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "afterId": {"type": "integer", "minimum": 0, "default": 0},
                "type": {
                    "type": "string",
                    "enum": ["tab.created", "tab.updated", "tab.removed", "tab.activated", "download.created", "download.changed"],
                },
                "clientId": {"type": "string"},
                "tabId": {"type": ["integer", "string"]},
                "downloadId": {"type": "integer"},
                "timeout": {"type": "number", "default": 10},
            },
        },
    },
    {
        "name": "browser_takeover_extension_list_tabs",
        "description": "List tabs reported by the installed companion extension in the user's normal browser profile.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "browser_takeover_claim_tab",
        "description": "Claim an extension-reported tab with a renewable readonly or interactive lease before using V2 actions.",
        "inputSchema": {
            "type": "object",
            "required": ["clientId", "tabId"],
            "properties": {
                "clientId": {"type": "string"},
                "tabId": {"type": ["integer", "string"]},
                "owner": {"type": "string", "default": "mcp-client"},
                "mode": {"type": "string", "enum": ["readonly", "interactive"], "default": "interactive"},
                "ttl": {"type": "integer", "minimum": 10, "maximum": 3600, "default": 60},
            },
        },
    },
    {
        "name": "browser_takeover_renew_claim",
        "description": "Renew an active tab claim lease.",
        "inputSchema": {
            "type": "object",
            "required": ["claimId"],
            "properties": {
                "claimId": {"type": "string"},
                "ttl": {"type": "integer", "minimum": 10, "maximum": 3600, "default": 60},
            },
        },
    },
    {
        "name": "browser_takeover_release_tab",
        "description": "Release a previously claimed extension tab.",
        "inputSchema": {
            "type": "object",
            "required": ["claimId"],
            "properties": {"claimId": {"type": "string"}},
        },
    },
    {
        "name": "browser_takeover_extension_action",
        "description": "Run a structured V2 browser action through an active tab claim. Supports semantic and CSS targeting with read/write actions and waits.",
        "inputSchema": {
            "type": "object",
            "required": ["claimId", "action"],
            "properties": {
                "claimId": {"type": "string"},
                "action": {
                    "type": "object",
                    "required": ["type"],
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["click", "doubleClick", "hover", "clickAt", "fill", "press", "keypressPage", "read", "check", "select", "scroll", "wait", "snapshot", "upload"],
                        },
                        "target": {
                            "type": "object",
                            "properties": {
                                "css": {"type": "string"},
                                "testId": {"type": "string"},
                                "role": {"type": "string"},
                                "name": {"type": "string"},
                                "text": {"type": "string"},
                                "label": {"type": "string"},
                                "index": {"type": "integer", "minimum": 0},
                                "shadowPath": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                        "value": {},
                        "key": {"type": "string"},
                        "attribute": {"type": "string"},
                        "checked": {"type": "boolean"},
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "behavior": {"type": "string", "enum": ["instant", "smooth"]},
                        "state": {"type": "string", "enum": ["visible", "hidden", "attached"]},
                        "timeout": {"type": "number"},
                        "frameId": {"type": "integer"},
                        "frameScope": {"type": "string", "enum": ["top", "all"]},
                        "maxText": {"type": "integer"},
                        "maxControls": {"type": "integer"},
                        "dataUrl": {"type": "string"},
                        "fileName": {"type": "string"},
                        "mimeType": {"type": "string"},
                        "code": {"type": "string"},
                        "ctrlKey": {"type": "boolean"},
                        "shiftKey": {"type": "boolean"},
                        "commandTimeout": {"type": "number", "minimum": 500, "maximum": 10000},
                        "altKey": {"type": "boolean"},
                        "metaKey": {"type": "boolean"},
                        "options": {"type": "object"},
                        "expect": {
                            "type": "object",
                            "properties": {
                                "urlIncludes": {"type": "string"},
                                "textIncludes": {"type": "string"},
                                "cssVisible": {"type": "string"},
                                "cssHidden": {"type": "string"},
                                "css": {"type": "string"},
                                "value": {},
                                "visible": {"type": "boolean"},
                                "timeout": {"type": "number"},
                            },
                        },
                    },
                },
                "timeout": {"type": "number", "default": 10},
                "renewTtl": {"type": "integer", "minimum": 10, "maximum": 3600, "default": 60},
            },
        },
    },
    {
        "name": "browser_takeover_extension_batch_snapshot",
        "description": "Capture structured readonly snapshots from up to 20 already-open tabs in one operation using temporary claims.",
        "inputSchema": {
            "type": "object",
            "required": ["tabs"],
            "properties": {
                "tabs": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 20,
                    "items": {
                        "type": "object",
                        "required": ["clientId", "tabId"],
                        "properties": {
                            "clientId": {"type": "string"},
                            "tabId": {"type": ["integer", "string"]},
                        },
                    },
                },
                "owner": {"type": "string", "default": "batch-snapshot"},
                "maxText": {"type": "integer", "default": 20000},
                "maxControls": {"type": "integer", "default": 500},
                "timeout": {"type": "number", "default": 10},
            },
        },
    },
    {
        "name": "browser_takeover_extension_upload",
        "description": "Upload a local file into a claimed tab by populating a file input, including Shadow DOM or iframe targets.",
        "inputSchema": {
            "type": "object",
            "required": ["claimId", "filePath"],
            "properties": {
                "claimId": {"type": "string"},
                "filePath": {"type": "string"},
                "fileName": {"type": "string"},
                "mimeType": {"type": "string"},
                "maxBytes": {"type": "integer", "default": 26214400},
                "target": {"type": "object"},
                "frameId": {"type": "integer"},
                "frameScope": {"type": "string", "enum": ["top", "all"]},
                "expect": {"type": "object"},
                "timeout": {"type": "number", "default": 20},
                "renewTtl": {"type": "integer", "default": 60},
            },
        },
    },
    {
        "name": "browser_takeover_extension_workflow",
        "description": "Run a verified multi-step workflow against one claimed tab with per-step retries and stop/continue error policy.",
        "inputSchema": {
            "type": "object",
            "required": ["claimId", "steps"],
            "properties": {
                "claimId": {"type": "string"},
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 100,
                    "items": {
                        "type": "object",
                        "required": ["action"],
                        "properties": {
                            "name": {"type": "string"},
                            "action": {"type": "object"},
                            "attempts": {"type": "integer", "minimum": 1, "maximum": 5, "default": 1},
                            "retryDelay": {"type": "number", "minimum": 0, "maximum": 10, "default": 0.25},
                            "timeout": {"type": "number"},
                            "onError": {"type": "string", "enum": ["stop", "continue"], "default": "stop"},
                        },
                    },
                },
                "timeout": {"type": "number", "default": 15},
                "focusDelay": {"type": "number", "minimum": 0, "maximum": 2, "default": 0.15},
                "renewTtl": {"type": "integer", "default": 60},
            },
        },
    },
    {
        "name": "browser_takeover_extension_download",
        "description": "Start a browser-managed download through the connected extension.",
        "inputSchema": {
            "type": "object",
            "required": ["url"],
            "properties": {
                "clientId": {"type": "string"},
                "url": {"type": "string"},
                "filename": {"type": "string"},
                "saveAs": {"type": "boolean", "default": False},
                "conflictAction": {"type": "string", "enum": ["uniquify", "overwrite", "prompt"], "default": "uniquify"},
                "timeout": {"type": "number", "default": 20},
            },
        },
    },
    {
        "name": "browser_takeover_extension_download_status",
        "description": "Read progress and completion state for a browser-managed download.",
        "inputSchema": {
            "type": "object",
            "required": ["downloadId"],
            "properties": {
                "clientId": {"type": "string"},
                "downloadId": {"type": "integer"},
                "timeout": {"type": "number", "default": 10},
            },
        },
    },
    {
        "name": "browser_takeover_extension_full_screenshot",
        "description": "Capture a true full-page screenshot through optional advanced debugger permission.",
        "inputSchema": {
            "type": "object",
            "required": ["claimId"],
            "properties": {
                "claimId": {"type": "string"},
                "format": {"type": "string", "enum": ["png", "jpeg"], "default": "png"},
                "quality": {"type": "integer", "minimum": 1, "maximum": 100, "default": 90},
                "scale": {"type": "number", "minimum": 0.1, "maximum": 2, "default": 1},
                "outputPath": {"type": "string"},
                "timeout": {"type": "number", "default": 30},
            },
        },
    },
    {
        "name": "browser_takeover_extension_native_input",
        "description": "Dispatch browser-level mouse, wheel, drag, text, or keyboard input through optional advanced debugger permission.",
        "inputSchema": {
            "type": "object",
            "required": ["claimId", "action"],
            "properties": {
                "claimId": {"type": "string"},
                "action": {
                    "type": "object",
                    "required": ["type"],
                    "properties": {
                        "type": {"type": "string", "enum": ["nativeClick", "nativeWheel", "nativeDrag", "nativeText", "nativeKey"]},
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "deltaX": {"type": "number"},
                        "deltaY": {"type": "number"},
                        "button": {"type": "string", "enum": ["left", "middle", "right"]},
                        "clickCount": {"type": "integer", "minimum": 1, "maximum": 3},
                        "points": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["x", "y"],
                                "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                            },
                        },
                        "text": {"type": "string"},
                        "key": {"type": "string"},
                        "code": {"type": "string"},
                        "altKey": {"type": "boolean"},
                        "ctrlKey": {"type": "boolean"},
                        "metaKey": {"type": "boolean"},
                        "shiftKey": {"type": "boolean"},
                    },
                },
                "timeout": {"type": "number", "default": 15},
                "renewTtl": {"type": "integer", "default": 60},
            },
        },
    },
    {
        "name": "browser_takeover_extension_handle_dialog",
        "description": "Accept or dismiss an open JavaScript dialog using optional advanced debugger permission.",
        "inputSchema": {
            "type": "object",
            "required": ["claimId"],
            "properties": {
                "claimId": {"type": "string"},
                "accept": {"type": "boolean", "default": True},
                "promptText": {"type": "string"},
                "timeout": {"type": "number", "default": 10},
            },
        },
    },
    {
        "name": "browser_takeover_extension_advanced_control",
        "description": "Enable or disable the declared advanced debugger control channel on a connected extension client.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "clientId": {"type": "string"},
                "enabled": {"type": "boolean", "default": True},
                "timeout": {"type": "number", "default": 10},
            },
        },
    },
    {
        "name": "browser_takeover_extension_reload",
        "description": "Ask the companion extension to reload itself after extension files have been updated.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "clientId": {"type": "string"},
            },
        },
    },
    {
        "name": "browser_takeover_extension_evaluate",
        "description": "Evaluate JavaScript in an already-open tab through the companion extension.",
        "inputSchema": {
            "type": "object",
            "required": ["clientId", "tabId", "expression"],
            "properties": {
                "clientId": {"type": "string"},
                "tabId": {"type": ["integer", "string"]},
                "expression": {"type": "string"},
                "awaitPromise": {"type": "boolean", "default": True},
                "timeout": {"type": "number", "default": 10},
            },
        },
    },
    {
        "name": "browser_takeover_extension_navigate",
        "description": "Navigate an already-open tab through the companion extension.",
        "inputSchema": {
            "type": "object",
            "required": ["clientId", "tabId", "url"],
            "properties": {
                "clientId": {"type": "string"},
                "tabId": {"type": ["integer", "string"]},
                "url": {"type": "string"},
                "timeout": {"type": "number", "default": 10},
            },
        },
    },
    {
        "name": "browser_takeover_extension_screenshot",
        "description": "Capture the visible area of an already-open tab through the companion extension.",
        "inputSchema": {
            "type": "object",
            "required": ["clientId", "tabId"],
            "properties": {
                "clientId": {"type": "string"},
                "tabId": {"type": ["integer", "string"]},
                "format": {"type": "string", "enum": ["png", "jpeg"], "default": "png"},
                "outputPath": {"type": "string"},
                "timeout": {"type": "number", "default": 10},
            },
        },
    },
]


def main():
    start_extension_bridge()
    while True:
        message = read_message()
        if message is None:
            return
        request_id = message.get("id")
        method = message.get("method")
        try:
            if method == "initialize":
                result(
                    request_id,
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": SERVER_NAME, "version": "0.2.0"},
                    },
                )
            elif method == "tools/list":
                result(request_id, {"tools": TOOLS})
            elif method == "tools/call":
                params = message.get("params") or {}
                payload = handle_tool(params.get("name"), params.get("arguments") or {})
                result(request_id, tool_text(payload))
            elif request_id is not None:
                error(request_id, -32601, f"Method not found: {method}")
        except Exception as exc:
            if request_id is not None:
                error(request_id, -32000, str(exc))


if __name__ == "__main__":
    main()
