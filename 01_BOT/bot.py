import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from config import BOT_TOKEN, ADMIN_ID
from database import init_db, ensure_user, get_user, claim_daily, grant_signup_referral_rewards
from services import get_upgrade_cost, upgrade_for_internal_balance
from admin import admin_summary, user_details, user_ledger, set_frozen, pending_withdrawals, review_withdrawal
from api_server import start_api, stop_api

logging.basicConfig(level=logging.INFO)

def keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("⛏️ التعدين"), KeyboardButton("💰 رصيدي")],
        [KeyboardButton("🎁 الدخول اليومي"), KeyboardButton("⭐ مستواي")],
        [KeyboardButton("🚀 ترقية المستوى"), KeyboardButton("👥 دعوة الأصدقاء")],
        [KeyboardButton("📤 السحب"), KeyboardButton("🔄 التحويل")],
        [KeyboardButton("❓ المساعدة")]
    ], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    referrer = None
    if context.args and context.args[0].startswith("ref"):
        try:
            referrer = int(context.args[0][3:])
        except ValueError:
            pass
    created = ensure_user(u.id, u.username or "", u.first_name or "", referrer)
    if created:
        grant_signup_referral_rewards(u.id)
    await update.message.reply_text(
        "🏆 أهلاً بك في SAHARA GOLD MINING\nعملة المشروع: DRJ\n"
        "هذه نسخة اختبارية؛ بعض الخدمات متوقفة حتى استكمال الربط والتحقق.",
        reply_markup=keyboard()
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    await update.message.reply_text(
        f"💰 رصيدك التجريبي: {user['balance']} DRJ\n⭐ مستواك: {user['level']}"
    )

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok, amount, day = claim_daily(update.effective_user.id)
    if ok:
        await update.message.reply_text(f"🎁 تمت إضافة {amount} DRJ تجريبية. اليوم {day}/7.")
    else:
        await update.message.reply_text("لقد حصلت على مكافأة الدخول اليوم بالفعل.")

async def mining(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⛏️ التعدين متوقف مؤقتاً. يتطلب 15 مشاهدة إعلان مع إثبات إكمال موثوق من مزود الإعلانات. "
        "لن نسجل مشاهدات وهمية أو نمنح مكافآت دون إثبات."
    )

async def level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    await update.message.reply_text(f"⭐ مستواك الحالي: {user['level']} من 30.")

async def upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    cost = get_upgrade_cost(user["level"])
    if cost is None:
        await update.message.reply_text("أنت في المستوى 30.")
    else:
        await update.message.reply_text(
            f"الترقية إلى المستوى {user['level']+1} تكلف {cost} DRJ تجريبية.\n"
            "لتنفيذها على الرصيد الداخلي التجريبي أرسل /upgrade_confirm. "
            "هذا ليس حرقاً على شبكة TON."
        )

async def upgrade_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok, msg = upgrade_for_internal_balance(update.effective_user.id)
    await update.message.reply_text(msg)

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = await context.bot.get_me()
    uid = update.effective_user.id
    await update.message.reply_text(
        f"رابط الدعوة: https://t.me/{bot.username}?start=ref{uid}\n"
        "المكافآت المحددة في التصميم: 500 DRJ للداعي، 200 DRJ للصديق، "
        "و300 إضافية للداعي عند وصول الصديق للمستوى 5. المكافآت تُضاف تلقائياً إلى رصيد DRJ الداخلي التجريبي."
    )

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "السحب غير متاح في النسخة التجريبية. يلزم عقد Jetton منشور، احتياطي، "
        "التحقق من معاملات TON، ومراجعة أمنية قبل فتحه."
    )

async def transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "التحويل بين اللاعبين غير مفعّل بعد. يجب أولاً بناء نظام تحقق ومعالجة آمن."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start بدء البوت\n/balance الرصيد\n/daily الدخول اليومي\n/mining التعدين\n"
        "/level المستوى\n/upgrade الترقية\n/upgrade_confirm تأكيد الترقية التجريبية\n"
        "/referral رابط الدعوة\n/withdraw السحب\n/transfer التحويل\n/admin لوحة المدير"
    )

def is_admin(update):
    return bool(ADMIN_ID and update.effective_user and update.effective_user.id == ADMIN_ID)


def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="admin:stats")],
        [InlineKeyboardButton("🔎 البحث عن لاعب", callback_data="admin:search")],
        [InlineKeyboardButton("💰 طلبات السحب", callback_data="admin:withdrawals")],
    ])


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("غير مصرح لك.")
        return
    await update.message.reply_text(
        "🛡️ لوحة إدارة SAHARA GOLD",
        reply_markup=admin_keyboard()
    )


