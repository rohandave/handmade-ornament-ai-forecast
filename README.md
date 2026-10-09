# OrnaCast AI — Handmade Ornaments Sales Forecasting

A small, beginner-friendly web app for handmade jewellery sellers: track products and sales,
forecast demand, get business insights and restocking advice.

**Stack:** Flask (Python) · SQLite · HTML/CSS/JavaScript · Chart.js (bundled, works offline)

## Architecture overview

| File | Job |
|------|-----|
| `app.py` | Flask routes (pages, forms, JSON forecast API, CSV export) |
| `database.py` | SQLite tables, CRUD, demo-data seeding (parameterized SQL only) |
| `forecasting.py` | Forecast engine: weighted moving average + trend, fallback for small data, back-testing, restock logic. **No Flask/SQLite inside**, so you can swap in a real AI API later |
| `insights.py` | Rule-based insights computed from real data |
| `templates/`, `static/` | Pages, styling and JavaScript |
| `tests/` | Automated tests (`pytest`) |

> The forecast is a **statistical estimate**, not a large language model. No API key is needed.

## Run on Windows (step by step)

1. **Install Python** from <https://www.python.org/downloads/>. On the first installer screen,
   tick **"Add python.exe to PATH"**. Check it with `python --version` in a new terminal.
2. **Open the folder in VS Code:** File → Open Folder → choose `ornacast-ai`. Open a terminal with
   ``Ctrl+` `` (PowerShell is fine).
3. **Create a virtual environment:**
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```
   If PowerShell blocks the script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use Command Prompt and `.venv\Scripts\activate.bat`.
4. **Install dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```
5. **Initialize the database + demo data** (optional — `python app.py` does this automatically on first start):
   ```powershell
   python -c "import database; database.init_db()"
   ```
6. **Start the app:**
   ```powershell
   python app.py
   ```
7. **Open it in your browser:** <http://127.0.0.1:5000>
8. **Stop / restart:** click in the terminal and press `Ctrl+C` to stop. To restart, run `python app.py` again
   (activate the virtual environment first if you opened a new terminal). Your data is kept in `ornacast.db`.

## Using the app

- **Demo data** is labelled with a "Demo" badge. Use *Reset demo* or *Delete demo* in the left menu
  (your own products and sales are never touched).
- **Sales:** pick a product — price and total fill in automatically; stock goes down when you save a sale.
- **Sales Forecast:** choose product + 7/30/90 days, click **Generate Forecast**.
- **Reports:** daily/weekly/monthly summaries, category revenue, best sellers, forecast vs actual, CSV export.

## Run the tests

```powershell
pytest
```

## How the forecast works

1. Take the last 28 days of daily units (days without sales count as 0).
2. Recent days get a higher weight (weighted moving average).
3. Add a damped trend (up or down) from comparing the two halves of the window.
4. Fewer than 14 days of history → plain average, labelled *low confidence*. No sales → no estimate.
5. Revenue = estimated units × average selling price.

To use a real AI model later, write a function with the same inputs/outputs as `forecasting.forecast()` and call it from `app.py`.

## Ideas to practise

Add seasonal factors for Diwali/wedding season, per-category forecasts, a login page, or an LLM-written insights summary.
