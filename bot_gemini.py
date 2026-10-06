import os
import json
import logging
import re
import html
import time
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from google import genai
from google.genai import types

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:
    plt = None

# ============================================================
# INFOCHARGE MARKET INTELLIGENCE BOT — V4
# Free-first architecture:
#   RSS discovery + public market/calendar data + Gemini reasoning
#   No paid Google Search grounding required.
#
# Features:
#   1. Very selective Indian stock/sector intelligence
#   2. Geopolitics -> commodity/currency/trade -> Indian stock/sector link
#   3. Fed/FOMC, US CPI, inflation, Treasury yields, RBI/SEBI/NSE events
#   4. Educational market-learning posts and historical thinking frameworks
#   5. Nifty IT / Nasdaq ratio educational snapshot when data is available
#   6. IPO watch / due-diligence posts from discovered public information
#   7. Occasional market-related motivation, never spammy
#   8. Persistent editorial memory
#   9. Automatic branded visual cards (free; no image-generation API)
#  10. Gemini retry + 3.7 fallback for temporary 503s
#
# IMPORTANT:
#   This is educational market intelligence, not investment advice.
# ============================================================

IST = ZoneInfo("Asia/Kolkata")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

PRIMARY_MODEL = "gemini-3.8-flash"
FALLBACK_MODEL = "gemini-3.7-flash"

MEMORY_FILE = Path("infocharge_memory.json")
MAX_MEMORY_ITEMS = 140
MAX_ARTICLES = 90
HTTP_TIMEOUT = 18
GEMINI_RETRIES = 4
MIN_IMPORTANCE = 8

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

client = genai.Client(api_key=GEMINI_API_KEY)

# ============================================================
# PUBLIC DISCOVERY SOURCES
# ============================================================

NEWS_FEEDS = [
    # Broad but market-focused
    "https://news.google.com/rss/search?q=India+listed+company+order+contract+capex+results&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+NSE+BSE+corporate+announcement+stocks&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+SEBI+RBI+market+policy+stocks&hl=en-IN&gl=IN&ceid=IN:en",

    # Sector intelligence
    "https://news.google.com/rss/search?q=India+data+centre+AI+infrastructure+stocks+order&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+semiconductor+electronics+manufacturing+stocks+investment&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+defence+order+contract+listed+company&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+pharma+USFDA+EMA+approval+listed+company&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+power+renewable+grid+order+listed+company&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+bank+NPA+credit+deposit+RBI+listed+bank&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+IT+services+deal+contract+guidance+listed+company&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+chemical+specialty+chemical+export+import+stocks&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+cement+steel+commodity+capex+infrastructure+stocks&hl=en-IN&gl=IN&ceid=IN:en",

    # Geopolitical transmission channels
    "https://news.google.com/rss/search?q=India+geopolitics+tariff+trade+sanctions+stocks+sector&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Middle+East+oil+shipping+India+stocks+sector&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Russia+Ukraine+India+trade+energy+stocks&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=US+China+trade+tariff+India+stocks+sector&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+China+border+trade+industry+stocks&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Red+Sea+shipping+freight+India+stocks&hl=en-IN&gl=IN&ceid=IN:en",

    # IPO
    "https://news.google.com/rss/search?q=India+IPO+DRHP+RHP+price+band+listing+2026&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=upcoming+IPO+India+2026+NSE+BSE&hl=en-IN&gl=IN&ceid=IN:en",

    # Macro / market structure
    "https://news.google.com/rss/search?q=US+Fed+CPI+inflation+Treasury+yield+India+market&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=US+10+year+yield+India+equity+market+IT+stocks&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+rupee+crude+oil+FII+equity+market&hl=en-IN&gl=IN&ceid=IN:en",
]

# Official-ish calendar/release URLs used as deterministic reminders.
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
CPI_URL = "https://www.bls.gov/schedule/news_release/cpi.htm"
NSE_HOLIDAY_URL = "https://www.nseindia.com/resources/exchange-communication-holidays"

NSE_HOLIDAYS_2026 = {
    "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26",
    "2026-03-31", "2026-04-03", "2026-04-14", "2026-05-01",
    "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02",
    "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25",
    # NSE says Nov 8 is a trading holiday; Muhurat Trading is scheduled separately.
    "2026-11-08",
}

# FOMC 2026 dates. Keep explicit so reminders are deterministic.
FOMC_DATES_2026 = {
    "2026-01-27", "2026-01-28",
    "2026-03-17", "2026-03-18",
    "2026-04-28", "2026-04-29",
    "2026-06-16", "2026-06-17",
    # Add remaining dates if/when official calendar is updated.
    "2026-07-28", "2026-07-29",
    "2026-09-15", "2026-09-16",
    "2026-10-27", "2026-10-28",
    "2026-12-08", "2026-12-09",
}

# 2026 BLS CPI release dates from the official BLS calendar.
CPI_RELEASE_DATES_2026 = {
    "2026-01-13", "2026-02-13", "2026-03-11", "2026-04-10",
    "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12",
    "2026-09-11", "2026-10-14", "2026-11-10", "2026-12-10",
}

