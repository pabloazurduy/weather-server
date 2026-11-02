/**
 * Weather Display for reTerminal E1001 (7.5" B&W UC8179, 800×480)
 *
 * Downloads a pre-rendered 1-bit bitmap from the local weather server and
 * displays it, then deep-sleeps for 15 minutes before repeating.
 *
 * Server endpoint: GET /dashboard.bin
 *   Response: raw packed 1-bit pixels, MSB-first, row-major, 800×480 = 48000 bytes
 *   (1 = white, 0 = black — matches GxEPD2 drawImage convention directly)
 *
 * Libraries (install before compiling):
 *   - GxEPD2      https://github.com/ZinggJM/GxEPD2  (ZIP install)
 *   - Adafruit GFX  (Library Manager)
 *   - Sensirion I2C SHT4x and Sensirion Core  (Library Manager)
 *   - RTClib (PCF8563 clock, Library Manager)
 *
 * Board settings:
 *   Board:        XIAO_ESP32S3
 *   PSRAM:        OPI PSRAM   ← required for 48 KB bitmap buffer
 *   Upload Speed: 115200
 *   Port:         /dev/cu.usbserial-110
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <SensirionI2cSht4x.h>
#include <SPI.h>
#include <GxEPD2_BW.h>
#include <LittleFS.h>
#include <RTClib.h>
#include <esp_sleep.h>
#include <esp_system.h>
#include <esp_partition.h>
#include <driver/rtc_io.h>
#include <sys/time.h>
#include "secrets.h"
#include "entrance_telemetry.h"

// ── Server ──────────────────────────────────────────────────────────────────
#define BIN_PATH      "/dashboard.bin"
#define SLEEP_SEC     900ULL   // 15 minutes
// Cached source fallback can take ~20 seconds while the NAS is offline.
#define HTTP_READ_TIMEOUT_MS 45000
#define PIPECAR_PORT 9471
#define PIPECAR_PATH "/api/r/api/v1/sensor/entrance"
#define PIPECAR_CONNECT_TIMEOUT_MS 2500
#define PIPECAR_READ_TIMEOUT_MS 4500
#define MAX_SENSOR_REPLAY_PER_WAKE 4
#define MAX_SENSOR_PENDING 512

// ── Pin Definitions ──────────────────────────────────────────────────────────
#define EPD_SCK_PIN   7
#define EPD_MOSI_PIN  9
#define EPD_CS_PIN    10
#define EPD_DC_PIN    11
#define EPD_RES_PIN   12
#define EPD_BUSY_PIN  13

#define SD_EN_PIN     16
#define SD_CS_PIN     14

#define BAT_EN_PIN    21
#define BAT_ADC_PIN   1    // GPIO1 - Battery voltage ADC (via 1:2 divider)

#define BUTTON_KEY0   3    // Right / green button (active-low)
#define BUTTON_KEY1   4    // Middle button (active-low)
#define BUTTON_KEY2   5    // Left button (active-low)
#define BUTTON_WAKE_MASK ((1ULL << BUTTON_KEY0) | \
                          (1ULL << BUTTON_KEY1) | \
                          (1ULL << BUTTON_KEY2))

#define I2C_SDA       19   // SHT40 data
#define I2C_SCL       20   // SHT40 clock

#define SERIAL_RX     44
#define SERIAL_TX     43

// ── GxEPD2 Setup ─────────────────────────────────────────────────────────────
#define MAX_DISPLAY_BUFFER_SIZE 65536ul
#define MAX_HEIGHT(EPD) (EPD::HEIGHT <= MAX_DISPLAY_BUFFER_SIZE / (EPD::WIDTH / 8) \
                         ? EPD::HEIGHT : MAX_DISPLAY_BUFFER_SIZE / (EPD::WIDTH / 8))

SPIClass hspi(HSPI);
GxEPD2_BW<GxEPD2_750_GDEY075T7, MAX_HEIGHT(GxEPD2_750_GDEY075T7)>
    display(GxEPD2_750_GDEY075T7(EPD_CS_PIN, EPD_DC_PIN, EPD_RES_PIN, EPD_BUSY_PIN));

// ── Constants ─────────────────────────────────────────────────────────────────
static const uint32_t BITMAP_BYTES = 800UL * 480UL / 8UL;  // 48000
static const char* CACHE_PATH = "/weather-forecast.bin";
static const char* CACHE_TEMP_PATH = "/weather-forecast.tmp";
static const uint32_t CACHE_MAGIC = 0x57444331;  // weather display cache v1

struct ForecastCacheHeader {
  uint32_t magic;
  uint32_t bytes;
  uint32_t checksum;
};

static bool cache_ready = false;
RTC_PCF8563 rtc;
static bool rtc_ready = false;

enum StatusScreen : uint8_t {
  STATUS_DASHBOARD = 0,
  STATUS_NETWORK_ERROR,
};

// Redraw the offline badge once per outage. The bitmap itself lives in flash,
// because ordinary RAM and PSRAM do not survive deep sleep.
RTC_DATA_ATTR static uint8_t shown_status = STATUS_DASHBOARD;
RTC_DATA_ATTR static uint32_t displayed_checksum = 0;

// ── Persistent last forecast ─────────────────────────────────────────────────
uint32_t bitmapChecksum(const uint8_t* bitmap) {
  uint32_t checksum = 2166136261UL;  // FNV-1a, for corruption detection
  for (uint32_t i = 0; i < BITMAP_BYTES; ++i) {
    checksum = (checksum ^ bitmap[i]) * 16777619UL;
  }
  return checksum;
}

bool initForecastCache() {
  if (LittleFS.begin(false)) return true;

  // Initialize only a completely unused filesystem partition. Never format
  // existing or corrupt user data merely because mounting failed.
  const esp_partition_t* partition = esp_partition_find_first(
      ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_SPIFFS, "spiffs");
  if (!partition) {
    Serial1.println("[cache] No filesystem partition; retaining panel on failure");
    return false;
  }
  uint8_t block[512];
  for (size_t offset = 0; offset < partition->size; offset += sizeof(block)) {
    size_t count = min(sizeof(block), partition->size - offset);
    if (esp_partition_read(partition, offset, block, count) != ESP_OK) return false;
    for (size_t i = 0; i < count; ++i) {
      if (block[i] != 0xFF) {
        Serial1.println("[cache] Existing filesystem unavailable; leaving it untouched");
        return false;
      }
    }
    yield();
  }
  Serial1.println("[cache] Initializing unused filesystem partition");
  return LittleFS.format() && LittleFS.begin(false);
}

bool saveCachedBitmap(const uint8_t* bitmap) {
  if (!cache_ready) return false;
  ForecastCacheHeader header = {CACHE_MAGIC, BITMAP_BYTES, bitmapChecksum(bitmap)};
  File file = LittleFS.open(CACHE_TEMP_PATH, FILE_WRITE);
  if (!file) return false;
  bool complete = file.write(reinterpret_cast<const uint8_t*>(&header), sizeof(header))
                      == sizeof(header)
                  && file.write(bitmap, BITMAP_BYTES) == BITMAP_BYTES;
  file.flush();
  file.close();
  // Atomic replacement leaves the previous cache intact if writing is interrupted.
  if (!complete || !LittleFS.rename(CACHE_TEMP_PATH, CACHE_PATH)) {
    LittleFS.remove(CACHE_TEMP_PATH);
    Serial1.println("[cache] Save failed; previous cache retained");
    return false;
  }
  Serial1.printf("[cache] Saved %u bytes, checksum=%08x\n", BITMAP_BYTES, header.checksum);
  return true;
}

bool loadCachedBitmap(uint8_t* bitmap) {
  if (!cache_ready || !LittleFS.exists(CACHE_PATH)) return false;
  File file = LittleFS.open(CACHE_PATH, FILE_READ);
  if (!file || file.size() != sizeof(ForecastCacheHeader) + BITMAP_BYTES) return false;
  ForecastCacheHeader header;
  if (file.read(reinterpret_cast<uint8_t*>(&header), sizeof(header)) != sizeof(header)
      || header.magic != CACHE_MAGIC || header.bytes != BITMAP_BYTES
      || file.read(bitmap, BITMAP_BYTES) != BITMAP_BYTES) return false;
  if (bitmapChecksum(bitmap) != header.checksum) {
    Serial1.println("[cache] Checksum mismatch; retaining panel image");
    return false;
  }
  // If saving the most recent displayed image failed, do not replace it with
  // an older cached forecast on the next wake.
  if (displayed_checksum != 0 && displayed_checksum != header.checksum) {
    Serial1.println("[cache] Older than displayed image; retaining panel image");
    return false;
  }
  Serial1.printf("[cache] Restored %u bytes, checksum=%08x\n", BITMAP_BYTES, header.checksum);
  return true;
}

// ── Battery ───────────────────────────────────────────────────────────────────
float readBattery() {
  pinMode(BAT_EN_PIN, OUTPUT);
  digitalWrite(BAT_EN_PIN, HIGH);       // enable battery monitoring circuit
  analogReadResolution(12);
  analogSetPinAttenuation(BAT_ADC_PIN, ADC_11db);  // full 0-3.3V range
  delay(100);                            // let circuit stabilize (wiki: 100ms)
  // Average 8 readings for stability
  uint32_t sum = 0;
  for (int i = 0; i < 8; i++) {
    sum += analogReadMilliVolts(BAT_ADC_PIN);
    delay(5);
  }
  float mv = sum / 8.0f;
  float v = (mv / 1000.0f) * 2.0f;     // x2 for voltage divider
  digitalWrite(BAT_EN_PIN, LOW);
  return v;
}

// ── Display helpers ───────────────────────────────────────────────────────────
void initDisplay() {
  hspi.begin(EPD_SCK_PIN, /*MISO*/ -1, EPD_MOSI_PIN, /*SS*/ -1);
  display.epd2.selectSPI(hspi, SPISettings(4000000, MSBFIRST, SPI_MODE0));
  display.init(0, true);
}

