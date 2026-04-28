"""
Aurelius — Forex Sentiment Aggregator
Stoic, logical, focused only on what is objectively true.

Pairs:    EUR/USD, GBP/USD
Brain:    Gemini (Google Generative AI)
Memory:   ChromaDB (local vector store)
Sources:  ForexFactory RSS, Reuters RSS, Investing.com RSS
Delivery: Email (smtplib) + Dashboard (Flask)
"""

import os
import json
import time
import logging
import hashlib
import smtplib
import schedule
import threading
import feedparser
import requests
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
import google.generativeai as genai
import chromadb
from chromadb.utils import embedding_functions

# ─────────────────────────────────────────────
#  CONFIGURATION  (override via .env or env vars)
# ─────────────────────────────────────────────
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")
EMAIL_FROM          = os.getenv("AURELIUS_EMAIL_FROM", "you@gmail.com")
EMAIL_PASSWORD      = os.getenv("AURELIUS_EMAIL_PASSWORD", "your_app_password")
EMAIL_TO            = os.getenv("AURELIUS_EMAIL_TO", "you@gmail.com")
SMTP_HOST           = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT           = int(os.getenv("SMTP_PORT", "587"))
POLL_INTERVAL_MIN   = int(os.getenv("POLL_INTERVAL_MIN", "15"))   # minutes
DASHBOARD_PORT      = int(os.getenv("DASHBOARD_PORT", "5000"))
CHROMA_DB_PATH      = os.getenv("CHROMA_DB_PATH", "./aurelius_memory")

TARGET_CURRENCIES   = ["USD", "EUR", "GBP"]
TARGET_PAIRS        = ["EUR/USD", "GBP/USD"]
RED_FOLDER_KEYWORDS = [
    "interest rate", "rate decision", "fomc", "ecb", "boe", "bank of england",
    "federal reserve", "inflation", "cpi", "gdp", "nonfarm", "nfp",
    "employment", "unemployment", "monetary policy", "rate hike", "rate cut",
    "quantitative", "balance sheet", "forward guidance", "hawkish", "dovish"
]

RSS_FEEDS = [
    {
        "name": "Reuters Business",
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "currency_hint": None
    },
    {
        "name": "Reuters USD",
        "url": "https://feeds.reuters.com/reuters/USDollar",
        "currency_hint": "USD"
    },
    {
        "name": "Investing.com Forex",
        "url": "https://www.investing.com/rss/news_285.rss",
        "currency_hint": None
    },
    {
        "name": "Investing.com EUR/USD",
        "url": "https://www.investing.com/rss/news_301.rss",
        "currency_hint": "EUR"
    },
    {
        "name": "Investing.com GBP/USD",
        "url": "https://www.investing.com/rss/news_25.rss",
        "currency_hint": "GBP"
    },
    {
        "name": "ForexFactory News",
        "url": "https://www.forexfactory.com/ff_calendar_thisweek.xml",
        "currency_hint": None
    },
    {
        "name": "FXStreet EUR/USD",
        "url": "https://www.fxstreet.com/rss/news",
        "currency_hint": None
    },
]

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("aurelius.log", encoding="utf-8")
    ]
)
log = logging.getLogger("Aurelius")

# ─────────────────────────────────────────────
#  GEMINI SETUP
# ─────────────────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-1.5-flash")

# ─────────────────────────────────────────────
#  CHROMADB MEMORY SETUP
# ─────────────────────────────────────────────
chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
embed_fn = embedding_functions.DefaultEmbeddingFunction()
headline_collection = chroma_client.get_or_create_collection(
    name="headlines",
    embedding_function=embed_fn
)

# ─────────────────────────────────────────────
#  IN-MEMORY RESULTS STORE (for dashboard)
# ─────────────────────────────────────────────
analysis_store = {
    "last_updated": None,
    "analyses": [],       # list of result dicts, newest first
    "red_alerts": [],     # high-impact only
    "divergence_flags": []
}
store_lock = threading.Lock()


# ══════════════════════════════════════════════
#  LAYER 1 — DATA INGESTION
# ══════════════════════════════════════════════

