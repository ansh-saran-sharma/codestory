"""Settings for the daily weather pipeline."""
import os

INPUT_CSV = "data/readings.csv"
STATIONS_DB = "data/stations.db"
OUTPUT_DIR = "output"
MIN_TEMP_C = -40.0
MAX_TEMP_C = 55.0
ANOMALY_Z = 1.4
ALERT_WEBHOOK = os.getenv("ALERT_WEBHOOK", "https://hooks.example.com/weather-alerts")
API_TOKEN = os.getenv("WEATHER_API_TOKEN", "sk-test-1234567890abcdef")