async def admin_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("غير مصرح لك.")
        return

    if not context.args:
        await update.message.reply_text("استعمل الأمر هكذا: /admin_user TELEGRAM_ID")
        return

    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("المعرف يجب أن يكون رقماً.")
        return

    await update.message.reply_text(
        user_details(uid),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 سجل العمليات", callback_data=f"admin:ledger:{uid}")],
            [InlineKeyboardButton("🔒 تجميد الحساب", callback_data=f"admin:confirm_freeze:{uid}")],
            [InlineKeyboardButton("🔓 فك التجميد", callback_data=f"admin:confirm_unfreeze:{uid}")],
            [InlineKeyboardButton("⬅️ رجوع", callback_data="admin:back")]
        ])
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not is_admin(update):
        await query.answer("غير مصرح لك.", show_alert=True)
        return

    await query.answer()
    data = query.data

    if data == "admin:stats":
        await query.edit_message_text(
            admin_summary(),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ رجوع", callback_data="admin:back")]
            ])
        )

    elif data == "admin:withdrawals":
        requests = pending_withdrawals()
        if not requests:
            await query.edit_message_text(
                "لا توجد طلبات سحب معلّقة حالياً.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ رجوع", callback_data="admin:back")]
                ])
            )
            return

        lines = ["💰 طلبات السحب المعلّقة:"]
        buttons = []
        for req in requests:
            lines.append(
                f"\\nطلب #{req['id']} | اللاعب: {req['user_id']}\\n"
                f"المبلغ: {req['amount']} DRJ\\n"
                f"المحفظة: {req['wallet_address']}\\n"
                f"التاريخ: {req['created_at']}"
            )
            buttons.append([
                InlineKeyboardButton(
                    f"مراجعة الطلب #{req['id']}",
                    callback_data=f"admin:review_withdrawal:{req['id']}"
                )
            ])
        buttons.append([
            InlineKeyboardButton("⬅️ رجوع", callback_data="admin:back")
        ])
        await query.edit_message_text(
            "\\n".join(lines),
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    elif data.startswith("admin:review_withdrawal:"):
        try:
            request_id = int(data.split(":")[2])
        except (ValueError, IndexError):
            await query.edit_message_text("رقم الطلب غير صالح.")
            return

        requests = pending_withdrawals(50)
        req = next((r for r in requests if r["id"] == request_id), None)
        if not req:
            await query.edit_message_text(
                "الطلب غير موجود أو لم يعد معلّقاً.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ رجوع", callback_data="admin:withdrawals")]
                ])
            )
            return

        await query.edit_message_text(
            f"مراجعة طلب السحب #{req['id']}\\n"
            f"اللاعب: {req['user_id']}\\n"
            f"المبلغ: {req['amount']} DRJ\\n"
            f"المحفظة: {req['wallet_address']}\\n"
            f"تاريخ الطلب: {req['created_at']}\\n\\n"
            "اختر القرار. لن يتم تحويل أي أموال.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ قبول", callback_data=f"admin:confirm_withdrawal:{request_id}:approved")],
                [InlineKeyboardButton("❌ رفض", callback_data=f"admin:confirm_withdrawal:{request_id}:rejected")],
                [InlineKeyboardButton("⬅️ رجوع", callback_data="admin:withdrawals")]
            ])
        )
    elif data.startswith("admin:confirm_withdrawal:"):
        try:
            _, _, request_text, decision = data.split(":")
            request_id = int(request_text)
        except (ValueError, IndexError):
            await query.edit_message_text("طلب غير صالح.")
            return

        if decision not in ("approved", "rejected"):
            await query.edit_message_text("قرار غير صالح.")
            return

        label = "قبول" if decision == "approved" else "رفض"
        await query.edit_message_text(
            f"⚠️ واش متأكد من {label} طلب السحب #{request_id}؟\\n"
            "هذا يسجل القرار الإداري فقط، ولا يرسل أموالاً.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "✅ تأكيد",
                    callback_data=f"admin:execute_withdrawal:{request_id}:{decision}"
                )],
                [InlineKeyboardButton(
                    "❌ إلغاء",
                    callback_data=f"admin:review_withdrawal:{request_id}"
                )]
            ])
        )
    elif data.startswith("admin:execute_withdrawal:"):
        try:
            _, _, request_text, decision = data.split(":")
            request_id = int(request_text)
        except (ValueError, IndexError):
            await query.edit_message_text("طلب غير صالح.")
            return

        success, message = review_withdrawal(
            update.effective_user.id,
            request_id,
            decision
        )
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 طلبات السحب", callback_data="admin:withdrawals")],
                [InlineKeyboardButton("⬅️ لوحة المدير", callback_data="admin:back")]
            ])
        )
    elif data == "admin:search":
        await query.edit_message_text(
            "🔎 للبحث عن لاعب، أرسل الأمر التالي مع معرف Telegram:\n"
            "/admin_user TELEGRAM_ID\n\n"
            "مثال: /admin_user 123456789",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ رجوع", callback_data="admin:back")]
            ])
        )

    elif data.startswith("admin:ledger:"):
        try:
            uid = int(data.split(":")[2])
        except (ValueError, IndexError):
            await query.edit_message_text("معرف اللاعب غير صالح.")
            return

        await query.edit_message_text(
            user_ledger(uid),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 معلومات اللاعب", callback_data=f"admin:player:{uid}")],
                [InlineKeyboardButton("⬅️ رجوع", callback_data="admin:back")]
            ])
        )

    elif data.startswith("admin:player:"):
        try:
            uid = int(data.split(":")[2])
        except (ValueError, IndexError):
            await query.edit_message_text("معرف اللاعب غير صالح.")
            return

        await query.edit_message_text(
            user_details(uid),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📜 سجل العمليات", callback_data=f"admin:ledger:{uid}")],
                [InlineKeyboardButton("⬅️ رجوع", callback_data="admin:back")]
            ])
        )

    elif data.startswith("admin:confirm_freeze:") or data.startswith("admin:confirm_unfreeze:"):
        try:
            parts = data.split(":")
            uid = int(parts[2])
            action = parts[1]
        except (ValueError, IndexError):
            await query.edit_message_text("طلب غير صالح.")
            return

        frozen = 1 if action == "confirm_freeze" else 0
        label = "تجميد" if frozen else "فك التجميد"

        await query.edit_message_text(
            f"⚠️ تأكيد {label} حساب اللاعب {uid}؟\\n"
            "لن يتم تنفيذ أي تغيير حتى تضغط زر التأكيد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأكيد", callback_data=f"admin:execute_freeze:{uid}:{frozen}")],
                [InlineKeyboardButton("❌ إلغاء", callback_data=f"admin:player:{uid}")]
            ])
        )

    elif data.startswith("admin:execute_freeze:"):
        try:
            _, _, uid_text, frozen_text = data.split(":")
            uid = int(uid_text)
            frozen = int(frozen_text)
        except (ValueError, IndexError):
            await query.edit_message_text("طلب غير صالح.")
            return

        if frozen not in (0, 1):
            await query.edit_message_text("قيمة حالة الحساب غير صالحة.")
            return

        success, message = set_frozen(
            update.effective_user.id,
            uid,
            frozen
        )

        await query.edit_message_text(
            message + "\\n\\n" + user_details(uid),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📜 سجل العمليات", callback_data=f"admin:ledger:{uid}")],
                [InlineKeyboardButton("🔒 تجميد الحساب", callback_data=f"admin:confirm_freeze:{uid}")],
                [InlineKeyboardButton("🔓 فك التجميد", callback_data=f"admin:confirm_unfreeze:{uid}")],
                [InlineKeyboardButton("⬅️ رجوع", callback_data="admin:back")]
            ])
        )

    elif data == "admin:back":
        await query.edit_message_text(
            "🛡️ لوحة إدارة SAHARA GOLD",
            reply_markup=admin_keyboard()
        )

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    actions = {
        "⛏️ التعدين": mining, "💰 رصيدي": balance, "🎁 الدخول اليومي": daily,
        "⭐ مستواي": level, "🚀 ترقية المستوى": upgrade, "👥 دعوة الأصدقاء": referral,
        "📤 السحب": withdraw, "🔄 التحويل": transfer, "❓ المساعدة": help_cmd
    }
    fn = actions.get(update.message.text)
    if fn:
        await fn(update, context)

def setup_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("mining", mining))
    app.add_handler(CommandHandler("level", level))
    app.add_handler(CommandHandler("upgrade", upgrade))
    app.add_handler(CommandHandler("upgrade_confirm", upgrade_confirm))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("transfer", transfer))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("admin_user", admin_user_cmd))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^admin:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))


def main():
    if not BOT_TOKEN:
        raise SystemExit("أضف BOT_TOKEN إلى ملف .env قبل التشغيل.")
    init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(start_api).post_shutdown(stop_api).build()
    setup_handlers(app)
    print("SAHARA GOLD test bot is running.")
    app.run_polling()

if __name__ == "__main__":
    main()
