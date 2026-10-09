/* app.js - small helpers: menu, delete confirmation, form validation, charts, forecast screen */

// ---- Mobile menu
document.getElementById("menuToggle")?.addEventListener("click", () =>
  document.getElementById("sidebar").classList.toggle("open"));

// ---- Confirm before destructive actions
document.querySelectorAll("form[data-confirm]").forEach(f =>
  f.addEventListener("submit", e => { if (!confirm(f.dataset.confirm)) e.preventDefault(); }));

// ---- Friendly client-side validation (server validates again)
document.querySelectorAll("form[data-validate]").forEach(form => {
  form.addEventListener("submit", e => {
    let ok = true;
    form.querySelectorAll("input, select").forEach(el => {
      el.classList.remove("invalid");
      if (!el.checkValidity()) { el.classList.add("invalid"); ok = false; }
    });
    if (!ok) { e.preventDefault(); alert("Please fix the highlighted fields. Quantity must be at least 1 and prices cannot be negative."); }
  });
});

// ---- Sales form: auto-fill price and calculate total
(function () {
  const sel = document.getElementById("saleProduct");
  if (!sel) return;
  const qty = document.getElementById("saleQty"), price = document.getElementById("salePrice"), total = document.getElementById("saleTotal");
  const inr = n => "₹" + Math.round(n).toLocaleString("en-IN");
  function update() { total.textContent = inr((+qty.value || 0) * (+price.value || 0)); }
  sel.addEventListener("change", () => {
    const opt = sel.selectedOptions[0];
    if (opt && opt.dataset.price) { price.value = opt.dataset.price; qty.max = opt.dataset.stock; }
    update();
  });
  qty.addEventListener("input", update); price.addEventListener("input", update);
})();

// ---- Chart helpers (Chart.js)
const PALETTE = ["#b9a7d9", "#c98a95", "#8fb8a6", "#e2b98a", "#8aa6c9", "#d6a3c7", "#a3a3a3"];
const OrnaCharts = {
  bar(id, labels, data, label) {
    new Chart(document.getElementById(id), { type: "bar",
      data: { labels, datasets: [{ label, data, backgroundColor: "#b9a7d9", borderRadius: 8 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
                 scales: { y: { beginAtZero: true, ticks: { callback: v => "₹" + v.toLocaleString("en-IN") } } } } });
  },
  line(id, labels, data, label) {
    new Chart(document.getElementById(id), { type: "line",
      data: { labels, datasets: [{ label, data, borderColor: "#c98a95", backgroundColor: "rgba(201,138,149,.15)", fill: true, tension: .35, pointRadius: 2 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } } });
  },
  doughnut(id, labels, data) {
    new Chart(document.getElementById(id), { type: "doughnut",
      data: { labels, datasets: [{ data, backgroundColor: PALETTE }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom" } } } });
  },
};

// ---- Forecast screen
const OrnaForecast = {
  chart: null,
  init() {
    const form = document.getElementById("forecastForm");
    form.addEventListener("submit", e => { e.preventDefault(); this.run(); });
  },
  async run() {
    const btn = document.getElementById("fcButton"), err = document.getElementById("fcError");
    const pid = document.getElementById("fcProduct").value, days = document.getElementById("fcDays").value;
    err.hidden = true; btn.disabled = true; btn.textContent = "Calculating…";
    try {
      const res = await fetch(`/api/forecast?days=${days}` + (pid ? `&product_id=${pid}` : ""));
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Something went wrong.");
      this.show(data);
    } catch (ex) {
      err.textContent = ex.message; err.hidden = false;
    } finally { btn.disabled = false; btn.textContent = "Generate Forecast"; }
  },
  show(d) {
    document.getElementById("fcEmpty").hidden = true;
    document.getElementById("fcResult").hidden = false;
    const none = d.confidence === "none";
    document.getElementById("fcUnits").textContent = none ? "No estimate" : d.total_units + " units";
    document.getElementById("fcRevenue").textContent = none ? "—" : "₹" + Math.round(d.total_revenue).toLocaleString("en-IN");
    document.getElementById("fcMethod").textContent = d.method;
    document.getElementById("fcConfidence").textContent = d.confidence.charAt(0).toUpperCase() + d.confidence.slice(1);
    document.getElementById("fcExplain").textContent = d.explanation;
    const bt = d.backtest;
    document.getElementById("fcBacktest").textContent = bt && bt.error_pct !== null
      ? `Back-test: a forecast made ${bt.period_days >= 30 ? 30 : 7} days ago predicted ${bt.predicted_units} units; ${bt.actual_units} were actually sold (${bt.error_pct}% difference).`
      : "Back-test unavailable: not enough earlier history to check this forecast against real results.";

    const fmt = s => s.slice(8, 10) + "-" + s.slice(5, 7);
    const labels = d.history.map(h => fmt(h.date)).concat(d.daily.map(x => fmt(x.date)));
    const actual = d.history.map(h => h.units).concat(d.daily.map(() => null));
    const fc = d.history.map(() => null).concat(d.daily.map(x => x.units));
    if (this.chart) this.chart.destroy();
    this.chart = new Chart(document.getElementById("fcChart"), { type: "line",
      data: { labels, datasets: [
        { label: "Actual units", data: actual, borderColor: "#7c63ad", backgroundColor: "rgba(185,167,217,.25)", fill: true, tension: .25, pointRadius: 0 },
        { label: "Forecast (estimate)", data: fc, borderColor: "#c98a95", borderDash: [6, 4], tension: .25, pointRadius: 0 } ] },
      options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
                 scales: { y: { beginAtZero: true, title: { display: true, text: "Units per day" } }, x: { ticks: { maxTicksLimit: 10 } } } } });
  },
};
