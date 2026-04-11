# Copy this file to local_settings.py and fill in your local values.
#
# CITY identifies the location label and cache key.
# Use a normal city name, optionally with country or state/country to disambiguate:
#   "Amsterdam"
#   "Amsterdam,NL"
#   "Portland,OR,US"
# No camel case is required. The app trims extra whitespace before caching it.
#
# CITY_LAT and CITY_LON must point to the same place as CITY because the dashboard
# uses Open-Meteo and Buienradar coordinates for weather data.

CITY = "Amsterdam,NL"
CITY_LAT = 52.370216
CITY_LON = 4.895168
BASE_URL = "http://192.168.1.100:8080"
BIND_HOST = "0.0.0.0"
BIND_PORT = 8080
CHARACTER_NAME = "hedgehog"
CHARACTER_RULES = {
	"warm_temp_c": 14.0,
	"freezing_temp_c": 2.0,
	"windy_speed_mps": 10.0,
	"rain_prob_percent": 35,
	"sunny_kinds": ["sun", "partly"],
	"rainy_kinds": ["rain", "storm"],
	"snowy_kinds": ["snow"],
}