void drawOfflineBitmap(const uint8_t* bitmap) {
  display.setRotation(0);
  display.setFullWindow();
  display.firstPage();
  do {
    // Adafruit's bitmap API maps set bits to the foreground. Our server's set
    // bits mean white, so use white foreground and black background.
    display.drawBitmap(0, 0, bitmap, 800, 480, GxEPD_WHITE, GxEPD_BLACK);
    // Only cover the footer URL, leaving all forecast data and its date visible.
    display.fillRect(640, 456, 144, 16, GxEPD_WHITE);
    display.drawRect(640, 456, 144, 16, GxEPD_BLACK);
    display.setFont(nullptr);
    display.setTextSize(1);
    display.setTextColor(GxEPD_BLACK);
    display.setCursor(650, 460);
    display.print("Connection lost");
  } while (display.nextPage());
}

void showConnectionLost(uint8_t* bitmap) {
  if (shown_status == STATUS_NETWORK_ERROR) {
    Serial1.println("[offline] Forecast and warning already visible");
    return;
  }
  if (!loadCachedBitmap(bitmap)) {
    // Without a safe copy, touching the controller could erase its last image.
    Serial1.println("[offline] No matching cache; keeping existing panel unchanged");
    return;
  }
  initDisplay();
  drawOfflineBitmap(bitmap);
  display.hibernate();
  shown_status = STATUS_NETWORK_ERROR;
  Serial1.println("[offline] Last forecast retained with connection warning");
}

