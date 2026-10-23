// TradeShift front-end: draws charts from the JSON each page embeds, fills the product
// search box, and shows slider values. Plain JavaScript, no build step, no external calls.

// Number formats for chart axes and tooltips; they mirror app/formatting.py (Feature 1).
const FORMATS = {
  usd_m: (v) => `US$${(v / 1e6).toLocaleString("en-US", { maximumFractionDigits: 1 })}m`,
  pct: (v) => `${v.toLocaleString("en-US", { maximumFractionDigits: 1 })}%`,
  hhi: (v) => Math.round(v).toLocaleString("en-US"),
  index: (v) => v.toLocaleString("en-US", { maximumFractionDigits: 1 }),
};

// "2018-07" -> "Jul 2018" for chart axes, matching month_label() in app/formatting.py.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monthLabel = (s) => (/^\d{4}-\d{2}$/.test(s) ? `${MONTHS[+s.slice(5, 7) - 1]} ${s.slice(0, 4)}` : s);

// Draws a dashed vertical line for each tariff event on line charts.
const eventMarks = {
  id: "eventMarks",
  afterDatasetsDraw(chart, _args, opts) {
    const { ctx, chartArea, scales } = chart;
    (opts.marks || []).forEach((m) => {
      const i = chart.data.labels.indexOf(m.month);
      if (i < 0) return;
      const x = scales.x.getPixelForValue(i);
      ctx.save();
      ctx.strokeStyle = "#8a94a6";
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.stroke();
      ctx.fillStyle = "#5c6b73";
      ctx.font = "11px system-ui, sans-serif";
      ctx.fillText(m.label, x + 4, chartArea.top + 12);
      ctx.restore();
    });
  },
};

function drawChart(spec) {
  const canvas = document.getElementById(`chart-${spec.id}`);
  if (!canvas || !window.Chart) return;
  const fmt = FORMATS[spec.y_format] || ((v) => v);
  const bar = spec.type === "bar";
  new Chart(canvas, {
    type: spec.type,
    data: {
      labels: spec.labels,
      datasets: spec.datasets.map((d) => ({
        label: d.label, data: d.data, borderColor: d.color, backgroundColor: bar ? d.color : d.color + "22",
        borderWidth: 2, pointRadius: 0, tension: 0.2, spanGaps: true,
      })),
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      indexAxis: bar ? "y" : "x",
      interaction: { mode: "index", intersect: false },
      scales: bar
        ? { x: { ticks: { callback: (v) => fmt(v) } } }
        : {
            y: { ticks: { callback: (v) => fmt(v) } },
            x: { ticks: { maxTicksLimit: 12, callback(v) { return monthLabel(this.getLabelForValue(v)); } } },
          },
      plugins: {
        legend: { display: !bar, position: "bottom" },
        tooltip: { callbacks: { title: (items) => monthLabel(items[0].label), label: (c) => `${c.dataset.label}: ${c.raw == null ? "–" : fmt(c.raw)}` } },
        eventMarks: { marks: spec.marks },
      },
    },
    plugins: [eventMarks],
  });
}

// Suggests products as the user types an HS code or keyword (uses this app's own API).
function productSearch(input) {
  const list = document.getElementById(input.getAttribute("list"));
  let timer;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2 || /^\d{6}$/.test(q)) return;
    timer = setTimeout(async () => {
      const res = await fetch(`/api/products?q=${encodeURIComponent(q)}`);
      const items = await res.json();
      list.innerHTML = items.map((p) => `<option value="${p.hs6}">${p.hs6} ${p.description || ""}</option>`).join("");
    }, 250);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("script[data-chart]").forEach((el) => drawChart(JSON.parse(el.textContent)));
  document.querySelectorAll("[data-product-search]").forEach(productSearch);
  document.querySelectorAll("input[type=range][data-output]").forEach((r) => {
    const out = r.parentElement.querySelector("output");
    r.addEventListener("input", () => { out.textContent = r.value; });
  });
});
