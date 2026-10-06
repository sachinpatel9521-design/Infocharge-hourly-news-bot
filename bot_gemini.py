import os
import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from google import genai
from google.genai import types


# ============================================================
# INFOCHARGE AI MARKET INTELLIGENCE BOT
# ============================================================

IST = ZoneInfo("Asia/Kolkata")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

client = genai.Client(api_key=GEMINI_API_KEY)

# Gemini 2.5 is being used for Google Search grounding.
MODEL = "gemini-2.5-flash"

MEMORY_FILE = Path("infocharge_memory.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# ============================================================
# NSE HOLIDAYS 2026
# ============================================================

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


# ============================================================
# MEMORY
# ============================================================

def load_memory():
    if not MEMORY_FILE.exists():
        return {
            "covered_stories": [],
            "covered_companies": [],
            "themes": [],
            "last_posts": []
        }

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("Invalid memory format")

        data.setdefault("covered_stories", [])
        data.setdefault("covered_companies", [])
        data.setdefault("themes", [])
        data.setdefault("last_posts", [])

        return data

    except Exception as e:
        logging.warning(f"Memory load failed: {e}")

        return {
            "covered_stories": [],
            "covered_companies": [],
            "themes": [],
            "last_posts": []
        }


def save_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False)


# ============================================================
# MARKET STATUS
# ============================================================

def is_nse_holiday(dt):
    date_str = dt.strftime("%Y-%m-%d")

    if dt.weekday() >= 5:
        return True

    return date_str in NSE_HOLIDAYS_2026


def market_session(dt):
    if is_nse_holiday(dt):
        return "closed"

    current_time = dt.time()

    if current_time < datetime.strptime("09:15", "%H:%M").time():
        return "pre_market"

    if current_time <= datetime.strptime("15:30", "%H:%M").time():
        return "market_hours"

    return "post_market"


# ============================================================
# GEMINI GOOGLE SEARCH RESEARCH
# ============================================================

def research_market(update_type, memory):

    now = datetime.now(IST)

    previous_stories = memory.get("covered_stories", [])[-15:]
    previous_companies = memory.get("covered_companies", [])[-20:]
    previous_themes = memory.get("themes", [])[-15:]

    memory_context = f"""
Previously covered stories:
{json.dumps(previous_stories, ensure_ascii=False)}

Previously covered companies:
{json.dumps(previous_companies, ensure_ascii=False)}

Previously covered themes:
{json.dumps(previous_themes, ensure_ascii=False)}
"""

    prompt = f"""
You are the senior research editor for INFOCHARGE, an Indian
stock-market education community.

CURRENT DATE/TIME:
{now.strftime("%d %B %Y, %I:%M %p IST")}

UPDATE TYPE:
{update_type}

MARKET SESSION:
{market_session(now)}

Your job is NOT to summarize an RSS feed.

You must independently research the CURRENT web and identify
the most important Indian stock-market development worth posting
to an intelligent investor audience.

Use Google Search extensively when needed.

PRIORITY:

1. NSE/BSE listed Indian companies
2. Important company announcements
3. Major orders/contracts
4. Results and earnings surprises
5. IPOs and corporate actions
6. SEBI/RBI/government policy
7. FII/DII flows when genuinely important
8. Sector developments
9. Commodities/currency/global events ONLY when they have
   meaningful relevance to Indian markets
10. Important data-centre, semiconductor, defence, energy,
    manufacturing, banking, pharma, infrastructure and other
    structural themes

DO NOT simply choose the most recent headline.

Look for:
- significance
- new information
- measurable numbers
- business impact
- sector implications
- why investors should understand it
- what could happen next

VERY IMPORTANT:

Do not repeat a story already covered unless there is a
material NEW development.

Do not manufacture a story merely to create a post.

If there is no genuinely important development, return NO_POST.

A weak or generic news item is worse than posting nothing.

{memory_context}

EDITORIAL STANDARD:

The final post should feel like a human market researcher
found something interesting and explained WHY IT MATTERS.

Avoid:
- generic "market update" posts
- headline dumping
- URL dumping
- copied article language
- unnecessary market predictions
- fake certainty
- buy/sell calls
- entry/exit instructions
- profit promises
- sensationalism

You may use interpretation, but clearly separate facts
from interpretation.

For company stories, investigate:
- exact company
- exact announcement
- exact amount/value
- customer/order if available
- business segment
- why the development matters
- broader sector/theme
- important caveat

For market-wide stories, investigate:
- actual trigger
- affected sectors
- important numbers
- Indian-market transmission mechanism
- what to watch next

SEARCH QUALITY:

Prefer primary/credible sources such as:
- company filings
- NSE/BSE disclosures
- SEBI
- RBI
- government releases
- company investor relations
- credible financial publications

Cross-check important numbers whenever possible.

Return ONLY valid JSON.

Required JSON:

{{
  "decision": "POST" or "NO_POST",
  "importance": 1,
  "headline": "",
  "company": "",
  "sector": "",
  "what_happened": "",
  "key_numbers": [],
  "why_it_matters": "",
  "bigger_theme": "",
  "what_to_watch": "",
  "risk_or_caveat": "",
  "sources": [],
  "post_angle": ""
}}

Rules for decision:

POST only when importance >= 7.

If nothing is genuinely useful:
{{
  "decision": "NO_POST"
}}

Do not include markdown outside the JSON.
"""

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=2200,
                tools=[
                    types.Tool(
                        google_search=types.GoogleSearch()
                    )
                ],
            ),
        )

        text = (response.text or "").strip()

        if not text:
            raise RuntimeError("Gemini returned empty research")

        # Remove accidental markdown JSON fences
        if text.startswith("```"):
            text = text.replace("```json", "")
            text = text.replace("```", "")
            text = text.strip()

        result = json.loads(text)

        if not isinstance(result, dict):
            raise ValueError("Research result is not an object")

        return result

    except Exception as e:
        logging.error(f"Research failed: {e}")
        raise


