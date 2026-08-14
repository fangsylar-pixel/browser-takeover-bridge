import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "webpage_monitor.py"
SPEC = importlib.util.spec_from_file_location("webpage_monitor", MODULE_PATH)
monitoring = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitoring)


class MonitorStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = monitoring.MonitorStore(Path(self.temp.name) / "monitors.json")

    def tearDown(self):
        self.temp.cleanup()

    def test_changed_rule_uses_first_check_as_baseline(self):
        created = self.store.create("Example", "example.test", rule={"type": "changed"})
        monitor_id = created["monitorId"]
        first = self.store.record(monitor_id, "Price: 99")
        second = self.store.record(monitor_id, "Price: 79")
        self.assertTrue(first["baselineCreated"])
        self.assertFalse(first["triggered"])
        self.assertTrue(second["changed"])
        self.assertTrue(second["triggered"])
        self.assertIn("Price: 79", second["diff"])

    def test_numeric_rule_extracts_price(self):
        created = self.store.create(
            "Price",
            "shop.test",
            rule={"type": "number_below", "value": 500, "numberPattern": r"¥([\d,]+)"},
        )
        result = self.store.record(created["monitorId"], "Current price ¥399")
        self.assertTrue(result["triggered"])
        self.assertEqual(result["condition"]["number"], 399)

    def test_pause_blocks_recording_and_history_hides_content(self):
        created = self.store.create("Stock", "shop.test", rule={"type": "contains", "value": "有货"})
        monitor_id = created["monitorId"]
        self.store.record(monitor_id, "当前有货")
        history = self.store.history(monitor_id)
        self.assertNotIn("content", history["history"][0])
        self.store.update(monitor_id, status="paused")
        with self.assertRaisesRegex(RuntimeError, "paused"):
            self.store.record(monitor_id, "仍然有货")

    def test_delete_removes_monitor(self):
        created = self.store.create("Delete", "example.test")
        self.assertTrue(self.store.delete(created["monitorId"])["deleted"])
        with self.assertRaisesRegex(RuntimeError, "not found"):
            self.store.get(created["monitorId"])


if __name__ == "__main__":
    unittest.main()

