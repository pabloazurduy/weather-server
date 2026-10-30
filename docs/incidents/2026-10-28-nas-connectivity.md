# NAS connectivity diagnosis — 28 October 2026

## Scope

Diagnose the reTerminal E1001 displaying “Weather server unavailable.” The
weather server runs on a UGREEN NAS and is normally accessed at
`http://nas.local:5050`. The NAS is connected by Ethernet through an extender.
This investigation used read-only SSH diagnostics and normal HTTP GET requests.
No network settings, services, containers, or display firmware were changed.

All times below are Europe/Amsterdam (CET, UTC+01:00). Docker timestamps were
converted from UTC.

## Findings

The NAS lost local network connectivity as well as access to external weather
services. Its Ethernet interface repeatedly lost carrier, DHCP requests received
no offers, and it fell back to the link-local address `169.254.8.5`. This explains
why the reTerminal could not retrieve the dashboard over the home network.

The NAS logs establish the network failure but cannot identify whether its
initial trigger was the extender, the extender's upstream link, the router,
cabling, or a NAS network-recovery action. The reported ISP maintenance is a
possible trigger for an upstream disruption, not a proven cause of the local
Ethernet/DHCP failure. Internet-only downtime would not, by itself, explain the
loss of a home-network address and repeated Ethernet link events.

The NAS had been running for 26 days. The weather container had been running
since 2 October, reported no OOM kill and zero automatic restarts, and already
contained the September threaded-server and socket-timeout fix. Recovery did
not require restarting or modifying that container.

The NAS already had `192.168.178.43` at 02:06 and received the same address when
connectivity recovered. `192.168.178.101`, recorded in the September investigation,
was an outdated address, not evidence of an address change during this outage.
The reTerminal firmware is configured for `nas.local:5050`, not a fixed IP.

## Timeline

| Local time | Evidence |
| --- | --- |
| 02:06 | DHCP ACK for `192.168.178.43` from router `192.168.178.1`. |
| 09:54:15 | reTerminal sensor POST and dashboard GET both returned HTTP 200. |
| 10:09:19 | reTerminal sensor POST returned HTTP 200. |
| 10:09:24–10:09:39 | Weather lookups failed with DNS errors; server used cached data. |
| 10:09:39 | Server began its dashboard HTTP 200 response, about 20 seconds after the sensor POST. |
| 10:13:47 | First recorded Ethernet `NIC Link is Down` event today. |
| 10:14:41 | DHCP client reported `No DHCPOFFERS received`. |
| 10:14:45–10:14:51 | Auto-IP selected and advertised `169.254.8.5`. |
| 10:13–11:40 | 55 Ethernet link-down events in this interval; DHCP repeatedly failed. |
| 18:18 | Three further link-down events; last link-up at 18:18:37. |
| 18:19:18 | Router again acknowledged `192.168.178.43`; network address restored. |
| 18:23:18 | Dashboard PNG request from the Mac returned HTTP 200. |
| 18:28:04 | reTerminal sensor POST and dashboard GET returned HTTP 200 again. |

Counts from today's NAS syslog/kernel log: 58 link-down events, 58 link-up
events, and 45 `No DHCPOFFERS` messages. No matching kernel driver-hang,
watchdog, or out-of-memory errors were found in the targeted kernel-log search.
Absence of those messages does not rule out every driver or hardware issue.

## Why the error screen appeared

There are two supported mechanisms:

1. Once the NAS lost its normal local-network address, the display could not
   reach `nas.local:5050`.
2. Before that, the server's cached-data fallback was too slow for the display's
   HTTP timeout. The 10:09 request waited through four sequential failed DNS
   lookups (roughly five seconds each, including an hourly-forecast lookup made
   twice), then produced a response. The firmware sets a ten-second HTTP read
   timeout, so the approximately twenty-second response is consistent with the
   error screen even while the server process remained running. Server-side HTTP
   200 logging alone does not prove the client received the full response.

The firmware then explicitly redraws a full-screen error message after a failed
download. That display behavior is the separately requested step 2.

## Current verification

At approximately 18:37–18:38 CET:

- NAS address: `192.168.178.43/24`; default route: `192.168.178.1` through `eth0`.
- Open-Meteo and Buienradar returned HTTP 200 from the NAS (about 0.24 and 0.19
  seconds respectively), and both were also reachable inside the weather
  container.
- `/up` and `/dashboard.png` returned HTTP 200 from the Mac.
- `/dashboard.bin`, addressed directly while preserving the `nas.local` host,
  returned HTTP 200, exactly 48,000 bytes, in about 0.25 seconds.
- No further Ethernet link-down, DHCP-no-offer, or selected memory-failure
  messages appeared in syslog after 18:19:20 up to the verification time.
- The Mac intermittently failed to resolve `nas.local`, while direct-IP checks
  worked. This observation alone does not establish the display's resolver
  behavior or the original cause of the outage.

## Recommended next network checks

1. Test the NAS with a known-good Ethernet cable directly to the router, bypassing
   the extender. This removes the main intermediate component and is the most
   useful isolation test if the issue returns.
