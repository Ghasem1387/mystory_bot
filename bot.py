import os
import io
import json
import random
import asyncio
import logging
from html import escape
from datetime import datetime, timezone

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup,
    InputMediaPhoto, InputMediaDocument, InlineQueryResultCachedPhoto,
    InlineQueryResultArticle, InputTextMessageContent,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, InlineQueryHandler,
    MessageHandler, ContextTypes, filters,
)

import cakes

try:
    import jdatetime
except ImportError:
    jdatetime = None

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("bot")

TOKEN = os.environ["BOT_TOKEN"]
ADMIN_USERNAME = "doyl0122"  # یوزرنیم ادمین / پشتیبانی (@Doyl0122)
ADMIN_ID_ENV = int(os.environ["ADMIN_ID"]) if os.environ.get("ADMIN_ID", "").strip().isdigit() else None
DB_FILE = "data.json"
BACKUP_NAME = "mystory_backup.json"
HTML = ParseMode.HTML
LINE = "━━━━━━━━━━━━━━"
FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
TO_EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def fa(n):
    return str(n).translate(FA)


# ═════════════════════ دیتابیس + بکاپ در چت ادمین ═════════════════════
DB = {"users": {}, "fids": {}}
USERS = DB["users"]
DIRTY = False
BACKUP_MSG_ID = None
BOT_USERNAME = ""


def _load_local():
    try:
        with open(DB_FILE, encoding="utf-8") as f:
            data = json.load(f)
        USERS.update({int(k): v for k, v in data.get("users", {}).items()})
        DB["fids"].update(data.get("fids", {}))
    except (FileNotFoundError, ValueError):
        pass


_load_local()


def save():
    global DIRTY
    DIRTY = True
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(DB, f, ensure_ascii=False)
    except OSError:
        pass


def admin_id():
    """شناسه ادمین: از سیکرت ADMIN_ID، یا از روی یوزرنیمش (اگر ربات را استارت کرده باشد)"""
    if ADMIN_ID_ENV:
        return ADMIN_ID_ENV
    for uid, u in USERS.items():
        if u.get("username") == ADMIN_USERNAME:
            return uid
    return None


async def restore_db(bot):
    """بازیابی دیتابیس از پیام پین‌شده‌ی چت ادمین"""
    global BACKUP_MSG_ID
    if not ADMIN_ID_ENV:
        return 0
    try:
        chat = await bot.get_chat(ADMIN_ID_ENV)
        pm = chat.pinned_message
        if pm and pm.document and pm.document.file_name == BACKUP_NAME:
            f = await bot.get_file(pm.document.file_id)
            data = json.loads((await f.download_as_bytearray()).decode("utf-8"))
            USERS.clear()
            USERS.update({int(k): v for k, v in data.get("users", {}).items()})
            DB["fids"].clear()
            DB["fids"].update(data.get("fids", {}))
            BACKUP_MSG_ID = pm.message_id
            log.info("دیتابیس بازیابی شد: %d کاربر", len(USERS))
            return len(USERS)
    except Exception:
        log.exception("بازیابی دیتابیس ناموفق بود")
    return 0


async def backup_db(bot, force=False):
    global DIRTY, BACKUP_MSG_ID
    aid = admin_id()
    if not aid or not (DIRTY or force):
        return False
    payload = json.dumps(DB, ensure_ascii=False).encode("utf-8")
    now = datetime.now(timezone.utc)
    stamp = jdatetime.datetime.fromgregorian(datetime=now).strftime("%Y/%m/%d %H:%M") if jdatetime else now.strftime("%Y-%m-%d %H:%M")
    caption = f"🗄 بکاپ دیتابیس\n👥 {fa(len(USERS))} کاربر • 🕒 {stamp}"
    DIRTY = False
    try:
        if BACKUP_MSG_ID:
            await bot.edit_message_media(
                chat_id=aid, message_id=BACKUP_MSG_ID,
                media=InputMediaDocument(payload, filename=BACKUP_NAME, caption=caption))
        else:
            msg = await bot.send_document(
                aid, document=payload, filename=BACKUP_NAME, caption=caption, disable_notification=True)
            await bot.pin_chat_message(aid, msg.message_id, disable_notification=True)
            BACKUP_MSG_ID = msg.message_id
        return True
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return True
        BACKUP_MSG_ID = None  # پیام قبلی پاک شده؛ دفعه بعد یکی جدید می‌فرستیم
        DIRTY = True
        log.warning("بکاپ: %s", e)
    except TelegramError as e:
        DIRTY = True
        log.warning("بکاپ: %s", e)
    return False


