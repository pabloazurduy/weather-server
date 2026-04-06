
# weather-server

99% vibe coded

Weather dashboard project for an e-ink display. The repo contains a Python server that renders weather images and an Arduino sketch for the display device that downloads and shows them.

<!-- markdownlint-disable MD033 MD045 -->
<img src="example-edisplay.JPG" alt="Photo of the e-ink display hardware" style="max-height: 350px;" />
<img src="example_dashboard.png" alt="Rendered weather dashboard example" style="max-height: 350px;" />
<!-- markdownlint-enable MD033 MD045 -->

## Repository layout

- `flask-server/` Python HTTP server that fetches weather data, caches it in SQLite, renders the dashboard image, and exposes API endpoints for the display client.
- `arduino/weather_display/` Arduino sketch for the reTerminal E1001. It reads the on-board SHT40 sensor, posts sensor data to the server, downloads `/dashboard.bin`, and deep-sleeps between refreshes.
- `arduino/epaper_test/` Minimal e-paper hardware test sketch for the reTerminal E1001.
- `Dockerfile` Container image definition for the Python server.

## Flask server

Run locally:

```bash
cd flask-server
python3 -m unittest test.py
python3 app.py
```

The server listens on port `8080` by default and exposes:

- `GET /up`
- `GET /dashboard.png`
- `GET /dashboard.bin`
- `GET /refresh`
- `GET /force-refresh-sources`
- `GET /api/setup`
- `GET /api/display`
- `POST /sensor`

Key configuration lives in `flask-server/local_settings.py` or `WEATHER_*` environment variables:

- `CITY` is used as the displayed city label and as the cache key for that location.
- `CITY_LAT` and `CITY_LON` are used for Open-Meteo and Buienradar and must match the same place as `CITY`.
- `API_KEY` and `BASE_URL` are required for normal operation.

`CITY` supports these formats when you want to disambiguate a place name:

- `City`
- `City,CC`
- `City,State,CC`

Examples: `Amsterdam`, `Amsterdam,NL`, `Portland,OR,US`. No camel case is required. Prefer `City,CC` when the name could be ambiguous.

The rendered dashboard now uses Open-Meteo for current conditions, daily min/max values, and the temperature plot. Buienradar is only used for short-range rain detail in the Netherlands and Belgium.

The weather cache is stored in `flask-server/weather_cache.sqlite3`. Weather-source history is partitioned by normalized city so one database can keep cached data for multiple locations.

Container publishing:

- Pushes to `main` build the root `Dockerfile` and publish `ghcr.io/pabloazurduy/weather-server` through GitHub Actions.
- Pull requests build the same image without publishing so Dockerfile changes stay validated.

Run with Docker:

```bash
docker build -t weather-dashboard .
docker run -p 8080:8080 \
   -e WEATHER_CITY=Amsterdam,NL \
   -e WEATHER_CITY_LAT=52.370216 \
   -e WEATHER_CITY_LON=4.895168 \
   -e WEATHER_API_KEY=your-device-api-key \
   -e WEATHER_BASE_URL=http://your-host:8080 \
   weather-dashboard
```

Or pull the published image:

```bash
docker pull ghcr.io/pabloazurduy/weather-server:latest
```

## Arduino sketches

For the production display sketch:

1. Copy `arduino/weather_display/secrets.example.h` to `arduino/weather_display/secrets.h`.
2. Fill in Wi-Fi credentials and the server host/port.
3. Install the libraries referenced at the top of `arduino/weather_display/weather_display.ino`.
4. Build and flash from the Arduino IDE for `XIAO_ESP32S3` with PSRAM enabled.

Use `arduino/epaper_test/epaper_test.ino` to verify the display wiring and driver before testing the full weather client.
