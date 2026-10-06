FINAL INFOCHARGE AI MARKET INTELLIGENCE V2

Replace these together:
1. bot_gemini.py
2. .github/workflows/main.yml
3. requirements_gemini.txt
4. infocharge_memory.json

Keep all existing GitHub Secrets unchanged:
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
GEMINI_API_KEY

This version uses Gemini 2.5 Flash-Lite/Flash with Google Search grounding,
Indian-market filtering, a NO_POST decision, human-style writing, duplicate
memory, and a free locally generated INFOCHARGE visual card.

It deliberately checks selected Indian-market windows instead of posting every
hour. The bot only posts when the AI rates a story as genuinely important.

The memory file is committed back to GitHub after a successful post so future
runs know what was already covered.
