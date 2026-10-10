"""Nightly stock check: which products need reordering, and how many to order."""
import csv
import json
import sys
from dataclasses import dataclass

STOCK_CSV = "data/stock.csv"
OUT_JSON = "orders.json"
SAFETY_DAYS = 7          # keep a week of stock on hand
MIN_ORDER = 10


@dataclass
class Item:
    sku: str
    on_hand: int
    daily_sales: float
    supplier: str


def load(path):
    with open(path, newline="") as fh:
        return [Item(r["sku"], int(r["on_hand"]), float(r["daily_sales"]), r["supplier"]) for r in csv.DictReader(fh)]


def needed(item):
    target = item.daily_sales * SAFETY_DAYS
    short = target - item.on_hand
    return max(MIN_ORDER, round(short)) if short > 0 else 0


def plan_orders(items):
    orders = {}
    for item in items:
        qty = needed(item)
        if qty:
            orders.setdefault(item.supplier, []).append({"sku": item.sku, "qty": qty})
    return orders


def main(path=STOCK_CSV):
    items = load(path)
    orders = plan_orders(items)
    with open(OUT_JSON, "w") as fh:
        json.dump(orders, fh, indent=2)
    print(f"{sum(len(v) for v in orders.values())} lines for {len(orders)} suppliers")


if __name__ == "__main__":
    main(*sys.argv[1:])
