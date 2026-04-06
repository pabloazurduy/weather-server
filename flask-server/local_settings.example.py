# Copy this file to local_settings.py and fill in your local values.

AMS_LAT = "replace-with-private-latitude"
AMS_LON = "replace-with-private-longitude"
OWM_KEY = "replace-with-openweather-api-key"
API_KEY = "replace-with-device-api-key"
BASE_URL = "http://192.168.1.100:8080"
BIND_HOST = "0.0.0.0"
BIND_PORT = 8080
CHARACTER_NAME = "hedgehog"
CHARACTER_RULES = {
	"warm_temp_c": 16.0,
	"freezing_temp_c": 2.0,
	"windy_speed_mps": 10.0,
	"rain_prob_percent": 35,
	"sunny_kinds": ["sun", "partly"],
	"rainy_kinds": ["rain", "storm"],
	"snowy_kinds": ["snow"],
}