void drawBitmap(const uint8_t* bitmap) {
  display.setRotation(0);
  // drawImage() = writeImage() + refresh() in one call.
  // Do NOT use firstPage()/nextPage() here — that loop writes the internal
  // GxEPD2 buffer (blank white) and triggers a SECOND refresh, which is
  // exactly what was wiping the screen after the image appeared.
  display.drawImage(bitmap, 0, 0, 800, 480,
                    /*invert*/ false, /*mirror_y*/ false, /*pgm*/ false);
}

// ── SHT40 on-board sensor ────────────────────────────────────────────────────
// Requires: "Sensirion I2C SHT4x" library (Library Manager)
bool readSHT40(float& temp, float& hum) {
  SensirionI2cSht4x sht40;
  sht40.begin(Wire, 0x44);
  uint16_t err = sht40.measureHighPrecision(temp, hum);
  if (err) {
    Serial1.printf("SHT40 error: %u\n", err);
    return false;
  }
  Serial1.printf("SHT40: %.1f°C  %.0f%%\n", temp, hum);
  return true;
}

// The PCF8563 keeps UTC across deep sleep. NTP sets it on first network setup;
// a valid RTC can timestamp measurements even if the external time service fails.
bool prepareClock(bool network_available) {
  static bool wire_started = false;
  if (!wire_started) {
    Wire.begin(I2C_SDA, I2C_SCL);
    rtc_ready = rtc.begin(&Wire);
    wire_started = true;
    if (rtc_ready && !rtc.lostPower()) {
      DateTime current = rtc.now();
      if (current.year() >= 2024 && current.year() < 2100) {
        struct timeval value = {static_cast<time_t>(current.unixtime()), 0};
        settimeofday(&value, nullptr);
      }
    }
  }

  if (network_available) {
    configTime(0, 0, "pool.ntp.org", "time.google.com");
    uint32_t started = millis();
    while (time(nullptr) < 1704067200 && millis() - started < 4000) delay(100);
  }
  time_t now = time(nullptr);
  if (now < 1704067200) {
    Serial1.println("[clock] No valid UTC time yet");
    return false;
  }
  if (network_available && rtc_ready &&
      (rtc.lostPower() || abs(static_cast<long>(rtc.now().unixtime() - now)) > 3)) {
    rtc.adjust(DateTime(now));
  }
  return true;
}

