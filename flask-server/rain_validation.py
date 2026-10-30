#!/usr/bin/env python3
"""Bounded, independent rain-chart audit. Never writes the production database.

The reference calculations below do not use models.py or app.py. Production
code is imported only to reconstruct what the dashboard drew from its captured
cache, and that reconstruction must match the downloaded image before an issue
is attributed to that image. Fresh-provider differences are reported separately.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib
import io
import json
import math
import sqlite3
import sys
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageChops, ImageDraw

UTC = dt.timezone.utc
LOCAL = ZoneInfo("Europe/Amsterdam")
USER_AGENT = "weather-server-rain-audit/1.0 (+https://github.com/pabloazurduy/weather-server)"
TABLES = ("buienradar_rain", "openmeteo_hourly", "openmeteo_current", "openmeteo_daily", "device_sensor")
SOURCES = {
    "Buienradar": "https://www.buienradar.nl/overbuienradar/gratis-weerdata",
    "Open-Meteo": "https://open-meteo.com/en/docs",
    "MET Norway": "https://developer.yr.no/doc/ForecastJSON/",
}


def iso(timestamp=None, zone=UTC):
    return dt.datetime.fromtimestamp(time.time() if timestamp is None else timestamp, zone).isoformat()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def read_cache(database, city):
    """Read all latest records in one read-only SQLite transaction."""
    output = {}
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=10)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        for table in TABLES:
            output[table] = {}
            for label, successful in (("success", True), ("attempt", False)):
                clauses, values = [], []
                if table != "device_sensor":
                    clauses.append("city=?")
                    values.append(" ".join(city.split()).casefold())
                if successful:
                    clauses.append("success=1")
                where = " WHERE " + " AND ".join(clauses) if clauses else ""
                row = connection.execute(
                    f'SELECT id,fetched_at,success,payload_json,error_text FROM "{table}"'
                    + where + " ORDER BY fetched_at DESC,id DESC LIMIT 1", values,
                ).fetchone()
                if row:
                    record = dict(row)
                    record["payload"] = json.loads(record.pop("payload_json") or "null")
                    output[table][label] = record
    return output


def intensity(encoded):
    """Buienradar specification: encoded zero is dry; other values are mm/hour."""
    encoded = int(encoded)
    if not 0 <= encoded <= 255:
        raise ValueError(f"Invalid Buienradar intensity: {encoded}")
    return 0.0 if encoded == 0 else 10.0 ** ((encoded - 109.0) / 32.0)


def buienradar_intervals(points, fetched_at):
    """Anchor time-only forecasts to their FETCH date, not a later viewing date."""
    anchor = dt.datetime.fromtimestamp(fetched_at, LOCAL)
    intervals = []
    for point in points:
        hour, minute = map(int, point["time"].split(":"))
        if not intervals:
            dates = [anchor.date() + dt.timedelta(days=d) for d in (-1, 0, 1)]
            choices = [dt.datetime.combine(day, dt.time(hour, minute), LOCAL) for day in dates]
            current = min(choices, key=lambda value: abs(value.timestamp() - fetched_at))
            start = int(current.timestamp())
        else:
            start = intervals[-1]["end_ts"]
            clock = dt.datetime.fromtimestamp(start, LOCAL)
            if (clock.hour, clock.minute) != (hour, minute):
                raise ValueError("Buienradar time steps are not contiguous five-minute intervals")
        intervals.append({"start_ts": start, "end_ts": start + 300,
                          "mmh": intensity(point["value"]), "source": "Buienradar"})
    return intervals


def openmeteo_intervals(points):
    """Hourly precipitation is an amount over the PRECEDING hour, in mm."""
    return [{"start_ts": int(point["ts"]) - 3600, "end_ts": int(point["ts"]),
             "mmh": float(point["rain_mmh"]), "source": "Open-Meteo"} for point in points
            if point.get("rain_mmh") is not None]


def fresh_openmeteo(payload):
    if payload["hourly_units"]["precipitation"] != "mm":
        raise ValueError("Open-Meteo precipitation is not in millimetres")
    return openmeteo_intervals([
        {"ts": timestamp, "rain_mmh": amount}
        for timestamp, amount in zip(payload["hourly"]["time"], payload["hourly"]["precipitation"], strict=True)
        if amount is not None
    ])


def metno_intervals(payload):
    if payload["properties"]["meta"]["units"]["precipitation_amount"] != "mm":
        raise ValueError("MET Norway precipitation is not in millimetres")
    intervals = []
    for point in payload["properties"]["timeseries"]:
        following = point["data"].get("next_1_hours", {}).get("details", {})
        if "precipitation_amount" in following:
            start = int(dt.datetime.fromisoformat(point["time"].replace("Z", "+00:00")).timestamp())
            intervals.append({"start_ts": start, "end_ts": start + 3600,
                              "mmh": float(following["precipitation_amount"]), "source": "MET Norway"})
    return intervals


def average_rate(intervals, start, end):
    """Time-weighted mm/hour; refuse to invent zero rain for missing coverage."""
    if end <= start:
        raise ValueError("Empty reference interval")
    amount, covered = 0.0, 0
    for point in intervals:
        seconds = max(0, min(end, point["end_ts"]) - max(start, point["start_ts"]))
        amount += seconds * point["mmh"]
        covered += seconds
    return amount / (end - start) if covered == end - start else None


def fetch(url, name, sample, previous=None):
    started = time.time()
    headers = {"User-Agent": USER_AGENT}
    if previous and previous.get("last_modified"):
        headers["If-Modified-Since"] = previous["last_modified"]
    result = {"url": url, "started_at": iso(started)}
    try:
        response = requests.get(url, headers=headers, timeout=(8, 45))
        body = response.content
        result.update(status=response.status_code, final_url=response.url,
                      headers={k: v for k, v in response.headers.items()
                               if k.lower() in {"date", "age", "expires", "last-modified", "content-type", "etag"}})
        if response.status_code == 304 and previous:
            body = previous["body"]
            result["revalidated_cached_body"] = True
        elif response.status_code != 200:
            raise ValueError(f"HTTP {response.status_code}: {body[:160]!r}")
        suffix = ".png" if name == "dashboard" else ".txt" if name == "buienradar" else ".json"
        (sample / (name + suffix)).write_bytes(body)
        result.update(ok=True, bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
        result["body"] = body
        result["last_modified"] = response.headers.get("Last-Modified") or (previous or {}).get("last_modified")
        if name == "metno":
            expires = response.headers.get("Expires")
            try:
                expires_ts = parsedate_to_datetime(expires).timestamp() if expires else 0
            except (TypeError, ValueError):
                expires_ts = 0
            result["next_request_ts"] = max(time.time() + 3600, expires_ts)
    except Exception as exc:
        result.update(ok=False, error=str(exc))
    result.update(finished_at=iso(), finished_ts=time.time(), seconds=round(time.time() - started, 3))
    return result


def replay(cache, now, code_dir):
    """Production-only reconstruction. Independent reference code never calls this."""
    sys.path.insert(0, str(code_dir))
    app = importlib.import_module("app")
    models = importlib.import_module("models")

    class FrozenStore(models.WeatherStore):
        def __init__(self):
            super().__init__("/unused-audit-database", default_city=app.CITY)

        def latest_snapshot(self, endpoint_key, success_only=True, city=None):
            return cache.get(endpoint_key, {}).get("success" if success_only else "attempt")

        def fetch_with_history(self, endpoint_key, fetcher, force=False, city=None):
            snapshot = self.latest_snapshot(endpoint_key)
            if not snapshot or snapshot["payload"] is None:
                raise ValueError(f"No captured production cache for {endpoint_key}")
            return snapshot["payload"]

        def latest_sensor_reading(self):
            record = self.latest_snapshot("device_sensor")
            return {**record["payload"], "ts": record["fetched_at"]} if record else None

        def source_status_line(self, city=None):
            return ""  # Footer is outside the audited chart crop.

        def _current_timestamp(self):
            return int(now)

        def _buienradar_points_with_timestamps(self, points, now=None):
            return models.WeatherStore._buienradar_points_with_timestamps(
                points, now=now or dt.datetime.fromtimestamp(self._current_timestamp(), LOCAL))

    store = FrozenStore()
    forecast = store.get_rain_forecast(app.CITY_LAT, app.CITY_LON, hours=12, detailed_hours=3)
    original = app.weather_store
    try:
        app.weather_store = store
        image = app.generate_png()
    finally:
        app.weather_store = original
    sources = {int(p["group_start_ts"]): p["source"] for p in forecast["points"]}
    segments = [{**s, "source": sources[s["start_ts"]]} for s in app._rain_segments(forecast)]
    maximum = max((s["mmh"] for s in segments if s["mmh"] is not None), default=0.0)
    # Support the original audited image as well as the corrected server.
    scale = app._rain_scale_max(segments) if hasattr(app, "_rain_scale_max") else max(maximum, 1.0)
    printed = scale if hasattr(app, "_rain_scale_max") else maximum
    return image, {"forecast": forecast, "segments": segments,
                   "rain_axis": {"scale_max_mmh": scale, "printed_top_mmh": round(printed, 1)}}


def image_difference(actual, reconstructed):
    with Image.open(io.BytesIO(actual)) as first, Image.open(io.BytesIO(reconstructed)) as second:
        if first.size != (800, 480) or second.size != first.size:
            raise ValueError("Audit chart geometry requires the 800x480 production dashboard")
        box = (16, 236, 525, 451)
        first, second = first.convert("L").crop(box), second.convert("L").crop(box)
        difference = ImageChops.difference(first, second).point(lambda p: 255 if p else 0)
        foreground = ImageChops.darker(first, second).point(lambda p: 255 if p < 128 else 0)
        count = difference.histogram()[255]
        ink = foreground.histogram()[255]
        return {"different_pixels": count, "foreground_pixels": ink,
                "foreground_difference_fraction": count / max(ink, 1),
                "matched": count / max(ink, 1) <= 0.01}


def validate_segments(segments, cache, now, rain_axis=None):
    """Compare drawn groups with independently calculated source intervals."""
    buien_record = cache["buienradar_rain"].get("success")
    hourly_record = cache["openmeteo_hourly"].get("success")
    radar = buienradar_intervals(buien_record["payload"], buien_record["fetched_at"]) if buien_record else []
    hourly = openmeteo_intervals(hourly_record["payload"]) if hourly_record else []
    rows, issues = [], []
    for segment in segments:
        start, end = segment["start_ts"], segment["end_ts"]
        reference = radar if segment["source"] == "Buienradar" else hourly if segment["source"] == "Open-Meteo" else []
        expected = average_rate(reference, start, end)
        row = {**segment, "start_local": iso(start, LOCAL), "end_local": iso(end, LOCAL),
               "expected_mmh_from_cached_source": expected,
               "absolute_error_mmh": None if expected is None or segment["mmh"] is None else abs(segment["mmh"] - expected)}
        rows.append(row)
    wrong = [row for row in rows if row["absolute_error_mmh"] is not None and row["absolute_error_mmh"] > 0.0051]
    if wrong:
        issues.append({"code": "rain_values_or_intervals", "count": len(wrong),
                       "message": "Drawn rain rates differ from the source rates for the same time intervals.",
                       "examples": wrong[:5]})
    unavailable = [row for row in rows if row["expected_mmh_from_cached_source"] is None and row["mmh"] is not None]
    if unavailable:
        issues.append({"code": "cached_source_does_not_cover_plot", "count": len(unavailable),
                       "message": "Some plotted intervals are outside the captured provider forecast coverage.",
                       "examples": unavailable[:3]})
    priority_errors = [row for row in rows if row["source"] != "Buienradar" and any(
        point["start_ts"] < row["end_ts"] and point["end_ts"] > row["start_ts"] for point in radar)]
    if priority_errors:
        issues.append({"code": "buienradar_priority", "count": len(priority_errors),
                       "message": "A non-radar bar overlaps available Buienradar forecast coverage.",
                       "examples": priority_errors[:3]})
    maximum = max((row["mmh"] for row in rows if row["mmh"] is not None), default=0.0)
    axis = rain_axis or {"printed_top_mmh": round(maximum, 1), "scale_max_mmh": max(maximum, 1.0)}
    if maximum > 0 and round(axis["printed_top_mmh"], 1) != round(axis["scale_max_mmh"], 1):
        issues.append({"code": "rain_axis_label_scale", "count": 1,
                       "message": "Top rain label uses the data maximum, but bar heights use a 1 mm/h minimum axis range.",
                       "printed_top_mmh": axis["printed_top_mmh"], "actual_axis_top_mmh": axis["scale_max_mmh"]})
    # Track stale input separately: fresh-model differences alone do not prove a plot bug.
    ages = {name: round(now - data["success"]["fetched_at"], 1)
            for name, data in cache.items() if data.get("success")}
    return rows, issues, ages


def reference_image(rows, path):
    """Standalone comparison using independent, time-weighted source expectations."""
    image = Image.new("RGB", (1000, 310), "white")
    draw = ImageDraw.Draw(image)
    draw.text((25, 12), "Rain audit: red = dashboard groups; blue = correct source intervals (same cached forecast)", fill="black")
    start, end = rows[0]["start_ts"], rows[-1]["end_ts"]
    maximum = max([1.0] + [r["mmh"] for r in rows if r["mmh"] is not None] +
                  [r["expected_mmh_from_cached_source"] for r in rows if r["expected_mmh_from_cached_source"] is not None])
    x = lambda t: 55 + int((t - start) / (end - start) * 915)
    y = lambda value: 265 - int(value / maximum * 210)
    draw.line((55, 50, 55, 265, 970, 265), fill="black")
    draw.text((5, 42), f"{maximum:.2f}", fill="black")
    draw.text((5, 258), "0 mm/h", fill="black")
    for row in rows:
        left, right = x(row["start_ts"]), max(x(row["end_ts"]), x(row["start_ts"]) + 1)
        if row["mmh"] is not None:
            draw.line((left, y(row["mmh"]), right, y(row["mmh"])), fill="red", width=2)
        expected = row["expected_mmh_from_cached_source"]
        if expected is not None:
            draw.line((left, y(expected) + 2, right, y(expected) + 2), fill="blue", width=2)
    for offset in range(13):
        timestamp = start + offset * 3600
        draw.text((min(x(timestamp), 945), 279), dt.datetime.fromtimestamp(timestamp, LOCAL).strftime("%H:%M"), fill="black")
    image.save(path)


def provider_comparisons(results, rows):
    intervals, errors = {}, {}
    for name, result in results.items():
        if name == "dashboard" or not result.get("ok"):
            continue
        try:
            if name == "buienradar":
                points = [{"value": int(line.split("|")[0]), "time": line.split("|")[1].strip()}
                          for line in result["body"].decode().splitlines() if "|" in line]
                intervals[name] = buienradar_intervals(points, result["finished_ts"])
            elif name == "openmeteo":
                intervals[name] = fresh_openmeteo(json.loads(result["body"]))
            else:
                intervals[name] = metno_intervals(json.loads(result["body"]))
        except Exception as exc:
            errors[name] = str(exc)
    start = rows[0]["start_ts"] if rows else int(time.time() // 300 * 300)
    # The displayed cache may begin several minutes before a freshly issued
    # radar forecast. Use a shared covered start for cross-provider totals.
    start = max([start] + [reference[0]["start_ts"] for reference in intervals.values() if reference])
    totals = {}
    for name, reference in intervals.items():
        totals[name] = {}
        for hours in (1, 2, 12):
            rate = average_rate(reference, start, start + hours * 3600)
            totals[name][f"next_{hours}h_mm"] = None if rate is None else round(rate * hours, 4)
    differences, dashboard_differences = [], []
    for row in rows:
        source = "buienradar" if row["source"] == "Buienradar" else "openmeteo"
        fresh = average_rate(intervals.get(source, []), row["start_ts"], row["end_ts"])
        cached = row["expected_mmh_from_cached_source"]
        row["fresh_provider_mmh"] = fresh
        row["metno_mmh"] = average_rate(intervals.get("metno", []), row["start_ts"], row["end_ts"])
        row["fresh_vs_dashboard_absolute_error_mmh"] = None if fresh is None or row["mmh"] is None else abs(fresh - row["mmh"])
        if fresh is not None and row["mmh"] is not None:
            dashboard_differences.append(abs(fresh - row["mmh"]))
        if fresh is not None and cached is not None:
            differences.append(abs(fresh - cached))
    return {"fresh_provider_totals": totals, "comparison_window_start": iso(start), "parse_errors": errors,
            "fresh_vs_cached_mean_absolute_mmh": sum(differences) / len(differences) if differences else None,
            "fresh_vs_dashboard_mean_absolute_mmh": sum(dashboard_differences) / len(dashboard_differences) if dashboard_differences else None,
            "interpretation": "Provider differences and updated forecasts are not automatically plotting errors."}


def capture(args, sample, met_cache):
    sample.mkdir(parents=True, exist_ok=True)
    now = time.time()
    before = read_cache(args.database, args.city)
    write_json(sample / "cached_sources_before.json", before)
    coordinates = {"latitude": args.latitude, "longitude": args.longitude}
    urls = {
        "dashboard": args.base_url.rstrip("/") + "/dashboard.png",
        "buienradar": "https://gps.buienradar.nl/getrr.php?" + urlencode({"lat": args.latitude, "lon": args.longitude}),
        "openmeteo": "https://api.open-meteo.com/v1/forecast?" + urlencode({
            **coordinates, "hourly": "temperature_2m,precipitation", "forecast_days": 2,
            "timezone": "UTC", "timeformat": "unixtime", "precipitation_unit": "mm"}),
        "metno": "https://api.met.no/weatherapi/locationforecast/2.0/compact?" + urlencode({
            "lat": f"{args.latitude:.4f}", "lon": f"{args.longitude:.4f}"}),
    }
    results = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {name: pool.submit(fetch, url, name, sample, met_cache if name == "metno" else None)
                   for name, url in urls.items() if name != "metno" or not met_cache
                   or now >= met_cache.get("next_request_ts", met_cache["finished_ts"] + 3600)}
        for name, future in futures.items():
            results[name] = future.result()
    if "metno" not in results:
        results["metno"] = {**met_cache, "reused_within_hour": True}
        (sample / "metno.json").write_bytes(met_cache["body"])
    if results["metno"].get("ok"):
        met_cache = results["metno"]
    after = read_cache(args.database, args.city)
    write_json(sample / "cached_sources_after.json", after)
    write_json(sample / "requests.json", {name: {k: v for k, v in result.items() if k != "body"}
                                            for name, result in results.items()})
    analysis = {"captured_at": iso(now), "captured_local": iso(now, LOCAL), "issues": [],
                "request_errors": {name: value.get("error") for name, value in results.items() if not value.get("ok")}}
    candidates = []
    if results["dashboard"].get("ok"):
        for label, cache in (("after", after), ("before", before)):
            try:
                png, data = replay(cache, now, args.code_dir)
                metrics = image_difference(results["dashboard"]["body"], png)
                candidates.append((metrics["foreground_difference_fraction"], label, cache, png, data, metrics))
            except Exception as exc:
                analysis.setdefault("reconstruction_errors", {})[label] = str(exc)
    rows = []
    if candidates:
        _, label, cache, png, data, metrics = min(candidates, key=lambda candidate: candidate[0])
        (sample / "reconstructed.png").write_bytes(png)
        write_json(sample / "production_chart.json", data)
        rows, issues, ages = validate_segments(data["segments"], cache, now, data.get("rain_axis"))
        analysis.update(image_check=metrics, cache_variant=label, cached_source_age_seconds=ages,
                        issues=[{**issue, "confidence": "confirmed_in_image" if metrics["matched"] else "candidate_reconstruction_only"}
                                for issue in issues])
    analysis["provider_comparison"] = provider_comparisons(results, rows)
    if rows:
        with (sample / "segments.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        reference_image(rows, sample / "reference.png")
    analysis["finished_at"] = iso()
    write_json(sample / "analysis.json", analysis)
    return analysis, met_cache


def report(output, manifest, state, error=None):
    samples = []
    for path in sorted((output / "samples").glob("*/analysis.json")):
        value = json.loads(path.read_text())
        value["sample_directory"] = path.parent.name
        samples.append(value)
    confirmed = Counter(issue["code"] for sample in samples for issue in sample.get("issues", [])
                        if issue["confidence"] == "confirmed_in_image")
    parse_errors = sum(bool(s.get("provider_comparison", {}).get("parse_errors")) for s in samples)
    images = sum((output / "samples" / s["sample_directory"] / "dashboard.png").exists() for s in samples)
    matches = sum(bool(s.get("image_check", {}).get("matched")) for s in samples)
    incomplete = (images < manifest["planned_samples"] or matches < images
                  or any(s.get("request_errors") for s in samples) or parse_errors)
    if state == "completed" and incomplete:
        state = "completed_with_errors"
    status = {**manifest, "state": state, "updated_at": iso(), "samples_collected": images,
              "sample_attempts": len(samples), "samples_with_parse_errors": parse_errors,
              "dashboard_images_saved": sum((output / "samples" / s["sample_directory"] / "dashboard.png").exists() for s in samples),
              "image_matches": matches,
              "samples_with_request_errors": sum(bool(s.get("request_errors")) for s in samples),
              "confirmed_findings_by_sample": dict(confirmed), "last_sample": samples[-1] if samples else None,
              "error": error}
    write_json(output / "status.json", status)
    lines = ["# 24-hour rain validation", "", f"State: **{state}**", "",
             f"Window: {manifest['started_local']} to {manifest['scheduled_end_local']}.", "",
             f"Collected {images} dashboard images of {manifest['planned_samples']} planned samples "
             f"({len(samples)} recorded attempts). "
             f"Image-matched reconstructions: {status['image_matches']}. "
             f"Samples with request failures: {status['samples_with_request_errors']}. "
             f"Samples with provider parse errors: {parse_errors}.", "",
             "## Findings linked to captured dashboard images", ""]
    if not confirmed:
        lines += ["No image-confirmed plotting findings so far. Missing or unmatched data is inconclusive.", ""]
    for code, count in confirmed.items():
        example = next(s for s in samples if any(i["code"] == code and i["confidence"] == "confirmed_in_image" for i in s["issues"]))
        issue = next(i for i in example["issues"] if i["code"] == code)
        folder = "samples/" + example["sample_directory"]
        lines += [f"- **{code}** — {count} samples: {issue['message']} "
                  f"[Dashboard]({folder}/dashboard.png), [independent comparison]({folder}/reference.png), "
                  f"[numbers]({folder}/segments.csv), [details]({folder}/analysis.json)."]
    lines += ["", "## Evidence and limitations", "",
              "Each sample retains the real dashboard PNG, raw provider responses and request timings, "
              "production cache records before/after the request, a reconstructed production PNG, "
              "the underlying production chart data, and independent interval comparisons.", "",
              "Reference calculations use the documented Buienradar conversion and Open-Meteo preceding-hour "
              "precipitation periods. MET Norway is a third provider; it is sampled/revalidated at most hourly. "
              "Forecast changes and disagreement between providers are reported separately from chart errors.", "",
              "This audits plotting correctness and data freshness; it does not establish ground-truth "
              "forecast accuracy without independent observed rainfall. Production data is mounted read-only "
              "and no source-refresh endpoints are called. Image reconstruction mismatches are inconclusive, "
              "not treated as confirmed rendering bugs.", "", "## Provider documentation", ""]
    lines += [f"- [{name}]({url})" for name, url in SOURCES.items()]
    if error:
        lines += ["", "## Collector error", "", "```text", error, "```"]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:5050")
    parser.add_argument("--city", required=True)
    parser.add_argument("--latitude", required=True, type=float)
    parser.add_argument("--longitude", required=True, type=float)
    parser.add_argument("--code-dir", type=Path, default=Path(__file__).parent)
    parser.add_argument("--duration-hours", type=float, default=24)
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.interval_seconds < 60 or args.duration_hours <= 0:
        parser.error("Use an interval of at least 60 seconds and a positive duration")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Prevent two collectors from writing into the same evidence directory.
    import fcntl
    lock = (output / ".collector.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest["latitude"] != args.latitude or manifest["longitude"] != args.longitude:
            raise ValueError("Existing evidence directory belongs to different coordinates")
    else:
        start = time.time()
        duration = 0 if args.once else args.duration_hours * 3600
        manifest = {"started_ts": start, "end_ts": start + duration,
                    "started_at": iso(start), "started_local": iso(start, LOCAL),
                    "scheduled_end_at": iso(start + duration), "scheduled_end_local": iso(start + duration, LOCAL),
                    "interval_seconds": args.interval_seconds, "planned_samples": math.ceil(duration / args.interval_seconds) + 1,
                    "latitude": args.latitude, "longitude": args.longitude, "city": args.city,
                    "dashboard_url": args.base_url.rstrip("/") + "/dashboard.png", "source_documentation": SOURCES,
                    "production_code_sha256": {name: hashlib.sha256((args.code_dir / name).read_bytes()).hexdigest()
                                               for name in ("app.py", "models.py")}}
        write_json(manifest_path, manifest)
    met_cache = None
    report(output, manifest, "running")
    try:
        for index in range(manifest["planned_samples"]):
            due = min(manifest["started_ts"] + index * manifest["interval_seconds"], manifest["end_ts"])
            sample = output / "samples" / f"{index:04d}_{dt.datetime.fromtimestamp(due, UTC):%Y%m%dT%H%M%SZ}"
            if (sample / "analysis.json").exists():
                continue
            delay = due - time.time()
            if delay > 0:
                time.sleep(delay)
            if time.time() > due + manifest["interval_seconds"]:
                sample.mkdir(parents=True, exist_ok=True)
                write_json(sample / "analysis.json", {"captured_at": None, "issues": [],
                           "request_errors": {"collector": "Missed scheduled sample; no retrospective image invented"}})
            else:
                try:
                    analysis, met_cache = capture(args, sample, met_cache)
                    print(json.dumps({"sample": index, "at": analysis["captured_at"],
                                      "image_check": analysis.get("image_check"), "request_errors": analysis["request_errors"],
                                      "issues": [i["code"] for i in analysis["issues"]]}), flush=True)
                except Exception:
                    sample.mkdir(parents=True, exist_ok=True)
                    write_json(sample / "analysis.json", {"captured_at": iso(), "issues": [],
                               "request_errors": {"collector": traceback.format_exc()}})
                    print(traceback.format_exc(), flush=True)
            report(output, manifest, "running")
        status = report(output, manifest, "completed")
        print(json.dumps({"state": status["state"], "samples": status["samples_collected"],
                          "findings": status["confirmed_findings_by_sample"]}), flush=True)
    except BaseException:
        report(output, manifest, "interrupted", traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