def fetch_rss_headlines() -> list[dict]:
    """Pull all RSS feeds; return deduplicated headline dicts."""
    seen_ids = set()
    articles = []

    for feed_cfg in RSS_FEEDS:
        try:
            log.info(f"Fetching RSS: {feed_cfg['name']}")
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (compatible; AureliusBot/1.0; "
                    "+https://github.com/zenrix-studios/aurelius)"
                )
            }
            resp = requests.get(feed_cfg["url"], headers=headers, timeout=10)
            feed = feedparser.parse(resp.content)

            for entry in feed.entries[:20]:   # limit per feed
                title   = entry.get("title", "").strip()
                summary = entry.get("summary", "").strip()
                link    = entry.get("link", "")
                pub     = entry.get("published", datetime.now(timezone.utc).isoformat())

                if not title:
                    continue

                art_id = hashlib.md5(title.encode()).hexdigest()
                if art_id in seen_ids:
                    continue
                seen_ids.add(art_id)

                # Currency relevance filter
                combined = (title + " " + summary).upper()
                relevant = any(c in combined for c in ["EUR", "USD", "GBP", "EURO", "POUND", "DOLLAR"])
                relevant = relevant or feed_cfg["currency_hint"] is not None
                relevant = relevant or any(k in combined.lower() for k in RED_FOLDER_KEYWORDS)

                if not relevant:
                    continue

                articles.append({
                    "id":            art_id,
                    "source":        feed_cfg["name"],
                    "currency_hint": feed_cfg["currency_hint"],
                    "title":         title,
                    "summary":       summary[:400],
                    "link":          link,
                    "published":     pub,
                    "fetched_at":    datetime.now(timezone.utc).isoformat()
                })

        except Exception as e:
            log.warning(f"RSS fetch failed for {feed_cfg['name']}: {e}")

    log.info(f"Fetched {len(articles)} relevant headlines")
    return articles


def is_red_folder(article: dict) -> bool:
    """True if article matches high-impact Forex keywords."""
    combined = (article["title"] + " " + article["summary"]).lower()
    return any(k in combined for k in RED_FOLDER_KEYWORDS)


# ══════════════════════════════════════════════
#  LAYER 2 — ANALYSIS ENGINE (Gemini Brain)
# ══════════════════════════════════════════════

ANALYSIS_PROMPT = """
You are Aurelius, a stoic Forex macro-sentiment analyst. Your job is to analyze the following news headline and summary, and return ONLY a valid JSON object — no markdown, no explanation, no preamble.

Analyze strictly for impact on EUR/USD and GBP/USD.

Return this exact JSON structure:
{{
  "currencies_affected": ["USD", "EUR"],
  "pairs_affected": ["EUR/USD"],
  "impact_score": 0.85,
  "impact_level": "HIGH",
  "sentiment": "Hawkish",
  "direction": "Bullish USD / Bearish EUR",
  "summary": "One sentence: what happened and why it matters for the pair.",
  "surprise_factor": "above_expectations | below_expectations | in_line | unknown",
  "divergence_signal": false,
  "divergence_reason": ""
}}

Rules:
- impact_score: 0.0 to 1.0 (0.8+ = HIGH, 0.5–0.79 = MEDIUM, below 0.5 = LOW)
- impact_level: "HIGH" | "MEDIUM" | "LOW"
- sentiment: "Hawkish" | "Dovish" | "Neutral" | "Risk-On" | "Risk-Off"
- divergence_signal: true only if the news is strongly positive but price action context suggests exhaustion, or news is negative but pair has been falling hard (reversal divergence). Default false if unknown.
- Only include pairs from [EUR/USD, GBP/USD]. If neither is relevant, set pairs_affected to [].
- Be objective. No opinions. Only facts derivable from the headline.

HEADLINE: {title}
SUMMARY: {summary}
SOURCE: {source}
PUBLISHED: {published}
"""

def analyze_with_gemini(article: dict) -> dict | None:
    """Send headline to Gemini; return parsed JSON analysis."""
    prompt = ANALYSIS_PROMPT.format(
        title=article["title"],
        summary=article["summary"],
        source=article["source"],
        published=article["published"]
    )
    try:
        response = gemini_model.generate_content(prompt)
        raw = response.text.strip()

        # Strip any accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        result = json.loads(raw)
        result["headline"]   = article["title"]
        result["link"]       = article["link"]
        result["source"]     = article["source"]
        result["published"]  = article["published"]
        result["fetched_at"] = article["fetched_at"]
        result["article_id"] = article["id"]
        result["is_red"]     = is_red_folder(article)
        result["analysed_at"]= datetime.now(timezone.utc).isoformat()
        return result

    except Exception as e:
        log.warning(f"Gemini analysis failed for '{article['title']}': {e}")
        return None


