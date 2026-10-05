import os
import logging
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from html import unescape

import feedparser
import requests
from google import genai
from google.genai import types
from google.genai import errors as genai_errors

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

IST = ZoneInfo("Asia/Kolkata")
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"].strip()
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"].strip()
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"].strip()

# Primary + fallback. If Google temporarily returns 503/high demand,
# the bot automatically retries and then switches model.
GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
]

client = genai.Client(api_key=GEMINI_API_KEY)

RSS_FEEDS = [
    "https://www.moneycontrol.com/rss/latestnews.xml",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.business-standard.com/rss/markets-106.rss",
]

MARKET_KEYWORDS = [
    "nifty", "sensex", "stock market", "equity", "market", "sebi", "rbi",
    "ipo", "fii", "dii", "bank nifty", "dollar", "earnings", "results",
    "dow jones", "s&p 500", "nasdaq", "crude", "rupee", "inflation",
    "interest rate", "fed",
]

NSE_HOLIDAYS_2026 = {
    "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26",
    "2026-03-31", "2026-04-03", "2026-04-14", "2026-05-01",
    "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02",
    "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25",
}
SPECIAL_MUHURAT_2026 = {"2026-11-08"}


def is_closed(now):
    d = now.strftime("%Y-%m-%d")
    if d in SPECIAL_MUHURAT_2026:
        return False
    return now.weekday() >= 5 or d in NSE_HOLIDAYS_2026


def clean_text(value):
    value = unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def fetch_news():
    seen, articles = set(), []

    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:20]:
                title = clean_text(entry.get("title"))
                summary = clean_text(entry.get("summary") or entry.get("description"))
                link = str(entry.get("link") or "").strip()
                if not title:
                    continue

                haystack = f"{title} {summary}".lower()
                if not any(k in haystack for k in MARKET_KEYWORDS):
                    continue

                key = title.lower()
                if key in seen:
                    continue
                seen.add(key)

                articles.append({
                    "title": title,
                    "summary": summary[:700],
                    "link": link,
                })
                if len(articles) >= 15:
                    break
        except Exception as exc:
            logging.warning("RSS failed: %s | %s", exc)

    logging.info("Retrieved %d relevant articles.", len(articles))
    return articles[:15]


def update_title(kind):
    return {
        "morning": "Good Morning Market Brief",
        "premarket": "Pre-Market Update",
        "open": "Market Open Update",
        "hourly": "Hourly Market Update",
        "close": "Market Close Update",
        "evening": "Evening Market Recap",
        "global": "Global Market Update",
        "holiday": "Holiday / Weekend Market Brief",
    }.get(kind, "Market Update")


def build_prompt(kind, articles, now):
    title = update_title(kind)

    news = "\n\n".join(
        f"{i+1}. {a['title']}\nDetails: {a['summary']}\nSource: {a['link']}"
        for i, a in enumerate(articles)
    ) or "No relevant RSS articles were retrieved."

    if kind == "holiday":
        focus = (
            "This is a non-trading-day briefing. Do not say Indian markets are "
            "currently trading. Focus on global markets, corporate/macro news, "
            "and what may matter for the next Indian session."
        )
    else:
        focus = "This is a trading-day update. Never invent live prices or moves."

    return f"""
You are the news editor for INFOCHARGE, an educational Indian stock-market community.

Create a concise Telegram update titled "{title}".
Current IST time: {now.strftime("%d %b %Y, %I:%M %p")}.
Update type: {kind}.

{focus}

Use ONLY facts supplied in the RSS articles.
Never invent prices, percentages, company statements, events, or market moves.
No buy/sell calls, signals, guaranteed returns, or profit promises.
No HTML, Markdown tables, or code blocks.
Use plain Telegram-friendly text.
Cover the 4–6 most relevant developments, 1–3 sentences each.
Include the source URL after each relevant item.
Keep the final answer below 3500 characters.

Start exactly with:
📊 INFOCHARGE | {title}

End exactly with:
⚠️ Educational information only. No buy/sell recommendation.

SUPPLIED RSS ARTICLES:
{news}
""".strip()


def generate_with_model(model, prompt):
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=900,
        ),
    )
    text = (response.text or "").strip()
    text = re.sub(r"```(?:text|markdown)?", "", text, flags=re.I)
    text = text.replace("```", "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text).strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response.")
    return text


def generate_summary(kind, articles, now):
    prompt = build_prompt(kind, articles, now)
    last_error = None

    for model in GEMINI_MODELS:
        for attempt in range(2):
            try:
                logging.info("Trying Gemini model=%s attempt=%d", model, attempt + 1)
                text = generate_with_model(model, prompt)
                logging.info("Gemini success with model=%s", model)
                return text
            except Exception as exc:
                last_error = exc
                logging.warning(
                    "Gemini failed: model=%s attempt=%d error=%s",
                    model, attempt + 1, exc
                )
                # 503/429/transient failures are commonly temporary.
                time.sleep(3)

        logging.warning("Switching Gemini model after failures: %s", model)

    raise RuntimeError(f"All Gemini attempts failed. Last error: {last_error}")


def split_message(text, max_chars=3900):
    text = text.strip()
    parts = []
    while len(text) > max_chars:
        cut = text.rfind("\n\n", 0, max_chars)
        if cut < 500:
            cut = text.rfind("\n", 0, max_chars)
        if cut < 500:
            cut = max_chars
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        parts.append(text)
    return parts


def telegram_request(method, payload):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    r = requests.post(url, json=payload, timeout=30)

    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text}

    if not r.ok or not body.get("ok", False):
        logging.error("Telegram API error: HTTP=%s | response=%s", r.status_code, body)
        raise RuntimeError(f"Telegram API rejected request: HTTP {r.status_code} | {body}")

    return body


def verify_telegram_target():
    me = telegram_request("getMe", {})
    logging.info("Telegram bot authenticated: @%s",
                 me.get("result", {}).get("username", "unknown"))

    chat = telegram_request("getChat", {"chat_id": TELEGRAM_CHAT_ID})
    result = chat.get("result", {})
    logging.info(
        "Telegram target verified: id=%s | title=%s | type=%s",
        result.get("id"), result.get("title"), result.get("type")
    )


def send_telegram(message):
    verify_telegram_target()

    for part in split_message(message):
        telegram_request("sendMessage", {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": part,
            "disable_web_page_preview": True,
        })

    logging.info("Telegram message sent successfully.")


def main():
    now = datetime.now(IST)
    kind = os.environ.get("INFOCHARGE_UPDATE_TYPE", "hourly").strip().lower()
    closed = is_closed(now)

    logging.info("IST time: %s", now.isoformat())
    logging.info("Update type: %s", kind)
    logging.info("NSE holiday/weekend: %s", closed)

    if closed and kind != "holiday":
        logging.info("Market closed; skipping trading-session update.")
        return
    if not closed and kind == "holiday":
        logging.info("Trading day; skipping holiday update.")
        return

    articles = fetch_news()
    message = generate_summary(kind, articles, now)
    logging.info("Generated message length: %d", len(message))
    send_telegram(message)


if __name__ == "__main__":
    main()