bool sendPipeCarPayload(const char* payload) {
  char url[128];
  snprintf(url, sizeof(url), "http://%s:%d%s", SERVER_HOST, PIPECAR_PORT,
           PIPECAR_PATH);
  WiFiClient client;
  HTTPClient http;
  http.setConnectTimeout(PIPECAR_CONNECT_TIMEOUT_MS);
  http.setTimeout(PIPECAR_READ_TIMEOUT_MS);
  if (!http.begin(client, url)) return false;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Bearer ") + PIPECAR_INGEST_TOKEN);
  const int code = http.POST(String(payload));
  http.end();
  Serial1.printf("[pipecar] POST: %d\n", code);
  return code >= 200 && code < 300;
}

struct SensorOutbox {
  size_t count() {
    File root = LittleFS.open("/");
    if (!root) return 0;
    size_t result = 0;
    File file = root.openNextFile();
    while (file) {
      String name = file.name();
      if (!name.startsWith("/")) name = "/" + name;
      if (name.startsWith("/ent-") && name.endsWith(".json")) ++result;
      file = root.openNextFile();
    }
    return result;
  }

  bool enqueue(const char* path, const char* payload) {
    if (!cache_ready || count() >= MAX_SENSOR_PENDING) return false;
    const char* temp_path = "/ent-pending.tmp";
    LittleFS.remove(temp_path);
    File file = LittleFS.open(temp_path, FILE_WRITE);
    if (!file) return false;
    const size_t length = strlen(payload);
    const bool complete = file.write(reinterpret_cast<const uint8_t*>(payload), length) == length;
    file.flush();
    file.close();
    if (!complete || !LittleFS.rename(temp_path, path)) {
      LittleFS.remove(temp_path);
      return false;
    }
    return true;
  }

  bool peek(char* path, size_t path_capacity, char* payload,
            size_t payload_capacity) {
    File root = LittleFS.open("/");
    if (!root) return false;
    String oldest;
    File file = root.openNextFile();
    while (file) {
      String name = file.name();
      if (!name.startsWith("/")) name = "/" + name;
      if (name.startsWith("/ent-") && name.endsWith(".json") &&
          (oldest.isEmpty() || name.compareTo(oldest) < 0)) oldest = name;
      file = root.openNextFile();
    }
    if (oldest.isEmpty() || oldest.length() >= path_capacity) return false;
    File pending = LittleFS.open(oldest, FILE_READ);
    if (!pending || pending.size() == 0 || pending.size() >= payload_capacity) return false;
    strcpy(path, oldest.c_str());
    const size_t length = pending.readBytes(payload, pending.size());
    payload[length] = '\0';
    return length == pending.size();
  }

