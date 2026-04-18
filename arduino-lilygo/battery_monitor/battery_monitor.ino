/**
 * Battery Monitor for LilyGO T5 4.7" e-paper (T5-ePaper-S3 / ESP32-S3)
 *
 * - Reads battery voltage every 1 second, prints to USB Serial
 * - Updates e-ink display every 5 minutes with voltage, %, and charging status
 *
 * Requires: "LilyGo EPD47" library (Library Manager → search "LilyGo EPD47" → Install All)
 *
 * Board settings (Arduino IDE) — must use ESP32 core 2.0.5–2.0.15 (NOT 3.x):
 *   Board              : ESP32S3 Dev Module
 *   USB CDC On Boot    : Enable          ← required for Serial over USB
 *   CPU Frequency      : 240MHz (WiFi)
 *   Flash Mode         : QIO 80MHz
 *   Flash Size         : 16MB (128Mb)
 *   Partition Scheme   : 16M Flash(3M APP/9.9MB FATFS)
 *   PSRAM              : OPI PSRAM       ← required for display framebuffer
 *   Upload Mode        : UART0/Hardware CDC
 *   USB Mode           : CDC and JTAG
 */

#ifndef BOARD_HAS_PSRAM
#error "PSRAM must be enabled: Arduino IDE → Tools → PSRAM → OPI PSRAM"
#endif

#include <Arduino.h>
#include "epd_driver.h"
#include "firasans.h"
#include "esp_adc_cal.h"

#define BATT_PIN       14                         // GPIO14, 1:2 voltage divider
#define DISPLAY_PERIOD (5UL * 60UL * 1000UL)     // update display every 5 minutes
#define HIST_SIZE      60                         // 60s of history for charge detection

static int      vref      = 1100;
static uint8_t *fb        = NULL;   // display framebuffer in PSRAM

// Ring buffer — one voltage sample per second
static float voltHist[HIST_SIZE];
static int   histIdx   = 0;
static int   histCount = 0;

// ─── Battery ─────────────────────────────────────────────────────────────────

float readBattery() {
  epd_poweron();
  delay(10);
  uint32_t sum = 0;
  for (int i = 0; i < 8; i++) { sum += analogRead(BATT_PIN); delay(5); }
  epd_poweroff_all();
  float v = ((sum / 8.0f) / 4095.0f) * 2.0f * 3.3f * (vref / 1000.0f);
  return min(v, 4.2f);
}

// Returns: 1 = charging, 0 = discharging, -1 = unknown (< 30s of data)
int chargingStatus() {
  if (histCount < 30) return -1;
  float oldSum = 0, newSum = 0;
  for (int i = 0; i < 10; i++) {
    oldSum += voltHist[(histIdx - histCount + i + HIST_SIZE) % HIST_SIZE];
    newSum += voltHist[(histIdx - 1 - i      + HIST_SIZE) % HIST_SIZE];
  }
  float delta = (newSum - oldSum) / 10.0f;
  if (delta >  0.005f) return 1;
  if (delta < -0.005f) return 0;
  return -1;  // voltage stable — could be fully charged on USB
}

// ─── Display ─────────────────────────────────────────────────────────────────

void updateDisplay(float v, int pct, int charging) {
  if (!fb) return;

  memset(fb, 0xFF, EPD_WIDTH * EPD_HEIGHT / 2);  // fill white

  char line[64];
  int32_t cx, cy;

  cx = 80; cy = 160;
  snprintf(line, sizeof(line), "Voltage:  %.3f V", v);
  writeln((GFXfont*)&FiraSans, line, &cx, &cy, fb);

  cx = 80; cy = 280;
  snprintf(line, sizeof(line), "Charge:   %d %%", pct);
  writeln((GFXfont*)&FiraSans, line, &cx, &cy, fb);

  cx = 80; cy = 400;
  if      (charging == 1) snprintf(line, sizeof(line), "Status:   CHARGING");
  else if (charging == 0) snprintf(line, sizeof(line), "Status:   ON BATTERY");
  else                    snprintf(line, sizeof(line), "Status:   DETECTING...");
  writeln((GFXfont*)&FiraSans, line, &cx, &cy, fb);

  cx = 80; cy = 500;
  snprintf(line, sizeof(line), "Uptime:   %lu min", millis() / 60000UL);
  writeln((GFXfont*)&FiraSans, line, &cx, &cy, fb);

  epd_poweron();
  epd_clear();
  epd_draw_grayscale_image(epd_full_screen(), fb);
  epd_poweroff_all();
}

// ─── Main ────────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  delay(1500);

  esp_adc_cal_characteristics_t adc_chars;
  if (esp_adc_cal_characterize(ADC_UNIT_2, ADC_ATTEN_DB_11,
                               ADC_WIDTH_BIT_12, 1100, &adc_chars)
      == ESP_ADC_CAL_VAL_EFUSE_VREF) {
    vref = adc_chars.vref;
  }

  fb = (uint8_t*)ps_calloc(EPD_WIDTH * EPD_HEIGHT / 2, sizeof(uint8_t));
  if (!fb) Serial.println("[WARN] PSRAM alloc failed — display disabled");

  epd_init();
  memset(voltHist, 0, sizeof(voltHist));

  Serial.println("=== LilyGO T5 Battery Monitor ===");
  Serial.printf("ADC vref: %d mV | Serial: 1s | Display: 5min\n\n", vref);
}

void loop() {
  static uint32_t lastDisplay = 0;

  float v   = readBattery();
  int   pct = constrain((int)((v - 3.3f) / 0.9f * 100.0f), 0, 100);

  voltHist[histIdx] = v;
  histIdx = (histIdx + 1) % HIST_SIZE;
  if (histCount < HIST_SIZE) histCount++;

  int charge = chargingStatus();
  const char* chStr = (charge == 1) ? "CHARGING" :
                      (charge == 0) ? "ON BATTERY" : "---";
  Serial.printf("Battery: %.3f V  |  ~%d%%  |  %s\n", v, pct, chStr);

  if (millis() - lastDisplay >= DISPLAY_PERIOD || lastDisplay == 0) {
    lastDisplay = millis();
    Serial.println("[Updating display...]");
    updateDisplay(v, pct, charge);
    Serial.println("[Display updated]");
  }

  delay(1000);
}
