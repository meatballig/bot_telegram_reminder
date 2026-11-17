#!/usr/bin/env python3
"""Telegram-напоминалка о занятиях. Запускается из GitHub Actions каждые ~5 минут.

1. Читает новые сообщения (getUpdates): /start, /stop, /list -> data/groups.json
2. Отправляет напоминания о занятиях из data/schedule.json
Состояние (offset, что уже отправлено) хранится в data/state.json.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

DATA = Path(__file__).parent / "data"
TOKEN = os.environ.get("BOT_TOKEN", "")
GRACE_MIN = 15  # на сколько минут можно опоздать с напоминанием (cron в Actions бывает с задержкой)
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAYS_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def load(name, default):
    p = DATA / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save(name, obj):
    (DATA / name).write_text(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def api(method, **params):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["result"]
    except Exception as e:  # не роняем весь запуск из-за одной группы
        print(f"API {method} failed: {e}", file=sys.stderr)
        return None


def send(chat_id, text):
    return api("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
               disable_web_page_preview=True)


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def lesson_days(lesson):
    return "".join([]) or ", ".join(
        DAYS_RU[DAYS.index(d)] for d in lesson.get("days", [])
    ) or lesson.get("date", "?")


def handle_updates(groups, state, schedule):
    updates = api("getUpdates", offset=state["offset"], timeout=0,
                  allowed_updates=["message", "my_chat_member"]) or []
    for u in updates:
        state["offset"] = u["update_id"] + 1

        m = u.get("my_chat_member")
        if m and m["new_chat_member"]["status"] in ("left", "kicked"):
            if groups.pop(str(m["chat"]["id"]), None):
                print(f"removed (kicked): {m['chat']['id']}")
            continue

        msg = u.get("message")
        if not msg or not msg.get("text", "").startswith("/"):
            continue
        cmd = msg["text"].split()[0].split("@")[0].lower()
        chat = msg["chat"]
        cid = str(chat["id"])
        title = chat.get("title") or chat.get("first_name") or cid

        if cmd == "/start":
            groups[cid] = {"title": title}
            send(cid, "✅ Группа подключена. Буду напоминать о занятиях.\n"
                      f"ID чата: <code>{cid}</code>\n/list — расписание, /stop — отключить.")
        elif cmd == "/stop":
            groups.pop(cid, None)
            send(cid, "🛑 Группа отключена. /start — подключить снова.")
        elif cmd == "/list":
            mine = [l for l in schedule if str(l["group"]) == cid and "text" not in l]
            if not mine:
                send(cid, "Для этого чата занятий пока нет.")
            else:
                lines = [f"• {lesson_days(l)} {l['time']} — {esc(l['title'])}" for l in mine]
                send(cid, "<b>Расписание:</b>\n" + "\n".join(lines))


def lesson_on(l, d):
    """Проходит ли занятие в день d."""
    if "date" in l:
        return l["date"] == d.isoformat()
    return DAYS[d.weekday()] in l.get("days", [])


def due_digests(schedule, groups, config, tz, now):
    """Ежедневная сводка: все занятия дня с датой и временем начала."""
    h, mi = map(int, config.get("digest_time", "11:00").split(":"))
    t = datetime.combine(now.date(), dtime(h, mi), tzinfo=tz)
    if not (t <= now < t + timedelta(minutes=GRACE_MIN)):
        return
    d = now.date()
    for cid in groups:
        todays = sorted((l for l in schedule
                         if str(l["group"]) == cid and lesson_on(l, d)
                         and "text" not in l),
                        key=lambda l: l["time"])
        if not todays:
            continue
        lines = [f"• {d.strftime('%d.%m.%Y')} {l['time']} — {esc(l['title'])}"
                 for l in todays]
        text = f"📅 <b>Занятия на сегодня ({DAYS_RU[d.weekday()]}):</b>\n" + "\n".join(lines)
        yield f"digest|{cid}|{d.isoformat()}", t, cid, text


def due_reminders(schedule, groups, tz, now):
    """Выдаёт (ключ, chat_id, текст) для напоминаний, чьё время наступило."""
    for l in schedule:
        cid = str(l["group"])
        if cid not in groups:
            continue
        h, mi = map(int, l["time"].split(":"))
        for d in (now.date(), now.date() + timedelta(days=1)):
            if not lesson_on(l, d):
                continue
            start = datetime.combine(d, dtime(h, mi), tzinfo=tz)
            befores = l.get("remind", [60])
            for before in befores:
                t = start - timedelta(minutes=before)
                if t <= now < t + timedelta(minutes=GRACE_MIN) and (now < start or "text" in l):
                    # если уже наступило более позднее напоминание, это устарело
                    if any(b2 < before and start - timedelta(minutes=b2) <= now
                           for b2 in befores):
                        continue
                    key = f"{cid}|{start.isoformat()}|{l['title']}|{before}"
                    left = max(0, -(-int((start - now).total_seconds()) // 60))  # минут до начала, вверх
                    when = "сейчас" if left == 0 else (
                        f"через {left} мин" if left < 60 else
                        f"через {left // 60} ч" + (f" {left % 60} мин" if left % 60 else ""))
                    text = f"⏰ <b>{esc(l['title'])}</b> — {when} (в {l['time']})"
                    if "text" in l:  # произвольное сообщение в заданное время
                        text = esc(l["text"])
                    elif l.get("note"):
                        text += f"\n{esc(l['note'])}"
                    if l.get("link"):
                        text += f"\n{esc(l['link'])}"
                    yield key, start, cid, text


def main():
    if not TOKEN:
        sys.exit("BOT_TOKEN не задан")
    config = load("config.json", {"timezone": "Asia/Almaty"})
    tz = ZoneInfo(config["timezone"])
    now = datetime.now(tz)
    groups = load("groups.json", {})
    schedule = load("schedule.json", [])
    state = load("state.json", {"offset": 0, "sent": {}})

    handle_updates(groups, state, schedule)

    due = list(due_digests(schedule, groups, config, tz, now))
    due += list(due_reminders(schedule, groups, tz, now))
    for key, start, cid, text in due:
        if key in state["sent"]:
            continue
        if send(cid, text):
            state["sent"][key] = start.isoformat()
            print(f"sent: {key}")

    cutoff = now - timedelta(days=2)
    state["sent"] = {k: v for k, v in state["sent"].items()
                     if datetime.fromisoformat(v) > cutoff}

    save("groups.json", groups)
    save("state.json", state)


if __name__ == "__main__":
    main()
