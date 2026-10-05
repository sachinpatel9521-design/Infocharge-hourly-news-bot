import os
import time
import html
import requests
import feedparser
from datetime import datetime
from zoneinfo import ZoneInfo
from google import genai
from google.genai import types

# ============================================================
# INFOCHARGE MARKET NEWS BOT
# Final robust version:
# Telegram + RSS + Gemini model fallback + RSS-only fallback
# ============================================================

IST = ZoneInfo("Asia/Kolkata")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
UPDATE_TYPE = os.getenv("INFOCHARGE_UPDATE_TYPE", "hourly")

# Try lighter/less-demanded models first, then fall back.
GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
]

RSS_FEEDS = [
    "https://www.moneycontrol.com/rss/latestnews.xml",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.business-standard.com/rss/markets-106.rss",
]

KEYWORDS = [
    "nifty", "sensex", "stock market", "equity", "market", "sebi", "rbi",
    "ipo", "fii", "dii", "bank nifty", "dollar", "rupee", "inflation",
    "interest rate", "fed", "earnings", "results", "dow jones", "s&p 500",
    "nasdaq", "crude", "oil", "bond", "yield", "bank", "finance",
]

NSE_HOLIDAYS_2026 = {
    "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26",
    "2026-03-31", "2026-04-03", "2026-04-14", "2026-05-01",
    "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02",
    "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25",
}

SPECIAL_MUHURAT_2026 = {"2026-11-08"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 INFOCHARGE-News-Bot/1.0"
}


def is_market_closed(now=None):
    now = now or datetime.now(IST)
    date_str = now.strftime("%Y-%m-%d")

    # Muhurat Trading day is handled separately.
    if date_str in SPECIAL_MUHURAT_2026:
        return False

    if now.weekday() >= 5:
        return True

    return date_str in NSE_HOLIDAYS_2026


def fetch_news():
    items = []
    seen = set()

    for feed_url in RSS_FEEDS:
        try:
            response = requests.get(feed_url, headers=HEADERS, timeout=20)
            response.raise_for_status()
            feed = feedparser.parse(response.content)

            for entry in feed.entries[:20]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                summary = (entry.get("summary") or "").strip()

                if not title or not link:
                    continue

                text = f"{title} {summary}".lower()
                if not any(k in text for k in KEYWORDS):
                    continue

                key = title.lower().strip()
                if key in seen:
                    continue

                seen.add(key)
                items.append({
                    "title": title,
                    "summary": summary,
                    "link": link,
                })

        except Exception as e:
            print(f"RSS error: {feed_url} -> {e}")

    return items[:15]


def clean_text(value):
    value = html.unescape(value or "")
    # Remove simple HTML tags from RSS summaries.
    import re
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def build_prompt(news_items, now):
    news_text = []

    for i, item in enumerate(news_items, 1):
        title = clean_text(item["title"])
        summary = clean_text(item["summary"])
        if len(summary) > 500:
            summary = summary[:500] + "..."
        news_text.append(
            f"{i}. {title}\n"
            f"Details: {summary}\n"
            f"Source: {item['link']}"
        )

    joined = "\n\n".join(news_text)

    market_status = (
        "NSE is closed today."
        if is_market_closed(now)
        else "NSE is scheduled to be open today."
    )

    return f"""
You are the official market-news summarizer for INFOCHARGE.

Current India time: {now.strftime("%d %b %Y, %I:%M %p IST")}
Market status: {market_status}
Update type: {UPDATE_TYPE}

Use ONLY the supplied RSS news below.
Do NOT invent prices, percentages, company statements, events, or facts.
Do NOT make buy/sell calls or give personalized investment advice.

Create a concise Telegram-ready market update.

Format:
📊 INFOCHARGE MARKET UPDATE
🕒 {now.strftime("%d %b %Y, %I:%M %p IST")}

Give 4–6 important developments.
For each development:
• short headline
• 1–2 sentence explanation
• source link

At the end add:
⚠️ Educational information only. Not investment advice.

RSS NEWS:
{joined}
""".strip()


