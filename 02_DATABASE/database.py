import sqlite3
from datetime import datetime, date, timedelta, timezone
from config import DB_PATH, DAILY_REWARDS, MINING_INTERVAL_HOURS, MINING_REWARDS

def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users(
          user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '', first_name TEXT DEFAULT '',
          balance INTEGER NOT NULL DEFAULT 0, level INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL, last_daily TEXT, streak INTEGER NOT NULL DEFAULT 0,
          referrer_id INTEGER, frozen INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS referral_rewards(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          referrer_id INTEGER NOT NULL,
          reward_type TEXT NOT NULL,
          amount INTEGER NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(user_id, reward_type)
        );
        CREATE TABLE IF NOT EXISTS monetag_events(\n          ymid TEXT PRIMARY KEY, user_id INTEGER NOT NULL, zone_id INTEGER NOT NULL,\n          sub_zone_id INTEGER, estimated_price REAL NOT NULL DEFAULT 0,\n          created_at TEXT NOT NULL\n        );\n        CREATE TABLE IF NOT EXISTS ledger(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          event TEXT NOT NULL, amount INTEGER NOT NULL, note TEXT,
          created_at TEXT NOT NULL
        );
        ''')
        columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        if "last_mining" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN last_mining TEXT")


def ensure_user(uid, username='', first_name='', referrer=None):
    with connect() as db:
        found = db.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone()
        if found:
            return False
        if referrer == uid:
            referrer = None
        db.execute(
            "INSERT INTO users(user_id,username,first_name,created_at,referrer_id) VALUES(?,?,?,?,?)",
            (uid, username, first_name, datetime.now(timezone.utc).isoformat(), referrer)
        )
        return True

def get_user(uid):
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        if row:
            return dict(row)
    ensure_user(uid)
    with connect() as db:
        return dict(db.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone())

def claim_daily(uid):
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        if not row:
            return False, 0, 0
        if row["frozen"]:
            return False, 0, row["streak"]
        if row["last_daily"] == today:
            return False, 0, row["streak"]
        streak = row["streak"] + 1 if row["last_daily"] == yesterday else 1
        if streak > 7:
            streak = 1
        amount = DAILY_REWARDS[streak - 1]
        now = datetime.now(timezone.utc).isoformat()
        db.execute("UPDATE users SET balance=balance+?,last_daily=?,streak=? WHERE user_id=?",
                   (amount, today, streak, uid))
        db.execute("INSERT INTO ledger(user_id,event,amount,note,created_at) VALUES(?,?,?,?,?)",
                   (uid, "daily_reward", amount, f"day {streak}", now))
        return True, amount, streak

def grant_signup_referral_rewards(uid):
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        user = db.execute(
            "SELECT referrer_id, frozen FROM users WHERE user_id=?", (uid,)
        ).fetchone()
        if not user or not user["referrer_id"] or user["frozen"]:
            return False
        referrer_id = user["referrer_id"]
        referrer = db.execute(
            "SELECT frozen FROM users WHERE user_id=?", (referrer_id,)
        ).fetchone()
        if not referrer or referrer["frozen"]:
            return False

        rewards = [
            (uid, referrer_id, "referred_user", 200),
            (referrer_id, referrer_id, "referrer_signup", 500),
        ]
        for recipient, owner, reward_type, amount in rewards:
            cur = db.execute(
                """INSERT OR IGNORE INTO referral_rewards
                (user_id, referrer_id, reward_type, amount, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (uid, owner, reward_type, amount, now)
            )
            if cur.rowcount:
                db.execute(
                    "UPDATE users SET balance=balance+? WHERE user_id=?",
                    (amount, recipient)
                )
                db.execute(
                    """INSERT INTO ledger(user_id,event,amount,note,created_at)
                    VALUES(?,?,?,?,?)""",
                    (recipient, "referral_reward", amount,
                     f"{reward_type} for user {uid}", now)
                )
        return True


def claim_mining(uid):
    now = datetime.now(timezone.utc)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        if not row:
            return False, "الحساب غير موجود.", 0, 0
        if row["frozen"]:
            return False, "الحساب مجمّد مؤقتاً.", 0, 0
        level = max(1, min(int(row["level"]), len(MINING_REWARDS)))
        last = row["last_mining"]
        if last:
            ads_done = db.execute(
                "SELECT COUNT(*) FROM monetag_events WHERE user_id=? AND created_at>?",
                (uid, last)
            ).fetchone()[0]
        else:
            ads_done = db.execute(
                "SELECT COUNT(*) FROM monetag_events WHERE user_id=?",
                (uid,)
            ).fetchone()[0]
        if ads_done < 15:
            missing = 15 - ads_done
            return False, f"خاصك تكمل {missing} مشاهدة إعلان مؤكدة قبل التعدين.", 0, 0
        if last:
            try:
                elapsed = (now - datetime.fromisoformat(last)).total_seconds()
            except ValueError:
                elapsed = MINING_INTERVAL_HOURS * 3600
            remaining = int(MINING_INTERVAL_HOURS * 3600 - elapsed)
            if remaining > 0:
                minutes = (remaining + 59) // 60
                return False, f"المحاولة القادمة بعد {minutes} دقيقة تقريباً.", 0, remaining
        amount = MINING_REWARDS[level - 1]
        stamp = now.isoformat()
        db.execute("UPDATE users SET balance=balance+?, last_mining=? WHERE user_id=?",
                   (amount, stamp, uid))
        db.execute("INSERT INTO ledger(user_id,event,amount,note,created_at) VALUES(?,?,?,?,?)",
                   (uid, "mining_reward", amount, f"level {level}; internal test reward", stamp))
        return True, "تمت إضافة مكافأة التعدين إلى رصيدك التجريبي.", amount, 0


def record_monetag_event(uid, ymid, zone_id, sub_zone_id, estimated_price):
    """Credit a confirmed Monetag event once; each 15-event cycle pays 5 double and 10 normal rewards."""
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        user = db.execute("SELECT frozen, level FROM users WHERE user_id=?", (uid,)).fetchone()
        if not user or user["frozen"]:
            return False, 0, 0, 0
        cur = db.execute(
            "INSERT OR IGNORE INTO monetag_events(ymid,user_id,zone_id,sub_zone_id,estimated_price,created_at) VALUES(?,?,?,?,?,?)",
            (ymid, uid, zone_id, sub_zone_id, estimated_price, now)
        )
        count = db.execute("SELECT COUNT(*) FROM monetag_events WHERE user_id=?", (uid,)).fetchone()[0]
        if not cur.rowcount:
            return False, count, 0, 0
        level = max(1, min(int(user["level"]), len(MINING_REWARDS)))
        base = int(MINING_REWARDS[level - 1])
        position = ((count - 1) % 15) + 1
        multiplier = 2 if position <= 5 else 1
        amount = base * multiplier
        db.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, uid))
        note = f"Monetag event {count}; cycle position {position}/15; level {level}; x{multiplier}"
        db.execute("INSERT INTO ledger(user_id,event,amount,note,created_at) VALUES(?,?,?,?,?)",
                   (uid, "monetag_reward", amount, note, now))
        return True, count, amount, position