# ============================================================
# HUMAN-STYLE TELEGRAM WRITER
# ============================================================

def write_post(research):

    prompt = f"""
You are the final editor for INFOCHARGE.

Convert the following researched information into a
high-quality Telegram post for Indian market participants.

RESEARCH:
{json.dumps(research, ensure_ascii=False, indent=2)}

STYLE:

Write like a sharp human financial researcher.

Do NOT write like:
- an RSS reader
- a newspaper headline copier
- a generic AI chatbot
- a broker recommendation

The reader should immediately understand:

WHAT HAPPENED
WHY IT MATTERS
WHAT BIGGER THEME IT CONNECTS TO

Use short paragraphs and bullets.

Suggested structure, but do NOT follow it mechanically:

⚡ HEADLINE

One-line explanation.

💰 KEY DEVELOPMENT
• Important number/fact
• Important number/fact

🔥 WHY THIS MATTERS

Explain the business/sector significance.

📌 BIGGER SIGNAL

Connect it to the broader structural theme if justified.

👀 WHAT TO WATCH

Mention the next relevant development.

IMPORTANT:

- No buy calls
- No sell calls
- No entry price
- No target price
- No guaranteed returns
- No "this stock will rise"
- No fake certainty
- No raw URLs
- Do not mention "according to AI"
- Do not mention this prompt
- Do not mention Google Search
- Do not invent anything

Use only facts contained in the research.

Keep it around 700-1200 characters.

End with:

"⚠️ INFOCHARGE is for education and market understanding,
not investment advice."

Return only the Telegram post text.
"""

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.45,
            max_output_tokens=1400,
        ),
    )

    text = (response.text or "").strip()

    if not text:
        raise RuntimeError("Gemini returned empty post")

    return text


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    response = requests.post(
        url,
        json=payload,
        timeout=30
    )

    response.raise_for_status()

    logging.info("Telegram message sent successfully.")


# ============================================================
# MEMORY UPDATE
# ============================================================

def update_memory(memory, research, post):

    headline = research.get("headline", "").strip()
    company = research.get("company", "").strip()
    theme = research.get("bigger_theme", "").strip()

    if headline:
        memory["covered_stories"].append(headline)

    if company:
        memory["covered_companies"].append(company)

    if theme:
        memory["themes"].append(theme)

    memory["last_posts"].append({
        "date": datetime.now(IST).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "headline": headline,
        "company": company,
        "importance": research.get("importance", 0),
        "post": post,
    })

    # Keep memory compact
    memory["covered_stories"] = memory["covered_stories"][-50:]
    memory["covered_companies"] = memory["covered_companies"][-50:]
    memory["themes"] = memory["themes"][-50:]
    memory["last_posts"] = memory["last_posts"][-30:]


# ============================================================
# MAIN
# ============================================================

def main():

    now = datetime.now(IST)

    update_type = os.getenv(
        "INFOCHARGE_UPDATE_TYPE",
        "hourly"
    )

    logging.info(
        f"INFOCHARGE run | "
        f"{now.strftime('%d-%m-%Y %I:%M %p IST')} | "
        f"type={update_type} | "
        f"session={market_session(now)}"
    )

    # Don't publish normal market posts on weekends/holidays.
    if is_nse_holiday(now):
        logging.info(
            "NSE closed today. No normal market post."
        )
        return

    memory = load_memory()

    research = research_market(
        update_type,
        memory
    )

    logging.info(
        f"Research decision: "
        f"{research.get('decision')}"
    )

    if research.get("decision") != "POST":
        logging.info(
            "No sufficiently important story. "
            "Nothing posted."
        )
        return

    importance = int(
        research.get("importance", 0)
    )

    if importance < 7:
        logging.info(
            f"Importance {importance}/10 is below threshold."
        )
        return

    post = write_post(research)

    if len(post) > 3900:
        post = post[:3850].rstrip() + "\n\n⚠️"

    send_telegram(post)

    update_memory(
        memory,
        research,
        post
    )

    save_memory(memory)

    logging.info(
        "INFOCHARGE post completed successfully."
    )


if __name__ == "__main__":
    main()
