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


# =========================================================
# CONFIG
# =========================================================

IST = ZoneInfo("Asia/Kolkata")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

MODEL = "gemini-3.8-flash"

MEMORY_FILE = Path("infocharge_memory.json")

MAX_ARTICLES = 55
MAX_MEMORY_ITEMS = 80
HTTP_TIMEOUT = 15


# =========================================================
# NEWS SOURCES
# =========================================================

NEWS_FEEDS = [
    (
        "Google News",
        "https://news.google.com/rss/search?q=Indian+stock+market+NSE+Nifty+Sensex&hl=en-IN&gl=IN&ceid=IN:en",
    ),
    (
        "Google News",
        "https://news.google.com/rss/search?q=NSE+listed+company+order+results+announcement+India&hl=en-IN&gl=IN&ceid=IN:en",
    ),
    (
        "Google News",
        "https://news.google.com/rss/search?q=India+SEBI+RBI+markets+stocks&hl=en-IN&gl=IN&ceid=IN:en",
    ),
    (
        "Google News",
        "https://news.google.com/rss/search?q=India+IPO+stock+exchange+listing&hl=en-IN&gl=IN&ceid=IN:en",
    ),
    (
        "Google News",
        "https://news.google.com/rss/search?q=India+data+centre+stocks+order+investment&hl=en-IN&gl=IN&ceid=IN:en",
    ),
    (
        "Google News",
        "https://news.google.com/rss/search?q=India+semiconductor+stocks+investment+order&hl=en-IN&gl=IN&ceid=IN:en",
    ),
    (
        "Google News",
        "https://news.google.com/rss/search?q=India+defence+stocks+order+contract&hl=en-IN&gl=IN&ceid=IN:en",
    ),
    (
        "Google News",
        "https://news.google.com/rss/search?q=India+renewable+energy+stocks+order+capex&hl=en-IN&gl=IN&ceid=IN:en",
    ),
    (
        "Google News",
        "https://news.google.com/rss/search?q=India+manufacturing+stocks+capex+order&hl=en-IN&gl=IN&ceid=IN:en",
    ),
    (
        "Google News",
        "https://news.google.com/rss/search?q=India+banking+stocks+results+NPA+credit&hl=en-IN&gl=IN&ceid=IN:en",
    ),
    (
        "Google News",
        "https://news.google.com/rss/search?q=India+pharma+stocks+USFDA+order+approval&hl=en-IN&gl=IN&ceid=IN:en",
    ),
    (
        "Google News",
        "https://news.google.com/rss/search?q=India+IT+stocks+deal+contract+order&hl=en-IN&gl=IN&ceid=IN:en",
    ),
]


# =========================================================
# NSE EQUITY HOLIDAYS 2026
# =========================================================

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


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


# =========================================================
# GEMINI
# =========================================================

client = genai.Client(
    api_key=GEMINI_API_KEY
)


# =========================================================
# TEXT CLEANING
# =========================================================

def clean_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_title(title):
    title = clean_text(title).lower()
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


# =========================================================
# MEMORY
# =========================================================

