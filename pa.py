#!/usr/bin/env python3
"""
Tayyab's Personal Assistant Tracker & Scheduler for Hermes Agent.
- Database: ~/.hermes/memories/pa_tracker.db (persisted via GitHub Actions cache)
- CLI: `pa ...` (used by Hermes via terminal tool)
- Daemon: `pa daemon` (runs alongside hermes gateway in Asia/Karachi UTC+5)
"""
import datetime
import json
import os
import random
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

DB_PATH = os.path.expanduser("~/.hermes/memories/pa_tracker.db")
PKT = datetime.timezone(datetime.timedelta(hours=5))

QUOTES = [
    ("There is no power on earth that can undo Pakistan.", "Quaid-e-Azam Muhammad Ali Jinnah"),
    ("Work, work and only work for satisfaction and achievement.", "Quaid-e-Azam Muhammad Ali Jinnah"),
    ("Failure is a word unknown to me.", "Quaid-e-Azam Muhammad Ali Jinnah"),
    ("Life is like riding a bicycle. To keep your balance, you must keep moving.", "Albert Einstein"),
    ("Try not to become a man of success, but rather try to become a man of value.", "Albert Einstein"),
    ("It is not that I am so smart, it is just that I stay with problems longer.", "Albert Einstein"),
    ("When something is important enough, you do it even if the odds are not in your favour.", "Elon Musk"),
    ("Persistence is very important. You should not give up unless you are forced to give up.", "Elon Musk"),
    ("Your work is going to fill a large part of your life, and the only way to be truly satisfied is to do what you believe is great work.", "Steve Jobs"),
    ("Stay hungry. Stay foolish.", "Steve Jobs"),
    ("No religion is higher than humanity.", "Abdul Sattar Edhi"),
    ("One child, one teacher, one book, one pen can change the world.", "Malala Yousafzai"),
    ("I have not failed. I have just found ten thousand ways that will not work.", "Thomas Edison"),
    ("The best way to predict the future is to invent it.", "Alan Kay"),
    ("Sitaron se aage jahan aur bhi hain, abhi ishq ke imtihan aur bhi hain.", "Allama Muhammad Iqbal"),
    ("Khudi ko kar buland itna ke har taqdeer se pehle, Khuda bande se khud pooche bata teri raza kya hai.", "Allama Muhammad Iqbal"),
    ("Yaqeen muhkam, amal paiham, mohabbat fatah-e-aalam — jihad-e-zindagani mein hain ye mardon ki shamsheerein.", "Allama Muhammad Iqbal"),
    ("Your most unhappy customers are your greatest source of learning.", "Bill Gates"),
    ("We are stubborn on vision. We are flexible on details.", "Jeff Bezos"),
    ("The most successful people I know believe in themselves almost to the point of delusion.", "Sam Altman"),
    ("If you are not embarrassed by the first version of your product, you have launched too late.", "Reid Hoffman"),
]

ROMAN_URDU_SYSTEM = (
    "Roman Urdu mein jawab do — Urdu, Latin haroof mein, jaise Pakistan mein log WhatsApp pe likhte hain. "
    "Tayyab ko 'tum' kaho, 'aap' nahi (woh 21 saal ka hai). Seedhi aur sachi baat, chaploosi nahi, koi emoji nahi. "
    "Ek chhota jumla (20 lafz se kam)."
)


def now_pkt() -> datetime.datetime:
    return datetime.datetime.now(PKT)


def today_pkt(offset_days: int = 0) -> str:
    return (now_pkt() + datetime.timedelta(days=offset_days)).strftime("%Y-%m-%d")


