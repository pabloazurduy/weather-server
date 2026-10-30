# Offline recovery hardware test

Requires a reTerminal E1001, PSRAM, the default filesystem partition scheme, a
working NAS weather server, and the production sketch's local `secrets.h`.
Run from the repository root, replacing the serial port if necessary:

```bash
arduino-cli compile --upload \
  --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi,UploadSpeed=115200,PartitionScheme=default_8MB \
  --port /dev/cu.usbserial-110 \
  --build-property "compiler.cpp.extra_flags=-I$PWD/arduino-reterminal/tests/offline_recovery" \
  arduino-reterminal/tests/offline_recovery
arduino-cli monitor --port /dev/cu.usbserial-110 --config baudrate=115200
```

The test uses the production firmware's functions and checks:

- Downloading and saving a real forecast, followed by deep sleep.
- Recovering the exact cached pixels after sleep with an incomplete temporary
  cache file present, simulating a reset during the next save.
- Rejecting a cached image with one corrupted byte, then restoring that byte.
- Refusing to replace a newer displayed image with an older cache.
- A failed download while only the display's Wi-Fi is disconnected.
- Restoring the forecast with a `Connection lost` badge, skipping subsequent
  redraws during the same outage, and retaining that state across another sleep.
- Returning to the real production setup to download fresh data and clear the
  badge, then sleeping for the normal interval.

Inspect the screen during the offline stage to confirm that the forecast and
its date remain visible and that only the bottom-right footer contains a badge.
Serial output should report `PASS` for every check, followed by the production
`Display updated.` message. A failed assertion stops the test with a `FAIL` line.
The NAS and other clients are not disconnected by the test.

After testing, flash the ordinary production sketch again:

```bash
arduino-cli compile --upload \
  --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi,UploadSpeed=115200,PartitionScheme=default_8MB \
  --port /dev/cu.usbserial-110 \
  arduino-reterminal/weather_display
```