def generate_summary(news_items, now):
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = build_prompt(news_items, now)

    last_error = None

    # Each model gets multiple attempts. Temporary 429/5xx errors
    # are retried with increasing delays.
    for model in GEMINI_MODELS:
        for attempt in range(1, 4):
            try:
                print(f"Trying Gemini model={model}, attempt={attempt}")

                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        max_output_tokens=900,
                    ),
                )

                text = (response.text or "").strip()

                if text:
                    print(f"Gemini success: {model}")
                    return text

                last_error = RuntimeError("Gemini returned empty response")

            except Exception as e:
                last_error = e
                error_text = str(e)
                print(f"Gemini error: {model}, attempt={attempt}: {error_text}")

                # Temporary capacity/rate/server errors: wait and retry.
                retryable = any(
                    code in error_text
                    for code in ["429", "500", "502", "503", "504",
                                 "UNAVAILABLE", "RESOURCE_EXHAUSTED"]
                )

                if retryable and attempt < 3:
                    wait_seconds = 3 * (2 ** (attempt - 1))
                    print(f"Temporary Gemini error. Waiting {wait_seconds}s...")
                    time.sleep(wait_seconds)
                else:
                    break

    # Important: don't kill the scheduled Telegram job just because
    # Gemini is temporarily unavailable.
    print(f"All Gemini attempts failed: {last_error}")
    return None


def rss_fallback(news_items, now):
    """Guaranteed non-AI fallback so a scheduled post can still go out."""
    lines = [
        "📊 INFOCHARGE MARKET UPDATE",
        f"🕒 {now.strftime('%d %b %Y, %I:%M %p IST')}",
        "",
        "📰 Latest market-related developments:",
        "",
    ]

    for item in news_items[:6]:
        title = clean_text(item["title"])
        link = item["link"]
        lines.append(f"• {title}")
        lines.append(f"  {link}")
        lines.append("")

    lines.append("⚠️ AI summary temporarily unavailable. Headlines are from RSS sources.")
    lines.append("⚠️ Educational information only. Not investment advice.")

    return "\n".join(lines).strip()


def telegram_api(method, payload):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    response = requests.post(url, json=payload, timeout=30)

    try:
        data = response.json()
    except Exception:
        data = {"ok": False, "description": response.text}

    if not response.ok or not data.get("ok"):
        raise RuntimeError(
            f"Telegram {method} failed: HTTP {response.status_code} | {data}"
        )

    return data


def verify_telegram():
    me = telegram_api("getMe", {})
    chat = telegram_api("getChat", {"chat_id": TELEGRAM_CHAT_ID})

    print(
        f"Telegram bot authenticated: @{me['result'].get('username')}"
    )
    print(
        "Telegram target verified: "
        f"id={chat['result'].get('id')} | "
        f"title={chat['result'].get('title')} | "
        f"type={chat['result'].get('type')}"
    )


def send_telegram(message):
    # Telegram message limit is 4096 characters.
    chunks = []
    remaining = message

    while remaining:
        if len(remaining) <= 3900:
            chunks.append(remaining)
            break

        cut = remaining.rfind("\n", 0, 3900)
        if cut < 1000:
            cut = 3900

        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()

    for chunk in chunks:
        result = telegram_api(
            "sendMessage",
            {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "disable_web_page_preview": True,
            },
        )
        print(
            "Telegram message sent successfully. "
            f"message_id={result['result'].get('message_id')}"
        )


def main():
    now = datetime.now(IST)

    print("=" * 60)
    print("INFOCHARGE GEMINI MARKET BOT")
    print(f"Time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Update type: {UPDATE_TYPE}")
    print(f"Market closed: {is_market_closed(now)}")
    print("=" * 60)

    news_items = fetch_news()

    if not news_items:
        print("No relevant RSS news found. Nothing to send.")
        return

    print(f"Relevant news items found: {len(news_items)}")

    summary = generate_summary(news_items, now)

    if summary:
        message = summary
    else:
        print("Using RSS-only fallback message.")
        message = rss_fallback(news_items, now)

    verify_telegram()
    send_telegram(message)


if __name__ == "__main__":
    main()
