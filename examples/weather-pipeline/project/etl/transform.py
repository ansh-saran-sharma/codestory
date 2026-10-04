import numpy as np
from config import ANOMALY_Z


def enrich(df, stations):
    """Attach station name and region to every reading."""
    return df.merge(stations, on="station_id", how="left")


def daily_summary(df):
    """One row per station per day: min, max, mean temperature."""
    df = df.assign(day=df["timestamp"].dt.date)
    out = (df.groupby(["station_id", "name", "region", "day"])["temp"]
             .agg(["min", "max", "mean", "count"]).reset_index())
    out["mean"] = out["mean"].round(2)
    return out


def flag_anomalies(summary):
    """Stations whose daily mean is far from their region's mean."""
    g = summary.groupby("region")["mean"]
    z = (summary["mean"] - g.transform("mean")) / g.transform("std").replace(0, np.nan)
    return summary[z.abs() > ANOMALY_Z].copy()
