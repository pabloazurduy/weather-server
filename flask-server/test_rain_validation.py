import datetime as dt
import hashlib
import json
import sqlite3
import tempfile
import unittest
import io
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from PIL import Image

import rain_validation as audit


class IndependentRainReferenceTests(unittest.TestCase):
    def test_buienradar_conversion_matches_documented_examples(self):
        self.assertEqual(audit.intensity(0), 0)
        self.assertAlmostEqual(audit.intensity(77), 0.1)
        self.assertAlmostEqual(audit.intensity(109), 1)
        self.assertAlmostEqual(audit.intensity(141), 10)
        with self.assertRaises(ValueError):
            audit.intensity(256)

    def test_time_only_radar_crosses_midnight_using_capture_date(self):
        fetched = dt.datetime(2026, 10, 28, 23, 54, tzinfo=audit.LOCAL).timestamp()
        reference = audit.buienradar_intervals([
            {"time": "23:55", "value": 77}, {"time": "00:00", "value": 109},
        ], fetched)
        first = dt.datetime.fromtimestamp(reference[0]["start_ts"], audit.LOCAL)
        second = dt.datetime.fromtimestamp(reference[1]["start_ts"], audit.LOCAL)
        self.assertEqual(first.date(), dt.date(2026, 10, 28))
        self.assertEqual(second.date(), dt.date(2026, 10, 29))
        self.assertEqual(reference[0]["end_ts"], reference[1]["start_ts"])

    def test_hourly_precipitation_belongs_to_preceding_hour(self):
        intervals = audit.openmeteo_intervals([{"ts": 10 * 3600, "rain_mmh": 2}])
        self.assertEqual(intervals[0]["start_ts"], 9 * 3600)
        self.assertEqual(audit.average_rate(intervals, 9 * 3600, 10 * 3600), 2)
        self.assertIsNone(audit.average_rate(intervals, 10 * 3600, 11 * 3600))

    def test_unaligned_groups_use_overlap_weighted_amounts(self):
        intervals = audit.openmeteo_intervals([
            {"ts": 11 * 3600, "rain_mmh": 3},
            {"ts": 12 * 3600, "rain_mmh": 0},
        ])
        self.assertEqual(audit.average_rate(intervals, 10 * 3600 + 1800, 11 * 3600 + 1800), 1.5)

    def test_missing_coverage_is_not_reported_as_dry(self):
        intervals = [{"start_ts": 0, "end_ts": 300, "mmh": 0}]
        self.assertEqual(audit.average_rate(intervals, 0, 300), 0)
        self.assertIsNone(audit.average_rate(intervals, 0, 600))

    def test_audit_detects_forward_shifted_rain(self):
        cache = {
            "buienradar_rain": {},
            "openmeteo_hourly": {"success": {"fetched_at": 0, "payload": [
                {"ts": 10 * 3600, "rain_mmh": 1},
                {"ts": 11 * 3600, "rain_mmh": 3},
                {"ts": 12 * 3600, "rain_mmh": 0},
            ]}},
        }
        rows, issues, _ = audit.validate_segments([
            {"start_ts": 10 * 3600 + 1800, "end_ts": 11 * 3600 + 1800,
             "source": "Open-Meteo", "mmh": 1},
        ], cache, 0)
        self.assertEqual(rows[0]["expected_mmh_from_cached_source"], 1.5)
        self.assertIn("rain_values_or_intervals", [issue["code"] for issue in issues])

    def test_audit_flags_axis_scale_but_accepts_matching_values(self):
        cache = {"buienradar_rain": {}, "openmeteo_hourly": {"success": {
            "fetched_at": 0, "payload": [{"ts": 3600, "rain_mmh": 0.5}],
        }}}
        _, issues, _ = audit.validate_segments([
            {"start_ts": 0, "end_ts": 3600, "source": "Open-Meteo", "mmh": 0.5},
        ], cache, 0)
        self.assertEqual([issue["code"] for issue in issues], ["rain_axis_label_scale"])
        self.assertEqual(issues[0]["actual_axis_top_mmh"], 1)

    def test_radar_rounding_is_not_mistaken_for_a_bug(self):
        fetched = dt.datetime(2026, 10, 28, 10, 0, tzinfo=audit.LOCAL).timestamp()
        cache = {"buienradar_rain": {"success": {
            "fetched_at": fetched, "payload": [{"time": "10:00", "value": 95, "mmh": 0.37}],
        }}, "openmeteo_hourly": {}}
        _, issues, _ = audit.validate_segments([
            {"start_ts": fetched, "end_ts": fetched + 300, "source": "Buienradar", "mmh": 0.37},
        ], cache, fetched)
        self.assertNotIn("rain_values_or_intervals", [issue["code"] for issue in issues])

    def test_metno_amount_uses_following_hour(self):
        payload = {"properties": {"meta": {"units": {"precipitation_amount": "mm"}}, "timeseries": [{
            "time": "2026-10-28T10:00:00Z", "data": {"next_1_hours": {"details": {"precipitation_amount": 2}}},
        }]}}
        reference = audit.metno_intervals(payload)
        start = dt.datetime(2026, 10, 28, 10, 0, tzinfo=dt.timezone.utc).timestamp()
        self.assertEqual(audit.average_rate(reference, start, start + 3600), 2)
        self.assertIsNone(audit.average_rate(reference, start - 3600, start))

    def test_fresh_provider_totals_use_common_available_window(self):
        start = int(dt.datetime(2026, 10, 28, 10, 0, tzinfo=audit.LOCAL).timestamp())
        text = "\n".join(f"109|{hour:02d}:{minute:02d}" for hour in (10,) for minute in range(0, 60, 5))
        raw_hourly = {"hourly_units": {"precipitation": "mm"},
                      "hourly": {"time": [start + 3600], "precipitation": [2]}}
        results = {"buienradar": {"ok": True, "body": text.encode(), "finished_ts": start},
                   "openmeteo": {"ok": True, "body": json.dumps(raw_hourly).encode()}}
        rows = [{"start_ts": start - 300, "end_ts": start, "source": "Buienradar",
                 "mmh": 0, "expected_mmh_from_cached_source": 0}]
        result = audit.provider_comparisons(results, rows)
        self.assertEqual(result["fresh_provider_totals"]["buienradar"]["next_1h_mm"], 1)
        self.assertEqual(result["fresh_provider_totals"]["openmeteo"]["next_1h_mm"], 2)