def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            due_date TEXT NOT NULL,
            rollover_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL,
            category TEXT NOT NULL DEFAULT 'other',
            description TEXT,
            spent_on TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            data TEXT NOT NULL,
            happened_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS learnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_resurfaced TEXT,
            resurface_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS daily_logs (
            log_date TEXT PRIMARY KEY,
            tasks_planned INTEGER NOT NULL,
            tasks_completed INTEGER NOT NULL,
            completion_rate INTEGER NOT NULL,
            closing_line TEXT
        );
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            trigger_at TEXT NOT NULL,
            sent INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS job_runs (
            job TEXT PRIMARY KEY,
            last_run_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    defaults = {
        "morning_time": "10:00",
        "night_time": "03:00",
        "checkin_times": json.dumps(["13:00", "16:00", "19:00", "22:00", "01:00"]),
        "weekly_dow": "6",  # Python weekday(): Monday=0 ... Sunday=6
        "weekly_time": "21:00",
        "resurface_time": "18:00",
        "namaz_reminders": "true",
        "namaz_minutes_before": "15",
        "daily_tasks": json.dumps(["Gym", "Namaz (paanchon waqt)"]),
    }
    for k, v in defaults.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    return conn


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


def send_whatsapp(text: str) -> bool:
    phone_id = os.environ.get("WHATSAPP_CLOUD_PHONE_NUMBER_ID", "")
    token = os.environ.get("WHATSAPP_CLOUD_ACCESS_TOKEN", "")
    recipient = os.environ.get("WHATSAPP_CLOUD_ALLOWED_USERS", "").split(",")[0].strip()
    if not (phone_id and token and recipient):
        print("Missing WhatsApp env vars", file=sys.stderr)
        return False
    url = f"https://graph.facebook.com/v23.0/{phone_id}/messages"
    payload = json.dumps({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        print(f"WhatsApp send error: {e}", file=sys.stderr)
        return False


def groq_line(prompt: str, max_tokens: int = 120, system: str = ROMAN_URDU_SYSTEM) -> str:
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        return "Seedha kaam pe dhyan do."
    model = os.environ.get("PA_GROQ_MODEL", "qwen/qwen3.8-27b")
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "hermes-pa/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            text = data["choices"][0]["message"]["content"].strip()
            if "</think>" in text:
                text = text.split("</think>")[-1].strip()
            return text.strip('"\'')
    except Exception as e:
        print(f"Groq error: {e}", file=sys.stderr)
        return "Apne pending tasks pe nazar rakho."


def fetch_karachi_namaz() -> list[tuple[str, str]]:
    url = "https://api.aladhan.com/v1/timings?latitude=24.9056&longitude=67.1861&method=1"
    req = urllib.request.Request(url, headers={"User-Agent": "hermes-pa/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    timings = data["data"]["timings"]
    prayers = []
    for name in ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]:
        raw = timings.get(name, "").split(" ")[0].strip()
        if len(raw) == 5 and ":" in raw:
            prayers.append((name, raw))
    return prayers


def schedule_today_namaz(conn: sqlite3.Connection) -> str:
    if get_setting(conn, "namaz_reminders", "true") != "true":
        return "Namaz reminders off hain."
    mins_before = int(get_setting(conn, "namaz_minutes_before", "15"))
    try:
        prayers = fetch_karachi_namaz()
    except Exception as e:
        return f"Namaz timings fetch nahi ho sakin: {e}"

    today = today_pkt(0)
    now_ts = now_pkt()
    added = []
    for name, hhmm in prayers:
        h, m = map(int, hhmm.split(":"))
        prayer_dt = datetime.datetime(
            now_ts.year, now_ts.month, now_ts.day, h, m, tzinfo=PKT
        )
        remind_dt = prayer_dt - datetime.timedelta(minutes=mins_before)
        if remind_dt <= now_ts:
            continue
        label = f"{name} ki namaz — {hhmm}"
        exists = conn.execute(
            "SELECT 1 FROM reminders WHERE text = ? AND substr(trigger_at, 1, 10) = ?",
            (label, today),
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO reminders (text, trigger_at, sent) VALUES (?, ?, 0)",
                (label, remind_dt.isoformat()),
            )
            added.append(f"{name} ({hhmm})")
    conn.commit()
    return f"Scheduled {len(added)} namaz reminders: {', '.join(added)}" if added else "Aaj ke baaqi namaz reminders pehle se lage hue hain."


def ensure_daily_tasks(conn: sqlite3.Connection) -> list[str]:
    today = today_pkt(0)
    wanted = json.loads(get_setting(conn, "daily_tasks", '["Gym","Namaz (paanchon waqt)"]'))
    existing = {
        r["title"].lower()
        for r in conn.execute("SELECT title FROM tasks WHERE due_date = ? AND status != 'cancelled'", (today,)).fetchall()
    }
    added = []
    for title in wanted:
        if title.lower() not in existing:
            conn.execute(
                "INSERT INTO tasks (title, status, due_date, rollover_count, created_at) VALUES (?, 'pending', ?, 0, ?)",
                (title, today, now_pkt().isoformat()),
            )
            added.append(title)
    conn.commit()
    return added


def recent_rate(conn: sqlite3.Connection) -> int | None:
    rows = conn.execute("SELECT completion_rate FROM daily_logs ORDER BY log_date DESC LIMIT 7").fetchall()
    if not rows:
        return None
    return round(sum(r["completion_rate"] for r in rows) / len(rows))


def run_morning(conn: sqlite3.Connection) -> str:
    quote_text, quote_who = random.choice(QUOTES)
    pending = conn.execute("SELECT title, rollover_count FROM tasks WHERE status = 'pending' ORDER BY rollover_count DESC").fetchall()
    rolled = [r for r in pending if r["rollover_count"] > 0]
    rate = recent_rate(conn)

    prompt = (
        f"Write one short opening line for Tayyab's morning. "
        + (f"Last 7 days completion rate: {rate}%. " if rate is not None else "")
        + (f"He has been avoiding: {', '.join(r['title'] for r in rolled)}. Nudge him honestly. " if rolled else "Clean slate today. ")
        + "Do not congratulate him for work not done."
    )
    line = groq_line(prompt)
    msg1 = f'Subah bakhair!\n\n"{quote_text}"\n— {quote_who}\n\n{line}'
    send_whatsapp(msg1)

    added = ensure_daily_tasks(conn)
    schedule_today_namaz(conn)

    parts = []
    if added:
        parts.append(f"Aaj ke pakke tasks laga diye: {', '.join(added)}.")
    if rolled:
        rolled_lines = "\n".join(f"• {r['title']} ({r['rollover_count']}x)" for r in rolled)
        parts.append(f"Ab tak taale hue:\n{rolled_lines}")
    parts.append("Aaj aur kya karna hai? Bata do, main yaad dilata rahunga.")
    send_whatsapp("\n\n".join(parts))
    return "morning sent"


def run_checkin(conn: sqlite3.Connection) -> str:
    pending = conn.execute(
        "SELECT id, title, rollover_count FROM tasks WHERE status = 'pending' ORDER BY rollover_count DESC, id ASC"
    ).fetchall()
    if not pending:
        return "skipped: no pending tasks"
    worst = pending[0]
    prompt = (
        f"Write one short nudge asking if Tayyab made progress. {len(pending)} task(s) open. "
        + (f'Worst offender: "{worst["title"]}" ({worst["rollover_count"]}x rolled over). Mention it directly. ' if worst["rollover_count"] > 0 else "")
        + "No fake praise."
    )
    line = groq_line(prompt)
    items = "\n".join(
        f"• {r['title']}" + (f" ({r['rollover_count']}x)" if r["rollover_count"] > 0 else "")
        for r in pending[:6]
    )
    send_whatsapp(f"{line}\n\n{items}\n\nBatao inmein se kuch ho gaya?")
    return f"checkin sent ({len(pending)} pending)"


def run_night(conn: sqlite3.Connection) -> str:
    now_ts = now_pkt()
    day_closed = today_pkt(-1) if now_ts.hour < 6 else today_pkt(0)
    next_day = today_pkt(0) if now_ts.hour < 6 else today_pkt(1)

    rows = conn.execute(
        "SELECT id, title, status, rollover_count FROM tasks WHERE due_date = ? AND status != 'cancelled'",
        (day_closed,),
    ).fetchall()
    planned = len(rows)
    completed = sum(1 for r in rows if r["status"] == "done")
    unfinished = [r for r in rows if r["status"] == "pending"]
    rate = 0 if planned == 0 else round((completed / planned) * 100)

    for r in unfinished:
        conn.execute(
            "UPDATE tasks SET due_date = ?, rollover_count = ? WHERE id = ?",
            (next_day, r["rollover_count"] + 1, r["id"]),
        )

    line = groq_line(
        f"Tayyab completed {completed} of {planned} tasks today ({rate}%). "
        f"{len(unfinished)} rolled over to tomorrow. "
        + (f"Still open: {', '.join(r['title'] for r in unfinished)}. " if unfinished else "")
        + "Write one honest closing line for the day."
    )
    conn.execute(
        "INSERT OR REPLACE INTO daily_logs (log_date, tasks_planned, tasks_completed, completion_rate, closing_line) VALUES (?, ?, ?, ?, ?)",
        (day_closed, planned, completed, rate, line),
    )
    conn.commit()

    if planned == 0:
        body = f"Aaj koi task log nahi hua. {line}"
    else:
        body = f"Aaj: {planned} mein se {completed} ho gaye ({rate}%)."
        if unfinished:
            body += "\n\nKal pe chale gaye:\n" + "\n".join(f"• {r['title']}" for r in unfinished)
        body += f"\n\n{line}"
    send_whatsapp(body)
    return f"night summary sent ({completed}/{planned})"


def run_resurface(conn: sqlite3.Connection) -> str:
    intervals = [3, 7, 14, 30]
    rows = conn.execute("SELECT id, content, created_at, last_resurfaced, resurface_count FROM learnings WHERE resurface_count < 4").fetchall()
    now_ts = now_pkt()
    for r in rows:
        cnt = r["resurface_count"]
        ref_str = r["last_resurfaced"] or r["created_at"]
        ref_dt = datetime.datetime.fromisoformat(ref_str)
        if (now_ts - ref_dt).total_seconds() >= intervals[cnt] * 86400:
            send_whatsapp(f"Ye yaad hai?\n\n{r['content']}")
            conn.execute(
                "UPDATE learnings SET last_resurfaced = ?, resurface_count = ? WHERE id = ?",
                (now_ts.isoformat(), cnt + 1, r["id"]),
            )
            conn.commit()
            return f"resurfaced learning #{r['id']}"
    return "no learning due"


def run_weekly(conn: sqlite3.Connection) -> str:
    week_ago = today_pkt(-7)
    done_rows = conn.execute("SELECT title FROM tasks WHERE status = 'done' AND substr(completed_at, 1, 10) >= ?", (week_ago,)).fetchall()
    open_rows = conn.execute("SELECT title, rollover_count FROM tasks WHERE status = 'pending' ORDER BY rollover_count DESC").fetchall()
    logs = conn.execute("SELECT completion_rate, tasks_completed FROM daily_logs WHERE log_date >= ? ORDER BY log_date", (week_ago,)).fetchall()

    if not done_rows and not open_rows and not logs:
        send_whatsapp("Weekly review: is hafte koi task log nahi hua. Jab data hoga tabhi review ka faida hai.")
        return "weekly: no data"

    rates = [r["completion_rate"] for r in logs]
    avg_rate = round(sum(rates) / len(rates)) if rates else 0
    chronic = [f'"{r["title"]}" ({r["rollover_count"]}x)' for r in open_rows if r["rollover_count"] >= 3]

    facts = (
        f"Completed this week ({len(done_rows)}): {', '.join(r['title'] for r in done_rows) or 'none'}\n"
        f"Average daily rate: {avg_rate}% across {len(logs)} logged days\n"
        f"Chronically avoided: {', '.join(chronic) or 'none'}\n"
        f"Still open: {', '.join(r['title'] for r in open_rows) or 'none'}"
    )
    sys_prompt = (
        "Write a weekly review in Roman Urdu for Tayyab (21, call him 'tum'). "
        "Flowing prose, max 3 short paragraphs (~140 words). Manager tone, not a cheerleader. "
        "Use ONLY the exact numbers given. Name chronic rolled-over tasks directly with counts. "
        "End with one specific change for next week. No emojis."
    )
    review = groq_line(facts, max_tokens=450, system=sys_prompt)
    heading = f"Hafte ka review — {now_pkt().strftime('%d %b %Y')}\n\n"
    send_whatsapp(heading + review)
    return "weekly review sent"


def claim_job(conn: sqlite3.Connection, job: str, min_gap_hours: float) -> bool:
    row = conn.execute("SELECT last_run_at FROM job_runs WHERE job = ?", (job,)).fetchone()
    now_ts = now_pkt()
    if row:
        last_dt = datetime.datetime.fromisoformat(row["last_run_at"])
        if (now_ts - last_dt).total_seconds() < min_gap_hours * 3600:
            return False
    conn.execute("INSERT OR REPLACE INTO job_runs (job, last_run_at) VALUES (?, ?)", (job, now_ts.isoformat()))
    conn.commit()
    return True


def is_due(now_minutes: int, hhmm: str, window: int = 12) -> bool:
    try:
        h, m = map(int, hhmm.strip().split(":")[:2])
        sched = h * 60 + m
        diff = (now_minutes - sched + 1440) % 1440
        return diff < window
    except Exception:
        return False


def fire_due_reminders(conn: sqlite3.Connection) -> None:
    now_ts = now_pkt()
    upper = (now_ts + datetime.timedelta(minutes=1)).isoformat()
    lower = (now_ts - datetime.timedelta(minutes=45)).isoformat()
    rows = conn.execute(
        "SELECT id, text, trigger_at FROM reminders WHERE sent = 0 AND trigger_at <= ? AND trigger_at >= ?",
        (upper, lower),
    ).fetchall()
    for r in rows:
        conn.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (r["id"],))
        conn.commit()
        mins_before = get_setting(conn, "namaz_minutes_before", "15")
        if "ki namaz" in r["text"]:
            send_whatsapp(f"Namaz Reminder: {r['text']} ({mins_before} min baqi hain).")
        else:
            send_whatsapp(f"Reminder: {r['text']}")


def run_daemon() -> None:
    print("Starting pa-scheduler daemon (Asia/Karachi UTC+5)...", flush=True)
    conn = get_db()
    schedule_today_namaz(conn)
    last_namaz_date = today_pkt(0)

    while True:
        try:
            t = now_pkt()
            today_str = t.strftime("%Y-%m-%d")
            if today_str != last_namaz_date:
                schedule_today_namaz(conn)
                last_namaz_date = today_str

            fire_due_reminders(conn)

            now_mins = t.hour * 60 + t.minute

            morning_t = get_setting(conn, "morning_time", "10:00")
            if is_due(now_mins, morning_t) and claim_job(conn, "morning", 12):
                print(run_morning(conn), flush=True)

            night_t = get_setting(conn, "night_time", "03:00")
            if is_due(now_mins, night_t) and claim_job(conn, "night", 12):
                print(run_night(conn), flush=True)

            resurface_t = get_setting(conn, "resurface_time", "18:00")
            if is_due(now_mins, resurface_t) and claim_job(conn, "resurface", 12):
                print(run_resurface(conn), flush=True)

            checkins = json.loads(get_setting(conn, "checkin_times", '["13:00","16:00","19:00","22:00","01:00"]'))
            for ct in checkins:
                if is_due(now_mins, ct) and claim_job(conn, f"checkin-{ct}", 12):
                    print(run_checkin(conn), flush=True)

            weekly_dow = int(get_setting(conn, "weekly_dow", "6"))
            weekly_t = get_setting(conn, "weekly_time", "21:00")
            if t.weekday() == weekly_dow and is_due(now_mins, weekly_t) and claim_job(conn, "weekly", 24 * 6):
                print(run_weekly(conn), flush=True)

        except Exception as e:
            print(f"Daemon tick error: {e}", file=sys.stderr, flush=True)
        time.sleep(45)


def main() -> None:
    conn = get_db()
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(
            "Usage:\n"
            "  pa task list\n"
            "  pa task add <title>\n"
            "  pa task done <id_or_title>\n"
            "  pa task delete <id_or_title|all>\n"
            "  pa expense add <amount_pkr> <category> [description]\n"
            "  pa expense summary\n"
            "  pa record add <kind> <value_or_json>\n"
            "  pa record list <kind>\n"
            "  pa record kinds\n"
            "  pa learning add <text>\n"
            "  pa learning list\n"
            "  pa reminder add <HH:MM or YYYY-MM-DD HH:MM> <text>\n"
            "  pa reminder list\n"
            "  pa namaz\n"
            "  pa progress\n"
            "  pa settings [set <key> <value>]"
        )
        return

    cmd = args[0]
    sub = args[1] if len(args) > 1 else ""

    if cmd == "daemon":
        run_daemon()
        return

    if cmd == "task":
        if sub == "list":
            rows = conn.execute("SELECT id, title, due_date, rollover_count FROM tasks WHERE status = 'pending' ORDER BY rollover_count DESC, id ASC").fetchall()
            if not rows:
                print("Koi pending task nahi.")
            else:
                print(f"{len(rows)} pending task(s):")
                for r in rows:
                    roll = f" ({r['rollover_count']} dafa tala)" if r["rollover_count"] > 0 else ""
                    print(f"• id={r['id']} | {r['title']}{roll}")
        elif sub == "add":
            title = " ".join(args[2:]).strip()
            if not title:
                print("Error: title required")
                sys.exit(1)
            conn.execute(
                "INSERT INTO tasks (title, status, due_date, rollover_count, created_at) VALUES (?, 'pending', ?, 0, ?)",
                (title, today_pkt(0), now_pkt().isoformat()),
            )
            conn.commit()
            print(f'Task save ho gaya: "{title}" (due {today_pkt(0)}).')
        elif sub == "done":
            target = " ".join(args[2:]).strip()
            row = conn.execute(
                "SELECT id, title FROM tasks WHERE status = 'pending' AND (CAST(id AS TEXT) = ? OR lower(title) LIKE ?)",
                (target, f"%{target.lower()}%"),
            ).fetchone()
            if not row:
                print(f'"{target}" se koi pending task nahi mila.')
                sys.exit(1)
            conn.execute("UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ?", (now_pkt().isoformat(), row["id"]))
            conn.commit()
            rem = conn.execute("SELECT COUNT(*) AS c FROM tasks WHERE status = 'pending'").fetchone()["c"]
            print(f'"{row["title"]}" done mark ho gaya. {rem} pending baqi.')
        elif sub in ("delete", "cancel"):
            target = " ".join(args[2:]).strip()
            if target.lower() == "all":
                c = conn.execute("DELETE FROM tasks WHERE status = 'pending'").rowcount
                conn.commit()
                print(f"Sare {c} pending tasks delete kar diye.")
            else:
                row = conn.execute(
                    "SELECT id, title FROM tasks WHERE status = 'pending' AND (CAST(id AS TEXT) = ? OR lower(title) LIKE ?)",
                    (target, f"%{target.lower()}%"),
                ).fetchone()
                if not row:
                    print(f'"{target}" se koi pending task nahi mila.')
                    sys.exit(1)
                conn.execute("DELETE FROM tasks WHERE id = ?", (row["id"],))
                conn.commit()
                print(f'Task delete kar diya: "{row["title"]}".')
        return

    if cmd == "expense":
        if sub == "add":
            amt = float(args[2])
            cat = args[3].lower() if len(args) > 3 else "other"
            desc = " ".join(args[4:]).strip() if len(args) > 4 else ""
            conn.execute(
                "INSERT INTO expenses (amount, category, description, spent_on, created_at) VALUES (?, ?, ?, ?, ?)",
                (amt, cat, desc, today_pkt(0), now_pkt().isoformat()),
            )
            conn.commit()
            print(f"Likh liya: Rs {amt:,.0f} — {cat}" + (f" ({desc})" if desc else ""))
        elif sub == "summary":
            month_prefix = today_pkt(0)[:8] + "01"
            rows = conn.execute(
                "SELECT category, SUM(amount) AS total FROM expenses WHERE spent_on >= ? GROUP BY category ORDER BY total DESC",
                (month_prefix,),
            ).fetchall()
            if not rows:
                print("Is mahine koi kharcha log nahi hua.")
            else:
                grand = sum(r["total"] for r in rows)
                print(f"Is mahine ka kul kharcha: Rs {grand:,.0f}")
                for r in rows:
                    print(f"• {r['category']}: Rs {r['total']:,.0f}")
        return

    if cmd == "record":
        if sub == "add":
            kind = args[2].lower().strip()
            val = " ".join(args[3:]).strip()
            conn.execute(
                "INSERT INTO records (kind, data, happened_at) VALUES (?, ?, ?)",
                (kind, val, now_pkt().isoformat()),
            )
            conn.commit()
            print(f'"{kind}" mein record save ho gaya: {val}')
        elif sub == "list":
            kind = args[2].lower().strip()
            rows = conn.execute("SELECT data, happened_at FROM records WHERE kind = ? ORDER BY id DESC LIMIT 20", (kind,)).fetchall()
            if not rows:
                print(f'"{kind}" ki koi entry nahi mili.')
            else:
                for r in rows:
                    print(f"• {r['happened_at'][:16].replace('T', ' ')} — {r['data']}")
        elif sub == "kinds":
            rows = conn.execute("SELECT kind, COUNT(*) AS c, MAX(happened_at) AS latest FROM records GROUP BY kind ORDER BY c DESC").fetchall()
            if not rows:
                print("Abhi koi custom record nahi hai.")
            else:
                for r in rows:
                    print(f"• {r['kind']} — {r['c']} entries (last: {r['latest'][:16].replace('T', ' ')})")
        return

    if cmd == "learning":
        if sub == "add":
            text = " ".join(args[2:]).strip()
            conn.execute(
                "INSERT INTO learnings (content, created_at, resurface_count) VALUES (?, ?, 0)",
                (text, now_pkt().isoformat()),
            )
            conn.commit()
            print(f"Learning save ho gayi (3, 7, 14, 30 din baad yaad dilayi jayegi): {text}")
        elif sub == "list":
            rows = conn.execute("SELECT id, content, resurface_count FROM learnings ORDER BY id DESC LIMIT 20").fetchall()
            if not rows:
                print("Koi learning save nahi hai.")
            else:
                for r in rows:
                    print(f"• #{r['id']} ({r['resurface_count']}/4x): {r['content']}")
        return

    if cmd == "reminder":
        if sub == "add":
            when_str = args[2]
            text = " ".join(args[3:]).strip()
            t = now_pkt()
            if len(when_str) <= 5 and ":" in when_str:
                h, m = map(int, when_str.split(":"))
                dt = datetime.datetime(t.year, t.month, t.day, h, m, tzinfo=PKT)
                if dt <= t:
                    dt += datetime.timedelta(days=1)
            else:
                dt = datetime.datetime.fromisoformat(when_str).replace(tzinfo=PKT)
            conn.execute("INSERT INTO reminders (text, trigger_at, sent) VALUES (?, ?, 0)", (text, dt.isoformat()))
            conn.commit()
            print(f'Reminder set: "{text}" at {dt.strftime("%Y-%m-%d %H:%M")} PKT.')
        elif sub == "list":
            rows = conn.execute("SELECT id, text, trigger_at FROM reminders WHERE sent = 0 ORDER BY trigger_at").fetchall()
            if not rows:
                print("Koi pending reminder nahi.")
            else:
                for r in rows:
                    print(f"• id={r['id']} | {r['trigger_at'][:16].replace('T', ' ')} — {r['text']}")
        return

    if cmd == "namaz":
        prayers = fetch_karachi_namaz()
        sched_msg = schedule_today_namaz(conn)
        print("Aaj Karachi ki namaz timings (University of Islamic Sciences):")
        for name, hhmm in prayers:
            print(f"• {name}: {hhmm}")
        print(f"\n({sched_msg})")
        return

    if cmd == "progress":
        pending = conn.execute("SELECT title, rollover_count FROM tasks WHERE status = 'pending' ORDER BY rollover_count DESC").fetchall()
        done_today = conn.execute("SELECT COUNT(*) AS c FROM tasks WHERE status = 'done' AND due_date = ?", (today_pkt(0),)).fetchone()["c"]
        rate = recent_rate(conn)
        print(f"Aaj complete hue: {done_today} | Abhi pending: {len(pending)} | 7-day avg rate: {rate if rate is not None else 'N/A'}%")
        for r in pending:
            print(f"• {r['title']} (rolled over {r['rollover_count']}x)")
        return

    if cmd == "settings":
        if sub == "set" and len(args) >= 4:
            k, v = args[2], " ".join(args[3:])
            set_setting(conn, k, v)
            print(f"Setting updated: {k} = {v}")
        else:
            rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
            for r in rows:
                print(f"{r['key']}: {r['value']}")
        return


if __name__ == "__main__":
    main()