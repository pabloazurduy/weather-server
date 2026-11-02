#include <assert.h>
#include <string.h>

#include <deque>
#include <string>
#include <utility>
#include <vector>

#include "../weather_display/entrance_telemetry.h"

struct FakeQueue {
  std::deque<std::pair<std::string, std::string>> items;
  bool fail_erase = false;

  bool peek(char* path, size_t path_capacity, char* payload,
            size_t payload_capacity) {
    if (items.empty() || items.front().first.size() >= path_capacity ||
        items.front().second.size() >= payload_capacity) return false;
    strcpy(path, items.front().first.c_str());
    strcpy(payload, items.front().second.c_str());
    return true;
  }

  bool erase(const char* path) {
    if (fail_erase || items.empty() || items.front().first != path) return false;
    items.pop_front();
    return true;
  }
};

struct FakeSender {
  std::vector<bool> responses;
  size_t calls = 0;

  bool operator()(const char*) {
    const bool result = responses.at(calls);
    ++calls;
    return result;
  }
};

int main() {
  using namespace entrance_telemetry;
  Reading reading = {"0123456789abcdef", 1704067200, 21.25f, 47.50f,
                     3.912f, 30.4f, true, -61, true};
  char pipecar[PAYLOAD_BYTES];
  char weather[PAYLOAD_BYTES];
  assert(encode(reading, false, pipecar, sizeof(pipecar)));
  assert(encode(reading, true, weather, sizeof(weather)));
  assert(strstr(pipecar, "\"device_id\":\"entrance-reterminal\""));
  assert(strstr(pipecar, "\"reading_id\":\"0123456789abcdef\""));
  assert(strstr(pipecar, "\"measured_at\":\"2024-01-01T00:00:00+00:00\""));
  assert(strstr(weather, "\"measured_at\":\"2024-01-01T00:00:00+00:00\""));
  assert(strstr(pipecar, "\"ambient_temp_c\":21.25"));
  assert(strstr(weather, "\"temp\":21.25"));
  assert(strstr(pipecar, "\"humidity_pct\":47.50"));
  assert(strstr(weather, "\"humidity\":47.50"));
  assert(strstr(pipecar, "\"battery_voltage\":3.912"));
  assert(strstr(weather, "\"battery_voltage\":3.912"));
  assert(strstr(pipecar, "\"chip_temp_c\":30.4"));
  assert(strstr(pipecar, "\"wifi_rssi_dbm\":-61"));
  assert(strstr(pipecar, "\"battery_pct\":null"));
  assert(strstr(pipecar, "\"pressure_hpa\":null"));

  reading.chip_temp_available = false;
  reading.wifi_rssi_available = false;
  assert(encode(reading, false, pipecar, sizeof(pipecar)));
  assert(strstr(pipecar, "\"chip_temp_c\":null"));
  assert(strstr(pipecar, "\"wifi_rssi_dbm\":null"));
  assert(!encode(reading, false, pipecar, 32));
  reading.measured_epoch = 0;
  assert(!encode(reading, false, pipecar, sizeof(pipecar)));

  FakeQueue queue;
  queue.items.push_back({"/ent-1.json", "reading-one"});
  queue.items.push_back({"/ent-2.json", "reading-two"});
  FakeSender sender{{false, true, true}};
  assert(deliverPending(queue, sender, 4) == 0);  // outage retains first item
  assert(queue.items.size() == 2);
  assert(deliverPending(queue, sender, 1) == 1);  // one bounded retry
  assert(queue.items.size() == 1);
  assert(deliverPending(queue, sender, 4) == 1);
  assert(queue.items.empty());
  assert(sender.calls == 3);

  queue.items.push_back({"/ent-3.json", "reading-three"});
  queue.fail_erase = true;
  FakeSender acknowledged{{true}};
  assert(deliverPending(queue, acknowledged, 4) == 0);
  assert(queue.items.size() == 1);  // ack with failed delete retries later
  return 0;
}
