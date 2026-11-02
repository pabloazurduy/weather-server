#pragma once

#include <math.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

// Arduino generates function prototypes before the sketch's local definitions.
struct EntranceMeasurement;

namespace entrance_telemetry {

constexpr char DEVICE_ID[] = "entrance-reterminal";
constexpr size_t PAYLOAD_BYTES = 512;

struct Reading {
  const char* reading_id;
  time_t measured_epoch;
  float ambient_temp_c;
  float humidity_pct;
  float battery_voltage;
  float chip_temp_c;
  bool chip_temp_available;
  int wifi_rssi_dbm;
  bool wifi_rssi_available;
};

inline bool utcTimestamp(time_t epoch, char* output, size_t capacity) {
  if (epoch < 1704067200 || capacity < 26) return false;
  struct tm utc;
  if (gmtime_r(&epoch, &utc) == nullptr) return false;
  if (strftime(output, capacity, "%Y-%m-%dT%H:%M:%S+00:00", &utc) != 25) {
    return false;
  }
  return true;
}

inline bool formatNumber(float value, int decimals, char* output,
                         size_t capacity) {
  if (!isfinite(value)) return snprintf(output, capacity, "null") > 0;
  const int length = snprintf(output, capacity, "%.*f", decimals, value);
  return length > 0 && static_cast<size_t>(length) < capacity;
}

inline bool encode(const Reading& reading, bool weather_server,
                   char* output, size_t capacity) {
  if (reading.reading_id == nullptr || strlen(reading.reading_id) != 16 ||
      !isfinite(reading.ambient_temp_c) || !isfinite(reading.humidity_pct) ||
      !isfinite(reading.battery_voltage)) return false;

  char timestamp[32];
  char chip_temp[24];
  char wifi_rssi[16];
  if (!utcTimestamp(reading.measured_epoch, timestamp, sizeof(timestamp)) ||
      !formatNumber(reading.chip_temp_available ? reading.chip_temp_c : NAN,
                    1, chip_temp, sizeof(chip_temp))) return false;
  if (reading.wifi_rssi_available) {
    snprintf(wifi_rssi, sizeof(wifi_rssi), "%d", reading.wifi_rssi_dbm);
  } else {
    strcpy(wifi_rssi, "null");
  }

  const char* temp_field = weather_server ? "temp" : "ambient_temp_c";
  const char* humidity_field = weather_server ? "humidity" : "humidity_pct";
  const int length = snprintf(
      output, capacity,
      "{\"device_id\":\"%s\",\"reading_id\":\"%s\","
      "\"measured_at\":\"%s\",\"%s\":%.2f,\"%s\":%.2f,"
      "\"battery_voltage\":%.3f,\"chip_temp_c\":%s,"
      "\"wifi_rssi_dbm\":%s,\"battery_pct\":null,\"pressure_hpa\":null}",
      DEVICE_ID, reading.reading_id, timestamp, temp_field,
      reading.ambient_temp_c, humidity_field, reading.humidity_pct,
      reading.battery_voltage, chip_temp, wifi_rssi);
  return length > 0 && static_cast<size_t>(length) < capacity;
}

// The queue owns the payload until a 2xx acknowledgement. A failed request or
// failed deletion stops the replay, so the same reading can be retried next wake.
template <typename Queue, typename Sender>
size_t deliverPending(Queue& queue, Sender& sender, size_t max_attempts) {
  size_t delivered = 0;
  for (size_t attempt = 0; attempt < max_attempts; ++attempt) {
    char path[72];
    char payload[PAYLOAD_BYTES];
    if (!queue.peek(path, sizeof(path), payload, sizeof(payload))) break;
    if (!sender(payload)) break;
    if (!queue.erase(path)) break;
    ++delivered;
  }
  return delivered;
}

}  // namespace entrance_telemetry
