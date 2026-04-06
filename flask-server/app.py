#!/usr/bin/env python3
"""
Weather dashboard server for TRMNL-compatible e-ink device.
Serves a pre-rendered 800x480 PNG via a minimal TRMNL-like API.

Endpoints:
  GET /api/setup?mac_address=XX   -> {"status":200,"api_key":"...","image_url":"..."}
  GET /api/display                -> {"image_url":"...","refresh_rate":900}
  GET /dashboard.png              -> 800x480 2-bit grayscale PNG
  GET /dashboard.bin              -> raw 1-bit packed bitmap (48000 bytes)
  GET /refresh                    -> force-regenerate image cache, returns JSON
  GET /force-refresh-sources      -> bypass source TTLs and refresh remote sources
"""

import datetime
import io
import json
import math
import threading
import time
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont

from config import (
    API_KEY,
    BASE_URL,
    BIND_HOST,
    BIND_PORT,
    CHARACTER_ASSET_ROOT,
    CHARACTER_NAME,
    CHARACTER_RULES,
    CITY,
    CITY_LAT,
    CITY_LON,
    DB_PATH,
    HEIGHT,
    REFRESH_RATE,
    WIDTH,
)
from models import WeatherStore

weather_store = WeatherStore(DB_PATH, default_city=CITY)

# Cache rendered PNGs so repeated polls do not redraw the same image.
_cache: dict = {"png": None, "ts": 0}
_cache_lock = threading.Lock()
CACHE_TTL = 300  # regenerate image every 5 min

# Latest in-process sensor values; the persistent source of truth is SQLite.
_indoor: dict = {"temp": None, "humidity": None, "battery_voltage": None, "ts": None}
_character_icon_cache: dict[str, Image.Image] = {}


def _configured_location() -> tuple[str, float, float]:
    if CITY_LAT is None or CITY_LON is None:
        raise RuntimeError(
            "Set WEATHER_CITY_LAT and WEATHER_CITY_LON or define CITY_LAT and CITY_LON in flask-server/local_settings.py"
        )
    return CITY, CITY_LAT, CITY_LON


def _character_icon_key(
    today_forecast: dict | None,
    current_kind: str,
    current_wind_mps: float,
    rules: dict | None = None,
) -> str:
    active_rules = rules or CHARACTER_RULES
    warm_temp_c = float(active_rules.get("warm_temp_c", 16.0))
    freezing_temp_c = float(active_rules.get("freezing_temp_c", 2.0))
    windy_speed_mps = float(active_rules.get("windy_speed_mps", 10.0))
    rain_prob_percent = int(active_rules.get("rain_prob_percent", 35))
    sunny_kinds = set(active_rules.get("sunny_kinds", ["sun", "partly"]))
    rainy_kinds = set(active_rules.get("rainy_kinds", ["rain", "storm"]))
    snowy_kinds = set(active_rules.get("snowy_kinds", ["snow"]))

    forecast = today_forecast or {}
    forecast_kind = str(forecast.get("kind") or current_kind or "cloud")
    forecast_min = float(forecast.get("temp_min") or 0.0)
    forecast_max = float(forecast.get("temp_max") or forecast_min)
    rain_prob = int(forecast.get("rain_prob") or 0)

    if forecast_kind in snowy_kinds:
        return "snow"

    if forecast_min <= freezing_temp_c and current_wind_mps >= windy_speed_mps and forecast_kind not in rainy_kinds:
        return "freezing_windy"

    temp_variant = "warm" if forecast_max >= warm_temp_c else "cold"

    if forecast_kind in rainy_kinds or rain_prob >= rain_prob_percent:
        return f"rainy_{temp_variant}"

    if forecast_kind in sunny_kinds:
        return f"sunny_{temp_variant}"

    return f"cloudy_{temp_variant}"


def _load_character_icon(icon_key: str) -> Image.Image | None:
    icon_path = CHARACTER_ASSET_ROOT / CHARACTER_NAME / f"{icon_key}.png"
    cache_key = str(icon_path)
    cached_icon = _character_icon_cache.get(cache_key)
    if cached_icon is not None:
        return cached_icon
    if not icon_path.exists():
        return None
    with Image.open(icon_path) as image:
        cached_icon = image.convert("L")
    _character_icon_cache[cache_key] = cached_icon
    return cached_icon


