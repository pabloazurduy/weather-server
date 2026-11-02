# Entrance sensor delivery — 2 November 2026

The reTerminal E1001 now measures its SHT40 before connecting to Wi-Fi, retains
timestamped PipeCar payloads in a LittleFS outbox, and posts the same sample to
the weather-server `/sensor` endpoint. The server stores the original timestamp
in its existing SQLite `device_sensor` history. PipeCar receives the independent
device POST through authenticated Windmill flow `f/weather/entrance_sensor` and
stores it in `weather.entrance_sensor`, keyed by device and reading ID.

## Deployment

- Weather-server revision: `9832af66c5dc9bc15f1fec9e2698e0c7e05e728e`.
- [GHCR build](https://github.com/pabloazurduy/weather-server/actions/runs/41479623965): passed and published `ghcr.io/pabloazurduy/weather-server:latest`.
- NAS image digest: `sha256:55e582c1a380694cc6fa676ce4150e138679008b67a6387cf9c5f62711e8a6f9`.
- The container at port 5050 was replaced with the same environment, `/data`
  bind mount, port, bridge network, restart policy, and no-new-privileges setting.
- Private predeployment container settings and a consistent SQLite backup are in
  `/volume2/docker/weather-server-deployments/20261102T161745Z` on the NAS.
  The previous container is retained as `weather-server-rollback-20261102`,
  stopped with restart policy `no`.
- The device's active `app0` partition was flashed at `0x10000`. Its partition
  table, NVS, and LittleFS partition were left untouched. Private backups of
  the previous app, NVS, OTA data, and filesystem are in
  `/private/tmp/entrance-*preflash.bin` on the Mac; the partition table is in
  `/private/tmp/entrance-partitions.bin`. The new image's flashed hash was
  verified by esptool.

## Verification

| Check | Result |
| --- | --- |
| Host firmware mapping, failure, retry tests | Passed |
| Firmware build | Passed, 8 MB partition layout matching the device |
| Weather-server tests | 53 passed |
| PipeCar validation tests and flow lint | 3 passed; lint passed |
| Unauthenticated Windmill route | HTTP 401 |
| Scoped token against unrelated resource API | HTTP 403 |
| Duplicate ingest through authenticated route | HTTP 200, `inserted: false` |
| NAS `/up` and `/dashboard.bin` | HTTP 200; bitmap 48,000 bytes |
| NAS SQLite integrity | `PRAGMA quick_check`: ok |

A physical SHT40 sample with reading ID `be5fcf32eccf30a8` appeared in both
stores. SQLite and PipeCar agreed on original timestamp
`2026-11-02T16:20:09+00:00`, ambient temperature **20.46 °C**, humidity
**56.83%**, and battery voltage **4.111 V**. SQLite's `fetched_at` epoch also
matched that timestamp.

## Limits

- A first boot without valid RTC time and without Wi-Fi cannot assign a trusted
  original timestamp, so that sample cannot enter the durable PipeCar queue.
- The outbox holds 512 readings, about five days at the normal 15-minute
  interval. If the filesystem is unavailable or full, the device attempts a
  direct send, but cannot promise later retry.
- The Windmill token is scoped to this one HTTP trigger and stored only in the
  ignored local `secrets.h` (mode `600`) and the flashed firmware. The route is
  accessed over the LAN using HTTP; a party able to inspect that traffic could
  capture the scoped token. Do not expose the route outside the trusted LAN.
- The physical panel's image was not visually inspected after this flash. The
  NAS bitmap endpoint and sensor upload were verified.
