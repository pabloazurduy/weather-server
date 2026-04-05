# Weather Dashboard Server

This directory contains the Python weather dashboard server and its local test suite.

## Local setup

1. Copy `local_settings.example.py` to `local_settings.py`.
2. Fill in your local values or provide `WEATHER_*` environment variables.

## Run

```bash
python3 -m unittest test.py
python3 app.py
```

By default the SQLite database is stored in `weather_cache.sqlite3` in this directory.

## Configuration

`config.py` loads configuration from:

1. `WEATHER_*` environment variables.
2. `local_settings.py` if present.
3. Built-in defaults.