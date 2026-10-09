"""insights.py - rule-based business insights calculated from the real data.

No hardcoded claims: every sentence below is produced from numbers in the DB.
"""
from datetime import date, timedelta

import database as db


def _period_totals(start, end):
    """units per product between two dates (inclusive)."""
    sales = db.list_sales(date_from=start.isoformat(), date_to=end.isoformat())
    totals = {}
    for s in sales:
        totals[s["product_name"]] = totals.get(s["product_name"], 0) + s["quantity"]
    return totals


def generate_insights(today=None):
    """Return a list of {type, text} where type is good / warn / info."""
    today = today or date.today()
    products = db.list_products()
    insights = []
    if not products:
        return [{"type": "info", "text": "Add your first products to start getting insights."}]

    cur_start = today - timedelta(days=29)
    prev_start, prev_end = today - timedelta(days=59), today - timedelta(days=30)
    cur = _period_totals(cur_start, today)
    prev = _period_totals(prev_start, prev_end)

    if not cur:
        insights.append({"type": "info",
                         "text": "No sales were recorded in the last 30 days, so trend insights are unavailable."})
    else:
        best = max(cur, key=cur.get)
        insights.append({"type": "good",
                         "text": f"{best} is your best-selling product in the last 30 days ({cur[best]} units)."})

    # Growth / decline compared with the previous 30 days (needs a meaningful base)
    for name in sorted(set(cur) | set(prev)):
        c, p = cur.get(name, 0), prev.get(name, 0)
        if p >= 5:
            change = (c - p) / p * 100
            if change >= 20:
                insights.append({"type": "good",
                                 "text": f"{name} sales increased {change:.0f}% compared with the previous 30 days ({p} → {c} units)."})
            elif change <= -20:
                insights.append({"type": "warn",
                                 "text": f"{name} sales are declining ({change:.0f}% vs the previous 30 days). "
                                         f"Consider a new design or a promotional offer."})

    # Low stock
    for p in products:
        if p["stock"] <= p["min_stock"]:
            insights.append({"type": "warn",
                             "text": f"Consider restocking {p['name']}: only {p['stock']} left "
                                     f"(minimum level is {p['min_stock']})."})

    # Slow movers
    for p in products:
        if p["stock"] > 0 and cur.get(p["name"], 0) == 0 and (cur or prev):
            insights.append({"type": "info",
                             "text": f"{p['name']} had no sales in 30 days while {p['stock']} units sit in stock."})

    # Most profitable margin
    with_margin = [(p["name"], (p["price"] - p["cost"]) / p["price"] * 100) for p in products if p["price"] > 0]
    if with_margin:
        n, m = max(with_margin, key=lambda x: x[1])
        insights.append({"type": "info", "text": f"{n} has your highest profit margin ({m:.0f}%)."})

    return insights
