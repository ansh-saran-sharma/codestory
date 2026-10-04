"""Daily weather pipeline: readings CSV -> clean -> summarize -> report + DB + alerts."""
import argparse
import logging
from datetime import date

from config import INPUT_CSV, STATIONS_DB
from etl.extract import read_readings, load_stations
from etl.clean import clean
from etl.transform import enrich, daily_summary, flag_anomalies
from etl import load

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("pipeline")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=str(date.today()))
    p.add_argument("--full-refresh", action="store_true")
    p.add_argument("--no-alerts", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    raw = read_readings(INPUT_CSV)
    stations = load_stations(STATIONS_DB)
    log.info("loaded %d readings from %d stations", len(raw), len(stations))

    readings = clean(raw)
    summary = daily_summary(enrich(readings, stations))
    anomalies = flag_anomalies(summary)

    report = load.write_report(summary, args.date)
    saved = load.save_summary(summary, full_refresh=args.full_refresh)
    log.info("wrote %s and %d rows to the database", report, saved)

    if len(anomalies) and not args.no_alerts:
        load.send_alert(anomalies)
        log.info("alerted on %d anomalies", len(anomalies))
    else:
        log.info("no alerts sent")


if __name__ == "__main__":
    main()
