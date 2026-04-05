#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from models import EndpointPolicy, WeatherStore


TEST_ENDPOINT_POLICIES = {
    "alpha": EndpointPolicy(
        source="Alpha",
        ttl=300,
        table_name="alpha_history",
    ),
    "beta": EndpointPolicy(
        source="Beta",
        ttl=600,
        table_name="beta_history",
    ),
    "device_sensor": EndpointPolicy(
        source="Device sensor",
        ttl=None,
        table_name="device_sensor",
    ),
}


class WeatherStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "weather_cache.sqlite3"
        self.store = WeatherStore(self.db_path, endpoint_policies=TEST_ENDPOINT_POLICIES)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _open_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_init_db_creates_per_source_tables_and_single_file_mode(self):
        self.store.init_db()
        self.store.record_snapshot("alpha", {"ok": True})

        with self._open_db() as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

        self.assertIn("alpha_history", tables)
        self.assertIn("beta_history", tables)
        self.assertIn("device_sensor", tables)
        self.assertNotIn("source_history", tables)
        self.assertEqual(journal_mode.lower(), "delete")
        self.assertFalse(Path(f"{self.db_path}-wal").exists())
        self.assertFalse(Path(f"{self.db_path}-shm").exists())

    def test_fetch_with_history_uses_cache_until_ttl_expires(self):
        calls = {"count": 0}

        def fetcher():
            calls["count"] += 1
            return {"value": calls["count"]}

        first = self.store.fetch_with_history("alpha", fetcher)
        second = self.store.fetch_with_history("alpha", fetcher)

        self.assertEqual(first, {"value": 1})
        self.assertEqual(second, {"value": 1})
        self.assertEqual(calls["count"], 1)

    def test_fetch_with_history_returns_stale_cache_on_failure(self):
        self.store.fetch_with_history("alpha", lambda: {"value": "cached"})

        def failing_fetcher():
            raise RuntimeError("boom")

        result = self.store.fetch_with_history("alpha", failing_fetcher, force=True)
        latest_attempt = self.store.latest_snapshot("alpha", success_only=False)

        self.assertEqual(result, {"value": "cached"})
        self.assertIsNotNone(latest_attempt)
        assert latest_attempt is not None
        self.assertFalse(latest_attempt["success"])
        self.assertEqual(latest_attempt["error_text"], "boom")

    def test_store_sensor_reading_round_trip(self):
        self.store.store_sensor_reading(21.5, 48.0, 4.01)

        latest = self.store.latest_sensor_reading()

        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest["temp"], 21.5)
        self.assertEqual(latest["humidity"], 48.0)
        self.assertEqual(latest["battery_voltage"], 4.01)
        self.assertIn("ts", latest)

    def test_init_db_migrates_legacy_source_history(self):
        with self._open_db() as conn:
            conn.execute(
                """
                CREATE TABLE source_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    endpoint_key TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    fetched_at INTEGER NOT NULL,
                    success INTEGER NOT NULL,
                    payload_json TEXT,
                    error_text TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO source_history (
                    endpoint_key, source_name, fetched_at,
                    success, payload_json, error_text
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "alpha",
                    "Alpha",
                    1234,
                    1,
                    json.dumps({"migrated": True}),
                    None,
                ),
            )

        self.store.init_db()

        latest = self.store.latest_snapshot("alpha")
        with self._open_db() as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }

        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest["payload"], {"migrated": True})
        self.assertEqual(latest["fetched_at"], 1234)
        self.assertNotIn("source_history", tables)


if __name__ == "__main__":
    unittest.main(verbosity=2)