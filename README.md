# Hello Whale 🐋

A minimal Docker web app that displays an ASCII whale.

## Build

```bash
docker build -t hello-whale .
```

## Run

```bash
docker run -p 8080:8080 hello-whale
```

Visit: http://localhost:8080

## Features

- 🐋 ASCII whale ASCII art
- Minimal Python HTTP server (no dependencies)
- Runs in Alpine Linux (~50MB image)
- Single file app.py
