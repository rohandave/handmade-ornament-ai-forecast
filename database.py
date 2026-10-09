"""database.py - SQLite helpers for OrnaCast AI.

All SQL uses parameterized queries (?) so user input can never be executed as SQL.
"""
import os
import random
import sqlite3
from datetime import date, timedelta

DB_PATH = os.environ.get(
    "ORNACAST_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ornacast.db")
)

CATEGORIES = ["earrings", "necklaces", "bracelets", "bangles", "rings", "pendants", "other"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price REAL NOT NULL CHECK (price >= 0),
    cost REAL NOT NULL CHECK (cost >= 0),
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    min_stock INTEGER NOT NULL DEFAULT 5 CHECK (min_stock >= 0),
    is_demo INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_date TEXT NOT NULL,              -- ISO format YYYY-MM-DD
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price REAL NOT NULL CHECK (unit_price >= 0),
    total REAL NOT NULL,
    is_demo INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(sale_date);
CREATE INDEX IF NOT EXISTS idx_sales_product ON sales(product_id);
"""

# name, category, price, cost, stock, min_stock, base daily demand, pattern
DEMO_PRODUCTS = [
    ("Handmade Beaded Earrings", "earrings", 299, 110, 40, 15, 3.2, "steady"),
    ("Oxidized Silver Necklace", "necklaces", 649, 280, 14, 10, 1.6, "declining"),
    ("Pearl Bracelet", "bracelets", 449, 190, 6, 12, 2.0, "growing"),
    ("Clay Floral Pendant", "pendants", 199, 60, 55, 10, 0.5, "slow"),
    ("Decorative Glass Bangles (Set of 6)", "bangles", 349, 130, 30, 12, 2.2, "festive"),
    ("Kundan Jhumka Earrings", "earrings", 549, 230, 18, 8, 1.4, "festive"),
    ("Terracotta Ring", "rings", 149, 45, 70, 10, 0.4, "slow"),
    ("Layered Boho Necklace", "necklaces", 799, 340, 20, 8, 1.1, "steady"),
]


def get_connection():
    """Open a connection with rows accessible by column name and FK support on."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(seed=True):
    """Create tables; seed demo data only if the database is completely empty."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        empty = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
    if seed and empty:
        seed_demo_data()


def _demand_factor(pattern, day, total_days, d):
    """Multiplier on base demand to create trends / seasonality in demo data."""
    progress = day / max(total_days - 1, 1)
    f = 1.0
    if pattern == "growing":
        f = 0.6 + 1.0 * progress
    elif pattern == "declining":
        f = 1.5 - 1.0 * progress
    elif pattern == "festive":
        # Festive peak (Navratri/Diwali season: Oct-Nov) and wedding season bump
        f = 1.0 + (1.2 if d.month in (10, 11) else 0) + (0.3 if d.month in (12, 1) else 0)
    elif pattern == "slow":
        f = 0.8
    if d.weekday() >= 5:  # weekends are busier
        f *= 1.3
    return f


def seed_demo_data(months=6, seed=42):
    """Insert demo products and ~6 months of sales, all flagged is_demo=1."""
    rng = random.Random(seed)
    today = date.today()
    start = today - timedelta(days=months * 30)
    total_days = (today - start).days
    with get_connection() as conn:
        for (name, cat, price, cost, stock, min_stock, base, pattern) in DEMO_PRODUCTS:
            cur = conn.execute(
                "INSERT INTO products (name, category, price, cost, stock, min_stock, is_demo) "
                "VALUES (?, ?, ?, ?, ?, ?, 1)",
                (name, cat, price, cost, stock, min_stock),
            )
            pid = cur.lastrowid
            for i in range(total_days + 1):
                d = start + timedelta(days=i)
                lam = base * _demand_factor(pattern, i, total_days, d)
                # Poisson-like sample via sum of Bernoulli trials
                qty = sum(1 for _ in range(10) if rng.random() < lam / 10)
                if qty > 0:
                    conn.execute(
                        "INSERT INTO sales (sale_date, product_id, quantity, unit_price, total, is_demo) "
                        "VALUES (?, ?, ?, ?, ?, 1)",
                        (d.isoformat(), pid, qty, price, qty * price),
                    )


def delete_demo_data():
    """Remove only records flagged as demo."""
    with get_connection() as conn:
        conn.execute("DELETE FROM sales WHERE is_demo = 1")
        conn.execute("DELETE FROM products WHERE is_demo = 1")


def reset_demo_data():
    """Delete demo data, then re-seed it (user's own records are untouched)."""
    delete_demo_data()
    seed_demo_data()


# ---------------------------------------------------------------- products
def list_products():
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM products ORDER BY name")]


def get_product(pid):
    with get_connection() as conn:
        r = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        return dict(r) if r else None


def add_product(name, category, price, cost, stock, min_stock):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO products (name, category, price, cost, stock, min_stock) VALUES (?,?,?,?,?,?)",
            (name, category, price, cost, stock, min_stock),
        )
        return cur.lastrowid


def update_product(pid, name, category, price, cost, stock, min_stock):
    with get_connection() as conn:
        conn.execute(
            "UPDATE products SET name=?, category=?, price=?, cost=?, stock=?, min_stock=? WHERE id=?",
            (name, category, price, cost, stock, min_stock, pid),
        )


def delete_product(pid):
    with get_connection() as conn:
        conn.execute("DELETE FROM products WHERE id = ?", (pid,))


# ------------------------------------------------------------------- sales
def add_sale(sale_date, product_id, quantity, unit_price):
    """Record a sale and reduce stock in ONE transaction.

    Raises ValueError if the quantity is invalid or stock is insufficient.
    The stock update only succeeds when enough stock exists (atomic check).
    """
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
            (quantity, product_id, quantity),
        )
        if cur.rowcount == 0:
            exists = conn.execute("SELECT stock FROM products WHERE id=?", (product_id,)).fetchone()
            if not exists:
                raise ValueError("Product not found.")
            raise ValueError(f"Not enough stock. Only {exists['stock']} unit(s) available.")
        total = round(quantity * unit_price, 2)
        conn.execute(
            "INSERT INTO sales (sale_date, product_id, quantity, unit_price, total) VALUES (?,?,?,?,?)",
            (sale_date, product_id, quantity, unit_price, total),
        )