  bool erase(const char* path) { return LittleFS.remove(path); }
};

struct EntranceMeasurement {
  bool measured = false;
  bool encoded = false;
  bool queued = false;
  float temp = 0;
  float humidity = 0;
  float battery_voltage = 0;
  float chip_temp = 0;
  uint32_t sampled_millis = 0;
  char reading_id[17] = {};
  char weather_payload[entrance_telemetry::PAYLOAD_BYTES] = {};
  char pipecar_payload[entrance_telemetry::PAYLOAD_BYTES] = {};
};

void encodeEntranceReading(EntranceMeasurement& measurement, time_t epoch) {
  if (!measurement.measured || measurement.encoded || epoch < 1704067200) return;
  entrance_telemetry::Reading reading = {
      measurement.reading_id, epoch, measurement.temp, measurement.humidity,
      measurement.battery_voltage, measurement.chip_temp, true,
      WiFi.RSSI(), WiFi.status() == WL_CONNECTED};
  measurement.encoded =
      entrance_telemetry::encode(reading, true, measurement.weather_payload,
                                 sizeof(measurement.weather_payload)) &&
      entrance_telemetry::encode(reading, false, measurement.pipecar_payload,
                                 sizeof(measurement.pipecar_payload));
  if (!measurement.encoded) {
    Serial1.println("[sensor] Invalid reading; not forwarding");
    return;
  }
  char path[72];
  snprintf(path, sizeof(path), "/ent-%010llu-%s.json",
           static_cast<unsigned long long>(epoch), measurement.reading_id);
  SensorOutbox outbox;
  measurement.queued = outbox.enqueue(path, measurement.pipecar_payload);
  if (!measurement.queued) {
    Serial1.println("[pipecar] Outbox unavailable/full; attempting direct delivery");
  }
}

// Keep the legacy keys that drive the weather dashboard, while adding the
// stable reading ID and original UTC timestamp to its SQLite history.
void pushSensorData(const char* payload) {
  char url[64];
  snprintf(url, sizeof(url), "http://%s:%d/sensor", SERVER_HOST, SERVER_PORT);
  HTTPClient http;
  http.begin(url);
  http.setTimeout(HTTP_READ_TIMEOUT_MS);
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(payload);
  if (code < 0) {
    Serial1.printf("POST /sensor: %d (%s)\n", code,
                   HTTPClient::errorToString(code).c_str());
  } else {
    Serial1.printf("POST /sensor: %d\n", code);
  }
  http.end();
}

// ── WiFi ──────────────────────────────────────────────────────────────────────
bool connectWiFi(uint32_t timeout_ms = 15000) {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial1.printf("Connecting to %s", WIFI_SSID);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - start > timeout_ms) {
      Serial1.println(" TIMEOUT");
      return false;
    }
    delay(250);
    Serial1.print('.');
  }
  Serial1.printf(" OK  IP=%s  RSSI=%d dB\n",
                 WiFi.localIP().toString().c_str(), WiFi.RSSI());
  return true;
}

// ── Server refresh trigger ──────────────────────────────────────────────────
void triggerRefresh() {
  char url[64];
  snprintf(url, sizeof(url), "http://%s:%d/refresh", SERVER_HOST, SERVER_PORT);
  Serial1.printf("Triggering server refresh: %s\n", url);
  HTTPClient http;
  http.begin(url);
  http.setTimeout(HTTP_READ_TIMEOUT_MS);
  int code = http.GET();
  if (code < 0) {
    Serial1.printf("Refresh response: %d (%s)\n", code,
                   HTTPClient::errorToString(code).c_str());
  } else {
    Serial1.printf("Refresh response: %d\n", code);
  }
  http.end();
}

