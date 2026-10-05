# INFOCHARGE Gemini Market Updates

Telegram market-news bot for INFOCHARGE.

## Secrets required

Add these GitHub Actions secrets:

- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- GEMINI_API_KEY

No OpenAI secret is required.

## Schedule

Trading days:
- 07:30 IST morning
- 08:45 IST pre-market
- 09:20 IST market open
- 10:00–15:00 IST hourly
- 15:45 IST close
- 18:30 IST evening recap
- 21:30 IST global update

Weekends/NSE holidays:
- 00:00, 06:00, 12:00, 18:00 IST general market/news briefing

GitHub Actions scheduled jobs can occasionally start late. The bot determines the update type from the scheduled event itself, so a delayed job does not get misclassified.

## Manual test

Actions → INFOCHARGE Gemini Market Updates → Run workflow → choose `hourly`.
