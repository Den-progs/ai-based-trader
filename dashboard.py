"""
dashboard.py — web dashboard for the trading bot.
Run alongside main.py: python dashboard.py
Open http://localhost:5000 in your browser.

You and your friend each run this with your own Alpaca API keys — you'll see
your own separate portfolios, positions, and trades.

Note: the Bot Activity feed (Llama decisions) reads from data/activity_log.json
which only exists on the machine running main.py. If your friend isn't running
the bot, his activity feed will be empty.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest, GetPortfolioHistoryRequest
from alpaca.trading.enums import QueryOrderStatus, OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

load_dotenv()

app = Flask(__name__)

_live = (
    os.environ.get("LIVE_TRADING") == "true"
    and os.environ.get("CONFIRM_LIVE") == "YES_I_MEAN_IT"
)
trading_client = TradingClient(
    os.environ["ALPACA_API_KEY"],
    os.environ["ALPACA_SECRET_KEY"],
    paper=not _live,
)

ACTIVITY_LOG = Path(__file__).parent / "data" / "activity_log.json"
CONFIG_PATH  = Path(__file__).parent / "config.py"

# Settings exposed in the config editor (key, type, label)
EDITABLE_CONFIG = [
    ("LOOP_INTERVAL",              "int",   "Loop interval (seconds)"),
    ("QTY_PER_TRADE",              "int",   "Shares per stock trade"),
    ("MAX_POSITION_SHARES",        "int",   "Max shares per stock"),
    ("CRYPTO_TRADE_DOLLARS",       "int",   "$ per crypto trade"),
    ("MAX_CRYPTO_POSITION_VALUE",  "int",   "Max $ per crypto position"),
    ("CONFIDENCE_THRESHOLD",       "float", "Min Llama confidence (0–1)"),
    ("BUY_COOLDOWN_SECONDS",       "int",   "Buy cooldown (seconds)"),
    ("TAKE_PROFIT_PCT",            "float", "Take-profit % (0.05 = 5%)"),
    ("STOP_LOSS_PCT",              "float", "Stop-loss % (0.03 = 3%)"),
    ("THREAD_WORKERS",             "int",   "Parallel analysis threads"),
]


def read_config_values() -> dict:
    content = CONFIG_PATH.read_text(encoding="utf-8")
    result = {}
    for key, typ, _ in EDITABLE_CONFIG:
        m = re.search(rf'^{key}\s*=\s*([0-9.]+)', content, re.MULTILINE)
        if m:
            result[key] = float(m.group(1)) if typ == "float" else int(float(m.group(1)))
    return result


def write_config_value(key: str, raw: str) -> None:
    content = CONFIG_PATH.read_text(encoding="utf-8")
    content = re.sub(
        rf'^({key}\s*=\s*)[0-9.]+',
        rf'\g<1>{raw}',
        content,
        flags=re.MULTILINE,
    )
    CONFIG_PATH.write_text(content, encoding="utf-8")


def _is_crypto(symbol: str) -> bool:
    return "/" in symbol or symbol.endswith("USD")


HTML = """<!DOCTYPE html>
<html>
<head>
  <title>AI Trader</title>
  <meta charset="utf-8">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #0d1117; color: #c9d1d9; font-family: 'Courier New', monospace; font-size: 13px; }

    /* ── Header ── */
    header {
      background: #161b22; border-bottom: 1px solid #30363d;
      padding: 10px 20px; display: flex; align-items: center; gap: 14px;
    }
    h1 { color: #58a6ff; font-size: 17px; letter-spacing: 1px; }
    .badge { padding: 3px 9px; border-radius: 4px; font-size: 11px; font-weight: bold; }
    .open   { background: #1a4731; color: #3fb950; }
    .closed { background: #3d1f1f; color: #f85149; }
    .stat { color: #79c0ff; font-size: 13px; }
    .stat strong { color: #e6edf3; }
    .updated { color: #6e7681; font-size: 11px; margin-left: auto; }
    #dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #3fb950; margin-left: 5px; vertical-align: middle; }
    #dot.spin { animation: pulse 0.6s infinite; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.15} }

    /* ── Layout ── */
    .chart-wrap { background: #0d1117; border-bottom: 1px solid #30363d; padding: 14px 20px; }
    .chart-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
    .chart-header h2 { color: #8b949e; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
    .period-btn {
      padding: 3px 10px; border-radius: 4px; border: 1px solid #30363d;
      background: #21262d; color: #8b949e; cursor: pointer; font-size: 11px; font-family: inherit;
    }
    .period-btn.active { background: #1f6feb; border-color: #388bfd; color: #e6edf3; }
    #portfolio-chart { max-height: 180px; }

    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1px; background: #21262d; margin: 1px 0;
    }
    .panel { background: #0d1117; padding: 14px 16px; overflow: auto; max-height: 380px; }
    .panel.full { grid-column: 1 / -1; max-height: 220px; }
    .panel h2 {
      color: #8b949e; font-size: 11px; text-transform: uppercase;
      letter-spacing: 1px; margin-bottom: 10px;
      border-bottom: 1px solid #21262d; padding-bottom: 6px;
      display: flex; align-items: center; gap: 8px;
    }

    /* ── Tables ── */
    table { width: 100%; border-collapse: collapse; }
    th { color: #6e7681; font-size: 10px; text-transform: uppercase; padding: 3px 7px; text-align: left; }
    td { padding: 5px 7px; border-bottom: 1px solid #161b22; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: #161b22; }

    /* ── Colors ── */
    .pos  { color: #3fb950; }
    .neg  { color: #f85149; }
    .buy  { color: #3fb950; font-weight: bold; }
    .sell { color: #f85149; font-weight: bold; }
    .hold { color: #6e7681; }
    .conf { color: #6e7681; }
    .reason { color: #8b949e; max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .tag { font-size: 10px; color: #6e7681; background: #21262d; padding: 1px 5px; border-radius: 3px; }
    .no-data { color: #6e7681; padding: 18px; text-align: center; }

    /* ── Buttons ── */
    .btn {
      padding: 3px 9px; border-radius: 4px; border: none; cursor: pointer;
      font-size: 11px; font-family: inherit; font-weight: bold;
    }
    .btn-sell { background: #3d1f1f; color: #f85149; }
    .btn-sell:hover { background: #6e2020; }
    .btn-buy  { background: #1a4731; color: #3fb950; }
    .btn-buy:hover  { background: #1e5c3a; }
    .btn-save { background: #1f6feb; color: #e6edf3; padding: 5px 14px; font-size: 12px; }
    .btn-save:hover { background: #388bfd; }

    /* ── Trade form ── */
    .trade-form {
      display: flex; gap: 6px; margin-top: 10px; padding-top: 10px;
      border-top: 1px solid #21262d; align-items: center; flex-wrap: wrap;
    }
    .trade-form input {
      background: #161b22; border: 1px solid #30363d; border-radius: 4px;
      color: #e6edf3; padding: 4px 8px; font-family: inherit; font-size: 12px;
    }
    .trade-form input:focus { outline: none; border-color: #388bfd; }
    .trade-form input.sym { width: 90px; text-transform: uppercase; }
    .trade-form input.qty { width: 70px; }
    #trade-msg { font-size: 11px; color: #6e7681; margin-top: 4px; width: 100%; }

    /* ── Activity filter ── */
    .filter-row { display: flex; gap: 5px; margin-left: auto; }
    .filter-btn {
      padding: 2px 7px; border-radius: 3px; border: 1px solid #30363d;
      background: #161b22; color: #6e7681; cursor: pointer; font-size: 10px; font-family: inherit;
    }
    .filter-btn.active { border-color: #58a6ff; color: #58a6ff; background: #0d1f3c; }

    /* ── Config editor ── */
    .config-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; margin-bottom: 10px; }
    .config-row { display: flex; flex-direction: column; gap: 2px; }
    .config-row label { font-size: 10px; color: #6e7681; }
    .config-row input {
      background: #161b22; border: 1px solid #30363d; border-radius: 4px;
      color: #e6edf3; padding: 4px 8px; font-family: inherit; font-size: 12px; width: 100%;
    }
    .config-row input:focus { outline: none; border-color: #388bfd; }
    #config-msg { font-size: 11px; color: #3fb950; margin-left: 10px; }
    .restart-note { font-size: 10px; color: #6e7681; margin-top: 6px; }
  </style>
</head>
<body>

<header>
  <h1>AI TRADER</h1>
  <span id="market-badge" class="badge closed">...</span>
  <span class="stat">Cash: <strong id="cash">...</strong></span>
  <span class="stat">Portfolio: <strong id="portfolio">...</strong></span>
  <span class="updated">Updated: <span id="updated">--:--:--</span><span id="dot"></span></span>
</header>

<!-- Portfolio chart -->
<div class="chart-wrap">
  <div class="chart-header">
    <h2>Portfolio Value</h2>
    <button class="period-btn active" onclick="loadChart('1D',this)">1D</button>
    <button class="period-btn" onclick="loadChart('1W',this)">1W</button>
    <button class="period-btn" onclick="loadChart('1M',this)">1M</button>
  </div>
  <canvas id="portfolio-chart"></canvas>
</div>

<div class="grid">

  <!-- Positions + manual trade -->
  <div class="panel">
    <h2>Open Positions</h2>
    <div id="positions"><p class="no-data">Loading...</p></div>
    <div class="trade-form">
      <input class="sym" id="t-symbol" placeholder="SYMBOL" maxlength="10">
      <input class="qty" id="t-qty" placeholder="Qty" type="number" min="0.000001" step="any">
      <button class="btn btn-buy"  onclick="manualTrade('BUY')">BUY</button>
      <button class="btn btn-sell" onclick="manualTrade('SELL')">SELL</button>
      <div id="trade-msg"></div>
    </div>
  </div>

  <!-- Activity feed -->
  <div class="panel">
    <h2>
      Bot Activity
      <span class="filter-row">
        <button class="filter-btn active" onclick="setFilter('ALL',this)">ALL</button>
        <button class="filter-btn" onclick="setFilter('BUY',this)">BUY</button>
        <button class="filter-btn" onclick="setFilter('SELL',this)">SELL</button>
        <button class="filter-btn" onclick="setFilter('HOLD',this)">HOLD</button>
      </span>
    </h2>
    <div id="activity"><p class="no-data">Loading...</p></div>
  </div>

  <!-- Recent trades -->
  <div class="panel">
    <h2>Recent Trades — last 24h</h2>
    <div id="trades"><p class="no-data">Loading...</p></div>
  </div>

  <!-- Config editor -->
  <div class="panel">
    <h2>Config Editor</h2>
    <div class="config-grid" id="config-inputs">Loading...</div>
    <button class="btn btn-save" onclick="saveConfig()">Save</button>
    <span id="config-msg"></span>
    <p class="restart-note">* Changes take effect after restarting main.py</p>
  </div>

</div>

<script>
  const $ = id => document.getElementById(id);
  let activityData = [];
  let activityFilter = 'ALL';
  let chart = null;

  // ── Formatters ──
  function fmtPct(v) {
    const n = parseFloat(v) * 100;
    return `<span class="${n>=0?'pos':'neg'}">${n>=0?'+':''}${n.toFixed(2)}%</span>`;
  }
  function fmtPl(v) {
    const n = parseFloat(v);
    return `<span class="${n>=0?'pos':'neg'}">${n>=0?'+$':'-$'}${Math.abs(n).toFixed(2)}</span>`;
  }
  function fmtMoney(v) { return '$' + parseFloat(v||0).toFixed(2); }
  function fmtTime(ts) { return ts ? new Date(ts).toLocaleTimeString() : ''; }

  // ── Main data refresh ──
  function refresh() {
    $('dot').classList.add('spin');
    fetch('/api/data').then(r=>r.json()).then(d => {

      const badge = $('market-badge');
      badge.textContent = d.market_open ? 'MARKET OPEN' : 'MARKET CLOSED';
      badge.className = 'badge ' + (d.market_open ? 'open' : 'closed');
      $('cash').textContent = fmtMoney(d.cash);
      $('portfolio').textContent = fmtMoney(d.portfolio_value);
      $('updated').textContent = d.updated + ' ';

      // Positions
      if (!d.positions.length) {
        $('positions').innerHTML = '<p class="no-data">No open positions</p>';
      } else {
        let h = '<table><tr><th>Symbol</th><th>Qty</th><th>Value</th><th>P&L%</th><th>P&L$</th><th></th></tr>';
        d.positions.forEach(p => {
          const qty = parseFloat(p.qty).toFixed(6).replace(/\.?0+$/,'');
          h += `<tr>
            <td>${p.symbol}</td>
            <td>${qty}</td>
            <td>${fmtMoney(p.market_value)}</td>
            <td>${fmtPct(p.unrealized_plpc)}</td>
            <td>${fmtPl(p.unrealized_pl)}</td>
            <td><button class="btn btn-sell" onclick="quickSell('${p.symbol}',${p.qty})">Sell All</button></td>
          </tr>`;
        });
        $('positions').innerHTML = h + '</table>';
      }

      // Activity
      activityData = d.activity;
      renderActivity();

      // Trades
      if (!d.trades.length) {
        $('trades').innerHTML = '<p class="no-data">No trades in the last 24h</p>';
      } else {
        let h = '<table><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Price</th></tr>';
        d.trades.forEach(t => {
          const cls = t.side==='buy' ? 'buy' : 'sell';
          h += `<tr>
            <td>${fmtTime(t.ts)}</td>
            <td>${t.symbol}</td>
            <td><span class="${cls}">${t.side.toUpperCase()}</span></td>
            <td>${t.qty}</td>
            <td>${fmtMoney(t.price)}</td>
          </tr>`;
        });
        $('trades').innerHTML = h + '</table>';
      }

      $('dot').classList.remove('spin');
    }).catch(()=> $('dot').classList.remove('spin'));
  }

  // ── Activity filter ──
  function setFilter(f, btn) {
    activityFilter = f;
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    renderActivity();
  }

  function renderActivity() {
    const filtered = activityFilter === 'ALL'
      ? activityData
      : activityData.filter(a => a.action === activityFilter);

    if (!filtered.length) {
      $('activity').innerHTML = '<p class="no-data">' + (activityData.length ? 'No '+activityFilter+' signals' : 'No activity yet — start main.py') + '</p>';
      return;
    }
    let h = '<table><tr><th>Time</th><th>Symbol</th><th>Type</th><th>Action</th><th>Conf</th><th>Reason</th></tr>';
    filtered.forEach(a => {
      const cls = a.action==='BUY' ? 'buy' : a.action==='SELL' ? 'sell' : 'hold';
      h += `<tr>
        <td>${fmtTime(a.ts)}</td>
        <td>${a.symbol}</td>
        <td><span class="tag">${a.type}</span></td>
        <td><span class="${cls}">${a.action}</span></td>
        <td class="conf">${(a.confidence*100).toFixed(0)}%</td>
        <td class="reason" title="${a.reason}">${a.reason}</td>
      </tr>`;
    });
    $('activity').innerHTML = h + '</table>';
  }

  // ── Portfolio chart ──
  function loadChart(period, btn) {
    document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    fetch('/api/portfolio-history?period=' + period).then(r=>r.json()).then(d => {
      const labels = d.points.map(p => new Date(p.ts).toLocaleString());
      const values = d.points.map(p => p.equity);
      if (chart) chart.destroy();
      chart = new Chart($('portfolio-chart'), {
        type: 'line',
        data: {
          labels,
          datasets: [{
            data: values,
            borderColor: '#58a6ff',
            backgroundColor: 'rgba(88,166,255,0.08)',
            borderWidth: 1.5,
            pointRadius: 0,
            fill: true,
            tension: 0.3,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: true,
          plugins: { legend: { display: false }, tooltip: {
            callbacks: { label: ctx => '$' + ctx.parsed.y.toFixed(2) }
          }},
          scales: {
            x: { display: false },
            y: {
              grid: { color: '#21262d' },
              ticks: { color: '#6e7681', callback: v => '$'+v.toFixed(0) }
            }
          }
        }
      });
    });
  }

  // ── Manual trade ──
  function manualTrade(action) {
    const symbol = $('t-symbol').value.trim().toUpperCase();
    const qty = parseFloat($('t-qty').value);
    if (!symbol || !qty || qty <= 0) { $('trade-msg').textContent = 'Enter a symbol and quantity.'; return; }
    $('trade-msg').textContent = 'Submitting...';
    fetch('/api/trade', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({symbol, action, qty})
    }).then(r=>r.json()).then(d => {
      if (d.ok) {
        $('trade-msg').textContent = action + ' ' + qty + ' ' + symbol + ' submitted.';
        $('t-symbol').value = '';
        $('t-qty').value = '';
        setTimeout(refresh, 1500);
      } else {
        $('trade-msg').textContent = 'Error: ' + d.error;
      }
    }).catch(e => { $('trade-msg').textContent = 'Request failed.'; });
  }

  function quickSell(symbol, qty) {
    if (!confirm('Sell all ' + qty + ' of ' + symbol + '?')) return;
    $('trade-msg').textContent = 'Selling ' + symbol + '...';
    fetch('/api/trade', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({symbol, action:'SELL', qty})
    }).then(r=>r.json()).then(d => {
      $('trade-msg').textContent = d.ok ? 'Sold ' + symbol : 'Error: ' + d.error;
      if (d.ok) setTimeout(refresh, 1500);
    });
  }

  // ── Config editor ──
  function loadConfig() {
    fetch('/api/config').then(r=>r.json()).then(d => {
      let h = '';
      Object.entries(d.values).forEach(([k, v]) => {
        h += `<div class="config-row">
          <label>${d.labels[k]}</label>
          <input id="cfg-${k}" type="number" step="${d.types[k]==='float'?'0.01':'1'}" value="${v}">
        </div>`;
      });
      $('config-inputs').innerHTML = h;
    });
  }

  function saveConfig() {
    const inputs = document.querySelectorAll('#config-inputs input');
    const data = {};
    inputs.forEach(inp => {
      const key = inp.id.replace('cfg-', '');
      data[key] = parseFloat(inp.value);
    });
    $('config-msg').textContent = 'Saving...';
    fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(data)
    }).then(r=>r.json()).then(d => {
      $('config-msg').textContent = d.ok ? 'Saved! Restart main.py to apply.' : 'Error saving.';
      setTimeout(() => { $('config-msg').textContent = ''; }, 4000);
    });
  }

  // ── Init ──
  refresh();
  loadConfig();
  loadChart('1D', document.querySelector('.period-btn.active'));
  setInterval(refresh, 10000);
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/data")
def api_data():
    try:
        clock = trading_client.get_clock()
        market_open = clock.is_open
    except Exception:
        market_open = False

    try:
        account = trading_client.get_account()
        cash = float(account.cash)
        portfolio_value = float(account.portfolio_value)
    except Exception:
        cash = portfolio_value = 0.0

    try:
        positions = [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
            }
            for p in trading_client.get_all_positions()
        ]
        positions.sort(key=lambda x: x["unrealized_pl"], reverse=True)
    except Exception:
        positions = []

    try:
        since = datetime.now(timezone.utc) - timedelta(days=1)
        orders = trading_client.get_orders(
            GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=since, limit=30)
        )
        trades = [
            {
                "symbol": o.symbol,
                "side": o.side.value,
                "qty": str(o.qty),
                "price": str(o.filled_avg_price),
                "ts": str(o.filled_at),
            }
            for o in orders if o.filled_at
        ]
    except Exception:
        trades = []

    activity = []
    if ACTIVITY_LOG.exists():
        try:
            activity = json.loads(ACTIVITY_LOG.read_text())[-50:][::-1]
        except Exception:
            pass

    return jsonify({
        "market_open": market_open,
        "cash": cash,
        "portfolio_value": portfolio_value,
        "positions": positions,
        "trades": trades,
        "activity": activity,
        "updated": datetime.now().strftime("%H:%M:%S"),
    })


@app.route("/api/portfolio-history")
def api_portfolio_history():
    period = request.args.get("period", "1D")
    timeframe = "15Min" if period == "1D" else "1H" if period == "1W" else "1D"
    try:
        history = trading_client.get_portfolio_history(
            GetPortfolioHistoryRequest(period=period, timeframe=timeframe)
        )
        points = [
            {"ts": ts * 1000, "equity": eq}
            for ts, eq in zip(history.timestamp, history.equity)
            if eq is not None
        ]
        return jsonify({"points": points})
    except Exception as e:
        return jsonify({"points": [], "error": str(e)})


@app.route("/api/config", methods=["GET"])
def api_config_get():
    return jsonify({
        "values":  read_config_values(),
        "labels":  {k: lbl for k, _, lbl in EDITABLE_CONFIG},
        "types":   {k: typ for k, typ, _  in EDITABLE_CONFIG},
    })


@app.route("/api/config", methods=["POST"])
def api_config_post():
    data = request.json or {}
    allowed = {k for k, _, _ in EDITABLE_CONFIG}
    for key, value in data.items():
        if key in allowed:
            write_config_value(key, str(value))
    return jsonify({"ok": True})


@app.route("/api/trade", methods=["POST"])
def api_trade():
    data = request.json or {}
    symbol = data.get("symbol", "").upper().strip()
    action = data.get("action", "").upper()
    qty    = float(data.get("qty", 0))

    if not symbol or action not in ("BUY", "SELL") or qty <= 0:
        return jsonify({"ok": False, "error": "Invalid symbol, action, or qty"}), 400

    try:
        tif = TimeInForce.GTC if _is_crypto(symbol) else TimeInForce.DAY
        side = OrderSide.BUY if action == "BUY" else OrderSide.SELL
        order = trading_client.submit_order(MarketOrderRequest(
            symbol=symbol, qty=qty, side=side, time_in_force=tif,
        ))
        return jsonify({"ok": True, "order": str(order.id)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    print("[dashboard] Starting at http://localhost:5000")
    app.run(debug=False, port=5000)
