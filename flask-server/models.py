#!/usr/bin/env python3
from __future__ import annotations

import datetime
import json
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

DEFAULT_DB_PATH = Path(__file__).with_name("weather_cache.sqlite3")
BUIENRADAR_TZ = ZoneInfo("Europe/Amsterdam")


@dataclass(frozen=True)
class EndpointPolicy:
    source: str
    ttl: int | None
    table_name: str
    per_city: bool = True


LEGACY_ENDPOINT_KEYS = {
    "openmeteo_daily_ams": "openmeteo_daily",
    "openmeteo_current_ams": "openmeteo_current",
    "openmeteo_hourly_ams": "openmeteo_hourly",
    "buienradar_rain_ams": "buienradar_rain",
}

LEGACY_TABLE_NAMES = {
    "openmeteo_daily": "openmeteo_daily_ams",
    "openmeteo_current": "openmeteo_current_ams",
    "openmeteo_hourly": "openmeteo_hourly_ams",
    "buienradar_rain": "buienradar_rain_ams",
}


DEFAULT_ENDPOINT_POLICIES = {
    "openmeteo_daily": EndpointPolicy(
        source="Open-Meteo",
        ttl=12 * 60 * 60,
        table_name="openmeteo_daily",
    ),
    "openmeteo_current": EndpointPolicy(
        source="Open-Meteo",
        ttl=30 * 60,
        table_name="openmeteo_current",
    ),
    "openmeteo_hourly": EndpointPolicy(
        source="Open-Meteo",
        ttl=60 * 60,
        table_name="openmeteo_hourly",
    ),
    "buienradar_rain": EndpointPolicy(
        source="Buienradar",
        ttl=10 * 60,
        table_name="buienradar_rain",
    ),
    "device_sensor": EndpointPolicy(
        source="Device sensor",
        ttl=None,
        table_name="device_sensor",
        per_city=False,
    ),
}

SOURCE_FOOTER_ORDER = [
    "Open-Meteo",
    "Buienradar",
    "Device sensor",
]

SOURCE_FOOTER_LABELS = {
    "Open-Meteo": "Open-Meteo",
    "Buienradar": "Buienradar",
    "Device sensor": "Device",
}


