import os
import io
import json
from telegram import Update, InputMediaDocument, InlineKeyboardButton as Btn, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ChatMemberHandler, ContextTypes, filters,
)

TOKEN = os.environ["BOT_TOKEN"]
ADMIN_USERNAME = "doyle0122"  # آیدی ادمین بدون @ و با حروف کوچک
ADMIN_ID = int(os.environ["ADMIN_ID"]) if os.environ.get("ADMIN_ID") else None

users = set()  # دیتابیس: آیدی عددی کاربران
DB_NAME = "users.json"
DB_CAPTION = "💾 دیتابیس ربات (پین شده؛ پاکش نکن)"


# ---------- دیتابیس داخل چت ادمین ----------
async def load_db(app):
    """موقع روشن شدن، فایل پین‌شده‌ی چت ادمین رو می‌خونه."""
    if not ADMIN_ID:
        print("ADMIN_ID تنظیم نشده؛ دیتابیس غیرفعاله")
        return
    try:
        chat = await app.bot.get_chat(ADMIN_ID)
        pm = chat.pinned_message
        if pm and pm.document and pm.document.file_name == DB_NAME:
            f = await pm.document.get_file()
            data = json.loads((await f.download_as_bytearray()).decode())
            users.update(data)
            app.bot_data["db_msg"] = pm.message_id
            print(f"دیتابیس لود شد: {len(users)} کاربر")
    except Exception as e:
        print("load error:", e)


def _file():
    return io.BytesIO(json.dumps(sorted(users)).encode())


async def save_db(bot, bot_data):
    """فایل دیتابیس رو توی چت ادمین ذخیره/ویرایش می‌کنه."""
    if not ADMIN_ID:
        return
    mid = bot_data.get("db_msg")
    try:
        if mid:
            try:
                await bot.edit_message_media(
                    chat_id=ADMIN_ID, message_id=mid,
                    media=InputMediaDocument(_file(), filename=DB_NAME, caption=DB_CAPTION),
                )
                return
            except BadRequest as e:
                if "not modified" in str(e).lower():
                    return
        msg = await bot.send_document(
            ADMIN_ID, _file(), filename=DB_NAME,
            caption=DB_CAPTION, disable_notification=True,
        )
        await bot.pin_chat_message(ADMIN_ID, msg.message_id, disable_notification=True)
        bot_data["db_msg"] = msg.message_id
    except Exception as e:
        print("save error:", e)


# ---------- منو ----------
def is_admin(user) -> bool:
    if ADMIN_ID and user.id == ADMIN_ID:
        return True
    return (user.username or "").lower() == ADMIN_USERNAME


def main_menu(user):
    rows = [
        [Btn("👤 درباره من", callback_data="about"),
         Btn("📩 ارتباط با من", url="https://t.me/Doyle0122")],
        [Btn("ℹ️ راهنما", callback_data="help")],
    ]
    if is_admin(user):
        rows.append([Btn("⚙️ مدیریت", callback_data="admin")])
    return InlineKeyboardMarkup(rows)


BACK = InlineKeyboardMarkup([[Btn("🔙 بازگشت", callback_data="home")]])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in users:
        users.add(user.id)
        await save_db(context.bot, context.bot_data)
    await update.message.reply_text(
        f"سلام {user.first_name} 👋\nبه ربات من خوش اومدی. یکی از گزینه‌ها رو انتخاب کن:",
        reply_markup=main_menu(user),
    )
    if is_admin(user) and not ADMIN_ID:
        await update.message.reply_text(
            f"آیدی عددی تو: {user.id}\n"
            "اینو توی Secrets گیت‌هاب با اسم ADMIN_ID بذار تا دیتابیس فعال بشه."
        )


async def on_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ev = update.my_chat_member
    if ev.chat.type == "private":
        return
    if ev.new_chat_member.status in ("member", "administrator"):
        await context.bot.send_message(
            ev.chat.id,
            f"سلام! ممنون {ev.from_user.first_name} که من رو اضافه کردی 🌹",
        )


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = q.from_user
    await q.answer()
    d = q.data

    if d == "home":
        await q.edit_message_text(
            f"سلام {user.first_name} 👋\nیکی از گزینه‌ها رو انتخاب کن:",
            reply_markup=main_menu(user),
        )
    elif d == "about":
        await q.edit_message_text("من ربات شخصی قاسمم. 🤖", reply_markup=BACK)
    elif d == "help":
        await q.edit_message_text(
            "از دکمه‌های منو استفاده کن. برای ارتباط مستقیم، دکمه «ارتباط با من» رو بزن.",
            reply_markup=BACK,
        )
    elif d.startswith("adm_") or d == "admin":
        if not is_admin(user):
            await q.answer("دسترسی نداری ⛔", show_alert=True)
            return
        if d == "admin":
            kb = InlineKeyboardMarkup([
                [Btn("📊 آمار کاربران", callback_data="adm_stats")],
                [Btn("📢 پیام همگانی", callback_data="adm_broadcast")],
                [Btn("🔙 بازگشت", callback_data="home")],
            ])
            await q.edit_message_text("⚙️ پنل مدیریت", reply_markup=kb)
        elif d == "adm_stats":
            await q.edit_message_text(
                f"تعداد کاربران: {len(users)}",
                reply_markup=InlineKeyboardMarkup([[Btn("🔙 بازگشت", callback_data="admin")]]),
            )
        elif d == "adm_broadcast":
            context.user_data["broadcast"] = True
            await q.edit_message_text(
                "متنی که می‌خوای برای همه بفرستم رو همین الان بنویس:",
                reply_markup=InlineKeyboardMarkup([[Btn("❌ انصراف", callback_data="adm_cancel")]]),
            )
        elif d == "adm_cancel":
            context.user_data["broadcast"] = False
            await q.edit_message_text("لغو شد.", reply_markup=BACK)


async def text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # ربات چت نمی‌کنه؛ فقط وقتی ادمین در حالت پیام همگانیه عمل می‌کنه
    if is_admin(user) and context.user_data.get("broadcast"):
        context.user_data["broadcast"] = False
        sent = 0
        for uid in list(users):
            try:
                await context.bot.send_message(uid, update.message.text)
                sent += 1
            except Exception:
                pass
        await update.message.reply_text(f"برای {sent} نفر ارسال شد ✅")


app = ApplicationBuilder().token(TOKEN).post_init(load_db).build()
app.add_handler(CommandHandler("start", start, filters.ChatType.PRIVATE))
app.add_handler(CallbackQueryHandler(buttons))
app.add_handler(ChatMemberHandler(on_added, ChatMemberHandler.MY_CHAT_MEMBER))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, text))
app.run_polling(allowed_updates=Update.ALL_TYPES)
