# INFOCHARGE Hourly Market News Bot

Posts an Indian stock-market news bulletin to Telegram every hour.

## What it does
- Reads market-news RSS feeds.
- Filters for Indian/global market keywords.
- Removes duplicate headlines.
- Optionally uses the OpenAI Responses API to create a concise bulletin.
- Posts to a Telegram channel/group every hour.
- Uses Asia/Kolkata timezone.
- Includes an education/not-investment-advice footer.

## 1. Create the Telegram bot
Open Telegram and talk to @BotFather.
Use /newbot, choose a name and username, then copy the bot token.

## 2. Add the bot to your Telegram destination
For a channel: add the bot as an administrator with permission to post messages.
For a group: add the bot and allow it to send messages.

Set TELEGRAM_CHAT_ID to @yourchannelusername when possible.

## 3. Configure
Copy .env.example to .env and fill in:
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
OPENAI_API_KEY (optional)

## 4. Run locally
Python 3.11+ is recommended.

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env
    python bot.py

The bot sends one test update immediately, then every hour.

## 5. Deploy 24/7
Use any always-on Python host that supports a background worker. Keep the process:
    python bot.py

Do not commit .env or expose bot/API keys.

## Notes
RSS availability can change. Replace/add feeds in RSS_FEEDS inside bot.py if a source stops responding.
The bot intentionally does not generate buy/sell calls.
