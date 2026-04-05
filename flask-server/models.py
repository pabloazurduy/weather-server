#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests

DEFAULT_DB_PATH = Path(__file__).with_name("weather_cache.sqlite3")


@dataclass(frozen=True)
class EndpointPolicy:
    source: str
    ttl: int | None
    table_name: str


DEFAULT_ENDPOINT_POLICIES = {
    "owm_current_ams": EndpointPolicy(
        source="OpenWeather",
        ttl=30 * 60,
        table_name="owm_current_ams",
    ),
    "owm_forecast_ams": EndpointPolicy(
        source="OpenWeather",
        ttl=6 * 60 * 60,
        table_name="owm_forecast_ams",
    ),
    "openmeteo_daily_ams": EndpointPolicy(
        source="Open-Meteo",
        ttl=12 * 60 * 60,
        table_name="openmeteo_daily_ams",
    ),
    "buienradar_rain_ams": EndpointPolicy(
        source="Buienradar",
        ttl=10 * 60,
        table_name="buienradar_rain_ams",
    ),
    "device_sensor": EndpointPolicy(
        source="Device sensor",
        ttl=None,
        table_name="device_sensor",
    ),
}

SOURCE_FOOTER_ORDER = [
    "OpenWeather",
    "Open-Meteo",
    "Buienradar",
    "Device sensor",
]

SOURCE_FOOTER_LABELS = {
    "OpenWeather": "OpenWeather",
    "Open-Meteo": "Open-Meteo",
    "Buienradar": "Buienradar",
    "Device sensor": "Device",
}


