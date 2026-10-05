import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from html import unescape
import re

import feedparser
import requests
from google import genai
from google.genai import types


# =========================
# CONFIG
# =========================
IST = ZoneInfo("Asia/Kolkata")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# Current Google GenAI SDK model.
GEMINI_MODEL = "gemini-3.8-flash"

client = genai.Client(api_key=GEMINI_API_KEY)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


# NSE holidays for 2026.
NSE_HOLIDAYS_2026 = {
    "2026-01-15",
    "2026-01-26",
    "2026-03-03",
    "2026-03-26",
    "2026-03-31",
    "2026-04-03",
    "2026-04-14",
    "2026-05-01",
    "2026-05-28",
    "2026-06-26",
    "2026-09-14",
    "2026-10-02",
    "2026-10-20",
    "2026-11-10",
    "2026-11-24",
    "2026-12-25",
}

# Muhurat trading day: Sunday, 8 Nov 2026.
# Exact Muhurat session timing is intentionally not hard-coded here.
SPECIAL_MUHURAT_2026 = {"2026-11-08"}


RSS_FEEDS = [
    "https://www.moneycontrol.com/rss/latestnews.xml",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.business-standard.com/rss/markets-106.rss",
]

MARKET_KEYWORDS = [
    "nifty",
    "sensex",
    "stock market",
    "equity",
    "market",
    "sebi",
    "rbi",
    "ipo",
    "fii",
    "dii",
    "bank nifty",
    "dollar",
    "earnings",
    "results",
    "dow jones",
    "s&p 500",
    "nasdaq",
    "crude",
    "rupee",
    "inflation",
    "interest rate",
    "fed",
]


# =========================
# HELPERS
# =========================
def clean_text(value: str) -> str:
    """Remove HTML/XML noise from RSS text."""
    if not value:
        return ""

    value = unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def is_nse_holiday(dt: datetime) -> bool:
    date_str = dt.strftime("%Y-%m-%d")

    # Muhurat day is treated separately as a trading day.
    if date_str in SPECIAL_MUHURAT_2026:
        return False

    if dt.weekday() >= 5:
        return True

    return date_str in NSE_HOLIDAYS_2026


def fetch_news():
    articles = []

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:20]:
                title = clean_text(entry.get("title", ""))
                link = entry.get("link", "")
                summary = clean_text(
                    entry.get("summary", "")
                    or entry.get("description", "")
                )

                if not title or not link:
                    continue

                combined = f"{title} {summary}".lower()

                if any(keyword in combined for keyword in MARKET_KEYWORDS):
                    articles.append(
                        {
                            "title": title,
                            "summary": summary[:700],
                            "link": link,
                        }
                    )

        except Exception as exc:
            logging.warning("RSS error for %s: %s", feed_url, exc)

    # Remove duplicates by title.
    unique = []
    seen = set()

    for article in articles:
        key = article["title"].lower().strip()

        if key in seen:
            continue

        seen.add(key)
        unique.append(article)

    # Keep prompt size under control.
    return unique[:15]


def update_title(update_type: str, now: datetime) -> str:
    labels = {
        "morning": "GOOD MORNING",
        "premarket": "PRE-MARKET UPDATE",
        "open": "MARKET OPEN UPDATE",
        "hourly": "MARKET UPDATE",
        "close": "MARKET CLOSE",
        "evening": "EVENING RECAP",
        "global": "GLOBAL MARKET UPDATE",
        "holiday": "MARKET & NEWS BRIEFING",
    }

    return labels.get(update_type, "MARKET UPDATE")


