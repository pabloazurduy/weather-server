# Independent 24-hour rain-chart validation

## Completed run

- Started: **28 October 2026, 19:43:05 CET**.
- Finished: **29 October 2026, 19:43:06 CET**; collector exited successfully with zero restarts.
- Sampling interval: 5 minutes, with 289 planned samples including both endpoints.
- NAS collector: `weather-rain-audit-20261028`.
- NAS run directory: `/volume2/docker/weather-validation/2026-10-28-rain-audit`.
- Live run state and report: `evidence/status.json` and `evidence/report.md` in that directory.
- Complete local evidence: `tmp/rain-validation-2026-10-28/evidence/` in this repository. The older files in its parent directory are only the initial one-sample copy.
- Follow-up automation: confirmed absent on 29 October; no further checks are scheduled.

The finished audit container is no longer required. Its code and the opt-in
Compose definition are kept in the repository; the NAS evidence is retained.

The [verified final results](rain-validation-results-2026-10-28.md) cover all
289 real screenshots, with zero request or provider-parse errors and exact
rain-chart reconstruction matches for every image. Incorrect Open-Meteo rain
intervals occur in 58 snapshots; inconsistent rain-axis labels occur in 48.
No Buienradar bar-value mismatch was found within the rounding allowance.

The collector runs on the NAS, independently of the Mac. Its output persists on
the NAS. Collection errors are recorded instead of silently inventing a missing
screenshot or treating missing precipitation as zero. An interrupted process can
resume against the original saved deadline; it does not start another 24-hour
window. Docker is allowed up to three retries after a process failure.

## What is collected

Every sample directory contains:

- `dashboard.png`: the real image returned by the production dashboard endpoint.
- `buienradar.txt`: a separate request to Buienradar's documented coordinate feed.
- `openmeteo.json`: a separate Open-Meteo request using explicit millimetre units
  and UTC Unix timestamps.
- `metno.json`: a third forecast from MET Norway; queried/revalidated at most
  hourly, respecting `Expires`, and reused with that fact recorded between queries.
- `requests.json`: exact request URLs, HTTP status, source headers, content hashes,
  request timings, and any transport errors.
- `cached_sources_before.json` and `cached_sources_after.json`: the server's most
  recent successful source data and latest attempts, captured through read-only
  SQLite transactions around the image request.
- `reconstructed.png` and `production_chart.json`: the installed production
  code's reconstruction of its rain plot from those captured source records.
- `segments.csv`: per-bar displayed rates, correctly time-aligned rates from the
  cached source, fresh-provider rates, MET Norway rates, and numeric differences.
- `reference.png`: a red/blue comparison of the dashboard groups and independently
  calculated source intervals on a shared scale.
- `analysis.json`: reconstruction agreement, source ages, findings, and separate
  comparisons between freshly queried providers.

The collector queries `http://127.0.0.1:5050/dashboard.png` on the NAS itself. This
captures the image even if the NAS's external LAN address changes. It uses normal
GET requests and does not call the source-refresh endpoints.

## Independence and confidence

Reference calculations in `flask-server/rain_validation.py` do not call the
production rain-conversion or aggregation helpers. They implement the provider
definitions independently:

- Buienradar: zero means dry; otherwise `10 ** ((encoded - 109) / 32)` mm/hour.
  Five-minute time-only records are anchored to their original fetch date,
  including midnight rollover.
- Open-Meteo: the precipitation timestamp marks the **end** of its preceding
  one-hour accumulation. Groups that cross hour boundaries are compared with
  overlap-weighted amounts for their actual covered interval.
- MET Norway: `next_1_hours.precipitation_amount` covers the following hour,
  rather than the preceding one.

Production code is used separately to identify what the downloaded image actually
drew. Both before/after cache candidates are tried. Only a sufficiently matching
chart crop is eligible for an image-confirmed finding; differences greater than
1% of foreground pixels leave the reconstruction inconclusive. The first
preflight and first full-run sample each matched with **zero differing pixels**.

Fresh API responses can differ because a forecast updated after the server cached
its inputs. The audit records that difference separately. Provider disagreement
is not proof of a plotting bug. This validates presentation, source conversion,
and time alignment; independent observed rain would be needed to establish actual
meteorological forecast accuracy.

## Initial confirmed findings

The first full-run image was captured at 19:43:05 CET. Its rain chart matched the
production reconstruction exactly, with 4,381 foreground pixels checked.

1. **Wrong rain intervals:** the 21:35–22:35 bar showed 0.5 mm/hour, while the
   correctly aligned values from the very same cached Open-Meteo forecast average
   0.1 mm/hour for that interval. The production code takes a preceding-hour
   amount and extends it forward into an offset group. Three groups differed in
   this first image. This is separate from subsequent provider updates.
