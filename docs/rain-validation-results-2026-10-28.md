# Rain-chart validation results — 28–29 October 2026

Reviewed on 30 October after NAS SSH access was restored. The collection completed
normally: loss of SSH access did not interrupt the independently running container.
The weather server and reTerminal firmware were not changed during this review.

## Coverage verified from the saved files

| Check | Result |
| --- | --- |
| Capture window | 28 October 19:43:05 to 29 October 19:43:05 CET |
| Scheduled samples / complete sample directories | 289 / 289 |
| Actual dashboard PNGs / exact rain-chart reconstruction matches | 289 / 289 |
| Missing captures, request errors, provider parse errors, reconstruction errors | 0 each |
| Saved response-body hashes checked against request metadata | 1,156; all match |
| Collector exit / restarts | Exit 0 / 0 restarts |

Every sample has all 12 expected evidence files. Sample indices cover 0–288,
and capture starts are approximately 300 seconds apart, with no missed slot.
All downloaded dashboard rain-chart crops match their saved reconstruction with
**zero differing pixels**, not merely within the collector's 1% acceptance limit.

The independent interval calculations were rerun against every captured source
cache and compared with every per-bar CSV. The two finding totals reproduce.
Fresh-provider summaries also reproduce apart from four floating-point aggregate
differences below 0.00000000000000001 mm/hour between the Python runtimes; these
do not change a finding, source total, or plotted-bar comparison.

The earlier reporting weaknesses do not inflate coverage in this run: these are
289 real images and complete evidence sets, not counts of missed attempts. Parse
errors were checked explicitly, separately from the collector's request-error total.

## Confirmed plotting errors

### 1. Open-Meteo rain assigned to the wrong periods

**58 of 289 snapshots** contain incorrectly assigned hourly rain values. Across
the captures, 112 of 2,890 Open-Meteo bar records differ from independently
time-aligned values from the **same cached forecast**. Six distinct cached hourly
forecasts are affected; repeated snapshots are not separate forecast events.

Open-Meteo's hourly precipitation is the accumulation over the preceding hour.
The server instead selects a value at or before the bar start and extends it
forward across a group that may also be offset from the hour. The correct value
for such a group must account for the overlap with each source hour.
See the [official hourly definitions](https://open-meteo.com/en/docs#hourly-parameter-definition).

For the first captured image, the 28 October **21:35–22:35** bar shows
**0.5 mm/hour**, but correctly averaging the same cached source over that interval
gives **0.1 mm/hour**. A later image shows **0.5 mm/hour for 29 October
00:30–01:30**, although that cached source assigns **zero** to that interval.
The error can also hide predicted rain: 62 bar records show zero when the cached
forecast has a nonzero interval average. These are presentation errors relative
to the captured forecast, not measurements of actual rainfall.

Recommended correction: represent hourly precipitation as intervals ending at
the provider timestamp, and integrate overlap-weighted amounts over each drawn
bar's actual start/end. Preserve the Buienradar handover and handle partial hours.
Do not treat an uncovered interval as dry.

### 2. Rain-axis label and bar heights use different scales

**48 of 289 snapshots** have a positive maximum below 1 mm/hour. The label uses
that data maximum, but the bar-height calculation uses a minimum full-scale range
of 1 mm/hour. For example, an image prints 0.5 mm/hour at the top while a
0.5 mm/hour bar occupies only half the available height.

Recommended correction: calculate the displayed rain-axis label and bar heights
from the same scale maximum. Keeping a minimum range of 1 mm/hour is fine if the
label also says 1.0 mm/hour.

## Buienradar, availability, and forecast disagreement

All **6,936 Buienradar bar records**, including 64 nonzero records, agree with the
cached encoded source after allowing for the server's two-decimal rounding.
No Buienradar conversion or bar-assignment error was found in this capture window.
These counts include repeated forecasts across screenshots.

The collector made 289 successful requests each to the dashboard, Buienradar, and
Open-Meteo. MET Norway was requested 23 times and its cached response reused in
266 captures, as recorded in the evidence. All independent provider responses
parsed successfully. Provider updates and disagreement were kept separate from
the same-cache plotting checks above.

One distinct failed **production** request is visible in the captured cache:
Open-Meteo's current-conditions endpoint returned HTTP 503 on 29 October at
11:07:04 CET. This was not a failure of the independent rain requests. The
dashboard continued returning images using cached data. The production container
still has its original 2 October start time and zero restarts.

This audit establishes chart/source consistency, not ground-truth weather
accuracy. Rain-gauge or other independent observed rainfall would be needed to
judge whether a weather provider's prediction actually came true.

## Evidence

The complete 45 MiB evidence copy is in
`tmp/rain-validation-2026-10-28/evidence/` in this checkout. The original remains
on the NAS at
`/volume2/docker/weather-validation/2026-10-28-rain-audit/evidence/`.

- [Original collector report](../tmp/rain-validation-2026-10-28/evidence/report.md)
- [Final collector status](../tmp/rain-validation-2026-10-28/evidence/status.json)
- First image: [dashboard](../tmp/rain-validation-2026-10-28/evidence/samples/0000_20261028T184305Z/dashboard.png), [independent comparison](../tmp/rain-validation-2026-10-28/evidence/samples/0000_20261028T184305Z/reference.png), [bar values](../tmp/rain-validation-2026-10-28/evidence/samples/0000_20261028T184305Z/segments.csv).
- Largest bar error: [dashboard](../tmp/rain-validation-2026-10-28/evidence/samples/0034_20261028T213305Z/dashboard.png), [independent comparison](../tmp/rain-validation-2026-10-28/evidence/samples/0034_20261028T213305Z/reference.png), [bar values](../tmp/rain-validation-2026-10-28/evidence/samples/0034_20261028T213305Z/segments.csv).

No rain-logic fix was deployed as part of this review. The scheduled follow-up
was already confirmed absent on 29 October and has not been recreated.