def generate_ai_update(articles, update_type, now):
    title = update_title(update_type, now)

    if articles:
        news_block = "\n\n".join(
            [
                (
                    f"HEADLINE: {a['title']}\n"
                    f"DETAIL: {a['summary']}\n"
                    f"SOURCE: {a['link']}"
                )
                for a in articles
            ]
        )
    else:
        news_block = "No relevant RSS articles were available."

    if update_type == "holiday":
        purpose = (
            "The Indian market is closed. Do NOT write as if NSE/BSE is "
            "currently trading. Focus on global markets, macro/corporate "
            "developments and what could matter for the next Indian session."
        )
    elif update_type == "morning":
        purpose = "Prepare investors for the Indian market day ahead."
    elif update_type == "premarket":
        purpose = "Summarize the latest pre-market factors before the open."
    elif update_type == "open":
        purpose = "Give a concise market-open briefing using only supplied news."
    elif update_type == "close":
        purpose = "Summarize the market-close context and important news."
    elif update_type == "evening":
        purpose = "Give an evening recap of important market developments."
    elif update_type == "global":
        purpose = "Summarize important global developments relevant to Indian markets."
    else:
        purpose = "Give a concise intraday market-news briefing."

    prompt = f"""
You are the AI editor for INFOCHARGE, an educational Indian stock-market
community.

UPDATE TYPE: {title}
TIME (IST): {now.strftime("%d %b %Y, %I:%M %p")}
TASK: {purpose}

STRICT RULES:
1. Use ONLY facts present in the supplied RSS material.
2. Never invent prices, percentages, index levels, company statements,
   events or reasons that are not supplied.
3. Do NOT give buy calls, sell calls, entry/exit levels or guaranteed profits.
4. Clearly separate facts from cautious market context.
5. Keep it Telegram-friendly and concise.
6. Do not use HTML tags, Markdown tables, or code blocks.
7. Maximum target length: about 3000 characters.
8. Include the source URL after each important item.
9. If the supplied news is insufficient, say so instead of guessing.

FORMAT:
📊 INFOCHARGE | {title}

• 4–6 important developments, each in 1–3 short sentences.
• End with:
⚠️ Educational information only. No buy/sell recommendation.

SOURCE MATERIAL:
{news_block}
"""

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=900,
            ),
        )

        text = (response.text or "").strip()

        if not text:
            raise RuntimeError("Gemini returned empty text.")

        # Remove accidental HTML/Markdown formatting that can break Telegram.
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("```", "")
        text = text.strip()

        # Hard safety cap. Telegram's limit is 4096 chars per message.
        return text[:3900]

    except Exception as exc:
        logging.exception("Gemini error: %s", exc)
        return (
            f"📊 INFOCHARGE | {title}\n\n"
            "AI summary could not be generated right now.\n"
            "Please check the latest market/news sources manually.\n\n"
            "⚠️ Educational information only. No buy/sell recommendation."
        )


def split_message(message, max_chars=3900):
    """Split safely without exceeding Telegram's message limit."""
    if len(message) <= max_chars:
        return [message]

    chunks = []
    current = ""

    # Prefer paragraph/line boundaries.
    for part in re.split(r"(\n+)", message):
        if len(current) + len(part) <= max_chars:
            current += part
            continue

        if current.strip():
            chunks.append(current.strip())

        # A single line can still be too long.
        while len(part) > max_chars:
            chunks.append(part[:max_chars])
            part = part[max_chars:]

        current = part

    if current.strip():
        chunks.append(current.strip())

    return chunks


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    chunks = split_message(message)

    for index, chunk in enumerate(chunks, start=1):
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "disable_web_page_preview": True,
        }

        response = requests.post(
            url,
            json=payload,
            timeout=30,
        )

        if not response.ok:
            # Show Telegram's exact error in GitHub Actions logs.
            logging.error(
                "Telegram API error: status=%s body=%s",
                response.status_code,
                response.text,
            )

        response.raise_for_status()

        logging.info(
            "Telegram message sent successfully (%s/%s).",
            index,
            len(chunks),
        )


def main():
    now = datetime.now(IST)
    update_type = os.getenv("INFOCHARGE_UPDATE_TYPE", "hourly").strip().lower()

    holiday = is_nse_holiday(now)

    logging.info("IST time: %s", now)
    logging.info("Update type: %s", update_type)
    logging.info("NSE holiday/weekend: %s", holiday)

    # On a closed NSE day, only the dedicated holiday briefing is posted.
    if holiday:
        if update_type != "holiday":
            logging.info("NSE is closed; skipping normal trading update.")
            return
    else:
        if update_type == "holiday":
            logging.info("Trading day; skipping holiday briefing.")
            return

    articles = fetch_news()
    logging.info("Retrieved %s relevant articles.", len(articles))

    message = generate_ai_update(
        articles=articles,
        update_type=update_type,
        now=now,
    )

    send_telegram(message)


if __name__ == "__main__":
    main()
