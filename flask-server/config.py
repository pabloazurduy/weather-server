from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).with_name("weather_cache.sqlite3")
DEFAULT_IMG_ROOT = Path(__file__).with_name("img")

try:
    import local_settings as _local_settings
except ImportError:
    _local_settings = None


def _local_value(name: str):
    if _local_settings is None:
        return None
    return getattr(_local_settings, name, None)


def _setting(name: str, default, cast):
    value = os.getenv(f"WEATHER_{name}")
    if value is None:
        value = _local_value(name)
    if value is None:
        return default
    return cast(value)


def _structured_setting(name: str, default):
    value = os.getenv(f"WEATHER_{name}")
    if value is not None:
        return json.loads(value)
    value = _local_value(name)
    if value is None:
        return default
    return value


AMS_LAT = _setting("AMS_LAT", None, float)
AMS_LON = _setting("AMS_LON", None, float)
WIDTH = _setting("WIDTH", 800, int)
HEIGHT = _setting("HEIGHT", 480, int)
REFRESH_RATE = _setting("REFRESH_RATE", 900, int)
OWM_KEY = _setting("OWM_KEY", "", str)
API_KEY = _setting("API_KEY", "replace-with-device-api-key", str)
BASE_URL = _setting("BASE_URL", "http://127.0.0.1:8080", str)
BIND_HOST = _setting("BIND_HOST", "0.0.0.0", str)
BIND_PORT = _setting("BIND_PORT", 8080, int)
DB_PATH = Path(_setting("DB_PATH", str(DEFAULT_DB_PATH), str))
CHARACTER_NAME = _setting("CHARACTER_NAME", "hedgehog", str)
CHARACTER_ASSET_ROOT = Path(_setting("CHARACTER_ASSET_ROOT", str(DEFAULT_IMG_ROOT), str))
CHARACTER_RULES = _structured_setting(
    "CHARACTER_RULES",
    {
        "warm_temp_c": 16.0,
        "freezing_temp_c": 2.0,
        "windy_speed_mps": 10.0,
        "rain_prob_percent": 35,
        "sunny_kinds": ["sun", "partly"],
        "rainy_kinds": ["rain", "storm"],
        "snowy_kinds": ["snow"],
    },
)