async def backup_loop(app):
    while True:
        await asyncio.sleep(90)
        try:
            await backup_db(app.bot)
        except Exception:
            log.exception("backup loop")


def get_user(tg_user):
    u = USERS.get(tg_user.id)
    new = u is None
    if new:
        u = {
            "name": tg_user.full_name,
            "username": (tg_user.username or "").lower(),
            "joined": datetime.now(timezone.utc).isoformat(),
            "sent": 0, "wins": 0, "cakes": 0,
            "notify": True,
            "away_on": False,
            "away_text": "سلام! فعلاً در دسترس نیستم، به‌زودی جواب می‌دم 🌿",
        }
        USERS[tg_user.id] = u
    changed = new
    if u["name"] != tg_user.full_name:
        u["name"] = tg_user.full_name
        changed = True
    uname = (tg_user.username or "").lower()
    if u["username"] != uname:
        u["username"] = uname
        changed = True
    u.setdefault("cakes", 0)
    if changed:
        save()
    return u


def fa_date(iso):
    dt = datetime.fromisoformat(iso)
    if jdatetime:
        return jdatetime.datetime.fromgregorian(datetime=dt).strftime("%Y/%m/%d")
    return dt.strftime("%Y-%m-%d")


# ═════════════════════ دکمه‌ها ═════════════════════
BTN_SEND, BTN_PROFILE = "💌 ارسال پیام", "👤 پروفایل"
BTN_SETTINGS, BTN_SUPPORT, BTN_GAME = "⚙️ تنظیمات", "🛟 پشتیبانی", "🎮 بازی"
BTN_BIRTH, BTN_SECRETARY = "🎂 ارسال تولد", "🗂 منشی اکانت"
TEXT_TO_KEY = {
    BTN_SEND: "send", BTN_PROFILE: "profile", BTN_SETTINGS: "settings",
    BTN_SUPPORT: "support", BTN_GAME: "game", BTN_BIRTH: "birth",
    BTN_SECRETARY: "secretary",
}


def reply_keyboard():
    return ReplyKeyboardMarkup(
        [[BTN_SEND, BTN_PROFILE],
         [BTN_SETTINGS, BTN_SUPPORT, BTN_GAME],
         [BTN_BIRTH, BTN_SECRETARY]],
        resize_keyboard=True, is_persistent=True,
        input_field_placeholder="یکی از گزینه‌ها رو انتخاب کن ✨",
    )


def ib(text, data=None, style=None, **kw):
    """دکمه شیشه‌ای؛ style: primary(آبی) / success(سبز) / danger(قرمز)"""
    extra = {"api_kwargs": {"style": style}} if style else {}
    if data is not None:
        kw["callback_data"] = data
    return InlineKeyboardButton(text, **kw, **extra)


def main_inline():
    return InlineKeyboardMarkup([
        [ib(BTN_SEND, "send", "primary"), ib(BTN_PROFILE, "profile", "primary")],
        [ib(BTN_SETTINGS, "settings"), ib(BTN_SUPPORT, "support", "danger"), ib(BTN_GAME, "game", "success")],
        [ib(BTN_BIRTH, "birth", "success"), ib(BTN_SECRETARY, "secretary", "primary")],
    ])


def back_inline():
    return InlineKeyboardMarkup([[ib("🔙 بازگشت به منو", "menu")]])