def delete_sale(sale_id, restore_stock=True):
    """Delete a sale; by default put the units back into stock."""
    with get_connection() as conn:
        row = conn.execute("SELECT product_id, quantity FROM sales WHERE id=?", (sale_id,)).fetchone()
        if not row:
            return
        conn.execute("DELETE FROM sales WHERE id=?", (sale_id,))
        if restore_stock:
            conn.execute("UPDATE products SET stock = stock + ? WHERE id=?",
                         (row["quantity"], row["product_id"]))


def list_sales(date_from=None, date_to=None, product_id=None):
    """Sales joined with product info, newest first, with optional filters."""
    sql = ("SELECT s.*, p.name AS product_name, p.category FROM sales s "
           "JOIN products p ON p.id = s.product_id WHERE 1=1")
    params = []
    if date_from:
        sql += " AND s.sale_date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND s.sale_date <= ?"
        params.append(date_to)
    if product_id:
        sql += " AND s.product_id = ?"
        params.append(product_id)
    sql += " ORDER BY s.sale_date DESC, s.id DESC"
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def daily_sales(product_id=None):
    """Aggregated (date, units, revenue) rows - the input to forecasting."""
    sql = "SELECT sale_date, SUM(quantity) AS units, SUM(total) AS revenue FROM sales"
    params = []
    if product_id:
        sql += " WHERE product_id = ?"
        params.append(product_id)
    sql += " GROUP BY sale_date ORDER BY sale_date"
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def has_demo_data():
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM products WHERE is_demo=1").fetchone()[0] > 0
