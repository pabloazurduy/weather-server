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
#include <Fonts/FreeMonoBold9pt7b.h>
#include "secrets.h"

// ── Server ──────────────────────────────────────────────────────────────────
#define BIN_PATH      "/dashboard.bin"
#define SLEEP_SEC     900ULL   // 15 minutes

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

#define BUTTON_KEY0   3    // Green button (active-low) — used for manual refresh

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

void showError(const char* msg) {
  Serial1.printf("[ERROR] %s\n", msg);
  display.setRotation(0);
  display.setFullWindow();
  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);
    display.setFont(&FreeMonoBold9pt7b);
    display.setTextColor(GxEPD_BLACK);
    display.setCursor(20, 40);
    display.print("Weather Display Error:");
    display.setCursor(20, 70);
    display.print(msg);
    display.setCursor(20, 100);
    display.printf("Retry in %llu min", SLEEP_SEC / 60);
  } while (display.nextPage());
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
  Wire.begin(I2C_SDA, I2C_SCL);
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

// ── Push sensor data to server ────────────────────────────────────────────────
void pushSensorData(float temp, float hum, float batt_v) {
  char url[64];
  snprintf(url, sizeof(url), "http://%s:%d/sensor", SERVER_HOST, SERVER_PORT);
  char body[96];
  snprintf(body, sizeof(body),
           "{\"temp\":%.2f,\"humidity\":%.1f,\"battery_voltage\":%.3f}",
           temp, hum, batt_v);
  HTTPClient http;
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(body);
  Serial1.printf("POST /sensor: %d\n", code);
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
  http.setTimeout(10000);
  int code = http.GET();
  Serial1.printf("Refresh response: %d\n", code);
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
  http.setTimeout(10000);
  int code = http.GET();

  if (code != HTTP_CODE_OK) {
    Serial1.printf("HTTP error: %d\n", code);
    http.end();
    return false;
  }

  int contentLen = http.getSize();
  Serial1.printf("Content-Length: %d (expected %lu)\n", contentLen, BITMAP_BYTES);

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
    Serial1.printf("Short read: %lu / %lu bytes\n", received, BITMAP_BYTES);
    return false;
  }

  Serial1.printf("Downloaded %lu bytes OK\n", received);
  return true;
}

// ── Main ──────────────────────────────────────────────────────────────────────
void setup() {
  Serial1.begin(115200, SERIAL_8N1, SERIAL_RX, SERIAL_TX);
  delay(300);
  Serial1.println("\n=== Weather Display boot ===");

  // Deselect SD card early — must happen before any SPI activity
  pinMode(SD_CS_PIN, OUTPUT);  digitalWrite(SD_CS_PIN, HIGH);
  pinMode(SD_EN_PIN, OUTPUT);  digitalWrite(SD_EN_PIN, HIGH);

  // Battery reading
  float batt_v = readBattery();
  Serial1.printf("Battery: %.2f V\n", batt_v);

  // Allocate bitmap buffer in PSRAM
  uint8_t* bitmap = (uint8_t*) ps_malloc(BITMAP_BYTES);
  if (!bitmap) {
    Serial1.println("ps_malloc failed — falling back to heap");
    bitmap = (uint8_t*) malloc(BITMAP_BYTES);
  }
  if (!bitmap) {
    Serial1.println("RAM alloc failed — sleeping");
    goto sleep;
  }

  // Connect WiFi and download BEFORE touching the display.
  // UC8179 must not sit in Power-On state for 15+ seconds waiting for data —
  // it will auto-reset and produce a "flash then clear" failure pattern.
  if (!connectWiFi()) {
    Serial1.println("WiFi failed — sleeping");
    free(bitmap);
    goto sleep;
  }

  // Read SHT40 and push to server (always — this also invalidates the cache).
  // Do this BEFORE /refresh so the new image is built with fresh sensor data.
  {
    float sht_temp, sht_hum;
    if (readSHT40(sht_temp, sht_hum)) {
      pushSensorData(sht_temp, sht_hum, batt_v);
    }
  }

  // If woken by the green button, ask the server to regenerate with fresh
  // weather data (sensor data was already pushed above).
  if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0) {
    Serial1.println("Button wakeup — requesting server refresh");
    triggerRefresh();
  }

  if (!downloadBitmap(bitmap, batt_v)) {
    Serial1.println("Download failed — sleeping");
    free(bitmap);
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    goto sleep;
  }

  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);

  // Init display NOW — immediately before drawing so the Power-On
  // high-voltage state lasts only the few seconds needed for the refresh.
  initDisplay();

  drawBitmap(bitmap);
  Serial1.println("Display updated.");

  free(bitmap);
  display.hibernate();

sleep:
  Serial1.printf("Sleeping %llu s...\n", SLEEP_SEC);
  Serial1.flush();
  // Wake on timer OR green button press (GPIO3, active-low)
  esp_sleep_enable_timer_wakeup(SLEEP_SEC * 1000000ULL);
  esp_sleep_enable_ext0_wakeup((gpio_num_t)BUTTON_KEY0, 0);  // 0 = wake on LOW
  esp_deep_sleep_start();
}

void loop() {}