async def show(update: Update, text, markup=None):
    q = update.callback_query
    if q and q.message and not q.message.photo:
        try:
            await q.edit_message_text(text, parse_mode=HTML, reply_markup=markup)
        except BadRequest:
            pass
    else:
        await update.effective_message.reply_text(text, parse_mode=HTML, reply_markup=markup)


# ═════════════════════ کیک: فایل‌آیدی عکس‌ها ═════════════════════
FID_LOCK = asyncio.Lock()


def store_chats(*extra):
    ids = []
    for c in [admin_id(), *extra]:
        if c and c not in ids:
            ids.append(c)
    return ids


async def get_fid(bot, age, lit, chats):
    """عکس کیک را یک بار به تلگرام آپلود می‌کند و file_id را نگه می‌دارد"""
    key = f"{'lit' if lit else 'out'}_{age}"
    if key in DB["fids"]:
        return DB["fids"][key]
    async with FID_LOCK:
        if key in DB["fids"]:
            return DB["fids"][key]
        data = await asyncio.to_thread(cakes.jpeg_bytes, age, lit)
        last = None
        for chat_id in chats:
            try:
                msg = await bot.send_photo(chat_id, photo=data, disable_notification=True)
            except TelegramError as e:
                last = e
                continue
            fid = msg.photo[-1].file_id
            DB["fids"][key] = fid
            save()
            try:
                await msg.delete()
            except TelegramError:
                pass
            return fid
        raise last or RuntimeError("no chat to upload")


def birthday_caption(name, age, text):
    cap = (f"🎉🎂 <b>تولدت مبارک!</b> 🎂🎉\n{LINE}\n"
           f"🎁 <b>{escape(name)}</b> برات تولد <b>{fa(age)}</b> سالگی گرفته!\n")
    if text:
        cap += f"\n💬 <i>{escape(text)}</i>\n"
    return cap + "\n✨ آرزو کن و شمع‌ها رو فوت کن 👇"


# ═════════════════════ بخش‌ها ═════════════════════
async def section(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str):
    tg = update.effective_user
    u = get_user(tg)
    context.user_data.pop("state", None)
    name = escape(u["name"])

    if key == "menu":
        await show(update,
            f"✨ <b>سلام {name}!</b> خوش اومدی 🌈\n{LINE}\n"
            "💌 پیام بفرست  •  🎂 کیک تولد بساز  •  🎮 بازی کن\n\n"
            "👇 یکی از گزینه‌ها رو انتخاب کن", main_inline())

    elif key == "profile":
        uname = f"@{u['username']}" if u["username"] else "—"
        away = "🟢 فعال" if u["away_on"] else "⚪️ غیرفعال"
        await show(update,
            f"👤 <b>پروفایل من</b>\n{LINE}\n"
            f"🏷 نام: <b>{name}</b>\n"
            f"🆔 شناسه: <code>{tg.id}</code>\n"
            f"🔗 یوزرنیم: {uname}\n"
            f"📅 عضویت: {fa_date(u['joined'])}\n"
            f"{LINE}\n"
            f"💌 پیام‌های ارسالی: <b>{fa(u['sent'])}</b>\n"
            f"🎂 کیک‌های تولد: <b>{fa(u['cakes'])}</b>\n"
            f"🏆 برد در بازی: <b>{fa(u['wins'])}</b>\n"
            f"🗂 منشی: {away}", back_inline())

    elif key == "send":
        context.user_data["state"] = "send_target"
        await show(update,
            f"💌 <b>ارسال پیام</b>\n{LINE}\n"
            "شناسه عددی یا یوزرنیم گیرنده رو بفرست، مثل <code>@ali</code>\n"
            "<blockquote>⚠️ گیرنده باید قبلاً ربات رو استارت کرده باشه.</blockquote>", back_inline())

    elif key == "birth":
        rows = [
            [ib("🎈 ۱ تا ۲۰", "bda:g:1", "primary"), ib("🎈 ۲۱ تا ۴۰", "bda:g:21", "primary")],
            [ib("🎈 ۴۱ تا ۶۰", "bda:g:41", "primary"), ib("🎈 ۶۱ تا ۸۰", "bda:g:61", "primary")],
            [ib("🎈 ۸۱ تا ۱۰۰", "bda:g:81", "primary")],
            [ib("🔙 بازگشت به منو", "menu")],
        ]
        await show(update,
            f"🎂 <b>ارسال تولد</b>\n{LINE}\n"
            "یه کیک واقعی با شمع‌های روشن به شکل سن می‌سازم 🕯\n"
            "می‌تونی تو چت دوستت بفرستی یا مستقیم برای کاربر ربات؛ "
            "خودش باید شمع‌ها رو فوت کنه 🌬\n\n"
            "👇 اول گروه سنی رو انتخاب کن", InlineKeyboardMarkup(rows))

    elif key == "support":
        if admin_id() is None:
            await show(update, "🛟 پشتیبانی فعلاً در دسترس نیست، کمی بعد امتحان کن.", back_inline())
            return
        context.user_data["state"] = "support_text"
        await show(update,
            f"🛟 <b>پشتیبانی</b>\n{LINE}\n"
            "مشکل یا پیشنهادت رو بنویس و بفرست؛ مستقیم به دست ادمین می‌رسه 🙏", back_inline())

    elif key == "secretary":
        await render_secretary(update, u)

    elif key == "settings":
        await render_settings(update, u)

    elif key == "game":
        await show(update,
            f"🎮 <b>بازی</b>\n{LINE}\nیک بازی انتخاب کن:",
            InlineKeyboardMarkup([
                [ib("🔢 حدس عدد", "game:guess", "primary"), ib("🎲 تاس شانس", "game:dice", "success")],
                [ib("🔙 بازگشت به منو", "menu")],
            ]))


