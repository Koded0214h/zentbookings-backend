from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.observability import metrics

router = APIRouter(prefix="/observability", tags=["observability"])


def _guard(token: str | None, header_token: str | None) -> None:
    """No-auth by default. Only enforced if OBSERVABILITY_TOKEN is configured."""
    expected = settings.OBSERVABILITY_TOKEN
    if expected and token != expected and header_token != expected:
        raise AppError(401, "unauthorized", "Observability token required.")


TokenQ = Annotated[str | None, Query()]
TokenH = Annotated[str | None, Header(alias="X-Observability-Token")]


@router.get("/metrics")
async def get_metrics(token: TokenQ = None, x_observability_token: TokenH = None) -> dict:
    _guard(token, x_observability_token)
    return metrics.snapshot()


@router.get("/logs")
async def get_logs(token: TokenQ = None, x_observability_token: TokenH = None) -> dict:
    _guard(token, x_observability_token)
    return metrics.logs()


@router.get("/prometheus", response_class=PlainTextResponse)
async def prometheus(token: TokenQ = None, x_observability_token: TokenH = None) -> str:
    _guard(token, x_observability_token)
    s = metrics.snapshot()
    lat = s["latencyMs"]
    lines = [
        "# HELP zent_requests_total Total HTTP requests observed",
        "# TYPE zent_requests_total counter",
        f"zent_requests_total {s['totalRequests']}",
        "# HELP zent_request_error_rate Share of 4xx+5xx responses",
        "# TYPE zent_request_error_rate gauge",
        f"zent_request_error_rate {s['errorRate']}",
        "# HELP zent_uptime_seconds Process uptime",
        "# TYPE zent_uptime_seconds gauge",
        f"zent_uptime_seconds {s['uptimeSeconds']}",
        "# HELP zent_request_latency_ms Request latency percentiles (ms)",
        "# TYPE zent_request_latency_ms gauge",
        *(f'zent_request_latency_ms{{quantile="{q}"}} {v}' for q, v in lat.items()),
    ]
    for cls, count in s["statusClasses"].items():
        lines.append(f'zent_responses_total{{class="{cls}"}} {count}')
    return "\n".join(lines) + "\n"


@router.get("", response_class=HTMLResponse)
async def dashboard(token: TokenQ = None, x_observability_token: TokenH = None) -> str:
    _guard(token, x_observability_token)
    qs = f"?token={token}" if token else ""
    return _PAGE.replace("__QS__", qs)


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Zent · Observability</title>
<style>
  :root{
    --bg:#0d1117; --panel:#161b22; --border:#272e39; --text:#e6edf3;
    --dim:#8b949e; --accent:#3fb950; --warn:#d29922; --err:#f85149; --blue:#58a6ff;
    --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
    font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
  header{display:flex;align-items:baseline;gap:14px;padding:18px 24px;
    border-bottom:1px solid var(--border)}
  header h1{font-size:16px;margin:0;letter-spacing:.3px}
  header .meta{color:var(--dim);font:12px/1 var(--mono)}
  #err{color:var(--err);font:12px/1 var(--mono)}
  main{padding:24px;max-width:1200px;margin:0 auto}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
  .kpi{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:14px}
  .kpi .label{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.6px}
  .kpi .value{font:600 24px/1.2 var(--mono);margin-top:6px}
  .kpi .sub{color:var(--dim);font:11px/1 var(--mono);margin-top:4px}
  section{margin-top:26px}
  section h2{font-size:12px;text-transform:uppercase;letter-spacing:.8px;
    color:var(--dim);margin:0 0 10px}
  .bar{display:flex;height:10px;border-radius:6px;overflow:hidden;background:var(--border)}
  .bar>span{display:block}
  .legend{display:flex;gap:16px;margin-top:8px;color:var(--dim);font:12px/1 var(--mono)}
  .legend b{color:var(--text)}
  table{width:100%;border-collapse:collapse;font:12px/1.6 var(--mono)}
  th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--border)}
  th{color:var(--dim);font-weight:500;position:sticky;top:0;background:var(--bg)}
  td.num{text-align:right}
  .wrap{background:var(--panel);border:1px solid var(--border);border-radius:10px;
    overflow:auto;max-height:340px}
  .s2{color:var(--accent)} .s3{color:var(--blue)} .s4{color:var(--warn)} .s5{color:var(--err)}
  .pill{padding:1px 7px;border-radius:20px;font-size:11px;border:1px solid var(--border)}
  .empty{color:var(--dim);padding:14px;font:12px/1 var(--mono)}
</style></head>
<body>
<header>
  <h1>Zent · Observability</h1>
  <span class="meta" id="uptime">–</span>
  <span class="meta" id="proc"></span>
  <span id="err"></span>