// ── Download bitmap ───────────────────────────────────────────────────────────
bool downloadBitmap(uint8_t* buf, float batt_v) {
  char url[128];
  snprintf(url, sizeof(url),
           "http://%s:%d%s?battery_voltage=%.2f",
           SERVER_HOST, SERVER_PORT, BIN_PATH, batt_v);
  Serial1.printf("GET %s\n", url);

  HTTPClient http;
  http.begin(url);
  http.setTimeout(HTTP_READ_TIMEOUT_MS);
  int code = http.GET();

  if (code != HTTP_CODE_OK) {
    Serial1.printf("HTTP error: %d (%s)\n", code,
                   HTTPClient::errorToString(code).c_str());
    http.end();
    return false;
  }

  int contentLen = http.getSize();
  Serial1.printf("Content-Length: %d (expected %u)\n", contentLen, BITMAP_BYTES);
  if (contentLen != static_cast<int>(BITMAP_BYTES)) {
    Serial1.println("Unexpected bitmap size — keeping last forecast");
    http.end();
    return false;
  }

  WiFiClient* stream = http.getStreamPtr();

  uint32_t received = 0;
  uint32_t deadline = millis() + 15000;
  while (received < BITMAP_BYTES && millis() < deadline) {
    int avail = stream->available();
    if (avail > 0) {
      int chunk = stream->readBytes(buf + received,
                                    min((uint32_t)avail, BITMAP_BYTES - received));
      received += chunk;
    } else {
      delay(1);
    }
  }

  http.end();

  if (received < BITMAP_BYTES) {
    Serial1.printf("Short read: %u / %u bytes\n", received, BITMAP_BYTES);
    return false;
  }

  Serial1.printf("Downloaded %u bytes OK\n", received);
  return true;
}

