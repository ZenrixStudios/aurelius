"""
Aurelius Dashboard — Flask server
Serves a live web UI showing sentiment analysis results.
Run alongside aurelius_agent.py
"""

from flask import Flask, jsonify, render_template_string
from aurelius_agent import analysis_store, store_lock, DASHBOARD_PORT, start_scheduler
import threading

app = Flask(__name__)

# ─────────────────────────────────────────────
#  DASHBOARD HTML (self-contained, no CDN needed)
# ─────────────────────────────────────────────
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Aurelius · Forex Sentiment</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;700&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

    :root {
      --bg:        #0a0a0a;
      --surface:   #111111;
      --border:    #1e1e1e;
      --text:      #d0d0d0;
      --muted:     #555;
      --accent:    #c8a96e;
      --red:       #c0392b;
      --orange:    #e67e22;
      --green:     #27ae60;
      --blue:      #2980b9;
      --hawkish:   #e74c3c;
      --dovish:    #3498db;
      --neutral:   #666;
    }

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'IBM Plex Mono', monospace;
      min-height: 100vh;
    }

    /* ── HEADER ─────────────────────────── */
    .header {
      border-bottom: 1px solid var(--border);
      padding: 20px 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky; top: 0;
      background: var(--bg);
      z-index: 100;
    }
    .logo {
      display: flex; align-items: baseline; gap: 12px;
    }
    .logo-name {
      font-size: 20px; font-weight: 700; color: #e0e0e0;
      letter-spacing: 4px;
    }
    .logo-sub {
      font-size: 9px; color: var(--muted); letter-spacing: 3px;
      text-transform: uppercase;
    }
    .status-bar {
      display: flex; align-items: center; gap: 20px;
    }
    .pulse {
      width: 8px; height: 8px; border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 6px var(--green);
      animation: pulse 2s ease-in-out infinite;
    }
    .pulse.stale { background: var(--orange); box-shadow: 0 0 6px var(--orange); }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50%       { opacity: 0.3; }
    }
    .last-updated { font-size: 10px; color: var(--muted); }

    /* ── METRICS ROW ─────────────────────── */
    .metrics {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 1px;
      border-bottom: 1px solid var(--border);
      background: var(--border);
    }
    .metric {
      background: var(--surface);
      padding: 18px 24px;
    }
    .metric-label {
      font-size: 9px; color: var(--muted);
      letter-spacing: 2px; text-transform: uppercase;
      margin-bottom: 6px;
    }
    .metric-value {
      font-size: 28px; font-weight: 700; color: #e0e0e0;
    }
    .metric-value.red    { color: var(--red); }
    .metric-value.orange { color: var(--orange); }
    .metric-value.accent { color: var(--accent); }

    /* ── ALERT BANNER ────────────────────── */
    .alert-banner {
      background: var(--red);
      color: #fff;
      padding: 10px 32px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 2px;
      display: none;
    }
    .alert-banner.visible { display: block; }

    /* ── MAIN GRID ───────────────────────── */
    .main {
      display: grid;
      grid-template-columns: 2fr 1fr;
      gap: 0;
      min-height: calc(100vh - 130px);
    }

    .panel {
      border-right: 1px solid var(--border);
      overflow-y: auto;
    }
    .panel-header {
      padding: 14px 24px;
      border-bottom: 1px solid var(--border);
      font-size: 9px;
      color: var(--muted);
      letter-spacing: 3px;
      text-transform: uppercase;
      position: sticky; top: 0;
      background: var(--surface);
    }

    /* ── CARD ────────────────────────────── */
    .card {
      border-bottom: 1px solid var(--border);
      padding: 16px 24px;
      transition: background 0.15s;
    }
    .card:hover { background: #141414; }
    .card.high { border-left: 3px solid var(--red); }
    .card.medium { border-left: 3px solid var(--orange); }
    .card.low { border-left: 3px solid var(--green); }

    .card-top {
      display: flex; align-items: center; gap: 10px;
      margin-bottom: 6px;
    }
    .badge {
      font-size: 9px; font-weight: 700; letter-spacing: 1px;
      padding: 2px 7px; border-radius: 2px;
    }
    .badge.HIGH   { background: var(--red);    color: #fff; }
    .badge.MEDIUM { background: var(--orange);  color: #fff; }
    .badge.LOW    { background: #1e3a28; color: var(--green); }

    .sentiment-tag {
      font-size: 9px; padding: 2px 7px; border-radius: 2px; font-weight: 600;
    }
    .Hawkish  { background: rgba(231,76,60,0.15);  color: #e74c3c; }
    .Dovish   { background: rgba(52,152,219,0.15); color: #3498db; }
    .Neutral  { background: rgba(100,100,100,0.15);color: #888; }
    .Risk-On  { background: rgba(46,204,113,0.15); color: #2ecc71; }
    .Risk-Off { background: rgba(230,126,34,0.15); color: #e67e22; }

    .pair-tag {
      font-size: 9px; padding: 2px 7px; border-radius: 2px;
      background: rgba(200,169,110,0.1); color: var(--accent);
      font-weight: 600;
    }

    .card-headline {
      font-size: 12px; color: #ccc; line-height: 1.5;
      margin-bottom: 4px;
    }
    .card-headline a {
      color: #ccc; text-decoration: none;
    }
    .card-headline a:hover { color: var(--accent); }
    .card-summary {
      font-size: 11px; color: #666; line-height: 1.5;
    }
    .card-footer {
      margin-top: 8px;
      display: flex; align-items: center; gap: 14px;
      font-size: 10px; color: var(--muted);
    }
    .direction { color: #999; }

    .divergence-flag {
      font-size: 10px; color: #f39c12; margin-top: 4px;
      display: flex; align-items: center; gap: 5px;
    }

    /* ── SIDE PANEL ──────────────────────── */
    .side-panel { overflow-y: auto; }

    .mini-card {
      border-bottom: 1px solid var(--border);
      padding: 12px 20px;
    }
    .mini-card .card-headline { font-size: 11px; }
    .mini-card .card-footer   { font-size: 9px; }

    .empty-state {
      padding: 40px 24px;
      text-align: center;
      color: var(--muted);
      font-size: 11px;
      line-height: 2;
    }

    /* ── SCROLLBAR ───────────────────────── */
    ::-webkit-scrollbar { width: 4px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: #333; border-radius: 2px; }
  </style>
</head>
<body>

<header class="header">
  <div class="logo">
    <span class="logo-name">AURELIUS</span>
    <span class="logo-sub">Forex Sentiment Aggregator</span>
  </div>
  <div class="status-bar">
    <div class="pulse" id="pulse"></div>
    <span class="last-updated" id="lastUpdated">Connecting…</span>
    <span style="font-size:10px;color:#444">EUR/USD · GBP/USD</span>
  </div>
</header>

<div class="metrics">
  <div class="metric">
    <div class="metric-label">Total Signals</div>
    <div class="metric-value" id="mTotal">—</div>
  </div>
  <div class="metric">
    <div class="metric-label">Red Folder</div>
    <div class="metric-value red" id="mRed">—</div>
  </div>
  <div class="metric">
    <div class="metric-label">Divergence Flags</div>
    <div class="metric-value orange" id="mDiv">—</div>
  </div>
  <div class="metric">
    <div class="metric-label">Dominant Tone</div>
    <div class="metric-value accent" id="mTone">—</div>
  </div>
</div>

<div class="alert-banner" id="alertBanner"></div>

<div class="main">
  <div class="panel">
    <div class="panel-header">All Signals · Newest First</div>
    <div id="allCards"></div>
  </div>
  <div class="side-panel">
    <div class="panel-header">🔴 Red Folder Only</div>
    <div id="redCards"></div>
  </div>
</div>

<script>
  const POLL_MS = 30000;

  function timeAgo(iso) {
    if (!iso) return '';
    const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
    if (diff < 60)    return diff + 's ago';
    if (diff < 3600)  return Math.floor(diff/60) + 'm ago';
    if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
    return Math.floor(diff/86400) + 'd ago';
  }

  function dominantTone(analyses) {
    const counts = {};
    (analyses||[]).forEach(a => {
      const s = a.sentiment || 'Neutral';
      counts[s] = (counts[s]||0) + 1;
    });
    if (!Object.keys(counts).length) return '—';
    return Object.entries(counts).sort((a,b)=>b[1]-a[1])[0][0];
  }

  function buildCard(r, mini=false) {
    const pairs = (r.pairs_affected||[]).map(p =>
      `<span class="pair-tag">${p}</span>`).join(' ');
    const level = (r.impact_level||'LOW').toUpperCase();
    const sent  = r.sentiment || 'Neutral';
    const sentClass = sent.replace(/[^a-zA-Z]/g,'');
    const div   = r.divergence_signal
      ? `<div class="divergence-flag">⚠ DIVERGENCE SIGNAL · ${r.divergence_reason||''}</div>` : '';

    if (mini) {
      return `
        <div class="mini-card ${level.toLowerCase()}">
          <div class="card-top">
            <span class="badge ${level}">${level}</span>
            <span class="sentiment-tag ${sentClass}">${sent}</span>
            ${pairs}
          </div>
          <div class="card-headline">
            <a href="${r.link||'#'}" target="_blank">${r.headline||''}</a>
          </div>
          <div class="card-footer">
            <span>${r.source||''}</span>
            <span>${timeAgo(r.analysed_at)}</span>
          </div>
          ${div}
        </div>`;
    }

    return `
      <div class="card ${level.toLowerCase()}">
        <div class="card-top">
          <span class="badge ${level}">${level}</span>
          <span class="sentiment-tag ${sentClass}">${sent}</span>
          ${pairs}
        </div>
        <div class="card-headline">
          <a href="${r.link||'#'}" target="_blank">${r.headline||''}</a>
        </div>
        <div class="card-summary">${r.summary||''}</div>
        ${div}
        <div class="card-footer">
          <span>${r.source||''}</span>
          <span class="direction">${r.direction||''}</span>
          <span>·</span>
          <span>${timeAgo(r.analysed_at)}</span>
          <span>·</span>
          <span>Score: ${(r.impact_score||0).toFixed(2)}</span>
        </div>
      </div>`;
  }

  async function poll() {
    try {
      const res  = await fetch('/api/data');
      const data = await res.json();

      // Metrics
      document.getElementById('mTotal').textContent = (data.analyses||[]).length;
      document.getElementById('mRed').textContent   = (data.red_alerts||[]).length;
      document.getElementById('mDiv').textContent   = (data.divergence_flags||[]).length;
      document.getElementById('mTone').textContent  = dominantTone(data.analyses);

      // Timestamp
      const lu = data.last_updated;
      document.getElementById('lastUpdated').textContent = lu
        ? 'Updated ' + timeAgo(lu) : 'Waiting for first cycle…';

      // Pulse
      const stale = lu && (Date.now() - new Date(lu)) > 20 * 60 * 1000;
      document.getElementById('pulse').className = 'pulse' + (stale ? ' stale' : '');

      // Alert banner
      const banner = document.getElementById('alertBanner');
      if ((data.red_alerts||[]).length > 0) {
        banner.textContent = `🔴 ${data.red_alerts.length} RED FOLDER EVENT${data.red_alerts.length>1?'S':''} — CHECK IMMEDIATELY`;
        banner.classList.add('visible');
      } else {
        banner.classList.remove('visible');
      }

      // Cards
      const allEl = document.getElementById('allCards');
      const redEl = document.getElementById('redCards');

      if ((data.analyses||[]).length === 0) {
        allEl.innerHTML = '<div class="empty-state">No signals yet.<br>Aurelius is watching the feeds…</div>';
      } else {
        allEl.innerHTML = data.analyses.map(r => buildCard(r)).join('');
      }

      if ((data.red_alerts||[]).length === 0) {
        redEl.innerHTML = '<div class="empty-state">No red folder<br>events yet.<br>Stay patient.</div>';
      } else {
        redEl.innerHTML = data.red_alerts.map(r => buildCard(r, true)).join('');
      }

    } catch(e) {
      console.error('Poll error:', e);
      document.getElementById('lastUpdated').textContent = 'Connection error — retrying…';
    }
  }

  poll();
  setInterval(poll, POLL_MS);
</script>
</body>
</html>"""


@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/data")
def api_data():
    with store_lock:
        return jsonify({
            "last_updated":     analysis_store["last_updated"],
            "analyses":         analysis_store["analyses"],
            "red_alerts":       analysis_store["red_alerts"],
            "divergence_flags": analysis_store["divergence_flags"],
        })


@app.route("/api/trigger", methods=["POST"])
def api_trigger():
    """Manually trigger a cycle (useful for testing)."""
    from aurelius_agent import run_aurelius_cycle
    thread = threading.Thread(target=run_aurelius_cycle, daemon=True)
    thread.start()
    return jsonify({"status": "cycle triggered"})


if __name__ == "__main__":
    # Start Aurelius scheduler in background thread
    scheduler_thread = threading.Thread(target=start_scheduler, daemon=True)
    scheduler_thread.start()

    # Start Flask dashboard
    print(f"\n  Aurelius Dashboard → http://0.0.0.0:{DASHBOARD_PORT}\n")
    app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False)
