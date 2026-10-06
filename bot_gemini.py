import os
import json
import logging
import re
import html
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import feedparser
import requests
from google import genai
from google.genai import types

IST = ZoneInfo("Asia/Kolkata")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

MODEL = "gemini-3.8-flash"
MEMORY_FILE = Path("infocharge_memory.json")
MAX_ARTICLES = 55
MAX_MEMORY_ITEMS = 80
HTTP_TIMEOUT = 15

NEWS_FEEDS = [
    "https://news.google.com/rss/search?q=Indian+stock+market+NSE+Nifty+Sensex&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=NSE+listed+company+order+results+announcement+India&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+SEBI+RBI+markets+stocks&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+IPO+stock+exchange+listing&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+data+centre+stocks+order+investment&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+semiconductor+stocks+investment+order&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+defence+stocks+order+contract&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+renewable+energy+stocks+order+capex&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+manufacturing+stocks+capex+order&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+banking+stocks+results+NPA+credit&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+pharma+stocks+USFDA+order+approval&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=India+IT+stocks+deal+contract+order&hl=en-IN&gl=IN&ceid=IN:en",
]

NSE_HOLIDAYS_2026 = {
    "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31",
    "2026-04-03", "2026-04-14", "2026-05-01", "2026-05-28",
    "2026-06-26", "2026-09-14", "2026-10-02", "2026-10-20",
    "2026-11-08", "2026-11-10", "2026-11-24", "2026-12-25",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
client = genai.Client(api_key=GEMINI_API_KEY)


def clean_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_title(title):
    title = clean_text(title).lower()
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def load_memory():
    if not MEMORY_FILE.exists():
        return {"posted": [], "editorial_notes": []}
    try:
        data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Memory is not an object")
        data.setdefault("posted", [])
        data.setdefault("editorial_notes", [])
        return data
    except Exception as exc:
        logging.warning("Memory read failed: %s", exc)
        return {"posted": [], "editorial_notes": []}


def save_memory(memory):
    MEMORY_FILE.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")


def memory_for_prompt(memory):
    posted = memory.get("posted", [])[-MAX_MEMORY_ITEMS:]
    notes = memory.get("editorial_notes", [])[-20:]
    compact = {
        "posted": [
            {
                "date": x.get("date"),
                "headline": x.get("headline"),
                "company": x.get("company"),
                "key": x.get("key"),
            }
            for x in posted
        ],
        "editorial_notes": notes,
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


def fetch_news():
    collected = []
    seen = set()

    for feed_url in NEWS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:12]:
                title = clean_text(entry.get("title", ""))
                summary = clean_text(entry.get("summary") or entry.get("description") or "")
                link = entry.get("link", "")
                published = clean_text(entry.get("published") or entry.get("updated") or "")
                if not title:
                    continue
                key = normalize_title(title)
                if not key or key in seen:
                    continue
                seen.add(key)
                collected.append({
                    "title": title,
                    "summary": summary[:900],
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


def call_gemini(prompt, max_tokens):
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(max_output_tokens=max_tokens),
    )
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response.")
    return text


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


def research_story(articles, memory, update_type, now):
    prompt = "\n".join([
        "You are the senior news editor for INFOCHARGE INSIDERS CLUB, an Indian stock-market intelligence channel.",
        f"CURRENT TIME IST: {now.strftime('%d %b %Y, %I:%M %p')}",
        f"UPDATE TYPE: {update_type}",
        f"MARKET STATUS: {market_status(now)}",
        "",
        "Select at most ONE genuinely important story. Do not post every news item.",
        "Prioritize material listed-company orders, earnings/guidance, capex, acquisitions, fundraising, IPO developments, major SEBI/RBI/government changes, and important sector developments.",
        "Reject routine index movement, tiny contracts, vague commentary, rumours, clickbait, duplicates, and weakly supported stories.",
        "Prefer a story supported by multiple reports.",
        "Do not invent numbers, customers, dates, percentages, or company facts.",
        "No buy/sell recommendation, target price, or guaranteed-return language.",
        "NO_POST is completely acceptable.",
        "",
        "Return ONLY valid JSON with these keys:",
        'decision (POST or NO_POST), importance (0-10), headline, company, sector, key_facts (array), why_it_matters, bigger_theme, caveat, memory_key, editorial_note.',
        "",
        "EDITORIAL MEMORY:",
        memory_for_prompt(memory),
        "",
        "CURRENT NEWS REPORTS:",
        article_packet(articles),
    ])
    return extract_json(call_gemini(prompt, 2600))


def write_post(research, update_type, now):
    prompt = "\n".join([
        "You are the final editor for INFOCHARGE INSIDERS CLUB.",
        "Write ONE premium Telegram post from the research below.",
        "",
        "Style: human, sharp, concise, intelligent, financial-editor style. Do not sound like an RSS bot.",
        "Start with a strong hook. Explain the important fact first, then WHY IT MATTERS.",
        "Use important numbers prominently and connect to the larger business or sector theme when supported.",
        "Use short paragraphs and bullets where natural. Emojis are allowed selectively.",
        "Do not say Good morning, do not say Here are today's top news, do not add generic introductions.",
        "Do not use raw URLs, unnecessary hashtags, buy/sell calls, target prices, promises, or invented information.",
        "Do not force a fixed template.",
        "Length: approximately 700-1300 characters.",
        "Return ONLY the final Telegram post.",
        "",
        f"UPDATE TYPE: {update_type}",
        f"TIME: {now.strftime('%d %b %Y, %I:%M %p')}",
        "",
        "RESEARCH:",
        json.dumps(research, ensure_ascii=False, indent=2),
    ])
    return call_gemini(prompt, 1800).strip()


def split_message(text, limit=3900):
    if len(text) <= limit:
        return [text]
    chunks = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = paragraph if not current else current + "\n\n" + paragraph
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)

    result = []
    for chunk in chunks:
        if len(chunk) <= limit:
            result.append(chunk)
        else:
            result.extend(chunk[i:i + limit] for i in range(0, len(chunk), limit))
    return result


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chunk in split_message(text):
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "disable_web_page_preview": True,
            },
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram API error: {payload}")