// ── Main ──────────────────────────────────────────────────────────────────────
void setup() {
  Serial1.begin(115200, SERIAL_8N1, SERIAL_RX, SERIAL_TX);
  delay(300);
  Serial1.println("\n=== Weather Display boot ===");

  const esp_sleep_wakeup_cause_t wake_cause = esp_sleep_get_wakeup_cause();
  const bool button_wakeup = wake_cause == ESP_SLEEP_WAKEUP_EXT1;
  if (button_wakeup) {
    Serial1.printf("Button wakeup mask: 0x%llx\n",
                   esp_sleep_get_ext1_wakeup_status());
  }

  // All three buttons can wake the board. RTC pull-ups are configured again
  // immediately before sleep because ordinary GPIO pulls turn off in deep sleep.
  pinMode(BUTTON_KEY0, INPUT_PULLUP);
  pinMode(BUTTON_KEY1, INPUT_PULLUP);
  pinMode(BUTTON_KEY2, INPUT_PULLUP);

  // Deselect SD card early — must happen before any SPI activity
  pinMode(SD_CS_PIN, OUTPUT);  digitalWrite(SD_CS_PIN, HIGH);
  pinMode(SD_EN_PIN, OUTPUT);  digitalWrite(SD_EN_PIN, HIGH);

  // Battery reading
  float batt_v = readBattery();
  Serial1.printf("Battery: %.2f V\n", batt_v);

  uint8_t* bitmap = nullptr;
  EntranceMeasurement measurement;
  bool clock_ready = false;

  // Allocate bitmap buffer in PSRAM
  bitmap = (uint8_t*) ps_malloc(BITMAP_BYTES);
  if (!bitmap) {
    Serial1.println("ps_malloc failed — falling back to heap");
    bitmap = (uint8_t*) malloc(BITMAP_BYTES);
  }
  if (!bitmap) {
    Serial1.println("RAM alloc failed — sleeping");
    goto sleep;
  }

  cache_ready = initForecastCache();

  // Capture the physical reading before Wi-Fi. A valid PCF8563 clock lets us
  // commit it to LittleFS even when the network is down for the whole wake.
  clock_ready = prepareClock(false);
  measurement.battery_voltage = batt_v;
  measurement.measured = readSHT40(measurement.temp, measurement.humidity);
  if (measurement.measured) {
    measurement.sampled_millis = millis();
    measurement.chip_temp = temperatureRead();
    snprintf(measurement.reading_id, sizeof(measurement.reading_id),
             "%08x%08x", esp_random(), esp_random());
    if (clock_ready) encodeEntranceReading(measurement, time(nullptr));
  }

  // Connect WiFi and download BEFORE touching the display.
  // UC8179 must not sit in Power-On state for 15+ seconds waiting for data —
  // it will auto-reset and produce a "flash then clear" failure pattern.
  if (!connectWiFi()) {
    Serial1.println("WiFi failed — sleeping");
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    showConnectionLost(bitmap);
    free(bitmap);
    goto sleep;
  }

  // NTP supplies the missing time on a first boot without a valid RTC. The
  // elapsed monotonic time brings the timestamp back to the sample instant.
  if (measurement.measured && !measurement.encoded && prepareClock(true)) {
    const time_t sampled_epoch =
        time(nullptr) - (millis() - measurement.sampled_millis) / 1000;
    encodeEntranceReading(measurement, sampled_epoch);
  }

  // Both destinations receive the same physical reading and timestamp. The
  // PipeCar copy was queued before any HTTP request when time was available.
  {
    SensorOutbox outbox;
    if (measurement.measured) {
      if (measurement.encoded) {
        pushSensorData(measurement.weather_payload);
        if (!measurement.queued) sendPipeCarPayload(measurement.pipecar_payload);
      } else {
        char legacy_payload[128];
        snprintf(legacy_payload, sizeof(legacy_payload),
                 "{\"temp\":%.2f,\"humidity\":%.2f,\"battery_voltage\":%.3f}",
                 measurement.temp, measurement.humidity, batt_v);
        pushSensorData(legacy_payload);
      }
    }
    if (cache_ready) {
      auto sender = [](const char* payload) { return sendPipeCarPayload(payload); };
      const size_t delivered = entrance_telemetry::deliverPending(
          outbox, sender, MAX_SENSOR_REPLAY_PER_WAKE);
      Serial1.printf("[pipecar] Delivered %u pending; %u remain\n",
                     static_cast<unsigned>(delivered),
                     static_cast<unsigned>(outbox.count()));
    }
  }

  // If woken by any top button, ask the server to regenerate with fresh
  // weather data (sensor data was already pushed above).
  if (button_wakeup) {
    Serial1.println("Button wakeup — requesting server refresh");
    triggerRefresh();
  }

  if (!downloadBitmap(bitmap, batt_v)) {
    Serial1.println("Download failed — sleeping");
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    showConnectionLost(bitmap);
    free(bitmap);
    goto sleep;
  }

  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);

  // Store the clean bitmap before adding any local status overlay. This copy
  // survives deep sleep, reboots, and an interruption while the next file is saved.
  saveCachedBitmap(bitmap);

  // Init display NOW — immediately before drawing so the Power-On
  // high-voltage state lasts only the few seconds needed for the refresh.
  initDisplay();

  drawBitmap(bitmap);
  Serial1.println("Display updated.");
  shown_status = STATUS_DASHBOARD;
  displayed_checksum = bitmapChecksum(bitmap);

  free(bitmap);
  display.hibernate();

sleep:
  Serial1.printf("Sleeping %llu s...\n", SLEEP_SEC);
  Serial1.flush();
  // Wake on timer or any of the three active-low buttons. Normal GPIO pull-ups
  // are disabled during deep sleep, so keep these pins biased in the RTC domain.
  esp_sleep_enable_timer_wakeup(SLEEP_SEC * 1000000ULL);
  esp_sleep_enable_ext1_wakeup(BUTTON_WAKE_MASK, ESP_EXT1_WAKEUP_ANY_LOW);
  rtc_gpio_pullup_en((gpio_num_t)BUTTON_KEY0);
  rtc_gpio_pulldown_dis((gpio_num_t)BUTTON_KEY0);
  rtc_gpio_pullup_en((gpio_num_t)BUTTON_KEY1);
  rtc_gpio_pulldown_dis((gpio_num_t)BUTTON_KEY1);
  rtc_gpio_pullup_en((gpio_num_t)BUTTON_KEY2);
  rtc_gpio_pulldown_dis((gpio_num_t)BUTTON_KEY2);
  esp_deep_sleep_start();
}

void loop() {}
