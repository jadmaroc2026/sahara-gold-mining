from datetime import datetime, timezone
from database import connect


def admin_summary():
    with connect() as db:
        users = db.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        balances = db.execute(
            "SELECT COALESCE(SUM(balance),0) FROM users"
        ).fetchone()[0]

        frozen = db.execute(
            "SELECT COUNT(*) FROM users WHERE frozen=1"
        ).fetchone()[0]

        operations = db.execute(
            "SELECT COUNT(*) FROM ledger"
        ).fetchone()[0]

        return (
            "SAHARA GOLD - ADMIN SUMMARY\n"
            f"Players: {users}\n"
            f"Internal DRJ balances: {balances}\n"
            f"Frozen accounts: {frozen}\n"
            f"Ledger operations: {operations}\n"
            "On-chain supply/burn: not connected"
        )


def find_user(user_id):
    with connect() as db:
        row = db.execute(
            "SELECT * FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()
        return dict(row) if row else None


def user_details(user_id):
    user = find_user(user_id)

    if not user:
        return "لم يتم العثور على اللاعب."

    status = "مجمّد" if user["frozen"] else "نشط"

    return (
        f"معلومات اللاعب\n"
        f"ID: {user['user_id']}\n"
        f"Username: @{user['username'] or 'غير متوفر'}\n"
        f"الاسم: {user['first_name']}\n"
        f"الرصيد الداخلي: {user['balance']} DRJ\n"
        f"المستوى: {user['level']}/30\n"
        f"الحالة: {status}\n"
        f"تاريخ التسجيل: {user['created_at']}\n"
        f"الإحالات: {user['referrer_id'] or 'لا يوجد'}"
    )


def user_ledger(user_id, limit=10):
    limit = max(1, min(int(limit), 50))

    with connect() as db:
        rows = db.execute(
            "SELECT event, amount, note, created_at "
            "FROM ledger WHERE user_id=? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()

    if not rows:
        return "لا توجد عمليات مسجلة لهذا اللاعب."

    lines = ["آخر العمليات:"]
    for row in rows:
        lines.append(
            f"{row['event']} | {row['amount']} DRJ | "
            f"{row['note'] or ''} | {row['created_at']}"
        )

    return "\n".join(lines)


def set_frozen(admin_id, user_id, frozen):
    if frozen not in (0, 1):
        return False, "قيمة حالة الحساب غير صحيحة."

    now = datetime.now(timezone.utc).isoformat()

    with connect() as db:
        user = db.execute(
            "SELECT frozen FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()

        if not user:
            return False, "اللاعب غير موجود."

        if user["frozen"] == frozen:
            return False, "الحساب في الحالة المطلوبة بالفعل."

        db.execute(
            "UPDATE users SET frozen=? WHERE user_id=?",
            (frozen, user_id)
        )

        action = "freeze_user" if frozen else "unfreeze_user"

        db.execute(
            "INSERT INTO admin_audit "
            "(admin_id, action, target_user_id, details, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                admin_id,
                action,
                user_id,
                "Account frozen" if frozen else "Account unfrozen",
                now
            )
        )

    return True, "تم تجميد الحساب." if frozen else "تم فك تجميد الحساب."


def pending_withdrawals(limit=20):
    limit = max(1, min(int(limit), 50))
    with connect() as db:
        rows = db.execute(
            "SELECT id, user_id, amount, wallet_address, created_at "
            "FROM withdrawals WHERE status='pending' "
            "ORDER BY id ASC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def review_withdrawal(admin_id, request_id, decision, note=""):
    if decision not in ("approved", "rejected"):
        return False, "قرار غير صالح."

    now = datetime.now(timezone.utc).isoformat()

    with connect() as db:
        request = db.execute(
            "SELECT id, user_id, amount FROM withdrawals "
            "WHERE id=? AND status='pending'",
            (request_id,)
        ).fetchone()

        if not request:
            return False, "الطلب غير موجود أو تمت مراجعته سابقاً."

        db.execute(
            "UPDATE withdrawals SET status=?, reviewed_at=?, "
            "reviewed_by=?, decision_note=? "
            "WHERE id=? AND status='pending'",
            (decision, now, admin_id, note, request_id)
        )

        db.execute(
            "INSERT INTO admin_audit "
            "(admin_id, action, target_user_id, details, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                admin_id,
                "withdrawal_" + decision,
                request["user_id"],
                f"Request #{request_id}, amount={request['amount']} DRJ. {note}",
                now
            )
        )

    return True, "تم تسجيل قرار قبول الطلب." if decision == "approved" else "تم تسجيل رفض الطلب."