class EvidenceCollectionTests(unittest.TestCase):
    def test_capture_recognizes_a_cached_image_from_previous_chart_bucket(self):
        now = 1793358000.0
        def png(color):
            output = io.BytesIO()
            Image.new("L", (800, 480), color).save(output, format="PNG")
            return output.getvalue()
        actual, other = png(255), png(0)
        cache = {name: {} for name in audit.TABLES}
        def fetch(url, name, sample, previous=None):
            return {"ok": True, "body": actual} if name == "dashboard" else {"ok": False, "error": "test provider offline"}
        def replay(cache, rendered_at, code_dir):
            return (actual if rendered_at < now else other), {"segments": [],
                "rain_axis": {"printed_top_mmh": 1.0, "scale_max_mmh": 1.0}}
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(database=Path("unused"), city="Amsterdam", latitude=52.36,
                                   longitude=4.84, base_url="http://example.test", code_dir=Path("unused"))
            with patch.object(audit.time, "time", return_value=now), patch.object(audit, "read_cache", return_value=cache), \
                    patch.object(audit, "fetch", side_effect=fetch), patch.object(audit, "replay", side_effect=replay):
                analysis, _ = audit.capture(args, Path(directory) / "sample", None)
        self.assertTrue(analysis["image_check"]["matched"])
        self.assertEqual(analysis["image_check"]["different_pixels"], 0)
        self.assertEqual(analysis["reconstructed_at"], audit.iso(now - 300))

    def test_missed_attempt_is_not_counted_as_a_collected_image(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            sample = output / "samples" / "0000_missed"
            sample.mkdir(parents=True)
            audit.write_json(sample / "analysis.json", {"captured_at": None, "issues": [],
                             "request_errors": {"collector": "Missed scheduled sample"}})
            manifest = {"started_local": "start", "scheduled_end_local": "end", "planned_samples": 1}
            status = audit.report(output, manifest, "completed")
            self.assertEqual(status["samples_collected"], 0)
            self.assertEqual(status["sample_attempts"], 1)
            self.assertEqual(status["state"], "completed_with_errors")

    def test_provider_parse_failure_makes_completion_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            sample = output / "samples" / "0000_bad_json"
            sample.mkdir(parents=True)
            audit.write_json(sample / "analysis.json", {"issues": [], "request_errors": {},
                             "provider_comparison": {"parse_errors": {"openmeteo": "invalid response"}}})
            manifest = {"started_local": "start", "scheduled_end_local": "end", "planned_samples": 1}
            status = audit.report(output, manifest, "completed")
            self.assertEqual(status["samples_with_parse_errors"], 1)
            self.assertEqual(status["state"], "completed_with_errors")

    def test_corrected_axis_is_not_flagged(self):
        cache = {"buienradar_rain": {}, "openmeteo_hourly": {"success": {
            "fetched_at": 0, "payload": [{"ts": 3600, "rain_mmh": 0.5}]}}}
        _, issues, _ = audit.validate_segments([
            {"start_ts": 0, "end_ts": 3600, "source": "Open-Meteo", "mmh": 0.5}], cache, 0,
            {"printed_top_mmh": 1.0, "scale_max_mmh": 1.0})
        self.assertEqual(issues, [])

    def test_independent_check_detects_overridden_radar(self):
        start = int(dt.datetime(2026, 10, 30, 10, 0, tzinfo=audit.LOCAL).timestamp())
        cache = {"buienradar_rain": {"success": {"fetched_at": start,
            "payload": [{"time": "10:00", "value": 0}]}}, "openmeteo_hourly": {"success": {
            "fetched_at": start, "payload": [{"ts": start + 3600, "rain_mmh": 0.5}]}}}
        _, issues, _ = audit.validate_segments([
            {"start_ts": start, "end_ts": start + 300, "source": "Open-Meteo", "mmh": 0.5}], cache, start)
        self.assertIn("buienradar_priority", [issue["code"] for issue in issues])

    def test_cache_read_does_not_modify_database_and_filters_city(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "production.sqlite3"
            with sqlite3.connect(path) as connection:
                for name in audit.TABLES:
                    city_column = "city TEXT," if name != "device_sensor" else ""
                    connection.execute(f'CREATE TABLE "{name}" (id INTEGER PRIMARY KEY, {city_column}'
                                       'fetched_at INTEGER, success INTEGER, payload_json TEXT, error_text TEXT)')
                    if city_column:
                        connection.execute(f'INSERT INTO "{name}" VALUES (1,?,1,1,?,NULL)',
                                           ("amsterdam", json.dumps({"ok": True})))
                        connection.execute(f'INSERT INTO "{name}" VALUES (2,?,2,1,?,NULL)',
                                           ("berlin", json.dumps({"wrong_city": True})))
                    else:
                        connection.execute(f'INSERT INTO "{name}" VALUES (1,1,1,?,NULL)',
                                           (json.dumps({"temp": 20}),))
            previous = hashlib.sha256(path.read_bytes()).hexdigest()
            path.chmod(0o444)
            result = audit.read_cache(path, "Amsterdam")
            self.assertEqual(result["buienradar_rain"]["success"]["payload"], {"ok": True})
            self.assertEqual(previous, hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_unmatched_reconstruction_does_not_become_confirmed_finding(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            sample = output / "samples" / "0000_example"
            sample.mkdir(parents=True)
            audit.write_json(sample / "analysis.json", {
                "image_check": {"matched": False}, "request_errors": {},
                "issues": [{"code": "rain_values_or_intervals", "confidence": "candidate_reconstruction_only"}],
            })
            manifest = {"started_local": "start", "scheduled_end_local": "end", "planned_samples": 1}
            status = audit.report(output, manifest, "running")
            self.assertEqual(status["confirmed_findings_by_sample"], {})
            self.assertEqual(status["image_matches"], 0)


if __name__ == "__main__":
    unittest.main()
