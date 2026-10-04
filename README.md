# INFOCHARGE — Free AI Market News Bot

This version uses **GitHub Actions** instead of a paid always-on Render worker.

## What it posts

### Trading days (IST)
- 07:30 — Good Morning
- 08:45 — Pre-market
- 09:20 — Market Open
- 10:00–15:00 — Hourly updates
- 15:45 — Market Close
- 18:30 — Evening Recap
- 21:30 — Global Market Update

### Saturday / Sunday / NSE holiday
- Every 6 hours: 00:00, 06:00, 12:00, 18:00 IST
- These are non-trading-day briefings, not fake trading-session updates.

## GitHub Secrets

Add these repository secrets:
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- OPENAI_API_KEY
- OPENAI_MODEL

Use an OpenAI API model that is actually available in your API account for `OPENAI_MODEL`.

## Important

GitHub Actions scheduling can occasionally be delayed by GitHub. It is not guaranteed to fire to the exact second.

The 2026 NSE holiday list is embedded in `bot.py`. Update it for future years.

No buy/sell calls are generated. The AI is instructed to summarize supplied news only and not invent facts.