class WeatherStore:
    def __init__(
        self,
        db_path: Path | str = DEFAULT_DB_PATH,
        endpoint_policies: dict[str, EndpointPolicy] | None = None,
        default_city: str = "Amsterdam",
    ):
        self.db_path = Path(db_path)
        self.endpoint_policies = dict(endpoint_policies or DEFAULT_ENDPOINT_POLICIES)
        self.default_city = self._clean_city_name(default_city)
        self._db_lock = threading.Lock()
        self._db_initialized = False

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

    @staticmethod
    def _canonical_endpoint_key(endpoint_key: str) -> str:
        return LEGACY_ENDPOINT_KEYS.get(endpoint_key, endpoint_key)

    def _policy(self, endpoint_key: str) -> EndpointPolicy:
        return self.endpoint_policies[self._canonical_endpoint_key(endpoint_key)]

    @staticmethod
    def _clean_city_name(city: str) -> str:
        cleaned = " ".join(str(city).split())
        if not cleaned:
            raise ValueError("City must not be empty")
        return cleaned

    def _city_name(self, city: str | None = None) -> str:
        return self._clean_city_name(self.default_city if city is None else city)

    def _city_key(self, city: str | None = None) -> str:
        return self._city_name(city).casefold()

    @staticmethod
    def _sql_string_literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    @staticmethod
    def _safe_identifier(name: str) -> str:
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
        if not name or any(ch not in allowed for ch in name):
            raise ValueError(f"Unsafe SQLite identifier: {name!r}")
        return name

    def _table_sql(self, endpoint_key: str) -> str:
        table_name = self._safe_identifier(self._policy(endpoint_key).table_name)
        return f'"{table_name}"'

    def _drop_legacy_indexes(self, conn: sqlite3.Connection, table_name: str, per_city: bool):
        index_names = [
            f"idx_{table_name}_city_success_time",
            f"idx_{table_name}_city_time",
        ] if per_city else [
            f"idx_{table_name}_success_time",
            f"idx_{table_name}_time",
        ]
        for index_name in index_names:
            conn.execute(f'DROP INDEX IF EXISTS "{self._safe_identifier(index_name)}"')

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def _table_columns(self, conn: sqlite3.Connection, table_name: str) -> set[str]:
        safe_table_name = self._safe_identifier(table_name)
        rows = conn.execute(f'PRAGMA table_info("{safe_table_name}")').fetchall()
        return {row["name"] for row in rows}

    def _ensure_table_schema(self, conn: sqlite3.Connection, endpoint_key: str):
        policy = self._policy(endpoint_key)
        if not policy.per_city:
            return

        table_name = self._safe_identifier(policy.table_name)
        columns = self._table_columns(conn, table_name)
        if "city" not in columns:
            conn.execute(
                f'''
                ALTER TABLE "{table_name}"
                ADD COLUMN city TEXT NOT NULL DEFAULT {self._sql_string_literal(self._city_key())}
                '''
            )

        conn.execute(
            f'''
            UPDATE "{table_name}"
            SET city = ?
            WHERE city IS NULL OR TRIM(city) = ''
            ''',
            (self._city_key(),),
        )

    def _create_table_indexes(self, conn: sqlite3.Connection, endpoint_key: str):
        policy = self._policy(endpoint_key)
        table_name = self._safe_identifier(policy.table_name)
        if policy.per_city:
            conn.execute(
                f'''
                CREATE INDEX IF NOT EXISTS "idx_{table_name}_city_success_time"
                ON "{table_name}"(city, success, fetched_at DESC)
                '''
            )
            conn.execute(
                f'''
                CREATE INDEX IF NOT EXISTS "idx_{table_name}_city_time"
                ON "{table_name}"(city, fetched_at DESC)
                '''
            )
            return

        conn.execute(
            f'''
            CREATE INDEX IF NOT EXISTS "idx_{table_name}_success_time"
            ON "{table_name}"(success, fetched_at DESC)
            '''
        )
        conn.execute(
            f'''
            CREATE INDEX IF NOT EXISTS "idx_{table_name}_time"
            ON "{table_name}"(fetched_at DESC)
            '''
        )

    def _create_source_tables(self, conn: sqlite3.Connection):
        for endpoint_key, policy in self.endpoint_policies.items():
            table_name = self._safe_identifier(policy.table_name)
            if policy.per_city:
                conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS \"{table_name}\" (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        city TEXT NOT NULL,
                        fetched_at INTEGER NOT NULL,
                        success INTEGER NOT NULL,
                        payload_json TEXT,
                        error_text TEXT
                    )
                    """
                )
            else:
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
            self._ensure_table_schema(conn, endpoint_key)
            self._create_table_indexes(conn, endpoint_key)

    def _migrate_legacy_endpoint_tables(self, conn: sqlite3.Connection):
        for endpoint_key, legacy_table_name in LEGACY_TABLE_NAMES.items():
            if endpoint_key not in self.endpoint_policies:
                continue
            policy = self._policy(endpoint_key)
            target_table_name = self._safe_identifier(policy.table_name)
            legacy_table_name = self._safe_identifier(legacy_table_name)
            if not self._table_exists(conn, legacy_table_name):
                continue

            if not self._table_exists(conn, target_table_name):
                conn.execute(
                    f'ALTER TABLE "{legacy_table_name}" RENAME TO "{target_table_name}"'
                )
                self._drop_legacy_indexes(conn, legacy_table_name, policy.per_city)
                continue

            legacy_columns = self._table_columns(conn, legacy_table_name)
            if policy.per_city:
                if "city" in legacy_columns:
                    conn.execute(
                        f'''
                        INSERT INTO "{target_table_name}" (
                            city, fetched_at, success, payload_json, error_text
                        )
                        SELECT city, fetched_at, success, payload_json, error_text
                        FROM "{legacy_table_name}"
                        '''
                    )
                else:
                    conn.execute(
                        f'''
                        INSERT INTO "{target_table_name}" (
                            city, fetched_at, success, payload_json, error_text
                        )
                        SELECT ?, fetched_at, success, payload_json, error_text
                        FROM "{legacy_table_name}"
                        ''',
                        (self._city_key(),),
                    )
            else:
                conn.execute(
                    f'''
                    INSERT INTO "{target_table_name}" (
                        fetched_at, success, payload_json, error_text
                    )
                    SELECT fetched_at, success, payload_json, error_text
                    FROM "{legacy_table_name}"
                    '''
                )
            conn.execute(f'DROP TABLE "{legacy_table_name}"')

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
            endpoint_key = self._canonical_endpoint_key(row["endpoint_key"])
            if endpoint_key not in self.endpoint_policies:
                continue
            policy = self._policy(endpoint_key)
            if policy.per_city:
                conn.execute(
                    f"""
                    INSERT INTO {self._table_sql(endpoint_key)} (
                        city, fetched_at, success, payload_json, error_text
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        self._city_key(),
                        int(row["fetched_at"]),
                        int(row["success"]),
                        row["payload_json"],
                        row["error_text"],
                    ),
                )
            else:
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
                self._migrate_legacy_endpoint_tables(conn)
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
        city: str | None = None,
    ):
        self.init_db()
        if fetched_at is None:
            fetched_at = int(time.time())
        payload_json = json.dumps(payload) if payload is not None else None
        policy = self._policy(endpoint_key)
        with self._db_lock:
            with self._open_db() as conn:
                if policy.per_city:
                    conn.execute(
                        f"""
                        INSERT INTO {self._table_sql(endpoint_key)} (
                            city, fetched_at, success, payload_json, error_text
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            self._city_key(city),
                            int(fetched_at),
                            1 if success else 0,
                            payload_json,
                            error_text,
                        ),
                    )
                else:
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

    def latest_snapshot(
        self,
        endpoint_key: str,
        success_only: bool = True,
        city: str | None = None,
    ):
        self.init_db()
        policy = self._policy(endpoint_key)
        query = (
            "SELECT fetched_at, success, payload_json, error_text "
            f"FROM {self._table_sql(endpoint_key)}"
        )
        clauses = []
        params = []
        if policy.per_city:
            clauses.append("city = ?")
            params.append(self._city_key(city))
        if success_only:
            clauses.append("success = 1")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY fetched_at DESC, id DESC LIMIT 1"

        with self._db_lock:
            with self._open_db() as conn:
                row = conn.execute(query, params).fetchone()

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

    def fetch_with_history(
        self,
        endpoint_key: str,
        fetcher,
        force: bool = False,
        city: str | None = None,
    ):
        policy = self._policy(endpoint_key)
        latest = self.latest_snapshot(endpoint_key, city=city)
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
                city=city,
            )
            return payload
        except Exception as exc:
            self.record_snapshot(
                endpoint_key,
                None,
                success=False,
                error_text=str(exc),
                fetched_at=now,
                city=city,
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

    def source_refresh_times(self, city: str | None = None) -> dict[str, int]:
        refresh_times: dict[str, int] = {}
        for endpoint_key, policy in self.endpoint_policies.items():
            latest = self.latest_snapshot(endpoint_key, city=city)
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

    def source_status_line(self, city: str | None = None) -> str:
        refresh_times = self.source_refresh_times(city=city)
        parts = []
        for source in SOURCE_FOOTER_ORDER:
            label = SOURCE_FOOTER_LABELS.get(source, source)
            parts.append(f"{label} {self.format_source_age(refresh_times.get(source))}")
        return "  |  ".join(parts)

    def _refresh_status(self, endpoint_key: str, city: str | None = None) -> dict:
        latest_attempt = self.latest_snapshot(endpoint_key, success_only=False, city=city)
        latest_success = self.latest_snapshot(endpoint_key, city=city)
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
        force: bool = False,
        daily_days: int = 7,
        city: str | None = None,
    ) -> dict:
        snapshots = [
            (
                "openmeteo_current",
                lambda: self.openmeteo_current(lat, lon, force=force, city=city),
            ),
            (
                "openmeteo_daily",
                lambda: self.daily_forecast(
                    lat,
                    lon,
                    days=daily_days,
                    force=force,
                    city=city,
                ),
            ),
            (
                "openmeteo_hourly",
                lambda: self.hourly_forecast(
                    lat,
                    lon,
                    hours=24,
                    force=force,
                    city=city,
                ),
            ),
            (
                "buienradar_rain",
                lambda: self.buienradar(lat, lon, force=force, city=city),
            ),
        ]
        sources = {}
        ok = True

        for endpoint_key, loader in snapshots:
            try:
                loader()
                status = self._refresh_status(endpoint_key, city=city)
                if not status["ok"]:
                    ok = False
                sources[endpoint_key] = status
            except Exception as exc:
                ok = False
                latest_success = self.latest_snapshot(endpoint_key, city=city)
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

    def openmeteo_current(
        self,
        lat: float,
        lon: float,
        force: bool = False,
        city: str | None = None,
    ) -> dict:
        def fetch():
            url = (
                "https://api.open-meteo.com/v1/forecast"
                f"?latitude={lat}&longitude={lon}"
                "&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,weather_code,wind_speed_10m,wind_direction_10m,wind_gusts_10m"
                "&timezone=auto"
                "&temperature_unit=celsius"
                "&wind_speed_unit=ms"
                "&precipitation_unit=mm"
                "&forecast_days=1"
            )
            response = requests.get(url, timeout=6)
            response.raise_for_status()
            return response.json()

        return self.fetch_with_history(
            "openmeteo_current",
            fetch,
            force=force,
            city=city,
        )

    def daily_forecast(
        self,
        lat: float,
        lon: float,
        days: int = 7,
        force: bool = False,
        city: str | None = None,
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

        return self.fetch_with_history(
            "openmeteo_daily",
            fetch,
            force=force,
            city=city,
        )

    def hourly_forecast(
        self,
        lat: float,
        lon: float,
        hours: int = 24,
        force: bool = False,
        city: str | None = None,
    ) -> list:
        def fetch():
            url = (
                "https://api.open-meteo.com/v1/forecast"
                f"?latitude={lat}&longitude={lon}"
                "&hourly=temperature_2m,precipitation"
                "&timezone=auto"
                "&forecast_days=2"
            )
            response = requests.get(url, timeout=6)
            response.raise_for_status()
            payload = response.json()
            hourly = payload["hourly"]
            local_tz = self._timezone_from_name(payload.get("timezone"))
            out = []
            for index, timestamp in enumerate(hourly["time"]):
                out.append(
                    {
                        "ts": self._parse_local_hourly_timestamp(timestamp, local_tz),
                        "temp_c": float(hourly["temperature_2m"][index]),
                        "rain_mmh": float(hourly["precipitation"][index] or 0.0),
                    }
                )
            now_ts = self._current_timestamp()
            window_start_ts = now_ts - 3600
            window_end_ts = now_ts + max(hours + 3, 12) * 3600
            filtered = [
                point
                for point in out
                if window_start_ts <= point["ts"] <= window_end_ts
            ]
            if filtered:
                return filtered
            return out[-max(hours + 6, 12):]

        return self.fetch_with_history(
            "openmeteo_hourly",
            fetch,
            force=force,
            city=city,
        )

    def buienradar(
        self,
        lat: float,
        lon: float,
        force: bool = False,
        city: str | None = None,
    ) -> list:
        def fetch():
            url = f"https://gadgets.buienradar.nl/data/raintext/?lat={lat}&lon={lon}"
            response = requests.get(url, timeout=6)
            # Buienradar only serves Belgium/Netherlands coordinates. Outside that
            # area we fall back to Open-Meteo hourly precipitation data.
            if (
                response.status_code == 404
                and "inside the netherlands or belgium" in response.text.casefold()
            ):
                return []
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

        return self.fetch_with_history(
            "buienradar_rain",
            fetch,
            force=force,
            city=city,
        )

    def get_rain_forecast(
        self,
        lat: float,
        lon: float,
        hours: int = 12,
        detailed_hours: int = 3,
        force: bool = False,
        city: str | None = None,
    ) -> dict:
        buienradar_points = self._buienradar_points_with_timestamps(
            self.buienradar(lat, lon, force=force, city=city)
        )
        hourly_forecast = self.hourly_forecast(
            lat,
            lon,
            hours=hours + 6,
            force=force,
            city=city,
        )

        start_ts = (
            buienradar_points[0]["ts"]
            if buienradar_points
            else self._round_ts_to_5_minutes(self._current_timestamp())
        )
        end_ts = start_ts + hours * 3600
        desired_detail_end_ts = start_ts + detailed_hours * 3600
        available_detail_end_ts = start_ts
        if buienradar_points:
            available_detail_end_ts = min(
                desired_detail_end_ts,
                buienradar_points[-1]["ts"] + 5 * 60,
            )
        detailed_end_ts = min(available_detail_end_ts, end_ts)

        lookup = {point["ts"]: float(point.get("mmh", 0.0)) for point in buienradar_points}
        points = []
        slot_ts = start_ts
        while slot_ts < end_ts:
            if slot_ts < detailed_end_ts:
                points.append(
                    {
                        "ts": slot_ts,
                        "mmh": lookup.get(slot_ts, 0.0),
                        "group_start_ts": slot_ts,
                        "duration_minutes": 5,
                        "source": "Buienradar",
                    }
                )
            else:
                coarse_index = int((slot_ts - detailed_end_ts) // 3600)
                group_start_ts = detailed_end_ts + coarse_index * 3600
                points.append(
                    {
                        "ts": slot_ts,
                        "mmh": self._hourly_step_value(
                            hourly_forecast,
                            group_start_ts,
                            "rain_mmh",
                        ),
                        "group_start_ts": group_start_ts,
                        "duration_minutes": 60,
                        "source": "Open-Meteo",
                    }
                )
            slot_ts += 5 * 60

        return {
            "start_ts": start_ts,
            "end_ts": end_ts,
            "detailed_end_ts": detailed_end_ts,
            "points": points,
        }

    def get_temperature_forecast(
        self,
        lat: float,
        lon: float,
        start_ts: int,
        hours: int = 12,
        force: bool = False,
        city: str | None = None,
    ) -> list:
        hourly_forecast = self.hourly_forecast(
            lat,
            lon,
            hours=hours + 6,
            force=force,
            city=city,
        )
        points = []
        for offset in range(hours + 1):
            point_ts = start_ts + offset * 3600
            points.append(
                {
                    "ts": point_ts,
                    "temp_c": self._interpolate_hourly_value(
                        hourly_forecast,
                        point_ts,
                        "temp_c",
                    ),
                }
            )
        return points

    @staticmethod
    def _current_timestamp() -> int:
        return int(time.time())

    @staticmethod
    def _timezone_from_name(value: str | None) -> datetime.tzinfo:
        if value:
            try:
                return ZoneInfo(value)
            except Exception:
                pass
        return BUIENRADAR_TZ

    @staticmethod
    def _round_ts_to_5_minutes(timestamp: int) -> int:
        return timestamp - (timestamp % (5 * 60))

    @staticmethod
    def _parse_local_hourly_timestamp(
        value: str,
        tzinfo: datetime.tzinfo | None = None,
    ) -> int:
        dt = datetime.datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tzinfo or BUIENRADAR_TZ)
        return int(dt.timestamp())

    @classmethod
    def _buienradar_points_with_timestamps(
        cls,
        points: list[dict],
        now: datetime.datetime | None = None,
    ) -> list[dict]:
        if now is None:
            now = datetime.datetime.now(tz=BUIENRADAR_TZ)

        out = []
        previous_dt: datetime.datetime | None = None
        for point in points:
            hour, minute = map(int, point["time"].split(":"))
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate > now + datetime.timedelta(hours=12):
                candidate -= datetime.timedelta(days=1)
            if candidate < now - datetime.timedelta(hours=1):
                candidate += datetime.timedelta(days=1)
            if previous_dt is not None:
                while candidate <= previous_dt:
                    candidate += datetime.timedelta(days=1)
            out.append({**point, "ts": int(candidate.timestamp())})
            previous_dt = candidate
        return out

    @staticmethod
    def _hourly_step_value(series: list[dict], timestamp: int, field: str) -> float:
        if not series:
            return 0.0

        chosen = series[0]
        for point in series:
            if point["ts"] <= timestamp:
                chosen = point
            else:
                break
        return float(chosen[field])

    @staticmethod
    def _interpolate_hourly_value(series: list[dict], timestamp: int, field: str) -> float:
        if not series:
            return 0.0
        if timestamp <= series[0]["ts"]:
            return float(series[0][field])
        if timestamp >= series[-1]["ts"]:
            return float(series[-1][field])

        previous = series[0]
        for current in series[1:]:
            if timestamp <= current["ts"]:
                span = current["ts"] - previous["ts"]
                if span <= 0:
                    return float(current[field])
                fraction = (timestamp - previous["ts"]) / span
                return float(previous[field]) * (1 - fraction) + float(current[field]) * fraction
            previous = current
        return float(series[-1][field])

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