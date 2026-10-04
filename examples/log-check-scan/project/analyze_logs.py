"""Nightly check of web server logs: error rates per endpoint, with an email if things look bad."""
import json
import re
import smtplib
import sys
from collections import Counter
from email.message import EmailMessage

LOG_PATH = "logs/access.log"
REPORT_PATH = "reports/errors.json"
ERROR_RATE_ALERT = 0.05          # alert when more than 5% of requests fail
SMTP_HOST = "mail.internal"
ONCALL = "oncall@example.com"

LINE = re.compile(r'(?P<ip>\S+) .* "(?P<method>\w+) (?P<path>\S+) [^"]*" (?P<status>\d{3}) (?P<bytes>\d+)')


def parse(lines):
    """Turn raw log lines into dicts; skip lines that don't match."""
    for line in lines:
        m = LINE.search(line)
        if m:
            d = m.groupdict()
            d["status"] = int(d["status"])
            yield d


def endpoint(path):
    """Collapse ids so /orders/123 and /orders/456 count together."""
    return re.sub(r"/\d+", "/:id", path.split("?")[0])


def summarize(requests):
    total, errors = Counter(), Counter()
    for r in requests:
        ep = endpoint(r["path"])
        total[ep] += 1
        if r["status"] >= 500:
            errors[ep] += 1
    return [{"endpoint": ep, "requests": n, "errors": errors[ep], "error_rate": round(errors[ep] / n, 4)}
            for ep, n in total.most_common()]


def send_alert(rows, rate):
    msg = EmailMessage()
    msg["Subject"] = f"Error rate {rate:.1%} in last night's traffic"
    msg["To"] = ONCALL
    msg["From"] = "logbot@example.com"
    worst = sorted(rows, key=lambda r: r["errors"], reverse=True)[:5]
    msg.set_content("\n".join(f'{r["endpoint"]}: {r["errors"]} errors' for r in worst))
    with smtplib.SMTP(SMTP_HOST) as s:
        s.send_message(msg)


def main(path=LOG_PATH):
    with open(path) as fh:
        rows = summarize(parse(fh))
    with open(REPORT_PATH, "w") as out:
        json.dump(rows, out, indent=2)
    total = sum(r["requests"] for r in rows)
    errors = sum(r["errors"] for r in rows)
    rate = errors / total if total else 0
    if rate > ERROR_RATE_ALERT:
        send_alert(rows, rate)
    return rate


if __name__ == "__main__":
    main(*sys.argv[1:])