def load_memory():

    if not MEMORY_FILE.exists():
        return {
            "posted": [],
            "editorial_notes": [],
        }

    try:

        data = json.loads(
            MEMORY_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(data, dict):
            raise ValueError(
                "Memory is not a JSON object."
            )

        data.setdefault(
            "posted",
            []
        )

        data.setdefault(
            "editorial_notes",
            []
        )

        return data

    except Exception as exc:

        logging.warning(
            "Memory read failed: %s",
            exc
        )

        return {
            "posted": [],
            "editorial_notes": [],
        }


def save_memory(memory):

    MEMORY_FILE.write_text(
        json.dumps(
            memory,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


def memory_for_prompt(memory):

    posted = memory.get(
        "posted",
        []
    )[-MAX_MEMORY_ITEMS:]

    notes = memory.get(
        "editorial_notes",
        []
    )[-20:]

    compact = {
        "posted": [
            {
                "date": item.get("date"),
                "headline": item.get("headline"),
                "company": item.get("company"),
                "key": item.get("key"),
            }
            for item in posted
        ],
        "editorial_notes": notes,
    }

    return json.dumps(
        compact,
        ensure_ascii=False
    )


# =========================================================
# MARKET STATUS
# =========================================================

def market_status(now):

    date_key = now.strftime(
        "%Y-%m-%d"
    )

    if (
        now.weekday() >= 5
        or date_key in NSE_HOLIDAYS_2026
    ):
        return "closed"

    minutes = (
        now.hour * 60
        + now.minute
    )

    if minutes < 9 * 60 + 15:
        return "pre_market"

    if minutes <= 15 * 60 + 30:
        return "market_hours"

    return "post_market"


# =========================================================
# FETCH NEWS
# =========================================================

def fetch_news():

    collected = []
    seen = set()

    for feed_name, feed_url in NEWS_FEEDS:

        try:

            feed = feedparser.parse(
                feed_url
            )

            for entry in feed.entries[:12]:

                title = clean_text(
                    entry.get(
                        "title",
                        ""
                    )
                )

                summary = clean_text(
                    entry.get("summary")
                    or entry.get("description")
                    or ""
                )

                link = entry.get(
                    "link",
                    ""
                )

                published = clean_text(
                    entry.get("published")
                    or entry.get("updated")
                    or ""
                )

                source = ""

                source_obj = entry.get(
                    "source"
                )

                if isinstance(
                    source_obj,
                    dict
                ):

                    source = clean_text(
                        source_obj.get(
                            "title",
                            ""
                        )
                    )

                if not title:
                    continue

                key = normalize_title(
                    title
                )

                if (
                    not key
                    or key in seen
                ):
                    continue

                seen.add(key)

                collected.append(
                    {
                        "title": title,
                        "summary": summary[:900],
                        "source": (
                            source
                            or feed_name
                        ),
                        "published": published,
                        "link": link,
                    }
                )

        except Exception as exc:

            logging.warning(
                "News feed failed: %s | %s",
                feed_url,
                exc
            )

    return collected[:MAX_ARTICLES]


# =========================================================
# ARTICLE PACKET
# =========================================================

def article_packet(articles):

    blocks = []

    for i, item in enumerate(
        articles,
        1
    ):

        block = "\n".join(
            [
                f"ARTICLE {i}",
                f"Source: {item['source']}",
                f"Published: {item['published']}",
                f"Title: {item['title']}",
                f"Summary: {item['summary']}",
                f"Link: {item['link']}",
            ]
        )

        blocks.append(block)

    return "\n\n".join(blocks)


# =========================================================
# GEMINI CALL
# =========================================================

def call_gemini(
    prompt,
    max_tokens
):

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=max_tokens
        ),
    )

    text = (
        response.text
        or ""
    ).strip()

    if not text:

        raise RuntimeError(
            "Gemini returned an empty response."
        )

    return text


# =========================================================
# JSON EXTRACTION
# =========================================================

def extract_json(text):

    text = text.strip()

    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\s*```$",
        "",
        text
    )

    try:

        return json.loads(
            text
        )

    except json.JSONDecodeError:

        match = re.search(
            r"\{.*\}",
            text,
            flags=re.DOTALL
        )

        if not match:

            raise RuntimeError(
                "Gemini did not return valid JSON."
            )

        return json.loads(
            match.group(0)
        )


# =========================================================
# AI RESEARCH + EDITORIAL DECISION
# =========================================================

def research_story(
    articles,
    memory,
    update_type,
    now
):

    prompt_parts = [

        "You are the senior news editor for INFOCHARGE INSIDERS CLUB, an Indian stock-market intelligence channel.",

        "",

        f"CURRENT TIME (IST): {now.strftime('%d %b %Y, %I:%M %p')}",

        f"UPDATE TYPE: {update_type}",

        f"MARKET STATUS: {market_status(now)}",

        "",

        "Your job is NOT to post every news item.",

        "Use the supplied current-news reports as discovery material.",

        "Select at most ONE story worth publishing.",

        "",

        "PRIORITY:",

        "1. Major listed-company orders/contracts with meaningful value or strategic customers.",

        "2. Material earnings, guidance, capacity expansion, capex, acquisition, demerger, fundraising or major business wins.",

        "3. Major SEBI/RBI/government regulatory developments that can materially affect markets or sectors.",

        "4. IPO/listing/deal developments with genuine significance.",

        "5. Important sector developments: defence, power, data centres, semiconductors, renewables, manufacturing, pharma, banking, IT.",

        "6. Broad Nifty/Sensex moves only when there is a genuinely important catalyst.",

        "",

        "REJECT:",

        "- routine index movement",

        "- small/unimportant contracts",

        "- vague commentary",

        "- clickbait",

        "- rumours presented as facts",

        "- generic market updates",

        "- duplicate stories",

        "- stories already posted",

        "- stories where evidence is too weak",

        "",

        "IMPORTANT:",

        "- Do NOT invent numbers, customers, dates, percentages or company facts.",

        "- If reports conflict, mention the uncertainty.",

        "- Prefer stories supported by multiple reports.",

        "- One excellent story is better than five weak stories.",

        "- No buy/sell recommendation.",

        "- No target price.",

        "- No guaranteed-return language.",

        "- NO_POST is completely acceptable.",

        "",

        "Return ONLY valid JSON.",

        "Use exactly these keys:",

        '{"decision":"POST" or "NO_POST","importance":0-10,"headline":"...","company