async def render_secretary(update, u):
    status = "🟢 روشن" if u["away_on"] else "⚪️ خاموش"
    await show(update,
        f"🗂 <b>منشی اکانت</b>\n{LINE}\n"
        "وقتی روشن باشه، هر کس بهت پیام بده منشی خودکار این متن رو جواب می‌ده:\n\n"
        f"<blockquote>{escape(u['away_text'])}</blockquote>\n"
        f"وضعیت: {status}",
        InlineKeyboardMarkup([
            [ib("🔴 خاموش کن" if u["away_on"] else "🟢 روشن کن", "sec:toggle",
                "danger" if u["away_on"] else "success")],
            [ib("✏️ تغییر متن پاسخ", "sec:set", "primary")],
            [ib("🔙 بازگشت به منو", "menu")],
        ]))


async def render_settings(update, u):
    n = "🔔 روشن" if u["notify"] else "🔕 خاموش"
    await show(update,
        f"⚙️ <b>تنظیمات</b>\n{LINE}\n"
        f"دریافت پیام و کیک از بقیه: {n}",
        InlineKeyboardMarkup([
            [ib(f"دریافت پیام: {n}", "tg:notify", "success" if u["notify"] else "danger")],
            [ib("🔙 بازگشت به منو", "menu")],
        ]))


# ═════════════════════ هندلرها ═════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    u = get_user(tg)
    context.user_data.clear()
    await update.message.reply_text(
        f"🌟 <b>سلام {escape(u['name'])}!</b>\nبه ربات خودت خوش اومدی 💫\n"
        "دکمه‌های پایین صفحه همیشه در دسترسن 👇",
        parse_mode=HTML, reply_markup=reply_keyboard())
    if tg.username and tg.username.lower() == ADMIN_USERNAME and not ADMIN_ID_ENV:
        await update.message.reply_text(
            "🔐 <b>ادمین شناخته شد.</b>\nبرای اینکه دیتابیس بعد از هر ری‌استارت برگرده، این عدد را "
            f"در سیکرت <code>ADMIN_ID</code> مخزن بگذار:\n<code>{tg.id}</code>", parse_mode=HTML)
    await section(update, context, "menu")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ لغو شد.", reply_markup=reply_keyboard())
    await section(update, context, "menu")


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🆔 شناسه عددی تو: <code>{update.effective_user.id}</code>", parse_mode=HTML)