# ============================================================
# BASIC HELPERS
# ============================================================

def clean_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_title(title):
    title = clean_text(title).lower()
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def safe_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def load_memory():
    if not MEMORY_FILE.exists():
        return {
            "posted": [],
            "editorial_notes": [],
            "education": [],
            "ipo_watch": [],
            "calendar_sent": [],
        }

    try:
        data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Memory is not an object")

        for key in ("posted", "editorial_notes", "education", "ipo_watch", "calendar_sent"):
            data.setdefault(key, [])

        return data

    except Exception as exc:
        logging.warning("Memory read failed: %s", exc)
        return {
            "posted": [],
            "editorial_notes": [],
            "education": [],
            "ipo_watch": [],
            "calendar_sent": [],
        }


def save_memory(memory):
    MEMORY_FILE.write_text(
        json.dumps(memory, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def memory_for_prompt(memory):
    compact = {
        "recent_posts": [
            {
                "date": x.get("date"),
                "headline": x.get("headline"),
                "company": x.get("company"),
                "key": x.get("key"),
            }
            for x in memory.get("posted", [])[-MAX_MEMORY_ITEMS:]
        ],
        "editorial_notes": memory.get("editorial_notes", [])[-30:],
        "recent_education": memory.get("education", [])[-15:],
        "ipo_watch": memory.get("ipo_watch", [])[-20:],
    }
    return json.dumps(compact, ensure_ascii=False)


def market_status(now):
    date_key = now.strftime("%Y-%m-%d")

    if now.weekday() >= 5 or date_key in NSE_HOLIDAYS_2026:
        return "closed"

    minutes = now.hour * 60 + now.minute

    if minutes < 555:
        return "pre_market"
    if minutes <= 930:
        return "market_hours"
    return "post_market"


# ============================================================
# NEWS COLLECTION
# ============================================================

def fetch_news():
    collected = []
    seen = set()

    for feed_url in NEWS_FEEDS:
        try:
            response = requests.get(
                feed_url,
                timeout=HTTP_TIMEOUT,
                headers={"User-Agent": "INFOCHARGE-Market-Intelligence/4.0"},
            )
            response.raise_for_status()

            root = ET.fromstring(response.content)

            for item in root.findall(".//item")[:15]:

                def get_child(tag):
                    node = item.find(tag)
                    return node.text if node is not None and node.text else ""

                title = clean_text(get_child("title"))
                summary = clean_text(get_child("description"))
                link = clean_text(get_child("link"))
                published = clean_text(get_child("pubDate"))

                if not title:
                    continue

                key = normalize_title(title)

                if not key or key in seen:
                    continue

                seen.add(key)

                collected.append({
                    "title": title,
                    "summary": summary[:1200],
                    "published": published,
                    "link": link,
                })

        except Exception as exc:
            logging.warning("News feed failed: %s", exc)

    return collected[:MAX_ARTICLES]


def article_packet(articles):
    blocks = []

    for i, item in enumerate(articles, 1):
        blocks.append(
            "\n".join([
                f"ARTICLE {i}",
                f"Published: {item['published']}",
                f"Title: {item['title']}",
                f"Summary: {item['summary']}",
                f"Link: {item['link']}",
            ])
        )

    return "\n\n".join(blocks)


# ============================================================
# GEMINI WITH RETRIES / FALLBACK
# ============================================================

def call_gemini(prompt, max_tokens):
    models = [PRIMARY_MODEL, FALLBACK_MODEL]
    last_error = None

    for model in models:
        for attempt in range(GEMINI_RETRIES):
            try:
                logging.info(
                    "Gemini request | model=%s | attempt=%s",
                    model,
                    attempt + 1
                )

                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        max_output_tokens=max_tokens
                    ),
                )

                text = (response.text or "").strip()

                if not text:
                    raise RuntimeError("Gemini returned an empty response.")

                return text

            except Exception as exc:
                last_error = exc
                logging.warning(
                    "Gemini failed | model=%s | attempt=%s | %s",
                    model,
                    attempt + 1,
                    exc
                )

                # Retry temporary overload/server/rate-limit failures.
                error_text = str(exc).upper()
                retryable = any(
                    token in error_text
                    for token in (
                        "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED",
                        "500", "INTERNAL", "DEADLINE", "TIMEOUT"
                    )
                )

                if not retryable:
                    break

                time.sleep(3 * (2 ** attempt))

    raise RuntimeError(f"Gemini failed after retries: {last_error}")


def extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)

        if not match:
            raise RuntimeError("Gemini did not return valid JSON.")

        return json.loads(match.group(0))


# ============================================================
# MARKET DATA
# ============================================================

