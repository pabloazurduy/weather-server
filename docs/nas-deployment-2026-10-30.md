# NAS rain-chart correction — 30 October 2026

The corrected dashboard is deployed, not just committed. The running application
revision is `b3a69f243f33292bfc7a7d95dd030d6db2aff1dc`, published as
`ghcr.io/pabloazurduy/weather-server:latest` by the successful
[GitHub build](https://github.com/pabloazurduy/weather-server/actions/runs/41046911049).
Documentation-only commits after this revision do not rebuild the application.
The immutable registry reference for this deployment is
`ghcr.io/pabloazurduy/weather-server@sha256:6bd398d64b3861954c2e96af7f0d7214d48bbcba3e5c10b07a71802c4195d593`.
Pin that reference when auditing this version after the `latest` tag changes.

## Changes

- Buienradar takes precedence for all available short-term intervals, including
  zero rain. There is no arbitrary detail-hour cutoff overriding its coverage.
- Open-Meteo fills uncovered intervals using the overlap-weighted amounts from
  its preceding-hour accumulation periods, including partial final bars.
- Missing/null data stays unavailable instead of being drawn as dry. One rain
  provider failing does not hide the other provider's available data.
- Rain bar heights and the printed rain-axis label use the same scale.
- Old time-only radar responses are anchored to their original fetch date, so
  stale rain cannot accidentally become the next day's forecast.
- The optional validator distinguishes actual PNGs from failed attempts, counts
  provider parse errors, checks Buienradar priority, and handles cached images
  from the preceding five-minute chart bucket without forcing refreshes.

## Deployment and verification

The image was pulled before stopping the old container. Its revision label was
checked against the published commit. The existing settings, `nas.local` base
URL, port mapping, persistent database mount, restart policy, and custom
environment values were preserved. The new container started at 12:18:17 CET.

| Check | Verified result |
| --- | --- |
| Unit tests, locally and in GitHub CI | 49 passing |
| Corrected renders against all saved baseline inputs | 289 cases; zero timing, scale, or priority findings |
| Live `/up` | HTTP 200, status ok |
| Live `/dashboard.png` | HTTP 200, valid 800×480 PNG |
| Live `/dashboard.bin` | HTTP 200, 48,000 bytes |
| Live `/api/display` | HTTP 200; image URL uses `http://nas.local:5050` |
| Independent post-deployment check | One real screenshot; exact chart match; no findings or request/parse errors |
| Production database | SQLite `quick_check`: ok |
| Device contact after deployment | New sensor reading at 12:45:51 CET |
| New server restarts during checks | 0 |

The post-deployment check queried Buienradar, Open-Meteo, and MET Norway. It ran
once with `--rm`; it is not an ongoing collection service. Its evidence is on
the NAS at `/volume2/docker/weather-validation/2026-10-30-post-update-b3a69f2`
and copied locally beneath `tmp/rain-validation-2026-10-28/`.

One Mac check initially timed out while resolving `nas.local`, before opening a
TCP connection. Subsequent dual-stack requests succeeded after approximately
five seconds of resolution. Explicit IPv4 hostname lookup took about 3 ms and
the API and bitmap requests completed in under 50 ms. The NAS advertised the
correct IPv4 address, 192.168.178.43. These are separate name-resolution delays,
not dashboard HTTP failures; no DNS/router settings or base URL were changed.

## Cleanup and recovery

The completed `weather-rain-audit-20261028` container was removed. Its source,
original evidence, and preflight directory remain under
`/volume2/docker/weather-validation/2026-10-28-rain-audit`.
The current validator and [future audit instructions](rain-validation.md#run-another-audit-on-the-nas)
are committed, with the opt-in `compose.rain-validation.yml`. No validator or
scheduled follow-up is left running.

A consistent pre-update SQLite backup and private container configuration are
stored at `/volume2/docker/weather-server-deployments/20261030T111743Z`.
Do not publish `container-before.json`: it can contain private environment values.
The old container is retained as
`weather-server-rollback-20261030t111743z`, stopped with restart policy **no**,
so it cannot contend for port 5050 after a NAS restart.

If a code rollback is needed, stop the new container before restoring the old
name and restart policy. Do not overwrite the live database merely to roll back
the application. The original data mount remains unchanged.

The local device credential header is now ignored and no longer tracked; its
local copy was preserved. Because the repository is public and the file existed
in older commits, the affected Wi-Fi credentials should be rotated. Git history
was not rewritten.