def _character_icon_label(icon_key: str) -> str:
    return icon_key.replace("_", " ")


def _draw_character_panel(
    img: Image.Image,
    rect,
    today_forecast: dict | None,
    current_kind: str,
    current_wind_mps: float,
):
    draw = ImageDraw.Draw(img)
    x0, y0, x1, y1 = rect
    icon_key = _character_icon_key(today_forecast, current_kind, current_wind_mps)
    icon = _load_character_icon(icon_key)
    panel_label = _character_icon_label(icon_key)
    _draw_weather_icon(draw, x0 + 8, y0 + 2, current_kind, 20)
    _text(draw, (x0 + 36, y0 + 12), panel_label, 13)

    if icon is None:
        _text(draw, (x0 + 12, y0 + 30), f"{CHARACTER_NAME}/{icon_key}", 11)
        return

    max_w = max(1, x1 - x0 - 20)
    max_h = max(1, y1 - y0 - 36)
    scale = min(max_w / icon.width, max_h / icon.height)
    target_size = (
        max(1, int(round(icon.width * scale))),
        max(1, int(round(icon.height * scale))),
    )
    rendered = icon.resize(target_size, Image.Resampling.NEAREST) if target_size != icon.size else icon
    paste_x = x0 + (x1 - x0 - rendered.width) // 2
    paste_y = y0 + 24 + (y1 - y0 - 24 - rendered.height) // 2
    img.paste(rendered, (paste_x, paste_y))


# ── Weather helpers ────────────────────────────────────────────────────────────

def _wind_direction(deg: float) -> str:
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(deg / 45) % 8]


def _weather_kind_from_openmeteo(code: int, is_day: int | bool) -> str:
    kind = WeatherStore._weather_kind_from_code(code)
    if not bool(is_day):
        if kind == "sun":
            return "moon"
        if kind == "partly":
            return "partly-night"
    return kind


def _weather_desc_from_openmeteo(code: int) -> str:
    descriptions = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Light freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snowfall",
        73: "Moderate snowfall",
        75: "Heavy snowfall",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }
    return descriptions.get(int(code), "Unknown")


def _location_timezone(timezone_name: str | None) -> datetime.tzinfo:
    if timezone_name:
        try:
            return ZoneInfo(timezone_name)
        except Exception:
            pass
    return datetime.timezone.utc


# ── Font helpers ───────────────────────────────────────────────────────────────