def is_admin(tg):
    return tg.id == admin_id() or (tg.username or "").lower() == ADMIN_USERNAME


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    sent = sum(u["sent"] for u in USERS.values())
    cks = sum(u.get("cakes", 0) for u in USERS.values())
    await update.message.reply_text(
        f"📊 <b>آمار ربات</b>\n{LINE}\n👥 کاربران: <b>{fa(len(USERS))}</b>\n"
        f"💌 پیام‌ها: <b>{fa(sent)}</b>\n🎂 کیک‌ها: <b>{fa(cks)}</b>\n"
        f"🖼 عکس‌های ذخیره‌شده: <b>{fa(len(DB['fids']))}</b>", parse_mode=HTML)


async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    ok = await backup_db(context.bot, force=True)
    await update.message.reply_text("✅ بکاپ ارسال شد." if ok else "⚠️ بکاپ ممکن نشد (ADMIN_ID را چک کن).")


async def on_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await section(update, context, TEXT_TO_KEY[update.message.text])


def resolve(text, me_id):
    t = text.strip().translate(TO_EN)
    if t.startswith("@"):
        t = t[1:].lower()
        for uid, u in USERS.items():
            if u["username"] == t and uid != me_id:
                return uid
    elif t.isdigit() and int(t) in USERS and int(t) != me_id:
        return int(t)
    return None


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    u = get_user(tg)
    state = context.user_data.get("state")
    text = update.message.text

    if not state:
        await section(update, context, "menu")
        return

    if state in ("send_target", "birth_target"):
        tid = resolve(text, tg.id)
        if tid is None:
            await update.message.reply_text(
                "😕 کاربری با این مشخصات پیدا نشد.\nمطمئن شو ربات رو استارت کرده و دوباره بفرست (یا /cancel).")
            return
        context.user_data["target"] = tid
        if state == "birth_target":
            context.user_data["state"] = "birth_text"
            await update.message.reply_text(
                f"💬 اگه می‌خوای یه پیام کنار کیک <b>{escape(USERS[tid]['name'])}</b> بره، همین الان بنویس.\n"
                "وگرنه دکمه زیر رو بزن:", parse_mode=HTML,
                reply_markup=InlineKeyboardMarkup([[ib("⏭ بدون پیام، بفرست", "bd:skip", "success")]]))
        else:
            context.user_data["state"] = "send_text"
            await update.message.reply_text(
                f"✍️ حالا متن پیام برای <b>{escape(USERS[tid]['name'])}</b> رو بنویس:", parse_mode=HTML)

    elif state == "send_text":
        await deliver(update, context, tg, u, context.user_data["target"], text)

    elif state == "birth_text":
        await send_birthday(context, tg, u, update.message, text[:200])

    elif state == "support_text":
        context.user_data.pop("state")
        uname = f"@{u['username']}" if u["username"] else "—"
        try:
            await context.bot.send_message(
                admin_id(),
                f"🛟 <b>پیام پشتیبانی</b>\n{LINE}\n👤 {escape(u['name'])} ({uname})\n"
                f"🆔 <code>{tg.id}</code>\n\n{escape(text)}",
                parse_mode=HTML,
                reply_markup=InlineKeyboardMarkup([[ib("↩️ پاسخ", f"reply:{tg.id}", "primary")]]))
            await update.message.reply_text("✅ پیامت برای پشتیبانی ارسال شد. ممنون 🙏", reply_markup=reply_keyboard())
        except Exception:
            await update.message.reply_text("⚠️ ارسال به پشتیبانی ممکن نشد.")

    elif state == "away_text":
        u["away_text"] = text[:300]
        save()
        context.user_data.pop("state")
        await update.message.reply_text("✅ متن منشی ذخیره شد.")
        await render_secretary(update, u)