2. **Axis label does not match scale:** the chart labels its top with 0.5 mm/hour
   but scales bar heights against a minimum range of 1 mm/hour. When the maximum
   is below 1 mm/hour, the displayed label misstates the vertical scale.

The live server's calculations remained at their baseline throughout collection.
The [final review](rain-validation-results-2026-10-28.md) includes full-window
coverage, frequencies, examples, limitations, and recommended corrections.
The corrections and deployment checks are tracked below; the original run's
evidence remains unchanged as the pre-fix baseline.

## Isolation and reproducibility

The collector uses the same existing image as the weather server, pinned to
image ID `sha256:1c3e8124563d6c239c14a198f82d502f8368d7b612077adc2d3ceedc11d7c650`
(repository revision `57503816dfd6284d231f8659b118bc4f6b3e888a`). It records hashes
of the production Python files in its manifest. No image rebuild or server
restart was required.

The collector runs as UID 1000 with a read-only container filesystem and a
read-only bind mount of `/volume2/docker/weather-server`. Only its dedicated
evidence directory is writable. It is limited to half a CPU and 256 MiB RAM.
The validator source is mounted separately and does not alter the server.

Run reference tests from `flask-server`:

```bash
uv run --frozen python -m unittest test.py test_rain_validation.py
```

A single sample can be taken with:

```bash
python rain_validation.py \
  --database /production-data/weather_cache.sqlite3 \
  --output /evidence \
  --code-dir /app \
  --base-url http://127.0.0.1:5050 \
  --city Amstedam --latitude 52.36 --longitude 4.84 \
  --once
```

Use the actual production environment/configuration for the replay, including its
city, coordinates, and default 800×480 layout. `Amstedam` above preserves the
existing production city/cache key, including its spelling. For a full run omit
`--once` and use `--duration-hours 24 --interval-seconds 300`. Use a fresh output
directory for each distinct run.

## Run another audit on the NAS

The published dashboard image includes `rain_validation.py`. The separate
`compose.rain-validation.yml` service has an explicit opt-in profile, a read-only
production-data mount, limited resources, and no restart policy. Nothing starts
automatically when the normal dashboard starts.

From a checkout of this repository on the NAS, choose a **new** evidence directory
and create it as the NAS user (UID 1000, group 10 in this installation):

```bash
export RAIN_AUDIT_OUTPUT_DIR=/volume2/docker/weather-validation/new-rain-audit/evidence
mkdir -p "$RAIN_AUDIT_OUTPUT_DIR"
docker compose -f compose.rain-validation.yml --profile validation pull rain-validation
docker compose -f compose.rain-validation.yml --profile validation run -d \
  --name weather-rain-validation rain-validation
docker logs --tail 20 weather-rain-validation
```

The defaults match this NAS: `Amstedam` (its existing cache key), latitude 52.36,
longitude 4.84, production data in `/volume2/docker/weather-server`, and the local
dashboard at `http://127.0.0.1:5050`. Override `WEATHER_CITY`, `WEATHER_CITY_LAT`,
`WEATHER_CITY_LON`, `RAIN_AUDIT_DATA_DIR`, and `RAIN_AUDIT_BASE_URL` if needed.
`RAIN_AUDIT_HOURS` defaults to 24 and `RAIN_AUDIT_INTERVAL_SECONDS` to 300.
The configured city/coordinates and server code must match the actual dashboard.
For an old deployed version, pin the Compose image to that exact image digest;
reconstructing with a different version is intentionally inconclusive.

Inspect the persistent `status.json` and `report.md` in the evidence directory.
`samples_collected` now counts actual downloaded dashboard files; `sample_attempts`
also includes missed/failed slots. Provider parsing failures have their own
counter. `completed_with_errors` means incomplete images, failed requests/parsing,
or unmatched reconstructions. Findings and weather-provider disagreements remain
separate from those collection/validation failures. The independent reference
also checks that Open-Meteo has not overridden available Buienradar coverage.

To stop/remove **only this validator**, without deleting its saved files:

```bash
docker stop weather-rain-validation
docker rm weather-rain-validation
```

If it has already exited, only `docker rm` is needed. Do not remove the evidence
directory or the production weather-server container. No scheduler is needed:
the job ends after its saved deadline. Missed samples, including the final slot,
are marked missing instead of collecting a retrospective image after the window.

## Provider specifications

- [Buienradar coordinate data and conversion](https://www.buienradar.nl/overbuienradar/gratis-weerdata)
- [Open-Meteo hourly variable definitions](https://open-meteo.com/en/docs)
- [MET Norway period definitions](https://developer.yr.no/doc/ForecastJSON/)
- [MET Norway client identification and caching](https://developer.yr.no/doc/locationforecast/HowTO/)
