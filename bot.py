import os, re, hashlib, logging
from datetime import datetime, timezone, timedelta
import feedparser
import requests
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler

load_dotenv()
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-mini")
MAX_ARTICLES = int(os.getenv("MAX_ARTICLES", "8"))
IST = timezone(timedelta(hours=5, minutes=30))

RSS_FEEDS = [
    "https://www.moneycontrol.com/rss/marketreports.xml",
    "https://www.moneycontrol.com/rss/latestnews.xml",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.business-standard.com/rss/markets-106.rss",
]

KEYWORDS = (
    "nifty", "sensex", "bank nifty", "nse", "bse", "rbi", "sebi", "fii", "dii",
    "ipo", "earnings", "results", "quarter", "reliance", "tcs", "infosys",
    "hdfc", "icici", "sbi", "adani", "tata", "inflation", "rupee", "crude",
    "fed", "nasdaq", "dow", "gift nifty", "futures", "options", "stock",
    "shares", "market", "sector", "merger", "acquisition", "block deal"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def clean_html(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()

def fetch_news():
    items, seen = [], set()
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:25]:
                title = clean_html(e.get("title", ""))
                link = e.get("link", "")
                summary = clean_html(e.get("summary", ""))
                key = (title.lower(), link)
                if not title or key in seen:
                    continue
                text = f"{title} {summary}".lower()
                if any(k in text for k in KEYWORDS):
                    seen.add(key)
                    items.append({"title": title, "summary": summary, "link": link})
        except Exception as exc:
            logging.warning("RSS failed %s: %s", url, exc)
    return items[:MAX_ARTICLES]

def fallback_post(items):
    lines = ["🔔 <b>INFOCHARGE HOURLY MARKET UPDATE</b>",
             f"🕐 {datetime.now(IST).strftime('%d %b %Y • %I:%M %p IST')}", ""]
    if not items:
        lines.append("No major market-related headlines found in the latest RSS feeds.")
    else:
        lines.append("<b>📰 Key Headlines</b>")
        for i, x in enumerate(items[:6], 1):
            lines.append(f"{i}. {x['title']}")
            lines.append(f"🔗 {x['link']}")
    lines += ["", "⚠️ <i>Information for education and market awareness only. Not a buy/sell recommendation.</i>",
              "— INFOCHARGE"]
    return "\n".join(lines)[:4096]

def ai_post(items):
    if not OPENAI_API_KEY:
        return fallback_post(items)
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    source = "\n\n".join(
        f"HEADLINE: {x['title']}\nSUMMARY: {x['summary']}\nURL: {x['link']}" for x in items
    )
    prompt = f"""Create a concise hourly Indian stock-market news bulletin for an INFOCHARGE Telegram community.
Use ONLY the supplied headlines/summaries. Do not invent facts, prices, targets, or recommendations.
Prioritize Nifty/Sensex, RBI/SEBI, major companies, IPOs, results, FII/DII and global factors affecting India.
Format in Telegram HTML. Maximum 1800 characters.
Start with: 🔔 <b>INFOCHARGE HOURLY MARKET UPDATE</b>
Then time, 3-6 most important items, and a one-line "Market Impact" section.
Every item should include its source URL on a new line.
End exactly with:
⚠️ <i>Information for education and market awareness only. Not a buy/sell recommendation.</i>
— INFOCHARGE

SOURCE MATERIAL:
{source}"""
    r = client.responses.create(model=MODEL, input=prompt)
    text = r.output_text.strip()
    return text[:4096]

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML", "disable_web_page_preview": False}
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()

def run_once():
    items = fetch_news()
    message = ai_post(items)
    send_telegram(message)
    logging.info("Posted hourly update with %d headlines.", len(items))

if __name__ == "__main__":
    run_once()
    scheduler = BlockingScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(run_once, "interval", hours=1, id="hourly_market_news",
                      max_instances=1, coalesce=True)
    logging.info("INFOCHARGE bot running: every hour, Asia/Kolkata.")
    scheduler.start()
