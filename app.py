#!/usr/bin/env python3
import json
import math
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen
from urllib.error import URLError


def _buienradar_value_to_mmh(value: int) -> float:
    if value == 0:
        return 0.0
    return round(10 ** ((value - 109) / 32), 2)


def _fetch_buienradar(lat: str, lon: str) -> list:
    url = f"https://gadgets.buienradar.nl/data/raintext/?lat={lat}&lon={lon}"
    with urlopen(url, timeout=5) as resp:
        lines = resp.read().decode("utf-8").strip().splitlines()
    result = []
    max_value = max((int(l.split("|")[0]) for l in lines if "|" in l), default=1)
    for line in lines:
        if "|" not in line:
            continue
        raw, time = line.split("|", 1)
        value = int(raw)
        mmh = _buienradar_value_to_mmh(value)
        result.append({
            "time": time.strip(),
            "value": value,
            "mm_per_hour": mmh,
            "percent": round(value / max(max_value, 1) * 100),
        })
    return result


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/buienradar":
            qs = parse_qs(parsed.query)
            lat = qs.get("lat", ["52.37"])[0]
            lon = qs.get("lon", ["4.90"])[0]
            try:
                forecast = _fetch_buienradar(lat, lon)
                has_rain = any(p["value"] > 0 for p in forecast)
                now = forecast[0] if forecast else {}
                body = json.dumps({
                    "forecast": forecast,
                    "has_rain": has_rain,
                    "current_mm_per_hour": now.get("mm_per_hour", 0),
                    "current_time": now.get("time", ""),
                    "lat": lat,
                    "lon": lon,
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (URLError, ValueError) as e:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8080), Handler)
    print("Weather proxy running on http://0.0.0.0:8080")
    server.serve_forever()
