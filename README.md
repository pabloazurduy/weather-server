# weather-server

This repo contains:

- **`terminus/`** — Self-hosted [Terminus](https://github.com/usetrmnl/terminus) server for TRMNL e-ink devices, with a patched Docker image that fixes the `/api/setup` response format.
- **`firmware/`** — Patched firmware source for the [Seeed reTerminal E1001](https://github.com/Seeed-Projects/Seeed_TRMNL_Eink_Project) (ESP32-S3, 7.5" e-ink), fixing the `api/setup` trailing slash incompatibility with self-hosted Terminus.
- **`lilygo-weather-display/`** — Weather display firmware for LilyGo EPD 4.7" devices.

---

## Terminus — Self-Hosted TRMNL Server

### What's patched

Two bugs prevent TRMNL firmware from working with self-hosted Terminus out of the box:

1. **Terminus `app/models/firmware/setup.rb`** — Missing `"status": 200` in the `/api/setup` JSON response. The device firmware checks `doc["status"] == 200` and silently discards the `api_key` if absent, so the device never authenticates.
2. **Firmware `src/api-client/setup.cpp`** — The firmware calls `/api/setup/` (trailing slash), which Terminus returns 404 for. Fixed to `/api/setup`.

The Terminus fix is baked into the custom Docker image. The firmware fix is in `firmware/`.

### Docker image

The patched image is published to GitHub Container Registry on every push to `main`:

```
ghcr.io/pabloazurduy/ws-terminus:latest
```

### Running Terminus

#### Prerequisites
- Docker with Compose V2
- A static local IP or hostname for the machine running Terminus (see [Stable IP](#stable-ip))

#### First-time setup

```bash
cd terminus
bin/setup docker        # generates .env with secrets
```

Edit `.env` and set `API_URI` to the URL the device will use to reach this server:

```
API_URI=http://192.168.1.100:2300   # use your machine's LAN IP or hostname
```

Then start all containers:

```bash
docker compose up --detach
```

Open http://localhost:2300 and create an account.

#### Updating

When re-deploying (e.g. on a NAS), the custom `Dockerfile.custom` is already referenced in `compose.yml` for the `web` and `worker` services. Just run:

```bash
docker compose pull && docker compose up --detach
```

### Deploying on a NAS

1. Copy the `terminus/` directory to the NAS.
2. Edit `terminus/.env` — set `API_URI` to the NAS's IP or hostname, e.g.:
   ```
   API_URI=http://nas.local:2300
   ```
3. Run `docker compose up --detach` from the `terminus/` directory.
4. Reprovision the device (hold green button 5 s → captive portal) with the new server URL.

### Stable IP

The device stores the server URL in flash. If the IP changes, the device won't connect. Options:

- **DHCP reservation** — bind the server machine's MAC address to a fixed IP in your router.
- **mDNS hostname** — use `http://hostname.local:2300` instead of an IP (works on most LANs; NAS systems expose a `.local` hostname by default).

---

## Firmware — Seeed reTerminal E1001

The patched source file and diff are in `firmware/`:

| File | Description |
|------|-------------|
| `firmware/setup.cpp` | Patched `src/api-client/setup.cpp` — removes trailing slash from `/api/setup/` call |
| `firmware/fix-trailing-slash.patch` | Git patch, apply with `git apply` |

### Applying the patch to fresh firmware source

```bash
git clone https://github.com/Seeed-Projects/Seeed_TRMNL_Eink_Project
cd Seeed_TRMNL_Eink_Project
git apply /path/to/firmware/fix-trailing-slash.patch
```

### Building and flashing (macOS/Linux)

```bash
# Build
~/.platformio/penv/bin/pio run -e seeed_reTerminal_E1001

# Flash (device connected via USB)
~/.platformio/penv/bin/pio run -e seeed_reTerminal_E1001 --target upload
```

### Device provisioning

1. Power on the reTerminal — it broadcasts a `TRMNL` WiFi hotspot.
2. Connect to `TRMNL` and open `http://4.3.2.1`.
3. Enter your WiFi SSID/password and Custom Server URL (e.g. `http://192.168.1.100:2300`).
4. Submit — device connects to WiFi, calls `/api/setup`, and starts refreshing.

To force re-provisioning (e.g. after changing server URL), hold the green button for 5 seconds or erase NVS:

```bash
esptool --port /dev/cu.usbserial-110 --baud 115200 erase-region 0x9000 0x5000
```

---

## Weather Dashboard Server

The Python weather dashboard server now lives in `flask-server/`.

### Local configuration

- Copy `flask-server/local_settings.example.py` to `flask-server/local_settings.py` and fill in your local values.
- Copy `arduino/weather_display/secrets.example.h` to `arduino/weather_display/secrets.h` and fill in your local Wi-Fi and server values.
- Both local files are ignored by Git and excluded from the Docker build context.

### Run locally

```bash
cd flask-server
python3 -m unittest test.py
python3 app.py
```

The server listens on port `8080` by default and exposes `/up`, `/refresh`, `/force-refresh-sources`, `/dashboard.png`, and the TRMNL-compatible `/api/setup` and `/api/display` endpoints.

### Run with Docker

```bash
docker build -t weather-dashboard .
docker run -p 8080:8080 \
   -e WEATHER_OWM_KEY=your-openweather-key \
   -e WEATHER_API_KEY=your-device-api-key \
   -e WEATHER_BASE_URL=http://your-host:8080 \
   weather-dashboard
```
