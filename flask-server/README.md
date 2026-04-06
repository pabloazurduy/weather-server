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

- `CITY` changes the displayed city name and is forwarded to OpenWeather as the `q` parameter.
- `CITY_LAT` and `CITY_LON` are the coordinates used for Open-Meteo and Buienradar. They must describe the same place as `CITY`.
- `OWM_KEY`, `API_KEY`, and `BASE_URL` are required for normal operation.

`CITY` format follows OpenWeather's city-name query formats:

- `City`
- `City,CC`
- `City,State,CC`

Use ISO 3166 country codes for `CC`. The state code form is mainly for US locations. No camel case is required; use the normal city spelling, including spaces or local-language names when needed. Prefer `City,CC` when the city name is ambiguous, for example `Amsterdam,NL` or `Portland,OR,US`.

Legacy `AMS_LAT` and `AMS_LON` settings still work as fallbacks, but `CITY_LAT` and `CITY_LON` are the canonical names.
