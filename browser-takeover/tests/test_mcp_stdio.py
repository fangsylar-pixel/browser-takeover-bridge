import json
import subprocess
import sys
import unittest
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "scripts" / "browser_takeover_mcp.py"


class McpStdioCompatibilityTests(unittest.TestCase):
    def initialize(self, framing):
        process = subprocess.Popen(
            [sys.executable, str(SERVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "compat-test", "version": "1"},
            },
        }
        body = json.dumps(request, separators=(",", ":")).encode()
        if framing == "newline":
            wire = body + b"\n"
        else:
            wire = f"Content-Length: {len(body)}\r\n\r\n".encode() + body
        process.stdin.write(wire)
        process.stdin.flush()
        if framing == "newline":
            response = json.loads(process.stdout.readline())
        else:
            header = process.stdout.readline().decode().strip()
            process.stdout.readline()
            length = int(header.split(":", 1)[1])
            response = json.loads(process.stdout.read(length))
        process.terminate()
        process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()
        return response

    def test_newline_delimited_json_for_marvis(self):
        response = self.initialize("newline")
        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["serverInfo"]["name"], "browser-takeover")

    def test_content_length_for_codex_and_legacy_clients(self):
        response = self.initialize("content-length")
        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["serverInfo"]["name"], "browser-takeover")


if __name__ == "__main__":
    unittest.main()