2. Review the extender and router event logs around 10:09–10:14 and 18:18–18:19
   CET for an upstream disconnect, restart, or bridge/DHCP problem. Obtain the
   extender model before recommending model-specific firmware or settings.
3. Consider a DHCP reservation for the NAS's current address on the router. This
   makes its address predictable but does not fix Ethernet drops or a broken
   extender link. Changing DNS servers alone would not fix the demonstrated
   local-network failure either.

No router, extender, DNS, DHCP, or Ethernet configuration changes were made.

## Follow-up work

### Step 2 — preserve the last forecast (completed)

Implemented and flashed to the connected reTerminal E1001 on 28 October 2026,
after the initial read-only NAS investigation:

- Complete 48,000-byte forecasts are stored in LittleFS with a length/version
  header and FNV-1a integrity checksum. A temporary file is atomically renamed
  over the old cache only after the new file has been completely written.
- On Wi-Fi or download failure, the cached forecast is restored with a small
  `Connection lost` badge over the bottom-right footer URL. The forecast and its
  original date remain visible. RTC state prevents repeated redraws during an
  outage; a successful refresh clears the badge.
- An absent, corrupt, or older-than-displayed cache leaves the existing panel
  untouched. An unmountable filesystem is initialized only if its entire
  partition is erased; existing data is not formatted automatically.
- HTTP response timeouts increased from 10 to 45 seconds to accommodate the
  measured slow cached-source fallback. Automatic retries remain every 15
  minutes, with manual wake available on all three buttons.
- `nas.local:5050` remains the server address. No low-voltage cutoffs or charging
  thresholds were introduced, and no NAS/container changes were needed.

Validation used ESP32 Arduino core 2.0.15, XIAO_ESP32S3, OPI PSRAM, and the same
default 8 MB partition layout read from the device. Production and hardware-test
sketches compiled successfully. The on-device test emitted 22 PASS messages with
no FAIL messages, exercising a real forecast download, cache persistence across
deep sleep, an interrupted temporary save, corruption rejection, stale-cache
rejection, a real failed download with only the display's Wi-Fi disabled,
one-time warning drawing, another offline wake, and production recovery.

The normal production firmware was flashed again after the test and its written
data hash verified. Its startup log confirmed `POST /sensor: 200`, a GET to
`http://nas.local:5050/dashboard.bin`, all 48,000 bytes downloaded, a new cache
saved, `Display updated.`, and `Sleeping 900 s...`. The test firmware is no longer
installed. The original app0 firmware and boot data were backed up privately in
the temporary build directory before flashing.

Repeatable hardware checks are documented in
`arduino-reterminal/tests/offline_recovery/README.md`.

### Step 3 — independent 24-hour rain-plot validation (completed and reviewed)

Run a Python collection/validation job for 24 hours, saving dashboard images,
independently requested raw Buienradar and Open-Meteo responses, and timestamps.
Verify units, the Buienradar intensity conversion, time-zone/forecast alignment,
and the plotted values against those independent responses. Distinguish plot
correctness from actual forecast accuracy and differences between providers.
Started on the NAS at **19:43:05 CET on 28 October 2026**, with collection due to
end at **19:43:05 CET on 29 October**. The isolated
`weather-rain-audit-20261028` collector saves samples every five minutes (289
planned) under `/volume2/docker/weather-validation/2026-10-28-rain-audit/evidence`.
It reads production data through a read-only mount and records dashboard PNGs,
raw provider responses, source-cache records, and independent per-bar checks.
MET Norway is included as a third provider. The collector finished successfully
at **19:43:06 CET on 29 October**, with zero restarts. After SSH access was
restored, all evidence was retrieved and reviewed on **30 October**. The scheduled
follow-up was confirmed absent on 29 October and has not been recreated.

The preflight and first full-run sample both reconstructed the real chart with
zero pixel differences and confirmed two initial issues: Open-Meteo amounts
assigned to the wrong time intervals, and a rain-axis label that differs from
the bar-height scale when the maximum is below 1 mm/hour. Full-window checks
verified **289 actual screenshots and complete evidence sets**, all with exact
rain-chart reconstruction matches, and zero independent request or provider-parse
errors. The wrong rain intervals occur in 58 snapshots and the axis-label issue
in 48. Buienradar's 6,936 recorded bars pass the source-value comparison within
rounding. A separate production current-conditions request returned HTTP 503 at
11:07:04 CET on 29 October; cached data kept the dashboard available.

The run audited plotting correctness, not observed rainfall accuracy. No
production rain-logic fix has been deployed. See the
[verified final results and recommended corrections](../rain-validation-results-2026-10-28.md)
and [validation details](../rain-validation.md).

## Evidence locations

- NAS: `/var/log/syslog`, `/var/log/kern.log`,
  `/var/log/dhclient/dhclient.log`.
- Container: `ghcr.io_pabloazurduy_weather-server-1`
  (`c9a81cd48d72`), timestamped Docker logs and container inspection.
- Repository: `flask-server/app.py`, `flask-server/models.py`,
  `arduino-reterminal/weather_display/weather_display.ino`.

System journal access required additional privileges, but the account could read
the relevant syslog/kernel files and container logs without elevation; no sudo
password or additional privileges were used.
