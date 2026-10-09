"""app.py - Flask application for OrnaCast AI.

Run with:  python app.py   then open http://127.0.0.1:5000
"""
import csv
import io
from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import (Flask, Response, flash, jsonify, redirect, render_template,
                   request, url_for)

import database as db
import forecasting as fc
import insights as ins

app = Flask(__name__)
app.secret_key = "change-me-for-real-use"  # needed for flash messages


# ---------------------------------------------------------------- helpers
@app.template_filter("inr")
def inr(value):
    """Format a number as Indian Rupees with lakh/crore grouping, e.g. ₹1,23,456."""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return "₹0"
    sign = "-" if n < 0 else ""
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"{sign}₹{s}"


@app.template_filter("indian_date")
def indian_date(value):
    """2026-10-09 -> 09-10-2026 (DD-MM-YYYY)."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d-%m-%Y")
    except (TypeError, ValueError):
        return value or ""


@app.context_processor
def inject_globals():
    return {"has_demo": db.has_demo_data(), "today": date.today().isoformat()}


def parse_number(raw, label, integer=False, minimum=0.0, allow_zero=True):
    """Validate a form value. Returns (value, error_message)."""
    try:
        value = int(raw) if integer else float(raw)
    except (TypeError, ValueError):
        return None, f"{label} must be a valid {'whole ' if integer else ''}number."
    if value < minimum or (not allow_zero and value == 0):
        return None, f"{label} must be {'greater than' if not allow_zero else 'at least'} {minimum}."
    return value, None


def validate_product(form):
    errors = []
    name = (form.get("name") or "").strip()
    if not name:
        errors.append("Product name is required.")
    elif len(name) > 80:
        errors.append("Product name must be 80 characters or fewer.")
    category = form.get("category")
    if category not in db.CATEGORIES:
        errors.append("Please choose a valid category.")
    price, e = parse_number(form.get("price"), "Selling price")
    if e: errors.append(e)
    cost, e = parse_number(form.get("cost"), "Cost price")
    if e: errors.append(e)
    stock, e = parse_number(form.get("stock"), "Stock quantity", integer=True)
    if e: errors.append(e)
    min_stock, e = parse_number(form.get("min_stock"), "Minimum stock level", integer=True)
    if e: errors.append(e)
    return errors, (name, category, price, cost, stock, min_stock)


# -------------------------------------------------------------- dashboard
@app.route("/")
def dashboard():
    sales = db.list_sales()
    products = db.list_products()
    total_revenue = sum(s["total"] for s in sales)
    units = sum(s["quantity"] for s in sales)

    by_product = defaultdict(int)
    for s in sales:
        by_product[s["product_name"]] += s["quantity"]
    best = max(by_product.items(), key=lambda x: x[1]) if by_product else None

    next_month = fc.forecast(db.daily_sales(), 30)
    low_stock = [p for p in products if p["stock"] <= p["min_stock"]]

    # Monthly revenue trend for the chart
    monthly = defaultdict(float)
    for s in sales:
        monthly[s["sale_date"][:7]] += s["total"]
    months = sorted(monthly)
    # Weekly units trend
    weekly = defaultdict(int)
    for s in sales:
        d = datetime.strptime(s["sale_date"], "%Y-%m-%d").date()
        weekly[(d - timedelta(days=d.weekday())).isoformat()] += s["quantity"]
    weeks = sorted(weekly)[-26:]

    return render_template(
        "dashboard.html", total_revenue=total_revenue, total_orders=len(sales), units=units,
        best=best, next_month=next_month, low_stock=low_stock,
        insights=ins.generate_insights()[:5],
        month_labels=[datetime.strptime(m, "%Y-%m").strftime("%b %Y") for m in months],
        month_values=[round(monthly[m]) for m in months],
        week_labels=[datetime.strptime(w, "%Y-%m-%d").strftime("%d %b") for w in weeks],
        week_values=[weekly[w] for w in weeks],
    )


# --------------------------------------------------------------- products
@app.route("/products")
def products():
    return render_template("products.html", products=db.list_products())


@app.route("/products/new", methods=["GET", "POST"])
def product_new():
    if request.method == "POST":
        errors, values = validate_product(request.form)
        if errors:
            for e in errors: flash(e, "error")
            return render_template("product_form.html", product=request.form, categories=db.CATEGORIES, mode="new")
        db.add_product(*values)
        flash("Product added.", "success")
        return redirect(url_for("products"))
    return render_template("product_form.html", product={"min_stock": 5, "stock": 0},
                           categories=db.CATEGORIES, mode="new")


@app.route("/products/<int:pid>/edit", methods=["GET", "POST"])
def product_edit(pid):
    product = db.get_product(pid)
    if not product:
        flash("Product not found.", "error")
        return redirect(url_for("products"))
    if request.method == "POST":
        errors, values = validate_product(request.form)
        if errors:
            for e in errors: flash(e, "error")
            return render_template("product_form.html", product=request.form, categories=db.CATEGORIES,
                                   mode="edit", pid=pid)
        db.update_product(pid, *values)
        flash("Product updated.", "success")
        return redirect(url_for("products"))
    return render_template("product_form.html", product=product, categories=db.CATEGORIES, mode="edit", pid=pid)


@app.route("/products/<int:pid>/delete", methods=["POST"])
def product_delete(pid):
    db.delete_product(pid)
    flash("Product and its sales records were deleted.", "success")
    return redirect(url_for("products"))


# ------------------------------------------------------------------ sales
@app.route("/sales")
def sales():
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    pid = request.args.get("product_id", type=int)
    rows = db.list_sales(date_from, date_to, pid)
    return render_template("sales.html", sales=rows, products=db.list_products(),
                           filters={"date_from": date_from or "", "date_to": date_to or "", "product_id": pid},
                           total=sum(r["total"] for r in rows), units=sum(r["quantity"] for r in rows))


@app.route("/sales/add", methods=["POST"])
def sale_add():
    errors = []
    sale_date = request.form.get("sale_date", "")
    try:
        d = datetime.strptime(sale_date, "%Y-%m-%d").date()
        if d > date.today():
            errors.append("Sale date cannot be in the future.")
    except ValueError:
        errors.append("Please enter a valid sale date.")
    pid, e = parse_number(request.form.get("product_id"), "Product", integer=True, minimum=1)
    if e: errors.append("Please choose a product.")
    qty, e = parse_number(request.form.get("quantity"), "Quantity", integer=True, minimum=1, allow_zero=False)
    if e: errors.append("Quantity must be a whole number of at least 1.")
    price, e = parse_number(request.form.get("unit_price"), "Selling price per unit")
    if e: errors.append(e)
    if not errors:
        try:
            db.add_sale(sale_date, pid, qty, price)
            flash("Sale recorded and stock updated.", "success")
        except ValueError as ex:
            errors.append(str(ex))
    for er in errors:
        flash(er, "error")
    return redirect(url_for("sales"))


@app.route("/sales/<int:sid>/delete", methods=["POST"])
def sale_delete(sid):
    db.delete_sale(sid)
    flash("Sale deleted and stock restored.", "success")
    return redirect(url_for("sales"))


@app.route("/sales/export.csv")
def sales_export():
    """Download sales (respecting the same filters as the sales page) as CSV."""
    rows = db.list_sales(request.args.get("date_from") or None, request.args.get("date_to") or None,
                         request.args.get("product_id", type=int))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Sale ID", "Date", "Product", "Category", "Quantity", "Unit Price (INR)", "Total (INR)", "Demo"])
    for r in rows:
        w.writerow([r["id"], r["sale_date"], r["product_name"], r["category"], r["quantity"],
                    r["unit_price"], r["total"], "yes" if r["is_demo"] else "no"])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=ornacast_sales.csv"})


# --------------------------------------------------------------- forecast
@app.route("/forecast")
def forecast_page():
    return render_template("forecast.html", products=db.list_products())


@app.route("/api/forecast")
def api_forecast():
    """JSON endpoint used by the Generate Forecast button."""
    days = request.args.get("days", 30, type=int)
    pid = request.args.get("product_id", type=int)
    if days not in (7, 30, 90):
        return jsonify(error="Please choose 7, 30 or 90 days."), 400
    if pid and not db.get_product(pid):
        return jsonify(error="Product not found."), 404
    try:
        rows = db.daily_sales(pid)
        result = fc.forecast(rows, days)
        # Last 60 days of actuals for the comparison chart
        today = date.today()
        by_day = {r["sale_date"]: r["units"] for r in rows}
        history = [{"date": (today - timedelta(days=i)).isoformat(),
                    "units": by_day.get((today - timedelta(days=i)).isoformat(), 0)}
                   for i in range(59, -1, -1)]
        result["history"] = history
        result["backtest"] = fc.backtest(rows)
        return jsonify(result)
    except Exception as ex:  # keep the UI friendly if anything unexpected happens
        return jsonify(error=f"Could not generate forecast: {ex}"), 500


# -------------------------------------------------------------- inventory
@app.route("/inventory")
def inventory():
    items = []
    for p in db.list_products():
        f30 = fc.forecast(db.daily_sales(p["id"]), 30)
        status, qty = fc.restock_recommendation(p["stock"], p["min_stock"], f30["total_units"])
        items.append({**p, "forecast_units": f30["total_units"], "status": status, "suggested": qty,
                      "confidence": f30["confidence"]})
    order = {"restock": 0, "excess": 1, "ok": 2, "no_demand": 3}
    items.sort(key=lambda x: order[x["status"]])
    return render_template("inventory.html", items=items, insights=ins.generate_insights())


# ---------------------------------------------------------------- reports
@app.route("/reports")
def reports():
    sales = db.list_sales()
    today = date.today()

    def summarize(keyfn, limit):
        agg = defaultdict(lambda: [0, 0.0, 0])
        for s in sales:
            d = datetime.strptime(s["sale_date"], "%Y-%m-%d").date()
            a = agg[keyfn(d)]
            a[0] += s["quantity"]; a[1] += s["total"]; a[2] += 1
        keys = sorted(agg, reverse=True)[:limit]
        return [{"period": k, "units": agg[k][0], "revenue": agg[k][1], "orders": agg[k][2]} for k in keys]

    daily = summarize(lambda d: d.strftime("%d-%m-%Y"), 0) if False else None
    # Daily needs date-sorted keys, so build with ISO keys then format
    daily = summarize(lambda d: d.isoformat(), 14)
    for r in daily: r["period"] = indian_date(r["period"])
    weekly = summarize(lambda d: (d - timedelta(days=d.weekday())).isoformat(), 12)
    for r in weekly: r["period"] = "Week of " + indian_date(r["period"])
    monthly = summarize(lambda d: d.strftime("%Y-%m"), 12)
    for r in monthly: r["period"] = datetime.strptime(r["period"], "%Y-%m").strftime("%B %Y")

    by_cat = defaultdict(float)
    by_prod = defaultdict(lambda: [0, 0.0])
    for s in sales:
        by_cat[s["category"]] += s["total"]
        by_prod[s["product_name"]][0] += s["quantity"]
        by_prod[s["product_name"]][1] += s["total"]
    top = sorted(by_prod.items(), key=lambda x: x[1][0], reverse=True)[:8]

    # Forecast vs actual (backtest for each product that has enough history)
    compare = []
    for p in db.list_products():
        bt = fc.backtest(db.daily_sales(p["id"]), days=30)
        if bt:
            compare.append({"name": p["name"], **bt})

    return render_template(
        "reports.html", daily=daily, weekly=weekly, monthly=monthly,
        cat_labels=[c.title() for c in by_cat], cat_values=[round(v) for v in by_cat.values()],
        top=top, compare=compare)


# ------------------------------------------------------------- demo data
@app.route("/demo/reset", methods=["POST"])
def demo_reset():
    db.reset_demo_data()
    flash("Demo data has been reset.", "success")
    return redirect(url_for("dashboard"))


@app.route("/demo/delete", methods=["POST"])
def demo_delete():
    db.delete_demo_data()
    flash("Demo data deleted. Your own records were kept.", "success")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    db.init_db()
    app.run(debug=True)
