from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from models import UNIT_STEPS, get_sales_report_rows


def report_dates(start, end):
    today = datetime.now(ZoneInfo("Asia/Karachi")).date()
    try:
        first = date.fromisoformat(start) if start else today.replace(day=1)
        last = date.fromisoformat(end) if end else today
    except ValueError:
        raise ValueError("Enter valid start and end dates.") from None
    if first > last:
        raise ValueError("The end date must be on or after the start date.")
    return first, last


@dataclass
class Totals:
    sales: int = 0
    revenue: Decimal = Decimal(0)
    missing: int = 0
    quantities: dict = field(default_factory=lambda: dict.fromkeys(UNIT_STEPS, Decimal(0)))

    def add(self, unit, count, quantity, revenue, missing):
        self.sales += count
        self.revenue += revenue
        self.missing += missing
        self.quantities[unit] += quantity


def build_report(start, end):
    daily, products, total = {}, {}, Totals()
    for day, product_id, name, unit, count, quantity, revenue, missing in get_sales_report_rows(start, end):
        if day not in daily:
            daily[day] = Totals()
        daily[day].add(unit, count, quantity, revenue, missing)
        total.add(unit, count, quantity, revenue, missing)
        if count > missing:
            key = (product_id, name)
            products[key] = products.get(key, Decimal(0)) + revenue
    top = sorted(products.items(), key=lambda item: (-item[1], item[0][1], item[0][0]))[:10]
    return daily, top, total
