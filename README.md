# AURELIUS
### Forex Sentiment Aggregator · Zenrix Studios
*Stoic, logical, focused only on what is objectively true.*

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        AURELIUS                             │
│                                                             │
│  ┌──────────────┐    ┌───────────────┐    ┌─────────────┐  │
│  │  DATA LAYER  │───▶│  GEMINI BRAIN │───▶│  CHROMADB   │  │
│  │  (RSS Feeds) │    │  (Analysis)   │    │  (Memory)   │  │
│  └──────────────┘    └───────────────┘    └─────────────┘  │
│         │                    │                    │          │
│         ▼                    ▼                    ▼          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              NOTIFICATION LAYER                      │   │
│  │         Email (smtplib) + Dashboard (Flask)          │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**Pairs:** EUR/USD, GBP/USD  
**Sources:** ForexFactory, Reuters, Investing.com, FXStreet  
**Brain:** Gemini 1.5 Flash  
**Memory:** ChromaDB (local persistent vector store)  
**Delivery:** Email alerts + Live web dashboard  

---

## Quick Start (Docker — Recommended for Cloud)

### 1. Clone and configure

```bash
git clone <your-repo>
cd aurelius
cp .env.example .env
nano .env          # Fill in your keys (see below)
```

### 2. Fill in `.env`

```env
GEMINI_API_KEY=your_key_here

AURELIUS_EMAIL_FROM=you@gmail.com
AURELIUS_EMAIL_PASSWORD=your_app_password   # Gmail App Password, not main password
AURELIUS_EMAIL_TO=you@gmail.com

POLL_INTERVAL_MIN=15
DASHBOARD_PORT=5000
```

**Gmail App Password setup:**  
Google Account → Security → 2-Step Verification → App Passwords → Generate

**Gemini API key:**  
https://aistudio.google.com/app/apikey (free tier available)

### 3. Deploy

```bash
docker-compose up -d
```

Dashboard live at: `http://your-server-ip:5000`

---

## Manual Setup (without Docker)

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your values

# Load env vars
export $(cat .env | xargs)

# Run
python dashboard.py
```

---

## File Structure

```
aurelius/
├── aurelius_agent.py    ← Core agent (feeds, Gemini, ChromaDB, email)
├── dashboard.py         ← Flask server + live dashboard UI
├── requirements.txt     ← Python dependencies
├── .env.example         ← Config template
├── Dockerfile           ← Container build
├── docker-compose.yml   ← One-command deployment
└── README.md
```

---

## How Aurelius Works

### 1. Data Ingestion (every N minutes)
Polls 7 RSS feeds across ForexFactory, Reuters, Investing.com, and FXStreet.
Filters articles to only those relevant to USD, EUR, or GBP.

### 2. Gemini Analysis
Each new headline is sent to Gemini 1.5 Flash with a structured prompt.
Returns a JSON object:
```json
{
  "currencies_affected": ["USD", "EUR"],
  "pairs_affected": ["EUR/USD"],
  "impact_score": 0.85,
  "impact_level": "HIGH",
  "sentiment": "Hawkish",
  "direction": "Bullish USD / Bearish EUR",
  "summary": "Fed Chair signaled higher-for-longer rates.",
  "surprise_factor": "above_expectations",
  "divergence_signal": false,
  "divergence_reason": ""
}
```

### 3. Memory (ChromaDB)
Every processed headline is stored as a vector embedding.
Prevents duplicate analysis across cycles.
Enables contextual similarity lookups for divergence detection.

### 4. Red Folder Filter
Only HIGH-impact events trigger immediate email alerts.
Keyword list covers: rate decisions, CPI, NFP, FOMC, ECB, BOE, GDP, and more.

### 5. Divergence Signal
Aurelius flags when a Hawkish/Dovish signal appears but prior context
suggests the market may already have priced it in (exhaustion divergence).

---

## Dashboard

| Section | Description |
|---|---|
| Top metrics | Total signals, Red count, Divergence flags, Dominant tone |
| Red banner | Fires when any HIGH impact event is detected |
| All Signals | Full feed, newest first, color-coded by impact level |
| Red Folder | Right panel — only HIGH impact events |

Auto-refreshes every 30 seconds. No page reload needed.

---

## Email Alerts

Sent whenever new relevant signals are found.  
Subject line: `🔴 [AURELIUS RED ALERT] EUR/USD — 14:30 UTC` for high-impact,  
or `[Aurelius] EUR/USD — 14:30 UTC` for normal cycles.

HTML email with full signal table, color-coded by sentiment and impact.

---

## Customisation

| What | Where | How |
|---|---|---|
| Add more pairs | `aurelius_agent.py` | Add to `TARGET_PAIRS` and `TARGET_CURRENCIES` |
| Add RSS feeds | `aurelius_agent.py` | Add to `RSS_FEEDS` list |
| Change poll interval | `.env` | `POLL_INTERVAL_MIN=15` |
| Change email address | `.env` | `AURELIUS_EMAIL_TO=...` |
| Red folder keywords | `aurelius_agent.py` | Add to `RED_FOLDER_KEYWORDS` |

---

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Live dashboard UI |
| `/api/data` | GET | JSON — all current analysis results |
| `/api/trigger` | POST | Manually trigger an analysis cycle |

---

## Deployment Notes (Cloud)

**Recommended:** Any VPS with 1GB+ RAM and Python 3.11+
- DigitalOcean Droplet ($6/mo)
- Hetzner CX11 (~€4/mo)
- Railway, Render (free tiers available)

**Firewall:** Open port 5000 (or put Nginx in front for HTTPS)

**Nginx reverse proxy (optional):**
```nginx
server {
    listen 80;
    server_name your-domain.com;
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
    }
}
```

---

*Built by Zenrix Studios. Aurelius watches so you don't have to.*
