#!/usr/bin/env python3
from __future__ import annotations

import datetime
import json
import sqlite3
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

import app
import models
import weather_icons
from models import EndpointPolicy, WeatherStore


SAMPLE_LAT = 12.34
SAMPLE_LON = 56.78


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
        per_city=False,
    ),
    "openmeteo_hourly": EndpointPolicy(
        source="Open-Meteo",
        ttl=900,
        table_name="openmeteo_hourly",
    ),
}


class WeatherStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "weather_cache.sqlite3"
        self.store = WeatherStore(self.db_path, endpoint_policies=TEST_ENDPOINT_POLICIES)

    def tearDown(self):
        self.temp_dir.cleanup()

    @contextmanager
    def _open_db(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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
            alpha_columns = {
                row["name"]
                for row in conn.execute('PRAGMA table_info("alpha_history")').fetchall()
            }
            sensor_columns = {
                row["name"]
                for row in conn.execute('PRAGMA table_info("device_sensor")').fetchall()
            }

        self.assertIn("alpha_history", tables)
        self.assertIn("beta_history", tables)
        self.assertIn("device_sensor", tables)
        self.assertNotIn("source_history", tables)
        self.assertIn("city", alpha_columns)
        self.assertNotIn("city", sensor_columns)
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

    def test_latest_snapshot_isolated_by_city(self):
        self.store.record_snapshot("alpha", {"city": "Amsterdam"}, city="Amsterdam")
        self.store.record_snapshot("alpha", {"city": "Berlin"}, city="Berlin")

        amsterdam = self.store.latest_snapshot("alpha", city="Amsterdam")
        berlin = self.store.latest_snapshot("alpha", city="Berlin")

        self.assertIsNotNone(amsterdam)
        self.assertIsNotNone(berlin)
        assert amsterdam is not None
        assert berlin is not None
        self.assertEqual(amsterdam["payload"], {"city": "Amsterdam"})
        self.assertEqual(berlin["payload"], {"city": "Berlin"})

    def test_init_db_adds_city_column_to_existing_weather_table(self):
        with self._open_db() as conn:
            conn.execute(
                """
                CREATE TABLE alpha_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fetched_at INTEGER NOT NULL,
                    success INTEGER NOT NULL,
                    payload_json TEXT,
                    error_text TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO alpha_history (
                    fetched_at, success, payload_json, error_text
                ) VALUES (?, ?, ?, ?)
                """,
                (1234, 1, json.dumps({"legacy": True}), None),
            )

        self.store.init_db()

        latest = self.store.latest_snapshot("alpha")
        with self._open_db() as conn:
            columns = {
                row["name"]
                for row in conn.execute('PRAGMA table_info("alpha_history")').fetchall()
            }

        self.assertIn("city", columns)
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest["payload"], {"legacy": True})

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

    def test_init_db_renames_legacy_weather_tables(self):
        store = WeatherStore(self.db_path)

        with self._open_db() as conn:
            conn.execute(
                '''
                CREATE TABLE openmeteo_hourly_ams (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fetched_at INTEGER NOT NULL,
                    success INTEGER NOT NULL,
                    payload_json TEXT,
                    error_text TEXT
                )
                '''
            )
            conn.execute(
                '''
                INSERT INTO openmeteo_hourly_ams (
                    fetched_at, success, payload_json, error_text
                ) VALUES (?, ?, ?, ?)
                ''',
                (1234, 1, json.dumps([{"ts": 10, "temp_c": 15.0, "rain_mmh": 0.0}]), None),
            )

        store.init_db()

        latest = store.latest_snapshot("openmeteo_hourly")
        with self._open_db() as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }

        self.assertIn("openmeteo_hourly", tables)
        self.assertNotIn("openmeteo_hourly_ams", tables)
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest["payload"], [{"ts": 10, "temp_c": 15.0, "rain_mmh": 0.0}])

    def test_get_rain_forecast_keeps_5_min_detail_then_switches_to_hour_groups(self):
        self.store.buienradar = lambda lat, lon, force=False, city=None: [
            {"time": "10:00", "mmh": 0.0},
            {"time": "10:05", "mmh": 0.2},
            {"time": "10:10", "mmh": 0.4},
            {"time": "10:15", "mmh": 0.0},
        ]
        self.store.hourly_forecast = lambda lat, lon, hours=18, force=False, city=None: [
            {"ts": 1_710_000_000, "temp_c": 8.0, "rain_mmh": 0.5},
            {"ts": 1_710_003_600, "temp_c": 9.0, "rain_mmh": 1.0},
            {"ts": 1_710_007_200, "temp_c": 10.0, "rain_mmh": 0.0},
        ]
        self.store._buienradar_points_with_timestamps = lambda points, now=None: [
            {"ts": 1_710_000_000, "mmh": 0.0},
            {"ts": 1_710_000_300, "mmh": 0.2},
            {"ts": 1_710_000_600, "mmh": 0.4},
            {"ts": 1_710_000_900, "mmh": 0.0},
        ]

        forecast = self.store.get_rain_forecast(SAMPLE_LAT, SAMPLE_LON, hours=2, detailed_hours=1)

        self.assertEqual(forecast["start_ts"], 1_710_000_000)
        self.assertEqual(forecast["end_ts"], 1_710_007_200)
        self.assertEqual(forecast["points"][0]["duration_minutes"], 5)
        self.assertEqual(forecast["points"][1]["duration_minutes"], 5)
        coarse_point = next(point for point in forecast["points"] if point["ts"] >= forecast["detailed_end_ts"])
        self.assertEqual(coarse_point["duration_minutes"], 60)
        self.assertEqual(coarse_point["group_start_ts"], forecast["detailed_end_ts"])

    def test_hourly_forecast_filters_around_current_time(self):
        fixed_now = datetime.datetime(2026, 1, 1, 23, 35, tzinfo=models.BUIENRADAR_TZ)
        self.store._current_timestamp = lambda: int(fixed_now.timestamp())

        hourly_times = []
        temperatures = []
        precipitation = []
        start = datetime.datetime(2026, 1, 1, 0, 0)
        for hour in range(48):
            point = start + datetime.timedelta(hours=hour)
            hourly_times.append(point.strftime("%Y-%m-%dT%H:%M"))
            temperatures.append(float(hour))
            precipitation.append(float(hour % 3))

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "timezone": "Europe/Amsterdam",
                    "hourly": {
                        "time": hourly_times,
                        "temperature_2m": temperatures,
                        "precipitation": precipitation,
                    }
                }

        original_get = models.requests.get
        models.requests.get = lambda url, params=None, timeout=6: FakeResponse()
        self.addCleanup(lambda: setattr(models.requests, "get", original_get))

        forecast = self.store.hourly_forecast(SAMPLE_LAT, SAMPLE_LON, hours=12, force=True)

        self.assertTrue(forecast)
        self.assertLessEqual(forecast[0]["ts"], int(fixed_now.timestamp()))
        self.assertGreaterEqual(
            forecast[-1]["ts"],
            int((fixed_now + datetime.timedelta(hours=12)).timestamp()),
        )
        self.assertGreater(forecast[-1]["temp_c"], forecast[0]["temp_c"])

    def test_hourly_forecast_uses_response_timezone(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "timezone": "America/Lima",
                    "hourly": {
                        "time": ["2026-04-06T00:00"],
                        "temperature_2m": [12.5],
                        "precipitation": [0.0],
                    },
                }

        original_get = models.requests.get
        models.requests.get = lambda url, timeout=6: FakeResponse()
        self.addCleanup(lambda: setattr(models.requests, "get", original_get))

        forecast = self.store.hourly_forecast(SAMPLE_LAT, SAMPLE_LON, hours=1, force=True)
        expected_ts = int(datetime.datetime(2026, 4, 6, 0, 0, tzinfo=ZoneInfo("America/Lima")).timestamp())

        self.assertEqual(forecast[0]["ts"], expected_ts)

    def test_openmeteo_current_returns_current_payload(self):
        store = WeatherStore(self.db_path)
        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "timezone": "America/Lima",
                    "current": {
                        "temperature_2m": 15.2,
                        "relative_humidity_2m": 41,
                        "apparent_temperature": 14.8,
                        "is_day": 1,
                        "weather_code": 3,
                        "wind_speed_10m": 3.4,
                        "wind_direction_10m": 270,
                        "wind_gusts_10m": 5.6,
                    },
                }

        original_get = models.requests.get

        def fake_get(url, timeout=6):
            captured["url"] = url
            return FakeResponse()

        models.requests.get = fake_get
        self.addCleanup(lambda: setattr(models.requests, "get", original_get))

        payload = store.openmeteo_current(SAMPLE_LAT, SAMPLE_LON, city="Cusco", force=True)

        self.assertEqual(payload["timezone"], "America/Lima")
        self.assertEqual(payload["current"]["temperature_2m"], 15.2)
        self.assertIn("current=temperature_2m", captured["url"])
        self.assertIn("timezone=auto", captured["url"])

    def test_get_rain_forecast_uses_hourly_data_when_buienradar_missing(self):
        self.store.buienradar = lambda lat, lon, force=False, city=None: []
        self.store.hourly_forecast = lambda lat, lon, hours=18, force=False, city=None: [
            {"ts": 1_710_000_000, "temp_c": 8.0, "rain_mmh": 0.5},
            {"ts": 1_710_003_600, "temp_c": 9.0, "rain_mmh": 1.0},
            {"ts": 1_710_007_200, "temp_c": 10.0, "rain_mmh": 0.0},
        ]
        self.store._current_timestamp = lambda: 1_710_000_000

        forecast = self.store.get_rain_forecast(SAMPLE_LAT, SAMPLE_LON, hours=2, detailed_hours=1)

        self.assertEqual(forecast["detailed_end_ts"], forecast["start_ts"])
        self.assertEqual(forecast["points"][0]["duration_minutes"], 60)
        self.assertEqual(forecast["points"][0]["source"], "Open-Meteo")

    def test_buienradar_returns_empty_list_outside_supported_region(self):
        store = WeatherStore(self.db_path)

        class FakeResponse:
            status_code = 404
            text = "Not found: location must be inside the Netherlands or Belgium."

            def raise_for_status(self):
                raise AssertionError("raise_for_status should not be called")

        original_get = models.requests.get
        models.requests.get = lambda url, timeout=6: FakeResponse()
        self.addCleanup(lambda: setattr(models.requests, "get", original_get))

        forecast = store.buienradar(-13.5, -71.9, city="Cusco", force=True)
        latest = store.latest_snapshot("buienradar_rain", city="Cusco")

        self.assertEqual(forecast, [])
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest["payload"], [])

    def test_character_icon_key_selects_rainy_warm(self):
        icon_key = app._character_icon_key(
            {"kind": "rain", "temp_min": 12.0, "temp_max": 18.0, "rain_prob": 80},
            current_kind="rain",
            current_wind_mps=4.0,
            rules=app.CHARACTER_RULES,
        )

        self.assertEqual(icon_key, "rainy_warm")

    def test_character_icon_key_selects_freezing_windy(self):
        icon_key = app._character_icon_key(
            {"kind": "cloud", "temp_min": -3.0, "temp_max": 1.0, "rain_prob": 10},
            current_kind="cloud",
            current_wind_mps=12.0,
            rules=app.CHARACTER_RULES,
        )

        self.assertEqual(icon_key, "freezing_windy")

    def test_weather_icon_renderer_supports_all_kinds(self):
        for kind in weather_icons.ICON_KINDS:
            icon = weather_icons.render_weather_icon(kind, 64)
            self.assertEqual(icon.size, (64, 64))
            self.assertEqual(icon.getextrema(), (0, 255))


if __name__ == "__main__":
    unittest.main(verbosity=2)