class WeatherStore:
    def __init__(
        self,
        db_path: Path | str = DEFAULT_DB_PATH,
        endpoint_policies: dict[str, EndpointPolicy] | None = None,
    ):
        self.db_path = Path(db_path)
        self.endpoint_policies = dict(endpoint_policies or DEFAULT_ENDPOINT_POLICIES)
        self._db_lock = threading.Lock()
        self._db_initialized = False

    def _open_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _policy(self, endpoint_key: str) -> EndpointPolicy:
        return self.endpoint_policies[endpoint_key]

    @staticmethod
    def _safe_identifier(name: str) -> str:
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
        if not name or any(ch not in allowed for ch in name):
            raise ValueError(f"Unsafe SQLite identifier: {name!r}")
        return name

    def _table_sql(self, endpoint_key: str) -> str:
        table_name = self._safe_identifier(self._policy(endpoint_key).table_name)
        return f'"{table_name}"'

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def _create_source_tables(self, conn: sqlite3.Connection):
        for policy in self.endpoint_policies.values():
            table_name = self._safe_identifier(policy.table_name)
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS \"{table_name}\" (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fetched_at INTEGER NOT NULL,
                    success INTEGER NOT NULL,
                    payload_json TEXT,
                    error_text TEXT
                )
                """
            )
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS \"idx_{table_name}_success_time\"
                ON \"{table_name}\"(success, fetched_at DESC)
                """
            )
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS \"idx_{table_name}_time\"
                ON \"{table_name}\"(fetched_at DESC)
                """
            )

    def _migrate_legacy_source_history(self, conn: sqlite3.Connection):
        if not self._table_exists(conn, "source_history"):
            return

        rows = conn.execute(
            """
            SELECT endpoint_key, fetched_at, success, payload_json, error_text
            FROM source_history
            ORDER BY id ASC
            """
        ).fetchall()

        for row in rows:
            endpoint_key = row["endpoint_key"]
            if endpoint_key not in self.endpoint_policies:
                continue
            conn.execute(
                f"""
                INSERT INTO {self._table_sql(endpoint_key)} (
                    fetched_at, success, payload_json, error_text
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    int(row["fetched_at"]),
                    int(row["success"]),
                    row["payload_json"],
                    row["error_text"],
                ),
            )

        conn.execute("DROP TABLE source_history")

    def init_db(self):
        if self._db_initialized:
            return
        with self._db_lock:
            if self._db_initialized:
                return
            with self._open_db() as conn:
                # Keep a single on-disk database file instead of WAL sidecar files.
                conn.execute("PRAGMA journal_mode=DELETE")
                conn.execute("PRAGMA synchronous=NORMAL")
                self._create_source_tables(conn)
                self._migrate_legacy_source_history(conn)
            self._db_initialized = True

    def record_snapshot(
        self,
        endpoint_key: str,
        payload,
        success: bool = True,
        error_text: str | None = None,
        fetched_at: int | None = None,
    ):
        self.init_db()
        if fetched_at is None:
            fetched_at = int(time.time())
        payload_json = json.dumps(payload) if payload is not None else None
        with self._db_lock:
            with self._open_db() as conn:
                conn.execute(
                    f"""
                    INSERT INTO {self._table_sql(endpoint_key)} (
                        fetched_at, success, payload_json, error_text
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        int(fetched_at),
                        1 if success else 0,
                        payload_json,
                        error_text,
                    ),
                )

    def latest_snapshot(self, endpoint_key: str, success_only: bool = True):
        self.init_db()
        query = (
            "SELECT fetched_at, success, payload_json, error_text "
            f"FROM {self._table_sql(endpoint_key)}"
        )
        if success_only:
            query += " WHERE success = 1"
        query += " ORDER BY fetched_at DESC, id DESC LIMIT 1"

        with self._db_lock:
            with self._open_db() as conn:
                row = conn.execute(query).fetchone()

        if row is None:
            return None

        payload = json.loads(row["payload_json"]) if row["payload_json"] else None
        policy = self._policy(endpoint_key)
        return {
            "endpoint_key": endpoint_key,
            "source_name": policy.source,
            "fetched_at": int(row["fetched_at"]),
            "success": bool(row["success"]),
            "payload": payload,
            "error_text": row["error_text"],
        }

    def fetch_with_history(self, endpoint_key: str, fetcher, force: bool = False):
        policy = self._policy(endpoint_key)
        latest = self.latest_snapshot(endpoint_key)
        now = int(time.time())

        if (
            not force
            and latest is not None
            and policy.ttl is not None
            and now - latest["fetched_at"] < policy.ttl
        ):
            return latest["payload"]

        try:
            payload = fetcher()
            self.record_snapshot(
                endpoint_key,
                payload,
                success=True,
                fetched_at=now,
            )
            return payload
        except Exception as exc:
            self.record_snapshot(
                endpoint_key,
                None,
                success=False,
                error_text=str(exc),
                fetched_at=now,
            )
            if latest is not None and latest["payload"] is not None:
                print(
                    f"[WARN] {endpoint_key} fetch failed, using cached data from "
                    f"{latest['fetched_at']}: {exc}"
                )
                return latest["payload"]
            raise

    def store_sensor_reading(
        self,
        temp: float,
        humidity: float,
        battery_voltage: float | None,
    ):
        self.record_snapshot(
            "device_sensor",
            {
                "temp": temp,
                "humidity": humidity,
                "battery_voltage": battery_voltage,
            },
            success=True,
        )

    def latest_sensor_reading(self):
        latest = self.latest_snapshot("device_sensor")
        if latest is None or latest["payload"] is None:
            return None
        payload = dict(latest["payload"])
        payload["ts"] = latest["fetched_at"]
        return payload

    def source_refresh_times(self) -> dict[str, int]:
        refresh_times: dict[str, int] = {}
        for endpoint_key, policy in self.endpoint_policies.items():
            latest = self.latest_snapshot(endpoint_key)
            if latest is None:
                continue
            refresh_times[policy.source] = max(
                refresh_times.get(policy.source, 0),
                latest["fetched_at"],
            )
        return refresh_times

    @staticmethod
    def format_source_age(ts: int | None) -> str:
        if ts is None:
            return "--"
        hours = max(0.0, (time.time() - ts) / 3600.0)
        if hours < 10:
            return f"{hours:.1f}h"
        return f"{hours:.0f}h"

    def source_status_line(self) -> str:
        refresh_times = self.source_refresh_times()
        parts = []
        for source in SOURCE_FOOTER_ORDER:
            label = SOURCE_FOOTER_LABELS.get(source, source)
            parts.append(f"{label} {self.format_source_age(refresh_times.get(source))}")
        return "  |  ".join(parts)

    def _refresh_status(self, endpoint_key: str) -> dict:
        latest_attempt = self.latest_snapshot(endpoint_key, success_only=False)
        latest_success = self.latest_snapshot(endpoint_key)
        attempt_ok = bool(latest_attempt and latest_attempt["success"])

        return {
            "ok": attempt_ok,
            "source": self._policy(endpoint_key).source,
            "last_success_ts": latest_success["fetched_at"] if latest_success else None,
            "age_hours": (
                round((time.time() - latest_success["fetched_at"]) / 3600.0, 2)
                if latest_success is not None else None
            ),
            "used_cached_fallback": bool(
                latest_success is not None
                and latest_attempt is not None
                and not latest_attempt["success"]
            ),
            "error": (
                latest_attempt["error_text"]
                if latest_attempt is not None and not latest_attempt["success"]
                else None
            ),
        }

    def refresh_all_sources(
        self,
        lat: float,
        lon: float,
        owm_key: str,
        force: bool = False,
        forecast_count: int = 16,
        daily_days: int = 7,
    ) -> dict:
        snapshots = [
            ("owm_current_ams", lambda: self.owm_current(lat, lon, owm_key, force=force)),
            (
                "owm_forecast_ams",
                lambda: self.owm_forecast(lat, lon, owm_key, cnt=forecast_count, force=force),
            ),
            (
                "openmeteo_daily_ams",
                lambda: self.ams_daily_forecast(lat, lon, days=daily_days, force=force),
            ),
            ("buienradar_rain_ams", lambda: self.buienradar(lat, lon, force=force)),
        ]
        sources = {}
        ok = True

        for endpoint_key, loader in snapshots:
            try:
                loader()
                status = self._refresh_status(endpoint_key)
                if not status["ok"]:
                    ok = False
                sources[endpoint_key] = status
            except Exception as exc:
                ok = False
                latest_success = self.latest_snapshot(endpoint_key)
                sources[endpoint_key] = {
                    "ok": False,
                    "source": self._policy(endpoint_key).source,
                    "error": str(exc),
                    "last_success_ts": (
                        latest_success["fetched_at"] if latest_success else None
                    ),
                    "age_hours": (
                        round((time.time() - latest_success["fetched_at"]) / 3600.0, 2)
                        if latest_success is not None else None
                    ),
                    "used_cached_fallback": False,
                }

        latest_sensor = self.latest_snapshot("device_sensor")
        sources["device_sensor"] = {
            "ok": latest_sensor is not None,
            "source": self._policy("device_sensor").source,
            "mode": "push",
            "last_success_ts": latest_sensor["fetched_at"] if latest_sensor else None,
            "age_hours": (
                round((time.time() - latest_sensor["fetched_at"]) / 3600.0, 2)
                if latest_sensor is not None else None
            ),
        }
        return {"ok": ok, "sources": sources}

    def owm_current(
        self,
        lat: float,
        lon: float,
        api_key: str,
        force: bool = False,
    ) -> dict:
        def fetch():
            url = (
                "https://api.openweathermap.org/data/2.5/weather"
                f"?lat={lat}&lon={lon}&appid={api_key}&units=metric"
            )
            response = requests.get(url, timeout=6)
            response.raise_for_status()
            return response.json()

        return self.fetch_with_history("owm_current_ams", fetch, force=force)

    def owm_forecast(
        self,
        lat: float,
        lon: float,
        api_key: str,
        cnt: int = 16,
        force: bool = False,
    ) -> list:
        def fetch():
            url = (
                "https://api.openweathermap.org/data/2.5/forecast"
                f"?lat={lat}&lon={lon}&appid={api_key}&units=metric&cnt={cnt}"
            )
            response = requests.get(url, timeout=6)
            response.raise_for_status()
            return response.json()["list"]

        return self.fetch_with_history("owm_forecast_ams", fetch, force=force)

    def ams_daily_forecast(
        self,
        lat: float,
        lon: float,
        days: int = 7,
        force: bool = False,
    ) -> list:
        def fetch():
            url = (
                "https://api.open-meteo.com/v1/forecast"
                f"?latitude={lat}&longitude={lon}"
                "&daily=weather_code,temperature_2m_min,temperature_2m_max,precipitation_probability_max"
                "&timezone=auto"
                f"&forecast_days={days}"
            )
            response = requests.get(url, timeout=6)
            response.raise_for_status()
            daily = response.json()["daily"]
            rain_probs = daily.get("precipitation_probability_max", [])
            out = []
            for index, day in enumerate(daily["time"][:days]):
                out.append(
                    {
                        "date": day,
                        "kind": self._weather_kind_from_code(daily["weather_code"][index]),
                        "temp_min": float(daily["temperature_2m_min"][index]),
                        "temp_max": float(daily["temperature_2m_max"][index]),
                        "rain_prob": (
                            int(round(rain_probs[index]))
                            if index < len(rain_probs) and rain_probs[index] is not None
                            else None
                        ),
                    }
                )
            return out

        return self.fetch_with_history("openmeteo_daily_ams", fetch, force=force)

    def buienradar(
        self,
        lat: float,
        lon: float,
        force: bool = False,
    ) -> list:
        def fetch():
            url = f"https://gadgets.buienradar.nl/data/raintext/?lat={lat}&lon={lon}"
            response = requests.get(url, timeout=6)
            response.raise_for_status()
            out = []
            for line in response.text.strip().splitlines():
                if "|" not in line:
                    continue
                raw, value_time = line.split("|", 1)
                value = int(raw)
                mmh = round(10 ** ((value - 109) / 32), 2) if value > 0 else 0.0
                out.append({"time": value_time.strip(), "value": value, "mmh": mmh})
            return out

        return self.fetch_with_history("buienradar_rain_ams", fetch, force=force)

    @staticmethod
    def _weather_kind_from_code(code: int) -> str:
        code = int(code)
        if code == 0:
            return "sun"
        if code in (1, 2):
            return "partly"
        if code == 3:
            return "cloud"
        if code in (45, 48):
            return "fog"
        if 51 <= code <= 67 or 80 <= code <= 82:
            return "rain"
        if 71 <= code <= 77 or 85 <= code <= 86:
            return "snow"
        if 95 <= code <= 99:
            return "storm"
        return "cloud"