async def deliver(update, context, tg, u, tid, text):
    context.user_data.pop("state", None)
    context.user_data.pop("target", None)
    t = USERS[tid]
    if not t["notify"]:
        await update.message.reply_text("🔕 این کاربر دریافت پیام رو خاموش کرده.")
        return
    try:
        await context.bot.send_message(
            tid,
            f"💌 <b>پیام جدید</b>\n{LINE}\n👤 از: <b>{escape(u['name'])}</b>\n\n{escape(text)}",
            parse_mode=HTML,
            reply_markup=InlineKeyboardMarkup([[ib("↩️ پاسخ", f"reply:{tg.id}", "primary")]]))
    except Forbidden:
        await update.message.reply_text("🚫 این کاربر ربات رو بلاک کرده.")
        return
    u["sent"] += 1
    save()
    await update.message.reply_text("✅ پیامت ارسال شد 🚀", reply_markup=reply_keyboard())
    if t["away_on"]:
        await update.message.reply_text(
            f"🗂 <b>پاسخ خودکار منشی {escape(t['name'])}</b>\n{LINE}\n{escape(t['away_text'])}",
            parse_mode=HTML)


async def send_birthday(context, tg, u, msg, text):
    tid = context.user_data.get("target")
    age = context.user_data.get("age")
    context.user_data.clear()
    t = USERS.get(tid)
    if not t or not age:
        await msg.reply_text("⚠️ مشکلی پیش اومد، از اول امتحان کن.")
        return
    if not t["notify"]:
        await msg.reply_text("🔕 این کاربر دریافت پیام رو خاموش کرده.")
        return
    try:
        await context.bot.send_chat_action(msg.chat_id, "upload_photo")
        fid = await get_fid(context.bot, age, True, store_chats(msg.chat_id))
        await context.bot.send_photo(
            tid, fid, caption=birthday_caption(u["name"], age, text), parse_mode=HTML,
            reply_markup=InlineKeyboardMarkup([[ib("🌬 فوت کن!", f"blow:{tg.id}:{age}", "success")]]))
    except Forbidden:
        await msg.reply_text("🚫 این کاربر ربات رو بلاک کرده.")
        return
    except Exception:
        log.exception("send_birthday")
        await msg.reply_text("⚠️ ساخت کیک ممکن نشد، دوباره امتحان کن.")
        return
    u["cakes"] += 1
    save()
    await msg.reply_text(
        f"🎂 کیک <b>{fa(age)}</b> سالگی برای <b>{escape(t['name'])}</b> ارسال شد 🎉",
        parse_mode=HTML, reply_markup=reply_keyboard())


# ═════════════════════ اینلاین: ارسال کیک در چت دوست ═════════════════════
async def on_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    iq = update.inline_query
    tg = iq.from_user
    u = get_user(tg)
    parts = iq.query.strip().translate(TO_EN).split(maxsplit=1)
    age = int(parts[0]) if parts and parts[0].isdigit() and 1 <= int(parts[0]) <= 100 else None

    if age is None:
        await iq.answer([InlineQueryResultArticle(
            id="help", title="🎂 سن رو بنویس (۱ تا ۱۰۰)",
            description="مثلاً: 7   یا   25 تولدت مبارک عزیزم",
            input_message_content=InputTextMessageContent(
                "🎂 برای ساخت کیک تولد، بعد از اسم ربات سن رو بنویس؛ مثلاً <code>7</code>",
                parse_mode=HTML))], cache_time=5, is_personal=True)
        return

    text = parts[1][:150] if len(parts) > 1 else ""
    try:
        fid = await get_fid(context.bot, age, True, store_chats(tg.id))
    except Exception:
        log.exception("inline fid")
        await iq.answer([], cache_time=1)
        return
    result = InlineQueryResultCachedPhoto(
        id=f"c{age}x{tg.id}x{random.randint(1000, 9999)}",
        photo_file_id=fid,
        title=f"🎂 کیک {fa(age)} سالگی",
        description=text or "کیک تولد با شمع‌های روشن 🕯",
        caption=birthday_caption(u["name"], age, text),
        parse_mode=HTML,
        reply_markup=InlineKeyboardMarkup([[ib("🌬 فوت کن!", f"iblow:{tg.id}:{age}", "success")]]),
    )
    await iq.answer([result], cache_time=0, is_personal=True)
    asyncio.create_task(prewarm_out(context.bot, age, tg.id))