def yahoo_chart(symbol, period1=None, period2=None, interval="1d"):
    """
    Public Yahoo chart endpoint. Used only for educational snapshots.
    No API key is stored.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    params = {
        "interval": interval,
        "range": "1y" if not period1 else None,
    }

    if period1:
        params["period1"] = int(period1.timestamp())

    if period2:
        params["period2"] = int(period2.timestamp())

    try:
        response = requests.get(
            url,
            params={k: v for k, v in params.items() if v is not None},
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logging.warning("Yahoo chart failed for %s: %s", symbol, exc)
        return None


def latest_yahoo_price(symbol):
    data = yahoo_chart(symbol, interval="1d")

    try:
        result = data["chart"]["result"][0]
        meta = result.get("meta", {})
        price = meta.get("regularMarketPrice")

        if price is not None:
            return float(price)

        closes = result["indicators"]["quote"][0]["close"]
        closes = [x for x in closes if x is not None]

        return float(closes[-1]) if closes else None

    except Exception:
        return None


def nifty_it_nasdaq_ratio():
    """
    Educational ratio:
      NIFTY IT index proxy / NASDAQ-100 proxy.

    Yahoo symbols can change. If either series is unavailable,
    the bot simply skips the ratio rather than inventing data.
    """
    nifty_it_candidates = ["^CNXIT", "^NIFTYIT"]
    nasdaq_candidates = ["^NDX"]

    it_price = None
    ndx_price = None
    it_symbol = None
    ndx_symbol = None

    for symbol in nifty_it_candidates:
        it_price = latest_yahoo_price(symbol)
        if it_price is not None:
            it_symbol = symbol
            break

    for symbol in nasdaq_candidates:
        ndx_price = latest_yahoo_price(symbol)
        if ndx_price is not None:
            ndx_symbol = symbol
            break

    if it_price is None or ndx_price is None or ndx_price == 0:
        return None

    return {
        "nifty_it": it_price,
        "nasdaq100": ndx_price,
        "ratio": it_price / ndx_price,
        "symbols": [it_symbol, ndx_symbol],
    }


def treasury_10y():
    """
    Uses the U.S. Treasury daily CSV endpoint.
    """
    url = (
        "https://home.treasury.gov/resource-center/data-chart-center/"
        "interest-rates/daily-treasury-rates.csv/2026/all"
        "?type=daily_treasury_yield_curve"
    )

    try:
        response = requests.get(
            url,
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": "INFOCHARGE-Market-Intelligence/4.0"},
        )
        response.raise_for_status()

        lines = response.text.splitlines()

        if not lines:
            return None

        header = [x.strip().replace("\ufeff", "") for x in lines[0].split(",")]

        # Treasury CSV occasionally contains different column names.
        ten_candidates = [
            "10 YR",
            "10-year",
            "10-year Treasury",
            "10 Yr",
        ]

        idx = None

        for candidate in ten_candidates:
            if candidate in header:
                idx = header.index(candidate)
                break

        if idx is None:
            for i, h in enumerate(header):
                if "10" in h and "YR" in h.upper():
                    idx = i
                    break

        if idx is None:
            return None

        for row in reversed(lines[1:]):
            parts = row.split(",")

            if len(parts) <= idx:
                continue

            date_value = parts[0].strip()
            value = parts[idx].strip()

            if value and value != "N/A":
                return {
                    "date": date_value,
                    "yield": float(value),
                }

    except Exception as exc:
        logging.warning("Treasury 10Y fetch failed: %s", exc)

    return None



def fred_latest(series_id):
    """Read a public FRED CSV without requiring a FRED API key."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

    try:
        response = requests.get(
            url,
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": "INFOCHARGE-Market-Intelligence/4.0"},
        )
        response.raise_for_status()

        rows = response.text.splitlines()

        for row in reversed(rows[1:]):
            parts = row.split(",")

            if len(parts) >= 2 and parts[1].strip() not in ("", "."):
                return {
                    "date": parts[0].strip(),
                    "value": float(parts[1].strip()),
                    "series": series_id,
                }

    except Exception as exc:
        logging.warning("FRED series failed: %s | %s", series_id, exc)

    return None


def fred_history(series_id, limit=260):
    """Return recent daily FRED observations for educational charts."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

    try:
        response = requests.get(
            url,
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": "INFOCHARGE-Market-Intelligence/4.0"},
        )
        response.raise_for_status()

        data = []

        for row in response.text.splitlines()[1:]:
            parts = row.split(",")

            if len(parts) < 2:
                continue

            value = parts[1].strip()

            if value in ("", "."):
                continue

            try:
                data.append((parts[0].strip(), float(value)))
            except ValueError:
                continue

        return data[-limit:]

    except Exception as exc:
        logging.warning("FRED history failed: %s | %s", series_id, exc)
        return []


def fed_balance_sheet_snapshot():
    """
    Reads the current H.4.1 release page and extracts total assets.
    The Federal Reserve releases H.4.1 weekly.
    """
    url = "https://www.federalreserve.gov/releases/h41/current/"

    try:
        response = requests.get(
            url,
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": "INFOCHARGE-Market-Intelligence/4.0"},
        )
        response.raise_for_status()

        text = clean_text(response.text)

        # Search for Total assets followed by a number in the HTML/text.
        match = re.search(
            r"Total assets\s+([0-9,]+)",
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            # Some pages place the value later in the table.
            match = re.search(
                r"Total assets.*?([0-9,]{6,})",
    