# ══════════════════════════════════════════════
#  LAYER 3 — CONTEXTUAL MEMORY (ChromaDB)
# ══════════════════════════════════════════════

def already_processed(article_id: str) -> bool:
    """Check if this headline was already analysed (dedup)."""
    try:
        results = headline_collection.get(ids=[article_id])
        return len(results["ids"]) > 0
    except Exception:
        return False


def store_in_memory(article: dict, analysis: dict):
    """Persist headline + analysis embedding in ChromaDB."""
    try:
        doc_text = f"{article['title']} {article['summary']}"
        metadata = {
            "source":       article["source"],
            "sentiment":    analysis.get("sentiment", ""),
            "impact_level": analysis.get("impact_level", ""),
            "impact_score": str(analysis.get("impact_score", 0)),
            "pairs":        ", ".join(analysis.get("pairs_affected", [])),
            "published":    article["published"],
        }
        headline_collection.add(
            ids=[article["id"]],
            documents=[doc_text],
            metadatas=[metadata]
        )
    except Exception as e:
        log.warning(f"ChromaDB store failed: {e}")


def get_recent_context(pair: str, n: int = 5) -> list[dict]:
    """Retrieve last N stored headlines relevant to a pair."""
    try:
        results = headline_collection.query(
            query_texts=[pair],
            n_results=n,
            where={"pairs": {"$contains": pair}} if pair else {}
        )
        return results.get("metadatas", [[]])[0]
    except Exception:
        return []


# ══════════════════════════════════════════════
#  LAYER 4 — NOTIFICATION (Email)
# ══════════════════════════════════════════════

def build_email_html(red_alerts: list[dict], all_results: list[dict]) -> str:
    """Build a clean, structured HTML email report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def sentiment_color(s):
        return {
            "Hawkish":  "#e74c3c",
            "Dovish":   "#3498db",
            "Risk-On":  "#2ecc71",
            "Risk-Off": "#e67e22",
            "Neutral":  "#95a5a6",
        }.get(s, "#95a5a6")

    def impact_badge(level):
        colors = {"HIGH": "#c0392b", "MEDIUM": "#e67e22", "LOW": "#27ae60"}
        c = colors.get(level, "#7f8c8d")
        return f'<span style="background:{c};color:#fff;padding:2px 8px;border-radius:3px;font-size:11px;font-weight:700">{level}</span>'

    rows = ""
    for r in (red_alerts if red_alerts else all_results[:10]):
        sc = sentiment_color(r.get("sentiment","Neutral"))
        div = ""
        if r.get("divergence_signal"):
            div = '<br><span style="color:#f39c12;font-size:11px">⚠ DIVERGENCE SIGNAL DETECTED</span>'
        rows += f"""
        <tr style="border-bottom:1px solid #2a2a2a">
          <td style="padding:12px 8px;color:#aaa;font-size:11px">{r.get('source','')}</td>
          <td style="padding:12px 8px">
            <a href="{r.get('link','#')}" style="color:#e0e0e0;text-decoration:none;font-size:13px">{r.get('headline','')}</a>
            <br><span style="color:#888;font-size:11px">{r.get('summary','')}</span>{div}
          </td>
          <td style="padding:12px 8px;text-align:center">{impact_badge(r.get('impact_level',''))}</td>
          <td style="padding:12px 8px;color:{sc};font-weight:700;font-size:12px">{r.get('sentiment','')}</td>
          <td style="padding:12px 8px;color:#ddd;font-size:12px">{', '.join(r.get('pairs_affected',[]))}</td>
          <td style="padding:12px 8px;color:#e0e0e0;font-size:12px">{r.get('direction','')}</td>
        </tr>"""

    alert_banner = ""
    if red_alerts:
        alert_banner = f"""
        <div style="background:#c0392b;color:#fff;padding:12px 20px;font-size:14px;font-weight:700;letter-spacing:1px">
            🔴 {len(red_alerts)} RED FOLDER EVENT{'S' if len(red_alerts)>1 else ''} DETECTED
        </div>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#141414;font-family:'Courier New',monospace">
  <div style="max-width:900px;margin:0 auto;background:#1a1a1a;border:1px solid #333">
    <div style="background:#0d0d0d;padding:20px 24px;border-bottom:1px solid #333">
      <div style="font-size:22px;color:#e0e0e0;font-weight:700;letter-spacing:2px">AURELIUS</div>
      <div style="font-size:11px;color:#666;letter-spacing:3px">FOREX SENTIMENT AGGREGATOR</div>
      <div style="font-size:11px;color:#555;margin-top:4px">{now} · EUR/USD · GBP/USD</div>
    </div>
    {alert_banner}
    <div style="padding:0 0 20px 0">
      <table style="width:100%;border-collapse:collapse">
        <thead>
          <tr style="background:#0d0d0d;color:#666;font-size:10px;letter-spacing:1px;text-transform:uppercase">
            <th style="padding:10px 8px;text-align:left">SOURCE</th>
            <th style="padding:10px 8px;text-align:left">HEADLINE</th>
            <th style="padding:10px 8px;text-align:center">IMPACT</th>
            <th style="padding:10px 8px;text-align:left">SENTIMENT</th>
            <th style="padding:10px 8px;text-align:left">PAIR</th>
            <th style="padding:10px 8px;text-align:left">DIRECTION</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <div style="padding:12px 20px;border-top:1px solid #222;color:#444;font-size:10px;text-align:center">
      Aurelius · Zenrix Studios · Generated {now}
    </div>
  </div>
