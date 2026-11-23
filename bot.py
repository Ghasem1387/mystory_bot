import os
from collections import defaultdict
from anthropic import AsyncAnthropic
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, ContextTypes, filters,
)

TOKEN = os.environ["BOT_TOKEN"]
client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# اینجا خودت رو معرفی کن تا ربات مثل تو جواب بده
PERSONA = """
تو دستیار شخصی قاسم هستی و به جای او با مردم چت می‌کنی.
مودب، صمیمی و کوتاه جواب بده و به زبان کاربر پاسخ بده.
اگه چیزی درباره قاسم نمی‌دونی، حدس نزن؛ بگو قاسم بعداً جواب می‌ده.
"""

history = defaultdict(list)  # حافظه موقت هر کاربر


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! من دستیار قاسمم. هر سؤالی داری بپرس 👋")


async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    history[uid].append({"role": "user", "content": update.message.text})
    history[uid] = history[uid][-10:]
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    try:
        r = await client.messages.create(
            model="claude-sonnet-5-5",
            max_tokens=800,
            system=PERSONA,
            messages=history[uid],
        )
        text = r.content[0].text
    except Exception:
        text = "الان یه مشکلی پیش اومد، بعداً دوباره امتحان کن."
    history[uid].append({"role": "assistant", "content": text})
    await update.message.reply_text(text)


app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))
app.run_polling()
