"""forecasting.py - a simple, transparent forecasting engine.

This module is deliberately independent of Flask and SQLite: it takes plain
lists of dicts and returns plain dicts. That makes it easy to swap in a real AI
model or API later - just keep the same `forecast()` signature.

Method: Weighted moving average (WMA) of daily units with a gentle trend term.
  - Last 28 days of history are used (missing days count as 0 sales).
  - More recent days get larger weights.
  - With < 14 days of history we fall back to a plain average (low confidence).
  - With no history we return zeros and say so.
This is a statistical estimate, NOT a large language model.
"""
from datetime import date, datetime, timedelta

WINDOW_DAYS = 28
MIN_DAYS_FOR_WMA = 14


def _to_date(value):
    return value if isinstance(value, date) else datetime.strptime(value, "%Y-%m-%d").date()


def build_daily_series(rows, end_date=None, window=WINDOW_DAYS):
    """Turn sparse (date, units, revenue) rows into a continuous daily list.

    Returns (units_list, revenue_list, first_sale_date_or_None) for the last
    `window` days ending at `end_date` (default: today).
    """
    end_date = end_date or date.today()
    by_day = {_to_date(r["sale_date"]): r for r in rows}
    first = min(by_day) if by_day else None
    units, revenue = [], []
    for i in range(window - 1, -1, -1):
        d = end_date - timedelta(days=i)
        r = by_day.get(d)
        units.append(float(r["units"]) if r else 0.0)
        revenue.append(float(r["revenue"]) if r else 0.0)
    return units, revenue, first


def _weighted_average(values):
    """Linearly increasing weights: oldest=1 ... newest=n."""
    n = len(values)
    weights = list(range(1, n + 1))
    return sum(v * w for v, w in zip(values, weights)) / sum(weights)


def _trend_per_day(values):
    """Average daily change: second half mean minus first half mean."""
    half = len(values) // 2
    if half == 0:
        return 0.0
    first, second = values[:half], values[half:]
    return (sum(second) / len(second) - sum(first) / len(first)) / half


def forecast(rows, days, end_date=None):
    """Forecast the next `days` days.

    rows: list of dicts with sale_date, units, revenue (daily aggregates).
    Returns a dict with predicted totals, a per-day series, the method used,
    a confidence label and a human-readable explanation.
    """
    end_date = end_date or date.today()
    if days not in (7, 30, 90):
        raise ValueError("Forecast period must be 7, 30 or 90 days.")

    units, revenue, first = build_daily_series(rows, end_date)
    history_days = (end_date - first).days + 1 if first else 0
    total_units_in_window = sum(units)

    if not rows or total_units_in_window == 0:
        return {
            "days": days, "total_units": 0, "total_revenue": 0.0, "avg_unit_price": 0.0,
            "daily": [], "history_days": history_days, "method": "No data",
            "confidence": "none",
            "explanation": ("There are no sales in the last 28 days, so no estimate can be made. "
                            "Record some sales and try again."),
        }

    avg_price = sum(revenue) / total_units_in_window

    if history_days >= MIN_DAYS_FOR_WMA:
        method = "Weighted moving average (28 days) with trend"
        base = _weighted_average(units)
        trend = _trend_per_day(units)
        confidence = "high" if history_days >= 60 else "medium"
        explanation = (
            f"Based on your last 28 days of sales, giving recent days more weight, the typical day "
            f"is about {base:.1f} units. "
            + ("Sales are trending up, so the estimate rises slightly. " if trend > 0.01 else
               "Sales are trending down, so the estimate falls slightly. " if trend < -0.01 else
               "Sales look stable. ")
            + "Forecasts improve as more sales history is recorded."
        )
    else:
        # Fallback: not enough history for a weighted average -> simple average of days since first sale
        method = "Simple average (limited history fallback)"
        recent = units[-history_days:]
        base = sum(recent) / len(recent)
        trend = 0.0
        confidence = "low"
        explanation = (
            f"Only {history_days} day(s) of history exist, which is too little for a reliable trend. "
            f"The estimate is the plain average of {base:.1f} units/day. Treat it as a rough guide."
        )

    daily = []
    total_units = 0.0
    for i in range(1, days + 1):
        # Trend is damped (halved) and floored at 0 so long forecasts don't run away.
        predicted = max(0.0, base + trend * i * 0.5)
        total_units += predicted
        daily.append({"date": (end_date + timedelta(days=i)).isoformat(),
                      "units": round(predicted, 2)})

    return {
        "days": days,
        "total_units": int(round(total_units)),
        "total_revenue": round(total_units * avg_price, 2),
        "avg_unit_price": round(avg_price, 2),
        "daily": daily,
        "history_days": history_days,
        "method": method,
        "confidence": confidence,
        "explanation": explanation,
    }


def backtest(rows, days=30, end_date=None):
    """Forecast vs actual: pretend today was `days` ago, forecast, compare to what happened.

    Returns None when there is not enough history before the cut-off.
    """
    end_date = end_date or date.today()
    cutoff = end_date - timedelta(days=days)
    past = [r for r in rows if _to_date(r["sale_date"]) <= cutoff]
    if not past:
        return None
    first_past = min(_to_date(r["sale_date"]) for r in past)
    if (cutoff - first_past).days + 1 < MIN_DAYS_FOR_WMA:
        return None
    fc_days = 30 if days >= 30 else 7
    result = forecast(past, fc_days, end_date=cutoff)
    actual = sum(float(r["units"]) for r in rows
                 if cutoff < _to_date(r["sale_date"]) <= cutoff + timedelta(days=fc_days))
    predicted = result["total_units"]
    error_pct = (abs(predicted - actual) / actual * 100) if actual else None
    return {"period_days": fc_days, "predicted_units": predicted,
            "actual_units": int(actual), "error_pct": round(error_pct, 1) if error_pct is not None else None}


def restock_recommendation(stock, min_stock, forecast_units_30):
    """Compare stock with 30-day demand. Returns (status, suggested_qty)."""
    if forecast_units_30 <= 0:
        return ("no_demand", 0) if stock > 0 else ("ok", 0)
    safety = min_stock
    needed = forecast_units_30 + safety - stock
    if stock < forecast_units_30:
        return "restock", max(int(round(needed)), 1)
    if stock > forecast_units_30 * 2.5 and stock > min_stock * 2:
        return "excess", 0
    return "ok", 0
