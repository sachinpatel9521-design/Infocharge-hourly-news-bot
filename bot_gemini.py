import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import feedparser
import requests
from google import genai

IST = ZoneInfo("Asia/Kolkata")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

GEMINI_MODEL = "gemini-3.8-flash"
client = genai.Client(api_key=GEMINI_API_KEY)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

NSE_HOLIDAYS_2026 = {
    "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26",
    "2026-03-31", "2026-04-03", "2026-04-14", "2026-05-01",
    "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02",
    "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25",
}

SPECIAL_MUHURAT_2026 = {"2026-11-08"}

RSS_FEEDS = [
    "https://www.moneycontrol.com/rss/latestnews.xml",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.business-standard.com/rss/markets-106.rss",
]

MARKET_KEYWORDS = [
    "nifty", "sensex", "stock market", "share market", "stocks",
    "equity", "market", "sebi", "rbi", "inflation", "interest rate",
    "ipo", "fii", "dii", "bank nifty", "crude oil", "gold", "rupee",
    "dollar", "earnings", "results", "economy", "fed", "nasdaq",
    "dow jones", "s&p 500",
]

def is_nse_holiday(dt):
    date_str = dt.strftime("%Y-%m-%d")
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
            for entry in feed.entries[:15]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                summary = entry.get("summary", "").strip()
                if not title or not link:
                    continue
                combined = f"{title} {summary}".lower()
                if any(k in combined for k in MARKET_KEYWORDS):
                    articles.append({"title": title, "summary": summary, "link": link})
        except Exception as e:
            logging.warning(f"RSS error: {e}")

    unique, seen = [], set()
    for article in articles:
        key = article["title"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(article)
    return unique[:20]

def generate_ai_update(articles, update_type):
    if not articles:
        return (
            "📊 <b>INFOCHARGE MARKET UPDATE</b>\n\n"
            "No major market-related news was retrieved from the selected sources at this time."
        )

    news_text = ""
    for i, article in enumerate(articles, 1):
        news_text += f"\n{i}. {article['title']}\nSource: {article['link']}\n"

    prompt = f"""
You are the AI news editor for INFOCHARGE, an Indian stock-market education community.

Update type: {update_type}
Current Indian date/time: {datetime.now(IST).strftime("%d %B %Y, %I:%M %p IST")}

REAL headlines retrieved from RSS feeds:
{news_text}

Create a concise Telegram market update.

RULES:
1. No buy calls.
2. No sell calls.
3. No entry/exit instructions.
4. No profit promises.
5. Do not invent facts.
6. Use only information supported by the supplied headlines.
7. Clearly distinguish facts from interpretation.
8. Use simple language useful for Indian market participants.
9. Do not make up market prices.
10. Include source links.
11. Do not claim that the market moved unless the supplied information supports it.

FORMAT:

📊 <b>INFOCHARGE | {update_type.upper()}</b>

📰 <b>TOP NEWS</b>
• 3–6 important points

🌍 <b>MARKET IMPACT</b>
• Short explanation.
• No trading recommendation.

🔎 <b>WHAT TO WATCH</b>
• Important upcoming factors/events supported by the news.

🔗 <b>SOURCES</b>
Include relevant source links.

Keep the message concise and Telegram-friendly.
"""

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        text = response.text
        if not text:
            raise RuntimeError("Gemini returned an empty response")
        return text.strip()
    except Exception as e:
        logging.error(f"Gemini error: {e}")
        return (
            "📊 <b>INFOCHARGE MARKET UPDATE</b>\n\n"
            "AI summary could not be generated right now.\n"
            "Please check the latest market news manually."
        )

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    logging.info("Telegram message sent successfully.")

def main():
    now = datetime.now(IST)
    update_type = os.getenv("INFOCHARGE_UPDATE_TYPE", "hourly")
    holiday = is_nse_holiday(now)

    logging.info(f"IST time: {now}")
    logging.info(f"Update type: {update_type}")
    logging.info(f"NSE holiday/weekend: {holiday}")

    if holiday:
        if update_type != "holiday":
            logging.info("NSE is closed. Skipping normal market update.")
            return
    else:
        if update_type == "holiday":
            logging.info("Trading day. Skipping holiday briefing.")
            return

    articles = fetch_news()
    logging.info(f"Retrieved {len(articles)} relevant articles.")

    message = generate_ai_update(articles, update_type)
    send_telegram(message)

if __name__ == "__main__":
    main()
