"""Basic automated tests: run with `pytest` from the project folder."""
import os
import sys
import tempfile
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db
import forecasting as fc


@pytest.fixture()
def fresh_db(monkeypatch):
    """Each test gets its own empty temporary database."""
    path = os.path.join(tempfile.mkdtemp(), "test.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db(seed=False)
    return path


def make_rows(units_per_day, days, end=None):
    end = end or date.today()
    return [{"sale_date": (end - timedelta(days=i)).isoformat(), "units": units_per_day,
             "revenue": units_per_day * 100.0} for i in range(days)]


# ------------------------------------------------------------- forecasting
def test_no_history_returns_zero():
    r = fc.forecast([], 30)
    assert r["total_units"] == 0 and r["confidence"] == "none"


def test_stable_sales_forecast_is_close_to_average():
    r = fc.forecast(make_rows(2, 60), 30)
    assert abs(r["total_units"] - 60) <= 2
    assert r["total_revenue"] == pytest.approx(r["total_units"] * 100, rel=0.05)


def test_limited_history_uses_fallback():
    r = fc.forecast(make_rows(3, 5), 7)
    assert "fallback" in r["method"].lower() and r["confidence"] == "low"


def test_forecast_changes_when_history_changes():
    low = fc.forecast(make_rows(1, 60), 30)["total_units"]
    high = fc.forecast(make_rows(5, 60), 30)["total_units"]
    assert high > low


def test_invalid_period_rejected():
    with pytest.raises(ValueError):
        fc.forecast(make_rows(1, 30), 15)


def test_restock_recommendation():
    assert fc.restock_recommendation(5, 10, 40)[0] == "restock"
    assert fc.restock_recommendation(200, 10, 20)[0] == "excess"
    assert fc.restock_recommendation(30, 10, 25)[0] == "ok"


# ---------------------------------------------------------------- database
def test_product_crud(fresh_db):
    pid = db.add_product("Test Ring", "rings", 100, 40, 10, 3)
    assert db.get_product(pid)["name"] == "Test Ring"
    db.update_product(pid, "Test Ring 2", "rings", 120, 40, 8, 3)
    assert db.get_product(pid)["price"] == 120
    db.delete_product(pid)
    assert db.get_product(pid) is None


def test_sale_updates_stock_and_persists(fresh_db):
    pid = db.add_product("Bangle", "bangles", 250, 100, 10, 2)
    db.add_sale("2026-10-01", pid, 3, 250)
    assert db.get_product(pid)["stock"] == 7
    sales = db.list_sales()
    assert len(sales) == 1 and sales[0]["total"] == 750


def test_sale_rejects_zero_negative_and_oversell(fresh_db):
    pid = db.add_product("Bangle", "bangles", 250, 100, 5, 2)
    for bad in (0, -1):
        with pytest.raises(ValueError):
            db.add_sale("2026-10-01", pid, bad, 250)
    with pytest.raises(ValueError):
        db.add_sale("2026-10-01", pid, 6, 250)
    assert db.get_product(pid)["stock"] == 5 and db.list_sales() == []


def test_delete_sale_restores_stock(fresh_db):
    pid = db.add_product("Pendant", "pendants", 100, 30, 10, 2)
    db.add_sale("2026-10-01", pid, 4, 100)
    db.delete_sale(db.list_sales()[0]["id"])
    assert db.get_product(pid)["stock"] == 10


def test_filters(fresh_db):
    a = db.add_product("A", "rings", 10, 5, 100, 1)
    b = db.add_product("B", "rings", 10, 5, 100, 1)
    db.add_sale("2026-09-01", a, 1, 10)
    db.add_sale("2026-10-01", b, 1, 10)
    assert len(db.list_sales(product_id=a)) == 1
    assert len(db.list_sales(date_from="2026-09-15")) == 1


def test_seed_and_delete_demo(fresh_db):
    db.seed_demo_data()
    assert len(db.list_products()) >= 8 and len(db.list_sales()) > 500
    own = db.add_product("Mine", "other", 50, 20, 5, 1)
    db.delete_demo_data()
    assert [p["id"] for p in db.list_products()] == [own]


def test_empty_database_pages_work(fresh_db):
    import app as app_module
    client = app_module.app.test_client()
    for path in ["/", "/products", "/sales", "/forecast", "/inventory", "/reports",
                 "/api/forecast?days=30", "/sales/export.csv"]:
        assert client.get(path).status_code == 200, path
