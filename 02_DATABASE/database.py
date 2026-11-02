import sqlite3
from datetime import datetime, date, timedelta, timezone
from config import DB_PATH, DAILY_REWARDS

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
        CREATE TABLE IF NOT EXISTS ledger(
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