async def prewarm_out(bot, age, uid):
    try:
        await get_fid(bot, age, False, store_chats(uid))
    except Exception:
        pass


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    tg = q.from_user
    u = get_user(tg)

    # ─── فوت کردن شمع‌ها (چت ربات و چت دوست) ───
    if data.startswith(("blow:", "iblow:")):
        _, sid, age = data.split(":")
        sid, age = int(sid), int(age)
        try:
            fid = await get_fid(context.bot, age, False, store_chats(sid))
            cap = (f"🎉 <b>شمع‌ها خاموش شد!</b> 🎉\n{LINE}\n"
                   f"🌟 <b>{escape(u['name'])}</b> آرزوش رو کرد و شمع‌های {fa(age)} سالگی رو فوت کرد\n"
                   "💫 ان‌شاءالله به همه آرزوهات برسی 🎂")
            await q.edit_message_media(InputMediaPhoto(fid, caption=cap, parse_mode=HTML))
        except BadRequest:
            return
        except Exception:
            log.exception("blow")
            return
        if sid != tg.id:
            try:
                await context.bot.send_message(
                    sid, f"🌬 <b>{escape(u['name'])}</b> شمع‌های کیک {fa(age)} سالگی‌ات رو فوت کرد! 🎉🎂",
                    parse_mode=HTML)
            except TelegramError:
                pass
        return

    if data in ("menu", "send", "profile", "settings", "support", "game", "birth", "secretary"):
        await section(update, context, data)

    # ─── انتخاب سن برای کیک ───
    elif data.startswith("bda:g:"):
        start_age = int(data.split(":")[2])
        rows = [[ib(fa(n), f"bda:n:{n}", "primary") for n in range(r, r + 5)]
                for r in range(start_age, start_age + 20, 5)]
        rows.append([ib("🔙 گروه‌های سنی", "birth"), ib("🏠 منو", "menu")])
        await show(update,
            f"🎂 <b>سن رو انتخاب کن</b>\n{LINE}\n🎈 {fa(start_age)} تا {fa(start_age + 19)} سالگی",
            InlineKeyboardMarkup(rows))

    elif data.startswith("bda:n:"):
        age = int(data.split(":")[2])
        chat_id = q.message.chat_id
        await context.bot.send_chat_action(chat_id, "upload_photo")
        try:
            fid = await get_fid(context.bot, age, True, store_chats(chat_id))
        except Exception:
            log.exception("preview")
            await q.message.reply_text("⚠️ ساخت کیک ممکن نشد، دوباره امتحان کن.")
            return
        kb = InlineKeyboardMarkup([
            [ib("📤 ارسال در چت دوستم", style="success", switch_inline_query=f"{age} ")],
            [ib("👤 ارسال به کاربر ربات", f"bdt:{age}", "primary")],
            [ib("🔄 تغییر سن", "birth")],
        ])
        await context.bot.send_photo(
            chat_id, fid, parse_mode=HTML, reply_markup=kb,
            caption=(f"🎂 <b>کیک {fa(age)} سالگی آماده‌ست!</b>\n{LINE}\n"
                     "📤 <b>چت دوستم:</b> چت رو انتخاب کن، کیک آماده می‌شه؛ "
                     "اگه خواستی بعد از سن یه پیام هم بنویس و بفرست.\n"
                     "👤 <b>کاربر ربات:</b> با شناسه یا یوزرنیم مستقیم براش می‌فرستم."))

    elif data.startswith("bdt:"):
        context.user_data.clear()
        context.user_data["age"] = int(data.split(":")[1])
        context.user_data["state"] = "birth_target"
        await q.message.reply_text(
            f"🎂 <b>ارسال تولد</b>\n{LINE}\n"
            "شناسه عددی یا یوزرنیم کسی که تولدشه رو بفرست.\n"
            "<blockquote>⚠️ باید قبلاً ربات رو استارت کرده باشه. (لغو: /cancel)</blockquote>",
            parse_mode=HTML)

    elif data == "bd:skip":
        await send_birthday(context, tg, u, q.message, None)

    # ─── منشی / تنظیمات ───
    elif data == "sec:toggle":
        u["away_on"] = not u["away_on"]
        save()
        await render_secretary(update, u)

    elif data == "sec:set":
        context.user_data["state"] = "away_text"
        await show(update, "✏️ متن جدید منشی رو بفرست (حداکثر ۳۰۰ کاراکتر):", back_inline())

    elif data == "tg:notify":
        u["notify"] = not u["notify"]
        save()
        await render_settings(update, u)

    elif data.startswith("reply:"):
        context.user_data["state"] = "send_text"
        context.user_data["target"] = int(data.split(":")[1])
        await q.message.reply_text("✍️ متن پاسخت رو بنویس (یا /cancel):")

    # ─── بازی ───
    elif data == "game:guess":
        await show(update,
            f"🔢 <b>حدس عدد</b>\n{LINE}\nمن یه عدد بین ۱ تا ۵ انتخاب کردم. حدس بزن!",
            InlineKeyboardMarkup([
                [ib(fa(i), f"g:{i}", "primary") for i in range(1, 6)],
                [ib("🔙 بازگشت", "game")],
            ]))

    elif data.startswith("g:"):
        guess, secret = int(data[2:]), random.randint(1, 5)
        if guess == secret:
            u["wins"] += 1
            save()
            res = f"🏆 <b>آفرین! درست حدس زدی</b> ({fa(secret)})"
        else:
            res = f"😅 اشتباه بود! عدد من <b>{fa(secret)}</b> بود."
        await show(update, f"{res}\n{LINE}\nدوباره بازی می‌کنی؟",
                   InlineKeyboardMarkup([
                       [ib("🔁 دوباره", "game:guess", "success")],
                       [ib("🔙 بازگشت", "game")],
                   ]))

    elif data == "game:dice":
        msg = await q.message.reply_dice(emoji="🎲")
        if msg.dice.value == 6:
            u["wins"] += 1
            save()
            await q.message.reply_text("🏆 شش آوردی! یک امتیاز گرفتی 🎉")