TEXT_FONT_PATHS = {
    False: (
        "/System/Library/Fonts/SFNSDisplay.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ),
    True: (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ),
}

ICON_FONT_PATHS = (
    "/System/Library/Fonts/Apple Symbols.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",
)


@lru_cache(maxsize=None)
def _load_cached_font(paths: tuple[str, ...], size: int):
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _font(size: int, bold: bool = False):
    return _load_cached_font(TEXT_FONT_PATHS[bold], size)


def _icon_font(size: int):
    return _load_cached_font(ICON_FONT_PATHS, size)


# ── Drawing helpers ────────────────────────────────────────────────────────────

def _text(draw: ImageDraw.ImageDraw, xy, text: str, size: int,
          bold: bool = False, anchor="la"):
    draw.text(xy, text, font=_font(size, bold), fill=0, anchor=anchor)


def _icon_text(draw: ImageDraw.ImageDraw, xy, text: str, size: int,
               anchor: str = "la"):
    draw.text(xy, text, font=_icon_font(size), fill=0, anchor=anchor)


def _draw_weather_icon(draw: ImageDraw.ImageDraw, x: float, y: float,
                       kind: str, size: int = 24):
    if kind in {"partly", "partly-night", "cloud", "fog", "rain", "snow", "storm"}:
        y -= int(round(size * 0.35))

    if kind == "sun":
        _icon_text(draw, (x, y), "☀", int(size * 0.95))
        return

    if kind == "moon":
        _icon_text(draw, (x, y), "☾", int(size * 0.95))
        return

    if kind == "partly":
        _icon_text(draw, (x, y - 2), "☀", int(size * 0.8))
        _icon_text(draw, (x + size // 4, y + size // 6), "☁", int(size * 0.9))
        return

    if kind == "partly-night":
        _icon_text(draw, (x, y - 2), "☾", int(size * 0.8))
        _icon_text(draw, (x + size // 4, y + size // 6), "☁", int(size * 0.9))
        return

    if kind == "cloud":
        _icon_text(draw, (x, y + size // 10), "☁", int(size * 0.95))
        return

    if kind == "fog":
        _icon_text(draw, (x + 1, y + size // 12), "☁", int(size * 0.88))
        for row in (y + size - 6, y + size - 2):
            draw.line([x + 4, row, x + size + 4, row], fill=0, width=1)
        return

    _icon_text(draw, (x, y + size // 10), "☁", int(size * 0.95))

    if kind == "rain":
        rain_top = y + size + 1
        rain_bottom = y + size + 8
        for offset in (6, 12, 18):
            draw.line([x + offset, rain_top, x + offset - 2, rain_bottom],
                      fill=0, width=2)
    elif kind == "snow":
        _icon_text(draw, (x + size // 3, y + size // 2), "❄", int(size * 0.55))
    elif kind == "storm":
        draw.line([
            x + 12, y + size - 8,
            x + 8, y + size - 1,
            x + 13, y + size - 1,
            x + 10, y + size + 5,
        ], fill=0, width=2)


def _draw_daily_forecast(draw: ImageDraw.ImageDraw, rect, daily: list):
    x0, y0, x1, y1 = rect
    if not daily:
        _text(draw, (x0, y0 + 16), "7-day forecast", 15, bold=True)
        _text(draw, (x0, y0 + 38), "temporarily unavailable", 13)
        return

    temp_floor = math.floor(min(day["temp_min"] for day in daily) - 1)
    temp_ceiling = math.ceil(max(day["temp_max"] for day in daily) + 1)
    temp_span = max(temp_ceiling - temp_floor, 1)
    row_h = (y1 - y0) // len(daily)
    prob_font = _font(13, bold=True)
    min_temp_font = _font(13)
    icon_size = 26

    for idx, day in enumerate(daily):
        row_y = y0 + idx * row_h
        row_mid = row_y + row_h // 2
        date_obj = datetime.date.fromisoformat(day["date"])
        label = date_obj.strftime("%a %-d")
        prob_x = x0 + 60

        if idx > 0:
            draw.line([x0, row_y, x1, row_y], fill=220, width=1)

        _text(draw, (x0, row_mid), label, 14, bold=True, anchor="lm")
        rain_prob_text = None
        prob_right = prob_x + 18
        if day.get("rain_prob") is not None:
            rain_prob_text = f"{day['rain_prob']}%"
            _text(draw, (prob_x, row_mid), rain_prob_text, 13, bold=True, anchor="lm")
            prob_box = draw.textbbox((prob_x, row_mid), rain_prob_text, font=prob_font, anchor="lm")
            prob_right = prob_box[2]

        bar_x0 = x0 + 148
        bar_x1 = x1 - 38
        min_temp_text = f"{day['temp_min']:.0f}°"
        min_temp_x = bar_x0 - 8
        draw.textbbox((min_temp_x, row_mid), min_temp_text, font=min_temp_font, anchor="rm")
        icon_center_x = int((prob_right + min_temp_x) / 2) - 4
        icon_x = icon_center_x - icon_size // 2
        _draw_weather_icon(draw, icon_x, row_mid - 20, day["kind"], icon_size)

        draw.line([bar_x0, row_mid, bar_x1, row_mid], fill=180, width=7)

        seg_x0 = bar_x0 + int(((day["temp_min"] - temp_floor) / temp_span) * (bar_x1 - bar_x0))
        seg_x1 = bar_x0 + int(((day["temp_max"] - temp_floor) / temp_span) * (bar_x1 - bar_x0))
        seg_x1 = max(seg_x1, seg_x0 + 8)
        draw.rounded_rectangle([seg_x0, row_mid - 6, seg_x1, row_mid + 6],
                               radius=6, fill=0)

        _text(draw, (min_temp_x, row_mid), min_temp_text, 13, anchor="rm")
        _text(draw, (x1, row_mid), f"{day['temp_max']:.0f}°", 13, anchor="rm")


def _draw_bar_chart(draw: ImageDraw.ImageDraw, rect, data_mmh: list,
                    temp_data: list, x_labels: list):
    """Draw combined rain bars + temperature line in rect=(x0,y0,x1,y1)."""
    x0, y0, x1, y1 = rect
    w = x1 - x0
    h = y1 - y0
    n = len(data_mmh)
    if n == 0:
        return

    max_mmh = max((d for d in data_mmh), default=1) or 1
    min_temp = min(temp_data) if temp_data else 0
    max_temp = max(temp_data) if temp_data else 1
    temp_range = max(max_temp - min_temp, 1)

    bar_w = max(1, (w - 2) // n)

    # Rain bars (grey filled)
    for i, mmh in enumerate(data_mmh):
        bh = int((mmh / max_mmh) * (h - 20))
        bx = x0 + i * bar_w
        if bh > 0:
            draw.rectangle([bx, y1 - 20 - bh, bx + bar_w - 1, y1 - 20],
                           fill=180)

    # Baseline
    draw.line([x0, y1 - 20, x1, y1 - 20], fill=0, width=1)

    # Temperature line (black)
    if len(temp_data) >= 2:
        points = []
        for i, temp_value in enumerate(temp_data):
            px = x0 + int((i / (len(temp_data) - 1)) * (w - 2))
            py = y1 - 20 - int(((temp_value - min_temp) / temp_range) * (h - 28))
            points.append((px, py))
        for i in range(len(points) - 1):
            draw.line([points[i], points[i + 1]], fill=0, width=2)

    # X-axis labels (every 3rd)
    for i, label in enumerate(x_labels):
        if i % 3 == 0:
            lx = x0 + i * bar_w + bar_w // 2
            _text(draw, (lx, y1 - 18), label, 9, anchor="mt")

    # Y-axis rain label
    _text(draw, (x0, y0 + 2), f"{max_mmh:.1f}mm/h", 9)

    # Y-axis temp labels
    _text(draw, (x1 - 2, y0 + 2), f"{max_temp:.0f}°", 9, anchor="ra")
    _text(draw, (x1 - 2, y1 - 32), f"{min_temp:.0f}°", 9, anchor="ra")


def _rain_segments(rain_forecast: dict) -> list[dict]:
    segments = []
    end_ts = rain_forecast["end_ts"]
    seen_groups = set()
    for point in rain_forecast["points"]:
        group_start_ts = int(point["group_start_ts"])
        if group_start_ts in seen_groups:
            continue
        seen_groups.add(group_start_ts)
        duration_seconds = int(point["duration_minutes"]) * 60
        segments.append(
            {
                "start_ts": group_start_ts,
                "end_ts": min(group_start_ts + duration_seconds, end_ts),
                "mmh": float(point["mmh"]),
            }
        )
    return segments


def _draw_proportional_chart(
    draw: ImageDraw.ImageDraw,
    rect,
    rain_forecast: dict,
    temp_forecast: list,
    chart_tz: datetime.tzinfo,
):
    x0, y0, x1, y1 = rect
    w = x1 - x0
    plot_bottom = y1 - 28
    plot_height = plot_bottom - y0
    start_ts = int(rain_forecast["start_ts"])
    end_ts = int(rain_forecast["end_ts"])
    total_span = max(end_ts - start_ts, 1)
    rain_segments = _rain_segments(rain_forecast)

    actual_max_mmh = max((segment["mmh"] for segment in rain_segments), default=0.0)
    scale_max_mmh = max(actual_max_mmh, 1.0)
    temp_values = [point["temp_c"] for point in temp_forecast]
    min_temp = min(temp_values) if temp_values else 0.0
    max_temp = max(temp_values) if temp_values else 1.0
    display_min_temp = math.floor(min_temp - 5.0)
    display_max_temp = math.ceil(max_temp + 5.0)
    display_temp_range = max(display_max_temp - display_min_temp, 10.0)

    def x_for(timestamp: int) -> int:
        return x0 + int(((timestamp - start_ts) / total_span) * (w - 2))

    def y_for_temp(temp_c: float) -> int:
        ratio = (temp_c - display_min_temp) / display_temp_range
        ratio = max(0.0, min(1.0, ratio))
        return plot_bottom - int(ratio * (plot_height - 8))

    for segment in rain_segments:
        if segment["mmh"] <= 0:
            continue
        bar_height = max(1, int((segment["mmh"] / scale_max_mmh) * plot_height))
        seg_x0 = x_for(segment["start_ts"])
        seg_x1 = max(x_for(segment["end_ts"]), seg_x0 + 1)
        draw.rectangle([seg_x0, plot_bottom - bar_height, seg_x1 - 1, plot_bottom], fill=180)

    draw.line([x0, plot_bottom, x1, plot_bottom], fill=0, width=1)

    if display_min_temp <= 0 <= display_max_temp:
        zero_y = y_for_temp(0.0)
        dash_start = x0
        while dash_start < x1:
            dash_end = min(dash_start + 5, x1)
            draw.line([dash_start, zero_y, dash_end, zero_y], fill=170, width=1)
            dash_start += 9

    if len(temp_forecast) >= 2:
        points = []
        for point in temp_forecast:
            px = x_for(int(point["ts"]))
            py = y_for_temp(float(point["temp_c"]))
            points.append((px, py, float(point["temp_c"])))
        for index in range(len(points) - 1):
            draw.line([points[index][:2], points[index + 1][:2]], fill=0, width=2)
        for px, py, temp_c in points:
            draw.ellipse([px - 2, py - 2, px + 2, py + 2], fill=0)
            _text(draw, (px, max(y0 + 8, py - 10)), f"{temp_c:.0f}°", 10, anchor="mb")

    start_dt = datetime.datetime.fromtimestamp(start_ts, tz=chart_tz)
    end_dt = datetime.datetime.fromtimestamp(end_ts, tz=chart_tz)
    first_tick_dt = start_dt.replace(minute=0, second=0, microsecond=0)
    if first_tick_dt < start_dt:
        first_tick_dt += datetime.timedelta(hours=1)

    tick_dt = first_tick_dt
    tick_font = _font(12)
    while tick_dt <= end_dt:
        tick_ts = int(tick_dt.timestamp())
        tick_x = x_for(tick_ts)
        draw.line([tick_x, plot_bottom, tick_x, plot_bottom + 4], fill=0, width=1)
        label = tick_dt.strftime("%H:00")
        label_box = draw.textbbox((0, 0), label, font=tick_font, anchor="la")
        label_half_w = (label_box[2] - label_box[0]) // 2
        label_x = min(max(tick_x, x0 + label_half_w), x1 - label_half_w)
        _text(draw, (label_x, y1 - 18), label, 12, anchor="mt")
        tick_dt += datetime.timedelta(hours=1)

    _text(draw, (x0, y0 + 2), f"{actual_max_mmh:.1f}mm/h", 9)
    _text(draw, (x1 - 2, y0 + 2), f"{display_max_temp:.0f}°", 9, anchor="ra")
    _text(draw, (x1 - 2, plot_bottom - 12), f"{display_min_temp:.0f}°", 9, anchor="ra")


# ── PNG generation ─────────────────────────────────────────────────────────────

def generate_png(battery_voltage: float | None = None) -> bytes:
    city_name, lat, lon = _configured_location()

    # Fetch data
    current = weather_store.openmeteo_current(lat, lon, city=city_name)
    rain_forecast = weather_store.get_rain_forecast(
        lat,
        lon,
        hours=12,
        detailed_hours=3,
        city=city_name,
    )
    temp_forecast = weather_store.get_temperature_forecast(
        lat,
        lon,
        start_ts=rain_forecast["start_ts"],
        hours=12,
        city=city_name,
    )
    try:
        daily = weather_store.daily_forecast(lat, lon, days=7, city=city_name)
    except requests.RequestException as exc:
        print(f"[WARN] daily forecast unavailable: {exc}")
        daily = []

    current_data = current["current"]
    location_tz = _location_timezone(current.get("timezone"))
    now_local = datetime.datetime.now(tz=location_tz)
    indoor = weather_store.latest_sensor_reading() or _indoor
    footer_sources = weather_store.source_status_line(city=city_name)

    img = Image.new("L", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(img)

    MID_DIV_X = 352
    RIGHT_DIV_X = 540
    TOP_BOTTOM_Y = 214
    CHART_TOP_Y = 236
    C1_X = 16
    C3_X = RIGHT_DIV_X + 12

    # Layout frame: column titles, timestamp, and divider lines.
    title_y = 10
    _text(draw, (C1_X, title_y), city_name, 18, bold=True)
    city_title_box = draw.textbbox((C1_X, title_y), city_name,
                                   font=_font(18, True), anchor="la")
    _text(draw, (C3_X, 10), f"{city_name} 7-Day", 16, bold=True)
    _text(draw, (WIDTH - 16, 10),
            now_local.strftime("%b %-d  %-I:%M %p"), 13, anchor="ra")

    draw.line([16, 38, WIDTH - 16, 38], fill=180, width=1)

    draw.line([MID_DIV_X, 42, MID_DIV_X, TOP_BOTTOM_Y], fill=180, width=1)
    draw.line([RIGHT_DIV_X, 42, RIGHT_DIV_X, HEIGHT - 30], fill=180, width=1)
    draw.line([16, TOP_BOTTOM_Y, RIGHT_DIV_X - 16, TOP_BOTTOM_Y], fill=180, width=1)

    current_temp = float(current_data["temperature_2m"])
    current_feels_like = float(current_data["apparent_temperature"])
    current_humidity = int(round(float(current_data["relative_humidity_2m"])))
    current_description = _weather_desc_from_openmeteo(int(current_data["weather_code"]))
    current_wind_speed = float(current_data["wind_speed_10m"])
    current_wind_direction = _wind_direction(float(current_data["wind_direction_10m"]))
    current_wind_gust = float(current_data.get("wind_gusts_10m") or 0.0)
    current_kind = _weather_kind_from_openmeteo(
        int(current_data["weather_code"]),
        int(current_data.get("is_day", 1)),
    )
    header_icon_size = 20
    header_icon_x = city_title_box[2] + 8
    _draw_weather_icon(draw, header_icon_x, 8, current_kind, header_icon_size)
    _text(draw, (header_icon_x + 28, 12), now_local.strftime("%A %B %-d"), 11)
    today_rain_prob = daily[0].get("rain_prob") if daily else None
    today_min = daily[0].get("temp_min") if daily else None
    today_max = daily[0].get("temp_max") if daily else None

    # Left column: current configured-city conditions.
    current_temp_text = f"{current_temp:.0f}°C"
    _text(draw, (C1_X, 44), current_temp_text, 46, bold=True)
    left_detail_y = 96
    left_detail_step = 16
    device_temp_right_x = MID_DIV_X - 12
    if indoor["temp"] is not None:
        indoor_temp_text = f"{indoor['temp']:.1f}°C"
        _text(draw, (device_temp_right_x, 44), indoor_temp_text, 46, bold=True, anchor="ra")
        indoor_temp_box = draw.textbbox(
            (device_temp_right_x, 44),
            indoor_temp_text,
            font=_font(46, True),
            anchor="ra",
        )
        device_info_x = indoor_temp_box[0]
        _text(draw, (device_info_x, indoor_temp_box[3] + 4), "Indoor(sensor)", 12)
        _text(draw, (device_info_x, 98), f"Humidity  {indoor['humidity']:.0f}%", 12)
        bv = indoor.get("battery_voltage") or battery_voltage
        if bv is not None:
            batt_pct = max(0, min(100, int((bv - 3.3) / (4.2 - 3.3) * 100)))
            _text(draw, (device_info_x, 114), f"Battery  {batt_pct}%  ({bv:.2f} V)", 12)
        if indoor["ts"] is not None:
            ts_dt = datetime.datetime.fromtimestamp(indoor["ts"], tz=datetime.timezone.utc)
            ts_loc = ts_dt.astimezone(location_tz)
            _text(draw, (device_info_x, 130), ts_loc.strftime("Updated  %-I:%M %p"), 11)
    else:
        _text(draw, (device_temp_right_x, 74), "Indoor(sensor)", 12, anchor="ra")
        _text(draw, (device_temp_right_x, 98), "Device data unavailable", 12, anchor="ra")

    if today_min is not None and today_max is not None:
        _text(draw, (C1_X, left_detail_y),
              f"Min {today_min:.0f}°C  Max {today_max:.0f}°C", 12)
    else:
        _text(draw, (C1_X, left_detail_y), "Min --  Max --", 12)

    _text(draw, (C1_X, left_detail_y + left_detail_step), f"Feels  {current_feels_like:.0f}°C", 13)
    if today_rain_prob is not None:
        _text(draw, (C1_X, left_detail_y + left_detail_step * 2),
              f"Rain probability  {today_rain_prob}%", 13)
    else:
        _text(draw, (C1_X, left_detail_y + left_detail_step * 2),
              "Rain probability  --", 13)

    _text(draw, (C1_X, left_detail_y + left_detail_step * 3), current_description, 13)

    _text(draw, (C1_X, left_detail_y + left_detail_step * 4), f"Humidity  {current_humidity}%", 13)
    _text(draw, (C1_X, left_detail_y + left_detail_step * 5),
          f"Wind  {current_wind_speed:.0f} m/s {current_wind_direction}", 13)
    _text(draw, (C1_X, left_detail_y + left_detail_step * 6),
          f"Gusts  {current_wind_gust:.0f} m/s", 13)

    _draw_character_panel(
        img,
        (MID_DIV_X + 4, 46, RIGHT_DIV_X - 4, TOP_BOTTOM_Y - 4),
        daily[0] if daily else None,
        current_kind,
        current_wind_speed,
    )

    # Right column: 7-day configured-city forecast.
    _draw_daily_forecast(draw, (C3_X, 44, WIDTH - 16, HEIGHT - 42), daily)

    # Bottom-left panel: rain bars and temperature line chart.
    _text(draw, (16, CHART_TOP_Y - 12), "Rain next 12h (5m now, hourly later) + Temperature", 11)
    _draw_proportional_chart(
        draw,
        (16, CHART_TOP_Y, RIGHT_DIV_X - 16, HEIGHT - 30),
        rain_forecast,
        temp_forecast,
        chart_tz=location_tz,
    )

    # Footer: cached source freshness summary.
    draw.line([16, HEIGHT - 28, WIDTH - 16, HEIGHT - 28], fill=180, width=1)
    _text(draw, (16, HEIGHT - 22), footer_sources, 10)

    img = img.convert("1").convert("L")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Cached PNG ─────────────────────────────────────────────────────────────────

def get_png(battery_voltage: float | None = None) -> bytes:
    with _cache_lock:
        if time.time() - _cache["ts"] > CACHE_TTL or _cache["png"] is None:
            try:
                _cache["png"] = generate_png(battery_voltage)
                _cache["ts"] = time.time()
            except Exception as exc:
                print(f"[ERROR] generate_png: {exc}")
                if _cache["png"] is None:
                    raise
        return _cache["png"]


# ── HTTP Handler ───────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/sensor":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                _indoor["temp"] = float(data["temp"])
                _indoor["humidity"] = float(data["humidity"])
                _indoor["battery_voltage"] = (
                    float(data["battery_voltage"])
                    if "battery_voltage" in data else None
                )
                _indoor["ts"] = time.time()
                weather_store.store_sensor_reading(
                    _indoor["temp"],
                    _indoor["humidity"],
                    _indoor["battery_voltage"],
                )
                with _cache_lock:
                    _cache["ts"] = 0
                print(
                    f"[sensor] temp={_indoor['temp']:.1f}C  hum={_indoor['humidity']:.0f}%  "
                    f"batt={_indoor['battery_voltage']}V"
                )
                self._respond(200, "application/json", b'{"ok":true}')
            except (KeyError, ValueError) as exc:
                self._respond(400, "application/json",
                              json.dumps({"error": str(exc)}).encode())
        else:
            self._respond(404, "text/plain", b"Not found")

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path in ("/api/setup", "/api/setup/"):
            body = json.dumps({
                "status": 200,
                "api_key": API_KEY,
                "friendly_id": "weather-dashboard",
                "image_url": f"{BASE_URL}/dashboard.png",
                "message": "OK",
            }).encode()
            self._respond(200, "application/json", body)

        elif parsed.path == "/api/display":
            body = json.dumps({
                "image_url": f"{BASE_URL}/dashboard.png",
                "refresh_rate": REFRESH_RATE,
                "reset_firmware": False,
                "update_firmware": False,
                "firmware_url": None,
            }).encode()
            self._respond(200, "application/json", body)

        elif parsed.path == "/dashboard.png":
            batt = None
            if "battery_voltage" in qs:
                try:
                    batt = float(qs["battery_voltage"][0])
                except ValueError:
                    pass
            try:
                png = get_png(batt)
                self._respond(200, "image/png", png)
            except Exception as exc:
                self._respond(500, "text/plain", str(exc).encode())

        elif parsed.path == "/dashboard.bin":
            batt = None
            if "battery_voltage" in qs:
                try:
                    batt = float(qs["battery_voltage"][0])
                except ValueError:
                    pass
            try:
                png = get_png(batt)
                img_1bit = Image.open(io.BytesIO(png)).convert("1")
                raw = img_1bit.tobytes("raw", "1")
                self._respond(200, "application/octet-stream", raw)
            except Exception as exc:
                self._respond(500, "text/plain", str(exc).encode())

        elif parsed.path == "/refresh":
            with _cache_lock:
                _cache["ts"] = 0
            try:
                png = get_png()
                body = json.dumps({
                    "ok": True,
                    "bytes": len(png),
                    "ts": int(time.time()),
                }).encode()
                self._respond(200, "application/json", body)
                print("[refresh] cache regenerated")
            except Exception as exc:
                self._respond(500, "application/json",
                              json.dumps({"ok": False, "error": str(exc)}).encode())

        elif parsed.path == "/force-refresh-sources":
            try:
                _, lat, lon = _configured_location()
                result = weather_store.refresh_all_sources(
                    lat,
                    lon,
                    force=True,
                    city=CITY,
                )
                with _cache_lock:
                    _cache["ts"] = 0
                png = get_png()
                result["bytes"] = len(png)
                result["ts"] = int(time.time())
                self._respond(200, "application/json", json.dumps(result).encode())
                print("[force-refresh-sources] source TTLs bypassed")
            except Exception as exc:
                self._respond(500, "application/json",
                              json.dumps({"ok": False, "error": str(exc)}).encode())

        elif parsed.path in ("/", "/index.html"):
            ts = int(time.time())
            html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="300">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html, body {{ width: 800px; height: 480px; overflow: hidden; background: white; }}
    img {{ width: 800px; height: 480px; display: block; }}
  </style>
</head>
<body>
  <img src="/dashboard.png?t={ts}" alt="Weather Dashboard">
</body>
</html>""".encode()
            self._respond(200, "text/html", html)

        elif parsed.path == "/up":
            self._respond(200, "application/json", b'{"status":"ok"}')

        else:
            self._respond(404, "text/plain", b"Not found")

    def _respond(self, status: int, content_type: str, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[{self.address_string()}] {format % args}")


if __name__ == "__main__":
    weather_store.init_db()
    print("Warming up cache...")
    try:
        get_png()
        print("Cache ready.")
    except Exception as exc:
        print(f"Startup warning: {exc}")

    server = HTTPServer((BIND_HOST, BIND_PORT), Handler)
    print(f"Weather dashboard running on http://{BIND_HOST}:{BIND_PORT}")
    print(f"  Dashboard PNG: {BASE_URL}/dashboard.png")
    server.serve_forever()

