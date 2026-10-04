import os
import logging
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

import feedparser
import requests
from openai import OpenAI

IST = ZoneInfo("Asia/Kolkata")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-mini")

client = OpenAI(api_key=OPENAI_API_KEY)

RSS_FEEDS = [
    "https://www.moneycontrol.com/rss/latestnews.xml",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.business-standard.com/rss/markets-106.rss",
]

NSE_HOLIDAYS_2026 = {
    "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26",
    "2026-03-31", "2026-04-03", "2026-04-14", "2026-05-01",
    "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02",
    "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25",
}
SPECIAL_MUHURAT_2026 = {"2026-11-08"}

MARKET_WORDS = (
    "nifty", "sensex", "bank nifty", "stock", "shares", "market",
    "equity", "ipo", "fii", "dii", "rbi", "sebi", "earnings",
    "results", "crude", "rupee", "inflation", "fed", "nasdaq",
    "dow", "s&p", "oil", "gold", "bond", "tariff", "economy"
)

def is_nse_holiday(dt=None):
    dt = dt or datetime.now(IST)
    d = dt.strftime("%Y-%m-%d")
    if dt.weekday() >= 5:
        return d not in SPECIAL_MUHURAT_2026
    return d in NSE_HOLIDAYS_2026

def fetch_news(limit=18):
    articles = []
    seen = set()

    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries:
                title = getattr(e, "title", "").strip()
                link = getattr(e, "link", "").strip()
                summary = getattr(e, "summary", "").strip()
                text = f"{title} {summary}".lower()

                if not title or not link or link in seen:
                    continue
                if not any(w in text for w in MARKET_WORDS):
                    continue

                seen.add(link)
                articles.append({
                    "title": title,
                    "summary": summary[:500],
                    "link": link,
                })
                if len(articles) >= limit:
                    return articles
        except Exception:
            logging.exception("RSS error: %s", url)

    return articles

def ai_message(kind, articles):
    now = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
    news = "\n\n".join(
        f"{i+1}. {a['title']}\n{a['summary']}\nSource: {a['link']}"
        for i, a in enumerate(articles)
    )

    if kind == "holiday":
        focus = """Create a NON-TRADING-DAY market briefing. Clearly say Indian markets are closed.
Cover important global markets, major corporate/macro developments, and what Indian investors
should watch for the next trading session. Do not give buy/sell calls."""
    elif kind == "morning":
        focus = "Create a Good Morning briefing with global cues, key overnight developments, and what to watch today."
    elif kind == "premarket":
        focus = "Create a concise pre-market briefing covering important news, global cues, commodities, currency and key events."
    elif kind == "open":
        focus = "Create a market-open briefing focused on the most important developments around the opening session."
    elif kind == "hourly":
        focus = "Create an hourly market-news update. Only include meaningful new developments; avoid filler."
    elif kind == "close":
        focus = "Create a market-close briefing covering major developments, sectors/themes and important events for tomorrow."
    elif kind == "evening":
        focus = "Create an evening recap of the most important Indian and global market developments."
    else:
        focus = "Create a global-market update relevant to Indian investors."

    prompt = f"""You are the AI news editor for INFOCHARGE, an educational market-information community.

Current time: {now}

{focus}

Rules:
- Use ONLY facts supported by the supplied headlines/articles.
- Do not invent prices, percentages, events or statistics.
- No buy calls, sell calls, targets, guaranteed returns or personalized financial advice.
- Use simple professional English.
- Make it Telegram-friendly and easy to scan.
- Prefer 5-8 important points, not a huge article.
- Add source links at the end.
- Start with a suitable INFOCHARGE heading and 1-2 relevant emojis.
- If the supplied news is weak, say that there are no major fresh developments instead of inventing content.

News:
{news}
"""
    r = client.responses.create(model=OPENAI_MODEL, input=prompt)
    return r.output_text.strip()

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # Telegram message limit is ~4096 chars.
    for i in range(0, len(text), 3900):
        part = text[i:i+3900]
        resp = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": part,
                "disable_web_page_preview": False,
            },
            timeout=30,
        )
        resp.raise_for_status()

def run(kind):
    now = datetime.now(IST)

    if is_nse_holiday(now):
        if kind != "holiday":
            logging.info("Normal %s skipped: NSE holiday/weekend.", kind)
            return
    elif kind == "holiday":
        logging.info("Holiday update skipped: trading day.")
        return

    articles = fetch_news()
    if not articles:
        logging.warning("No relevant news found.")
        return

    message = ai_message(kind, articles)
    send_telegram(message)
    logging.info("Published %s update.", kind)

if __name__ == "__main__":
    kind = os.getenv("INFOCHARGE_UPDATE_TYPE", "hourly")
    logging.basicConfig(level=logging.INFO)
    run(kind)