def record_memory(memory, research, post):
    memory.setdefault("posted", []).append({
        "date": datetime.now(IST).strftime("%Y-%m-%d %H:%M"),
        "headline": research.get("headline", ""),
        "company": research.get("company", ""),
        "key": research.get("memory_key", ""),
        "importance": research.get("importance", 0),
        "post": post,
    })
    memory["posted"] = memory["posted"][-MAX_MEMORY_ITEMS:]

    note = research.get("editorial_note")
    if note:
        memory.setdefault("editorial_notes", []).append(note)
        memory["editorial_notes"] = memory["editorial_notes"][-20:]


def main():
    now = datetime.now(IST)
    update_type = os.getenv("INFOCHARGE_UPDATE_TYPE", "manual")
    status = market_status(now)

    logging.info(
        "INFOCHARGE AI Bot | %s | %s | %s",
        now.isoformat(),
        update_type,
        status,
    )

    if status == "closed":
        logging.info("Market is closed today. No normal market post.")
        return

    articles = fetch_news()
    logging.info("Collected %d unique news items.", len(articles))

    if not articles:
        logging.info("No news collected. Nothing to post.")
        return

    memory = load_memory()
    research = research_story(articles, memory, update_type, now)

    decision = str(research.get("decision", "NO_POST")).upper()
    try:
        importance = int(research.get("importance", 0) or 0)
    except Exception:
        importance = 0

    logging.info(
        "Editorial decision=%s | importance=%s | headline=%s",
        decision,
        importance,
        research.get("headline", ""),
    )

    # Deterministic duplicate protection: never post a story already
    # recorded in editorial memory, even if the model selects it again.
    candidate_key = normalize_title(
        research.get("memory_key")
        or research.get("headline")
        or ""
    )
    posted_keys = {
        normalize_title(
            item.get("key")
            or item.get("headline")
            or ""
        )
        for item in memory.get("posted", [])
    }

    if candidate_key and candidate_key in posted_keys:
        logging.info("Story already exists in memory. Nothing sent.")
        return

    if decision != "POST" or importance < 7:
        logging.info("No sufficiently important story. Nothing sent.")
        return

    post = write_post(research, update_type, now)
    if not post:
        raise RuntimeError("Final post was empty.")

    send_telegram(post)

    record_memory(memory, research, post)
    save_memory(memory)

    logging.info("INFOCHARGE post sent successfully.")


if __name__ == "__main__":
    main()
