from datetime import datetime, timezone
from database import connect

def get_upgrade_cost(level):
    if level >= 30:
        return None
    return 150 + 200 * (level - 1)

def upgrade_for_internal_balance(uid):
    with connect() as db:
        user = db.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        if not user:
            return False, "ابدأ باستخدام /start."
        if user["frozen"]:
            return False, "الحساب مجمد مؤقتاً."

        level = user["level"]
        cost = get_upgrade_cost(level)
        if cost is None:
            return False, "وصلت إلى المستوى 30."
        if user["balance"] < cost:
            return False, f"الرصيد غير كافٍ. المطلوب {cost} DRJ."

        burn = int(cost * 0.60)
        treasury = cost - burn
        now = datetime.now(timezone.utc).isoformat()
        new_level = level + 1

        db.execute(
            "UPDATE users SET balance=balance-?, level=? WHERE user_id=?",
            (cost, new_level, uid)
        )
        db.execute(
            "INSERT INTO ledger(user_id,event,amount,note,created_at) VALUES(?,?,?,?,?)",
            (uid, "upgrade_debit", -cost, f"to level {new_level}", now)
        )
        db.execute(
            "INSERT INTO ledger(user_id,event,amount,note,created_at) VALUES(?,?,?,?,?)",
            (uid, "accounting_burn", burn, "Internal accounting only; not on-chain", now)
        )
        db.execute(
            "INSERT INTO ledger(user_id,event,amount,note,created_at) VALUES(?,?,?,?,?)",
            (uid, "treasury_allocation", treasury, "Internal project allocation; not wallet transfer", now)
        )

        referral_bonus = 0
        if new_level == 5 and user["referrer_id"]:
            referrer_id = user["referrer_id"]
            referrer = db.execute(
                "SELECT frozen FROM users WHERE user_id=?", (referrer_id,)
            ).fetchone()

            if referrer and not referrer["frozen"]:
                cur = db.execute(
                    """INSERT OR IGNORE INTO referral_rewards
                    (user_id, referrer_id, reward_type, amount, created_at)
                    VALUES (?, ?, 'referrer_level5', 300, ?)""",
                    (uid, referrer_id, now)
                )
                if cur.rowcount:
                    db.execute(
                        "UPDATE users SET balance=balance+300 WHERE user_id=?",
                        (referrer_id,)
                    )
                    db.execute(
                        """INSERT INTO ledger(user_id,event,amount,note,created_at)
                        VALUES(?,?,?,?,?)""",
                        (referrer_id, "referral_reward", 300,
                         f"referred user {uid} reached level 5", now)
                    )
                    referral_bonus = 300

        message = (
            f"تمت الترقية للمستوى {new_level}. "
            f"حرق محاسبي {burn} DRJ وخزينة محاسبية {treasury} DRJ."
        )
        if referral_bonus:
            message += " تمت إضافة مكافأة 300 DRJ للداعي."
        return True, message
