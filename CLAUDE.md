# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is
Telegram bot that reminds groups about upcoming classes. Runs for free as a GitHub Actions cron job (every 5 min); there is no long-running server.

## Commands
- Run locally: `BOT_TOKEN=<token> python3 bot.py` (stdlib only, Python 3.9+; no tests/lint configured). It really calls Telegram and rewrites `data/*.json`.
- Production: `.github/workflows/remind.yml` with repo secret `BOT_TOKEN`.

## Architecture
Single script `bot.py`, one run = one pass: (1) poll `getUpdates` and handle `/start`, `/stop`, `/list` (also drops groups when the bot is kicked), (2) send due reminders, (3) save state.
- `data/groups.json` – connected chats (edited by bot commands or by hand).
- `data/schedule.json` – lessons: `group` (chat id), `days` (mon..sun) or one-off `date`, `time` HH:MM, `title`, `remind` (minutes before), optional `link`/`note`.
- `data/state.json` – `offset` for getUpdates and `sent` dedupe keys. The workflow commits `data/` back to the repo after each run, so this is the only persistence.
- Cron is imprecise, so a reminder fires if now is within `GRACE_MIN` (45 min) after its target time; dedupe via `sent` prevents repeats.
- getUpdates does not work if a webhook is set on the bot (`deleteWebhook` first).
