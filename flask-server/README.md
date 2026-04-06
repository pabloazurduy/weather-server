# Weather Dashboard Server

This directory contains the Python weather dashboard server and its local test suite.

The server renders an e-ink dashboard image, exposes TRMNL-compatible API endpoints,
stores weather responses in SQLite, and keeps weather-source history partitioned by city.

## Local setup

1. Copy `local_settings.example.py` to `local_settings.py`.
2. Fill in your local values or provide `WEATHER_*` environment variables.

## Run

```bash
python3 -m unittest test.py
python3 app.py
```

By default the SQLite database is stored in `weather_cache.sqlite3` in this directory.

## Endpoints

- `GET /up` health check.
- `GET /dashboard.png` rendered grayscale dashboard image.
- `GET /dashboard.bin` raw 1-bit bitmap for the Arduino display client.
- `GET /refresh` regenerate the image using cached source data.
- `GET /force-refresh-sources` bypass source TTLs and refresh remote weather sources.
- `GET /api/setup` and `GET /api/display` TRMNL-compatible device endpoints.
- `POST /sensor` store device temperature, humidity, and battery readings.

## Configuration

`config.py` loads configuration from:

1. `WEATHER_*` environment variables.
2. `local_settings.py` if present.
3. Built-in defaults.

Important settings:

- `CITY` changes the displayed city name and selects the location whose data is cached under that city key.
- `CITY_LAT` and `CITY_LON` are the coordinates used for Open-Meteo and Buienradar. They must describe the same place as `CITY`.
- `BASE_URL` is required for normal operation.

`CITY` supports these formats when you need to disambiguate the location:

- `City`
- `City,CC`
- `City,State,CC`

Use ISO 3166 country codes for `CC`. The state code form is mainly for US locations. No camel case is required; use the normal city spelling, including spaces or local-language names when needed. Prefer `City,CC` when the city name is ambiguous, for example `Amsterdam,NL` or `Portland,OR,US`.

Dashboard source usage:

- Current conditions, the left-side main temperature, the day header time, the 7-day min/max values, and the temperature plot all come from Open-Meteo.
- Buienradar is only used for short-range rain detail inside the Netherlands and Belgium; elsewhere the rain chart falls back to Open-Meteo precipitation.

Container image publishing:

- The repository workflow publishes the server image to `ghcr.io/pabloazurduy/weather-server` on pushes to `main`.
- Pull requests still build the image to validate Docker changes without pushing a package.

Set `CITY_LAT` and `CITY_LON` directly. The old Amsterdam-specific coordinate setting names are no longer supported.
