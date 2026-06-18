import importlib.util
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "browser_takeover_mcp.py"
SPEC = importlib.util.spec_from_file_location("browser_takeover_mcp", MODULE_PATH)
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


class ExtensionBridgeStateTests(unittest.TestCase):
    def setUp(self):
        self.state = bridge.ExtensionBridgeState()
        self.token = self.state.register(
            "extension-1",
            {
                "browser": "chromium-extension",
                "protocolVersion": 2,
                "capabilities": ["tabs", "action"],
            },
        )
        self.state.update_tabs("extension-1", [{"id": 7, "title": "Example"}])

    def test_registration_token_authenticates_and_is_hidden_from_status(self):
        self.assertTrue(self.state.authenticate("extension-1", self.token))
        self.assertFalse(self.state.authenticate("extension-1", "wrong-token"))
        self.assertNotIn("token", self.state.status()["clients"][0])
        self.assertIn("health", self.state.status()["clients"][0])

    def test_diagnostics_distinguishes_registration_tabs_poll_and_results(self):
        diagnostics = self.state.diagnostics()
        client = diagnostics["clients"][0]
        self.assertTrue(client["health"]["registered"])
        self.assertTrue(client["health"]["tabsFresh"])
        self.assertFalse(client["health"]["polling"])
        self.state.poll("extension-1")
        self.state.complete("extension-1", "test-command", {"ok": True})
        client = self.state.diagnostics()["clients"][0]
        self.assertTrue(client["health"]["polling"])
        self.assertTrue(client["health"]["roundTrip"])

    def test_event_feed_uses_incremental_cursor(self):
        recorded = self.state.record_events(
            "extension-1",
            [
                {"type": "tab.created", "tabId": 7, "details": {"url": "https://example.test"}},
                {"type": "tab.updated", "tabId": 7, "details": {"status": "complete"}},
            ],
        )
        self.assertEqual([event["eventId"] for event in recorded], [1, 2])
        self.assertEqual(len(self.state.list_events(after_id=0)), 2)
        remaining = self.state.list_events(after_id=1)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["type"], "tab.updated")

    def test_wait_event_matches_type_and_cursor(self):
        self.state.record_events("extension-1", [{"type": "tab.created", "tabId": 12}])
        event = self.state.wait_event(after_id=0, event_type="tab.created", timeout=0.2)
        self.assertEqual(event["tabId"], 12)
        with self.assertRaisesRegex(RuntimeError, "Timed out"):
            self.state.wait_event(after_id=event["eventId"], event_type="tab.created", timeout=0.1)

    def test_protocol_v1_client_keeps_transitional_compatibility(self):
        self.state.register("legacy-extension", {"protocolVersion": 1})
        self.assertTrue(self.state.authenticate("legacy-extension", ""))

    def test_interactive_claim_blocks_other_writer(self):
        first = self.state.claim_tab("extension-1", 7, "owner-a", "interactive", 60)
        with self.assertRaisesRegex(RuntimeError, "already claimed"):
            self.state.claim_tab("extension-1", 7, "owner-b", "interactive", 60)
        self.assertEqual(first["mode"], "interactive")

    def test_readonly_claims_can_coexist_but_cannot_write(self):
        first = self.state.claim_tab("extension-1", 7, "owner-a", "readonly", 60)
        second = self.state.claim_tab("extension-1", 7, "owner-b", "readonly", 60)
        self.assertNotEqual(first["claimId"], second["claimId"])
        with self.assertRaisesRegex(RuntimeError, "Readonly"):
            self.state.require_claim(first["claimId"], write=True)

    def test_claim_can_be_renewed_and_released(self):
        claim = self.state.claim_tab("extension-1", 7, "owner-a", "interactive", 10)
        renewed = self.state.renew_claim(claim["claimId"], 120)
        self.assertGreater(renewed["expiresAt"], claim["expiresAt"])
        self.assertIsNotNone(self.state.release_claim(claim["claimId"]))
        with self.assertRaisesRegex(RuntimeError, "missing or expired"):
            self.state.require_claim(claim["claimId"])

    def test_expired_claim_is_cleaned_up(self):
        claim = self.state.claim_tab("extension-1", 7, "owner-a", "interactive", 10)
        self.state.claims[claim["claimId"]]["expiresAt"] = time.time() - 1
        self.assertEqual(self.state.list_claims(), [])