</body></html>"""


def send_email_alert(red_alerts: list[dict], all_results: list[dict]):
    """Send email report via smtplib."""
    if not red_alerts and not all_results:
        log.info("No results to email.")
        return

    subject_prefix = "🔴 [AURELIUS RED ALERT]" if red_alerts else "[Aurelius]"
    pairs_summary  = ", ".join(set(
        p for r in (red_alerts or all_results) for p in r.get("pairs_affected", [])
    )) or "Forex"
    subject = f"{subject_prefix} {pairs_summary} — {datetime.now(timezone.utc).strftime('%H:%M UTC')}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO

    html_body = build_email_html(red_alerts, all_results)
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        log.info(f"Email sent: {subject}")
    except Exception as e:
        log.error(f"Email send failed: {e}")


# ══════════════════════════════════════════════
#  MAIN PIPELINE
# ══════════════════════════════════════════════

def run_aurelius_cycle():
    """Full pipeline: ingest → analyse → store → notify → update dashboard."""
    log.info("═" * 50)
    log.info("Aurelius cycle starting…")

    articles  = fetch_rss_headlines()
    new_results   = []
    new_red_alerts = []

    for article in articles:
        if already_processed(article["id"]):
            continue

        analysis = analyze_with_gemini(article)
        if not analysis:
            continue

        # Filter to only relevant pairs
        if not analysis.get("pairs_affected"):
            continue

        store_in_memory(article, analysis)
        new_results.append(analysis)

        if analysis.get("impact_level") == "HIGH" or analysis.get("is_red"):
            new_red_alerts.append(analysis)

        log.info(
            f"[{analysis.get('impact_level','?')}] {article['title'][:60]} "
            f"| {analysis.get('sentiment')} | {analysis.get('pairs_affected')}"
        )
        time.sleep(1.5)   # Gemini rate limit buffer

    # Update shared store for dashboard
    with store_lock:
        analysis_store["last_updated"] = datetime.now(timezone.utc).isoformat()
        analysis_store["analyses"]     = new_results + analysis_store["analyses"]
        analysis_store["analyses"]     = analysis_store["analyses"][:100]   # cap at 100
        analysis_store["red_alerts"]   = new_red_alerts + analysis_store["red_alerts"]
        analysis_store["red_alerts"]   = analysis_store["red_alerts"][:50]
        # Divergence flags
        divs = [r for r in new_results if r.get("divergence_signal")]
        analysis_store["divergence_flags"] = divs + analysis_store["divergence_flags"]
        analysis_store["divergence_flags"] = analysis_store["divergence_flags"][:20]

    # Send email if there are new results
    if new_results:
        send_email_alert(new_red_alerts, new_results)
    else:
        log.info("No new relevant headlines this cycle.")

    log.info(f"Cycle complete. New: {len(new_results)}, Red: {len(new_red_alerts)}")


def start_scheduler():
    """Run the pipeline on a schedule."""
    log.info(f"Scheduler started. Polling every {POLL_INTERVAL_MIN} minutes.")
    run_aurelius_cycle()   # Run once immediately on start
    schedule.every(POLL_INTERVAL_MIN).minutes.do(run_aurelius_cycle)
    while True:
        schedule.run_pending()
        time.sleep(30)
