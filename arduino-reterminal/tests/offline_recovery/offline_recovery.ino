/**
 * Hardware regression test for forecast retention on the reTerminal E1001.
 * Uses the production secrets.h. Flash the production sketch again afterwards.
 * This test disconnects only the display's Wi-Fi; it does not interrupt the NAS.
 */
#define setup weatherProductionSetup
#define loop weatherProductionLoop
#include "../../weather_display/weather_display.ino"
#undef setup
#undef loop

RTC_DATA_ATTR static uint8_t test_stage = 0;
RTC_DATA_ATTR static uint32_t expected_checksum = 0;

void verify(bool passed, const char* message) {
  Serial1.printf("[test] %s: %s\n", passed ? "PASS" : "FAIL", message);
  Serial1.flush();
  if (!passed) {
    while (true) delay(1000);
  }
}

void nextTestStage() {
  ++test_stage;
  Serial1.println("[test] Deep sleep for 5 seconds");
  Serial1.flush();
  esp_sleep_enable_timer_wakeup(5000000ULL);
  esp_deep_sleep_start();
}

void setup() {
  Serial1.begin(115200, SERIAL_8N1, SERIAL_RX, SERIAL_TX);
  delay(1000);
  Serial1.printf("\n[test] Offline recovery stage %u\n", test_stage);
  pinMode(SD_CS_PIN, OUTPUT);
  digitalWrite(SD_CS_PIN, HIGH);
  pinMode(SD_EN_PIN, OUTPUT);
  digitalWrite(SD_EN_PIN, HIGH);
  cache_ready = initForecastCache();
  verify(cache_ready, "persistent forecast storage available");
  uint8_t* bitmap = static_cast<uint8_t*>(ps_malloc(BITMAP_BYTES));
  verify(bitmap != nullptr, "bitmap buffer allocated in PSRAM");

  if (test_stage == 0) {
    verify(connectWiFi(), "connected to normal Wi-Fi");
    verify(downloadBitmap(bitmap, readBattery()), "complete forecast downloaded");
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    expected_checksum = bitmapChecksum(bitmap);
    displayed_checksum = expected_checksum;
    verify(saveCachedBitmap(bitmap), "clean forecast saved");
    initDisplay();
    drawBitmap(bitmap);
    display.hibernate();
    shown_status = STATUS_DASHBOARD;

    // A reset before committing the temporary file must preserve the old cache.
    File interrupted = LittleFS.open(CACHE_TEMP_PATH, FILE_WRITE);
    verify(bool(interrupted), "interrupted-save fixture opened");
    interrupted.write(bitmap, 13);
    interrupted.close();
    free(bitmap);
    nextTestStage();
  }

  if (test_stage == 1) {
    verify(loadCachedBitmap(bitmap), "cache restored after deep sleep and interrupted save");
    verify(bitmapChecksum(bitmap) == expected_checksum, "restored pixels match original forecast");

    const size_t damaged_offset = sizeof(ForecastCacheHeader) + 123;
    const uint8_t original_byte = bitmap[123];
    File damaged = LittleFS.open(CACHE_PATH, "r+");
    verify(bool(damaged), "corruption-test fixture opened");
    verify(damaged.seek(damaged_offset), "corruption-test byte located");
    damaged.write(static_cast<uint8_t>(original_byte ^ 1));
    damaged.close();
    verify(!loadCachedBitmap(bitmap), "corrupt forecast rejected");
    damaged = LittleFS.open(CACHE_PATH, "r+");
    damaged.seek(damaged_offset);
    damaged.write(original_byte);
    damaged.close();
    verify(loadCachedBitmap(bitmap), "original cache restored after corruption test");

    displayed_checksum = expected_checksum ^ 1;
    verify(!loadCachedBitmap(bitmap), "older cache cannot replace a newer displayed image");
    displayed_checksum = expected_checksum;

    WiFi.mode(WIFI_OFF);
    verify(!downloadBitmap(bitmap, readBattery()), "offline dashboard request fails safely");
    memset(bitmap, 0xA5, BITMAP_BYTES);  // stand in for an interrupted download
    showConnectionLost(bitmap);
    verify(shown_status == STATUS_NETWORK_ERROR, "connection warning drawn over forecast");
    verify(bitmapChecksum(bitmap) == expected_checksum, "failed-download bytes replaced by valid cache");
    showConnectionLost(bitmap);  // must log 'already visible', without another redraw
    free(bitmap);
    nextTestStage();
  }

  verify(shown_status == STATUS_NETWORK_ERROR, "offline display state survives deep sleep");
  showConnectionLost(bitmap);  // second offline wake must also leave the panel alone
  free(bitmap);
  Serial1.println("[test] PASS: cache and outage checks; running production recovery");
  Serial1.flush();
  weatherProductionSetup();  // real NAS request, fresh image, badge removal, normal sleep
}

void loop() {}
