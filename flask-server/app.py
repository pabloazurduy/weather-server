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
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import requests
from PIL import Image, ImageDraw, ImageFont

from config import (
    AMS_LAT,
    AMS_LON,
    API_KEY,
    BASE_URL,
    BIND_HOST,
    BIND_PORT,
    DB_PATH,
    HEIGHT,
    OWM_KEY,
    REFRESH_RATE,
    WIDTH,
)
from models import WeatherStore

weather_store = WeatherStore(DB_PATH)

# Cache rendered PNGs so repeated polls do not redraw the same image.
_cache: dict = {"png": None, "ts": 0}
_cache_lock = threading.Lock()
CACHE_TTL = 300  # regenerate image every 5 min

# Latest in-process sensor values; the persistent source of truth is SQLite.
_indoor: dict = {"temp": None, "humidity": None, "battery_voltage": None, "ts": None}


# ── Weather helpers ────────────────────────────────────────────────────────────

def _wind_direction(deg: float) -> str:
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(deg / 45) % 8]


def _weather_kind_from_owm(weather: dict) -> str:
    code = int(weather.get("id", 0))
    if 200 <= code < 300:
        return "storm"
    if 300 <= code < 600:
        return "rain"
    if 600 <= code < 700:
        return "snow"
    if 700 <= code < 800:
        return "fog"
    if code == 800:
        return "sun"
    if code in (801, 802):
        return "partly"
    return "cloud"


# ── Font helpers ───────────────────────────────────────────────────────────────

def _font(size: int, bold: bool = False):
    faces = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSDisplay.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in faces:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _icon_font(size: int):
    faces = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Apple Symbols.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in faces:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


# ── Drawing helpers ────────────────────────────────────────────────────────────

def _text(draw: ImageDraw.ImageDraw, xy, text: str, size: int,
          bold: bool = False, anchor="la"):
    draw.text(xy, text, font=_font(size, bold), fill=0, anchor=anchor)


def _icon_text(draw: ImageDraw.ImageDraw, xy, text: str, size: int,
               anchor: str = "la"):
    draw.text(xy, text, font=_icon_font(size), fill=0, anchor=anchor)


