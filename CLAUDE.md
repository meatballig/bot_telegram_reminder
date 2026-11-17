# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is
Telegram bot (`@bla_bla_reminder_bot`) that reminds groups about upcoming classes. No server: a GitHub Actions workflow runs `bot.py` once per trigger. The repo is public (`github.com/meatballig/bot_telegram_reminder`, branch `main`), so Actions minutes are free. The owner communicates in Russian; reply in Russian.

## Commands
- Run locally: `BOT_TOKEN=<token> python3 bot.py` (stdlib only, Python 3.9+, no tests/lint). It really calls Telegram and rewrites `data/*.json`; don't run it casually.
- Quick logic check without Telegram: `BOT_TOKEN=x python3 -c "import bot"` and call `bot.due_reminders(...)` / `bot.due_digests(...)` with a fake `now` (used this way to verify changes).
- Always `git pull --rebase` before editing: the bot commits `data/` back to `main` (`update state [skip ci]`).
- The token is only in the GitHub secret `BOT_TOKEN`; never write it to files or chat.

## Architecture
Single script `bot.py`, one run = one pass: (1) poll `getUpdates` and handle `/start`, `/stop`, `/list` (also drops a group if the bot is kicked), (2) send due daily digests and reminders, (3) save state.
- `data/config.json` – `timezone` (currently `Asia/Ho_Chi_Minh`, one zone for all groups; all `time` values are in it) and `digest_time` (11:00).
- `data/groups.json` – connected chats `{chat_id: {title}}`; edited by `/start`/`/stop` or by hand. A group must be here to get anything. Current groups: `-5531325762` ("Test"), `-1004317316680` (second group), plus a private chat `1175620964`.
- `data/schedule.json` – list of entries: `group` (chat id string), `days` (mon..sun) or one-off `date` (YYYY-MM-DD), `time` HH:MM, `title`, `remind` (minutes before start, e.g. `[60, 30]`), optional `link`/`note`. An entry with `text` sends exactly that message at `time` (use `"remind":[0]`); it is excluded from the digest and `/list`. The "Test" group still has temporary test lessons (`Тест 19:30`…`22:00`) meant to be deleted.
- Daily digest: at `digest_time` each group gets a list of the day's lessons with date and start time (skipped if none).
- `data/state.json` – getUpdates `offset` and `sent` dedupe keys (pruned after 2 days). The workflow commits `data/` after each run, so this is the only persistence.
- Reminder text shows the real minutes left; if a later reminder of the same lesson is already due, the earlier one is skipped. A reminder is never sent after the lesson started (except `text` entries).
- A reminder fires only within `GRACE_MIN` (15 min) after its target time; the `sent` keys prevent repeats.

## Triggers (important)
`.github/workflows/remind.yml` runs on: `schedule` (`*/5`, but GitHub's own cron has proven unreliable in this repo — it did not fire on its own), `push` to `data/schedule.json`, and `workflow_dispatch`. The reliable trigger is an external job on cron-job.org (every 5 min, POST to the GitHub `.../actions/workflows/remind.yml/dispatches` API with `{"ref":"main"}` and a fine-grained token stored only in cron-job.org). If reminders stop, check that job and the Actions tab first. Raising the interval beyond 5 min requires raising `GRACE_MIN` (interval + margin).

## Gotchas
- `getUpdates` does not work if a webhook is set on the bot (`deleteWebhook` first).
- When a group is upgraded to a supergroup its chat id changes (`-100…`); update `groups.json` and `schedule.json`.
- Bot replies to commands only when a workflow run happens (up to ~5 min delay).