async def on_error(update, context):
    log.error("خطا", exc_info=context.error)


async def post_init(app: Application):
    global BOT_USERNAME
    me = await app.bot.get_me()
    BOT_USERNAME = me.username
    n = await restore_db(app.bot)
    await app.bot.set_my_commands([
        ("start", "شروع و منوی اصلی"), ("cancel", "لغو عملیات"), ("id", "شناسه عددی من"),
    ])
    app.bot_data["backup_task"] = asyncio.create_task(backup_loop(app))
    if ADMIN_ID_ENV:
        try:
            await app.bot.send_message(
                ADMIN_ID_ENV,
                f"✅ <b>ربات آنلاین شد</b>\n👥 {fa(len(USERS))} کاربر"
                + (" (از بکاپ برگشت)" if n else ""), parse_mode=HTML, disable_notification=True)
        except TelegramError:
            pass


async def post_shutdown(app: Application):
    try:
        await backup_db(app.bot)
    except Exception:
        pass


def main():
    app = Application.builder().token(TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("id", my_id))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("backup", backup_cmd))
    app.add_handler(InlineQueryHandler(on_inline))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.Text(list(TEXT_TO_KEY)), on_menu_text))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    app.run_polling(drop_pending_updates=True, allowed_updates=["message", "callback_query", "inline_query"])


if __name__ == "__main__":
    main()