def _draw_weather_icon(draw: ImageDraw.ImageDraw, x: float, y: float,
                       kind: str, size: int = 24):
    if kind == "sun":
        _icon_text(draw, (x, y), "☀", int(size * 0.95))
        return

    if kind == "partly":
        _icon_text(draw, (x, y - 2), "☀", int(size * 0.8))
        _icon_text(draw, (x + size // 4, y + size // 6), "☁", int(size * 0.9))
        return

    if kind == "cloud":
        _icon_text(draw, (x, y + size // 10), "☁", int(size * 0.95))
        return

    if kind == "fog":
        _icon_text(draw, (x + 1, y + 1), "☁", int(size * 0.9))
        for row in (y + size - 4, y + size, y + size + 4):
            draw.line([x + 4, row, x + size + 6, row], fill=0, width=1)
        return

    _icon_text(draw, (x, y + size // 10), "☁", int(size * 0.95))

    if kind == "rain":
        for offset in (6, 12, 18):
            draw.line([x + offset, y + size - 6, x + offset - 2, y + size - 1],
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
        _text(draw, (x0, y0 + 16), "7-day forecast", 14, bold=True)
        _text(draw, (x0, y0 + 38), "temporarily unavailable", 12)
        return

    temp_floor = math.floor(min(day["temp_min"] for day in daily) - 1)
    temp_ceiling = math.ceil(max(day["temp_max"] for day in daily) + 1)
    temp_span = max(temp_ceiling - temp_floor, 1)
    row_h = (y1 - y0) // len(daily)

    for idx, day in enumerate(daily):
        row_y = y0 + idx * row_h
        row_mid = row_y + row_h // 2
        date_obj = datetime.date.fromisoformat(day["date"])
        label = date_obj.strftime("%a %-d")
        prob_x = x0 + 52
        icon_x = x0 + 92

        if idx > 0:
            draw.line([x0, row_y, x1, row_y], fill=220, width=1)

        _text(draw, (x0, row_mid), label, 12, bold=True, anchor="lm")
        if day.get("rain_prob") is not None:
            _text(draw, (prob_x, row_mid), f"{day['rain_prob']}%", 11, bold=True, anchor="lm")
        _draw_weather_icon(draw, icon_x, row_mid - 12, day["kind"], 24)

        bar_x0 = x0 + 136
        bar_x1 = x1 - 34
        draw.line([bar_x0, row_mid, bar_x1, row_mid], fill=180, width=6)

        seg_x0 = bar_x0 + int(((day["temp_min"] - temp_floor) / temp_span) * (bar_x1 - bar_x0))
        seg_x1 = bar_x0 + int(((day["temp_max"] - temp_floor) / temp_span) * (bar_x1 - bar_x0))
        seg_x1 = max(seg_x1, seg_x0 + 8)
        draw.rounded_rectangle([seg_x0, row_mid - 5, seg_x1, row_mid + 5],
                               radius=5, fill=0)

        _text(draw, (bar_x0 - 8, row_mid), f"{day['temp_min']:.0f}°", 12, anchor="rm")
        _text(draw, (x1, row_mid), f"{day['temp_max']:.0f}°", 12, anchor="rm")


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


# ── PNG generation ─────────────────────────────────────────────────────────────

def generate_png(battery_voltage: float | None = None) -> bytes:
    # Fetch data
    ams = weather_store.owm_current(AMS_LAT, AMS_LON, OWM_KEY)
    fc = weather_store.owm_forecast(AMS_LAT, AMS_LON, OWM_KEY, cnt=16)
    rain = weather_store.buienradar(AMS_LAT, AMS_LON)
    try:
        daily = weather_store.ams_daily_forecast(AMS_LAT, AMS_LON, days=7)
    except requests.RequestException as exc:
        print(f"[WARN] daily forecast unavailable: {exc}")
        daily = []

    # Build chart series
    rain_mmh = [r["mmh"] for r in rain]
    rain_times = [r["time"] for r in rain]

    for slot in fc[1:]:
        mmh = slot.get("rain", {}).get("3h", 0) / 3.0
        rain_mmh.append(round(mmh, 2))
        rain_times.append(slot["dt_txt"][11:16])
        if len(rain_mmh) >= 40:
            break

    temp_series = [slot["main"]["temp"] for slot in fc]

    n_points = min(len(rain_mmh), 40)
    rain_mmh = rain_mmh[:n_points]
    rain_times = rain_times[:n_points]
    temp_resampled = []
    for i in range(n_points):
        idx = i * (len(temp_series) - 1) / max(n_points - 1, 1)
        lo = int(idx)
        hi = min(int(idx) + 1, len(temp_series) - 1)
        frac = idx - lo
        temp_resampled.append(temp_series[lo] * (1 - frac) + temp_series[hi] * frac)

    tz_ams = datetime.timezone(datetime.timedelta(hours=2))
    now_ams = datetime.datetime.now(tz=tz_ams)
    indoor = weather_store.latest_sensor_reading() or _indoor
    footer_sources = weather_store.source_status_line()

    img = Image.new("L", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(img)

    MID_DIV_X = 270
    RIGHT_DIV_X = 540
    TOP_BOTTOM_Y = 214
    CHART_TOP_Y = 236
    C1_X = 16
    C2_X = MID_DIV_X + 12
    C3_X = RIGHT_DIV_X + 12

    _text(draw, (C1_X, 10), "Amsterdam", 18, bold=True)
    _text(draw, (C2_X, 10), "Device", 18, bold=True)
    _text(draw, (C3_X, 10), "Amsterdam 7-Day", 16, bold=True)
    _text(draw, (WIDTH - 16, 10),
          now_ams.strftime("%b %-d  %-I:%M %p"), 13, anchor="ra")

    draw.line([16, 38, WIDTH - 16, 38], fill=180, width=1)

    draw.line([MID_DIV_X, 42, MID_DIV_X, TOP_BOTTOM_Y], fill=180, width=1)
    draw.line([RIGHT_DIV_X, 42, RIGHT_DIV_X, HEIGHT - 30], fill=180, width=1)
    draw.line([16, TOP_BOTTOM_Y, RIGHT_DIV_X - 16, TOP_BOTTOM_Y], fill=180, width=1)

    ams_temp = ams["main"]["temp"]
    ams_feel = ams["main"]["feels_like"]
    ams_hum = ams["main"]["humidity"]
    ams_desc = ams["weather"][0]["description"].capitalize()
    ams_wind = ams["wind"]["speed"]
    ams_wdir = _wind_direction(ams["wind"]["deg"])
    ams_gust = ams["wind"].get("gust", 0)
    ams_kind = _weather_kind_from_owm(ams["weather"][0])
    today_rain_prob = daily[0].get("rain_prob") if daily else None
    today_min = daily[0].get("temp_min") if daily else None
    today_max = daily[0].get("temp_max") if daily else None

    ams_temp_text = f"{ams_temp:.0f}°C"
    _text(draw, (C1_X, 44), ams_temp_text, 46, bold=True)
    ams_temp_bbox = draw.textbbox((C1_X, 44), ams_temp_text,
                                  font=_font(46, True), anchor="la")
    ams_icon_x = ams_temp_bbox[2] + 8
    _draw_weather_icon(draw, ams_icon_x, 52, ams_kind, 34)
    _text(draw, (ams_icon_x + 36, 62), now_ams.strftime("%A %B %-d"), 10)
    if today_min is not None and today_max is not None:
        _text(draw, (C1_X, 196),
              f"Min {today_min:.0f}°C  Max {today_max:.0f}°C", 12)
    else:
        _text(draw, (C1_X, 196), "Min --  Max --", 12)
    _text(draw, (C1_X, 130), f"Feels  {ams_feel:.0f}°C", 13)
    if today_rain_prob is not None:
        _text(draw, (C1_X, 114), f"Rain probability  {today_rain_prob}%", 13)
    else:
        _text(draw, (C1_X, 114), "Rain probability  --", 13)
    _text(draw, (C1_X, 96), ams_desc, 13)

    _text(draw, (C1_X, 146), f"Humidity  {ams_hum}%", 13)
    _text(draw, (C1_X, 162), f"Wind  {ams_wind:.0f} m/s {ams_wdir}", 13)
    _text(draw, (C1_X, 178), f"Gusts  {ams_gust:.0f} m/s", 13)

    if indoor["temp"] is not None:
        _text(draw, (C2_X, 44), f"{indoor['temp']:.1f}°C", 46, bold=True)
        _text(draw, (C2_X, 96), f"Humidity  {indoor['humidity']:.0f}%", 13)
        bv = indoor.get("battery_voltage") or battery_voltage
        if bv is not None:
            batt_pct = max(0, min(100, int((bv - 3.3) / (4.2 - 3.3) * 100)))
            _text(draw, (C2_X, 114), f"Battery  {batt_pct}%  ({bv:.2f} V)", 13)
        if indoor["ts"] is not None:
            ts_dt = datetime.datetime.fromtimestamp(indoor["ts"],
                                                    tz=datetime.timezone.utc)
            ts_loc = ts_dt.astimezone(tz_ams)
            _text(draw, (C2_X, 134), ts_loc.strftime("Updated  %-I:%M %p"), 12)
    else:
        _text(draw, (C2_X, 70), "No sensor data", 15)
        _text(draw, (C2_X, 94), "POST /sensor to enable", 11)
        if battery_voltage is not None:
            batt_pct = max(0, min(100, int((battery_voltage - 3.3) / (4.2 - 3.3) * 100)))
            _text(draw, (C2_X, 114), f"Battery  {batt_pct}%  ({battery_voltage:.2f} V)", 13)

    _draw_daily_forecast(draw, (C3_X, 44, WIDTH - 16, HEIGHT - 42), daily)

    _text(draw, (16, CHART_TOP_Y - 12), "Rain (mm/h)  +  Temperature (°C)", 11)
    _draw_bar_chart(draw, (16, CHART_TOP_Y, RIGHT_DIV_X - 16, HEIGHT - 30),
                    rain_mmh, temp_resampled, rain_times)

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
                result = weather_store.refresh_all_sources(
                    AMS_LAT,
                    AMS_LON,
                    OWM_KEY,
                    force=True,
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

