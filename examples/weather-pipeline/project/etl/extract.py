import sqlite3
import pandas as pd


def read_readings(path):
    """Load raw sensor readings from the daily CSV drop."""
    df = pd.read_csv(path, parse_dates=["timestamp"])
    return df


def load_stations(db_path):
    """Fetch station metadata (name, region, elevation)."""
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql_query("SELECT station_id, name, region, elevation_m FROM stations", conn)