</header>
<main>
  <div class="grid" id="kpis"></div>

  <section>
    <h2>Responses by status class</h2>
    <div class="bar" id="statusbar"></div>
    <div class="legend" id="statuslegend"></div>
  </section>

  <section>
    <h2>Top routes</h2>
    <div class="wrap"><table id="routes">
      <thead><tr><th>Route</th><th class="num">Count</th><th class="num">Avg ms</th>
      <th class="num">Max ms</th><th class="num">5xx</th></tr></thead>
      <tbody></tbody></table></div>
  </section>

  <section>
    <h2>Recent errors</h2>
    <div class="wrap"><table id="errors">
      <thead><tr><th>Time</th><th>Status</th><th>Method</th><th>Path</th><th>Error</th></tr></thead>
      <tbody></tbody></table></div>
  </section>

  <section>
    <h2>Recent requests</h2>
    <div class="wrap"><table id="reqs">
      <thead><tr><th>Time</th><th>Status</th><th>Method</th><th>Path</th>
      <th class="num">ms</th><th>IP</th></tr></thead>
      <tbody></tbody></table></div>
  </section>
</main>
<script>
const QS = "__QS__";
const $ = s => document.querySelector(s);
const fmt = n => n >= 1000 ? (n/1000).toFixed(1)+"k" : String(n);
const dur = s => {
  s = Math.floor(s); const d=Math.floor(s/86400), h=Math.floor(s%86400/3600),
    m=Math.floor(s%3600/60);
  return (d?d+"d ":"")+(h?h+"h ":"")+(m?m+"m ":"")+(s%60)+"s";
};
const scls = st => "s"+String(st)[0];

function kpi(label, value, sub){
  return `<div class="kpi"><div class="label">${label}</div>
    <div class="value">${value}</div><div class="sub">${sub||""}</div></div>`;
}

async function tick(){
  let m, l;
  try{
    [m, l] = await Promise.all([
      fetch("metrics"+QS).then(r=>r.json()),
      fetch("logs"+QS).then(r=>r.json()),
    ]);
    $("#err").textContent = "";
  }catch(e){ $("#err").textContent = "fetch failed: "+e; return; }

  $("#uptime").textContent = "up "+dur(m.uptimeSeconds);
  $("#proc").textContent = `pid ${m.process.pid} · py ${m.process.python} · rss ${m.process.rssMb}MB`;

  const lat = m.latencyMs;
  $("#kpis").innerHTML = [
    kpi("Requests", fmt(m.totalRequests), (m.requestsPerSecond).toFixed(2)+" req/s"),
    kpi("Error rate", (m.errorRate*100).toFixed(2)+"%",
        (m.statusClasses["4xx"]||0)+" 4xx · "+(m.statusClasses["5xx"]||0)+" 5xx"),
    kpi("p50", lat.p50+" ms", "avg "+lat.avg+" ms"),
    kpi("p90", lat.p90+" ms", ""),
    kpi("p99", lat.p99+" ms", "max "+lat.max+" ms"),
    kpi("Samples", fmt(m.sampleSize), "latency window"),
  ].join("");

  const total = Object.values(m.statusClasses).reduce((a,b)=>a+b,0) || 1;
  const colors = {"2xx":"var(--accent)","3xx":"var(--blue)","4xx":"var(--warn)","5xx":"var(--err)"};
  $("#statusbar").innerHTML = Object.entries(m.statusClasses).map(([k,v])=>
    `<span style="width:${v/total*100}%;background:${colors[k]||'var(--dim)'}"></span>`).join("");
  $("#statuslegend").innerHTML = Object.entries(m.statusClasses).map(([k,v])=>
    `<span>${k} <b>${v}</b></span>`).join("");

  $("#routes tbody").innerHTML = m.topRoutes.length ? m.topRoutes.map(r=>
    `<tr><td>${r.route}</td><td class="num">${r.count}</td>
     <td class="num">${r.avgMs}</td><td class="num">${r.maxMs}</td>
     <td class="num ${r.errors?'s5':''}">${r.errors}</td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">no requests yet</td></tr>`;

  $("#errors tbody").innerHTML = l.recentErrors.length ? l.recentErrors.map(e=>
    `<tr><td>${e.ts}</td><td class="${scls(e.status)}">${e.status}</td>
     <td>${e.method}</td><td>${e.path}</td><td class="s5">${e.error||""}</td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">none</td></tr>`;

  $("#reqs tbody").innerHTML = l.recentRequests.length ? l.recentRequests.map(e=>
    `<tr><td>${e.ts}</td><td class="${scls(e.status)}">${e.status}</td>
     <td>${e.method}</td><td>${e.path}</td><td class="num">${e.ms}</td>
     <td>${e.ip||""}</td></tr>`).join("")
    : `<tr><td colspan="6" class="empty">none</td></tr>`;
}
tick();
setInterval(tick, 3000);
</script>
</body></html>
"""
