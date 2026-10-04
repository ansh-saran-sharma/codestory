import os
import sqlite3
import requests
from config import OUTPUT_DIR, STATIONS_DB, ALERT_WEBHOOK


def write_report(summary, run_date):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"daily_summary_{run_date}.csv")
    summary.to_csv(path, index=False)
    return path


def save_summary(summary, full_refresh=False):
    with sqlite3.connect(STATIONS_DB) as conn:
        if full_refresh:
            conn.execute("DELETE FROM daily_summary")
        summary.assign(day=summary["day"].astype(str)).to_sql("daily_summary", conn, if_exists="append", index=False)
        return len(summary)


def send_alert(anomalies):
    payload = {"count": len(anomalies),
               "stations": anomalies[["station_id", "name", "mean"]].to_dict(orient="records")}
    r = requests.post(ALERT_WEBHOOK, json=payload, timeout=10)
    return r.status_code