class BridgeHttpTests(unittest.TestCase):
    def setUp(self):
        bridge.BRIDGE_STATE = bridge.ExtensionBridgeState()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), bridge.BridgeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.origin = "chrome-extension://test-extension"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, payload=None, token=None, origin=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["X-Browser-Takeover-Token"] = token
        if origin:
            headers["Origin"] = origin
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method="POST" if payload is not None else "GET",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, dict(response.headers), json.loads(response.read())

    def test_register_then_authenticated_tab_sync(self):
        _, headers, registration = self.request(
            "/extension/register",
            {
                "clientId": "extension-http",
                "browser": "chromium-extension",
                "protocolVersion": 2,
            },
            origin=self.origin,
        )
        self.assertEqual(registration["protocolVersion"], 2)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), self.origin)
        token = registration["token"]
        status, _, payload = self.request(
            "/extension/tabs",
            {"clientId": "extension-http", "tabs": [{"id": 1}]},
            token=token,
            origin=self.origin,
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

    def test_tab_sync_rejects_missing_token(self):
        self.request(
            "/extension/register",
            {"clientId": "extension-http", "protocolVersion": 2},
            origin=self.origin,
        )
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(
                "/extension/tabs",
                {"clientId": "extension-http", "tabs": []},
                origin=self.origin,
            )
        self.assertEqual(error.exception.code, 401)

    def test_disallowed_web_origin_gets_no_cors_access(self):
        _, headers, _ = self.request(
            "/extension/register",
            {"clientId": "extension-http"},
            origin="https://malicious.example",
        )
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_authenticated_http_command_round_trip(self):
        _, _, registration = self.request(
            "/extension/register",
            {
                "clientId": "extension-roundtrip",
                "protocolVersion": 2,
                "capabilities": ["tabs", "action"],
            },
            origin=self.origin,
        )
        token = registration["token"]
        self.request(
            "/extension/tabs",
            {"clientId": "extension-roundtrip", "tabs": [{"id": 44, "title": "Round trip"}]},
            token=token,
            origin=self.origin,
        )
        command_id = bridge.BRIDGE_STATE.enqueue(
            "extension-roundtrip",
            {"type": "action", "tabId": 44, "action": {"type": "snapshot"}},
        )

        _, _, polled = self.request(
            "/extension/poll?clientId=extension-roundtrip",
            token=token,
            origin=self.origin,
        )
        self.assertEqual(polled["command"]["id"], command_id)
        self.request(
            "/extension/result",
            {
                "clientId": "extension-roundtrip",
                "commandId": command_id,
                "ok": True,
                "result": {"ok": True, "title": "Round trip"},
            },
            token=token,
            origin=self.origin,
        )
        result = bridge.BRIDGE_STATE.wait_result("extension-roundtrip", command_id, timeout=1)
        self.assertTrue(result["ok"])
        diagnostics = bridge.BRIDGE_STATE.diagnostics()["clients"][0]
        self.assertTrue(diagnostics["health"]["polling"])
        self.assertTrue(diagnostics["health"]["roundTrip"])


class ToolCompatibilityTests(unittest.TestCase):
    def test_legacy_and_v2_tools_are_both_exposed(self):
        names = {tool["name"] for tool in bridge.TOOLS}
        legacy = {
            "browser_takeover_extension_evaluate",
            "browser_takeover_extension_navigate",
            "browser_takeover_extension_screenshot",
            "browser_takeover_evaluate",
            "browser_takeover_navigate",
            "browser_takeover_screenshot",
        }
        v2 = {
            "browser_takeover_claim_tab",
            "browser_takeover_renew_claim",
            "browser_takeover_release_tab",
            "browser_takeover_extension_action",
            "browser_takeover_extension_diagnostics",
            "browser_takeover_extension_events",
            "browser_takeover_extension_batch_snapshot",
            "browser_takeover_extension_upload",
            "browser_takeover_extension_download",
            "browser_takeover_extension_download_status",
            "browser_takeover_extension_wait_event",
            "browser_takeover_extension_workflow",
            "browser_takeover_extension_full_screenshot",
            "browser_takeover_extension_native_input",
            "browser_takeover_extension_handle_dialog",
            "browser_takeover_extension_advanced_control",
        }
        self.assertTrue(legacy.issubset(names))
        self.assertTrue(v2.issubset(names))

    def test_v2_action_round_trip_uses_claimed_tab(self):
        original_state = bridge.BRIDGE_STATE
        original_start = bridge.start_extension_bridge
        bridge.BRIDGE_STATE = bridge.ExtensionBridgeState()
        bridge.start_extension_bridge = lambda: {"started": False, "test": True}
        try:
            bridge.BRIDGE_STATE.register("extension-action", {"protocolVersion": 2})
            bridge.BRIDGE_STATE.update_tabs("extension-action", [{"id": 9, "title": "Action Test"}])
            claimed = bridge.handle_tool(
                "browser_takeover_claim_tab",
                {
                    "clientId": "extension-action",
                    "tabId": 9,
                    "owner": "test-owner",
                    "mode": "interactive",
                },
            )["claim"]

            def fake_extension():
                deadline = time.time() + 2
                command = None
                while time.time() < deadline and command is None:
                    command = bridge.BRIDGE_STATE.poll("extension-action")
                    time.sleep(0.01)
                self.assertIsNotNone(command)
                self.assertEqual(command["type"], "action")
                self.assertEqual(command["tabId"], 9)
                bridge.BRIDGE_STATE.complete(
                    "extension-action",
                    command["id"],
                    {"ok": True, "result": {"ok": True, "value": "hello"}},
                )

            worker = threading.Thread(target=fake_extension)
            worker.start()
            response = bridge.handle_tool(
                "browser_takeover_extension_action",
                {
                    "claimId": claimed["claimId"],
                    "action": {"type": "read", "target": {"css": "h1"}},
                    "timeout": 2,
                },
            )
            worker.join(timeout=2)
            self.assertTrue(response["ok"])
            self.assertEqual(response["result"]["value"], "hello")
        finally:
            bridge.BRIDGE_STATE = original_state
            bridge.start_extension_bridge = original_start

    def test_readonly_claim_rejects_fill_before_dispatch(self):
        original_state = bridge.BRIDGE_STATE
        original_start = bridge.start_extension_bridge
        bridge.BRIDGE_STATE = bridge.ExtensionBridgeState()
        bridge.start_extension_bridge = lambda: {"started": False, "test": True}
        try:
            bridge.BRIDGE_STATE.register("extension-readonly", {"protocolVersion": 2})
            bridge.BRIDGE_STATE.update_tabs("extension-readonly", [{"id": 10}])
            claim = bridge.handle_tool(
                "browser_takeover_claim_tab",
                {
                    "clientId": "extension-readonly",
                    "tabId": 10,
                    "owner": "reader",
                    "mode": "readonly",
                },
            )["claim"]
            with self.assertRaisesRegex(RuntimeError, "Readonly"):
                bridge.handle_tool(
                    "browser_takeover_extension_action",
                    {
                        "claimId": claim["claimId"],
                        "action": {"type": "fill", "target": {"css": "input"}, "value": "blocked"},
                    },
                )
        finally:
            bridge.BRIDGE_STATE = original_state
            bridge.start_extension_bridge = original_start

    def test_workflow_retries_then_completes(self):
        original_state = bridge.BRIDGE_STATE
        original_start = bridge.start_extension_bridge
        bridge.BRIDGE_STATE = bridge.ExtensionBridgeState()
        bridge.start_extension_bridge = lambda: {"started": False, "test": True}
        try:
            bridge.BRIDGE_STATE.register("extension-workflow", {"protocolVersion": 2})
            bridge.BRIDGE_STATE.update_tabs("extension-workflow", [{"id": 21}])
            claim = bridge.handle_tool(
                "browser_takeover_claim_tab",
                {
                    "clientId": "extension-workflow",
                    "tabId": 21,
                    "owner": "workflow-test",
                    "mode": "interactive",
                },
            )["claim"]
            seen = []

            def fake_extension():
                while len(seen) < 3:
                    command = bridge.BRIDGE_STATE.poll("extension-workflow")
                    if not command:
                        time.sleep(0.01)
                        continue
                    seen.append(command)
                    ok = len(seen) != 1
                    bridge.BRIDGE_STATE.complete(
                        "extension-workflow",
                        command["id"],
                        {"ok": True, "result": {"ok": ok, "value": len(seen)}},
                    )

            worker = threading.Thread(target=fake_extension)
            worker.start()
            result = bridge.handle_tool(
                "browser_takeover_extension_workflow",
                {
                    "claimId": claim["claimId"],
                    "steps": [
                        {
                            "name": "retry-once",
                            "action": {"type": "click", "target": {"css": "#one"}},
                            "attempts": 2,
                            "retryDelay": 0,
                        },
                        {
                            "name": "read",
                            "action": {"type": "read", "target": {"css": "#two"}},
                        },
                    ],
                    "timeout": 2,
                },
            )
            worker.join(timeout=2)
            self.assertTrue(result["ok"])
            self.assertEqual(result["completedSteps"], 2)
            self.assertEqual(len(seen), 3)
            self.assertEqual(result["results"][0]["attempt"], 2)
        finally:
            bridge.BRIDGE_STATE = original_state
            bridge.start_extension_bridge = original_start

    def test_extension_poll_loop_starts_independently_of_initial_registration(self):
        background = (Path(__file__).parents[1] / "extension" / "background.js").read_text(encoding="utf-8")
        self.assertIn("safe(register);\nsafe(syncTabs);\npollLoop();", background)
        self.assertNotIn("await syncTabs();\n  pollLoop();", background)

    def test_extension_has_mv3_alarm_reconnect_fallback(self):
        root = Path(__file__).parents[1]
        manifest = json.loads((root / "extension" / "manifest.json").read_text(encoding="utf-8"))
        background = (root / "extension" / "background.js").read_text(encoding="utf-8")
        self.assertIn("alarms", manifest["permissions"])
        self.assertIn("if (chrome.alarms?.onAlarm && chrome.alarms?.create)", background)
        self.assertIn("chrome.alarms.create(RECONNECT_ALARM", background)
        self.assertIn("chrome.alarms.onAlarm.addListener", background)

    def test_extension_declares_complex_page_capabilities(self):
        root = Path(__file__).parents[1]
        manifest = json.loads((root / "extension" / "manifest.json").read_text(encoding="utf-8"))
        background = (root / "extension" / "background.js").read_text(encoding="utf-8")
        self.assertIn("downloads", manifest["permissions"])
        self.assertIn('request.type === "clickAt"', background)
        self.assertIn('request.type === "upload"', background)
        self.assertIn("selector.shadowPath?.length", background)
        self.assertIn('action.frameScope === "all"', background)
        self.assertIn("trackedDownloadIds.has(delta.id)", background)
        self.assertIn("Input.dispatchMouseEvent", background)
        self.assertIn("Page.captureScreenshot", background)
        self.assertIn("captureBeyondViewport: false", background)
        self.assertIn("commandTimeout(command)", background)
        self.assertIn("Page.handleJavaScriptDialog", background)
        self.assertIn("debugger", manifest["permissions"])
        self.assertNotIn("optional_permissions", manifest)


if __name__ == "__main__":
    unittest.main()
