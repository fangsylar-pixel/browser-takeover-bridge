#!/usr/bin/env python3
"""Minimal MCP server for attaching to local Chromium via CDP."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import random
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
        self.next_command_id = 1

    def register(self, client_id, payload):
        now = time.time()
        with self.lock:
            self.clients[client_id] = {
                "clientId": client_id,
                "browser": payload.get("browser"),
                "userAgent": payload.get("userAgent"),
                "lastSeen": now,
            }

    def update_tabs(self, client_id, tabs):
        now = time.time()
        with self.lock:
            if client_id in self.clients:
                self.clients[client_id]["lastSeen"] = now
            self.tabs[client_id] = tabs or []

    def status(self):
        with self.lock:
            clients = list(self.clients.values())
            return {
                "bridge": {"host": BRIDGE_HOST, "port": BRIDGE_PORT},
                "clients": clients,
                "tabCount": sum(len(tabs) for tabs in self.tabs.values()),
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
            queue = self.commands.setdefault(client_id, [])
            if queue:
                return queue.pop(0)
            return None

    def complete(self, client_id, command_id, payload):
        with self.lock:
            self.results[(client_id, command_id)] = payload

    def wait_result(self, client_id, command_id, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                key = (client_id, command_id)
                if key in self.results:
                    return self.results.pop(key)
            time.sleep(0.1)
        raise RuntimeError(f"Timed out waiting for extension command {command_id}")


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
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_OPTIONS(self):
        write_http_json(self, {"ok": True})

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
                BRIDGE_STATE.register(client_id, payload)
                write_http_json(self, {"ok": True})
                return
            if parsed.path == "/extension/tabs":
                if not client_id:
                    write_http_json(self, {"ok": False, "error": "clientId is required"}, 400)
                    return
                BRIDGE_STATE.update_tabs(client_id, payload.get("tabs") or [])
                write_http_json(self, {"ok": True})
                return
            if parsed.path == "/extension/result":
                command_id = payload.get("commandId")
                if not client_id or not command_id:
                    write_http_json(self, {"ok": False, "error": "clientId and commandId are required"}, 400)
                    return
                BRIDGE_STATE.complete(client_id, command_id, payload)
                write_http_json(self, {"ok": True})
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
    if name == "browser_takeover_extension_list_tabs":
        start_extension_bridge()
        return {"tabs": BRIDGE_STATE.all_tabs()}
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
        command_id = BRIDGE_STATE.enqueue(client_id, {"type": "screenshot", "tabId": tab_id, "format": args.get("format", "png")})
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
        "name": "browser_takeover_extension_list_tabs",
        "description": "List tabs reported by the installed companion extension in the user's normal browser profile.",
        "inputSchema": {"type": "object", "properties": {}},
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
                        "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"},
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
