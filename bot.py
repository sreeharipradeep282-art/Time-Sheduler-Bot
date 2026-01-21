import os
import asyncio
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    InputMediaPhoto,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from flask import Flask
from threading import Thread

from db import schedules_col, messages_col
from scheduler import scheduler, interval_trigger

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

# ----------------------------
# MULTIPLE WELCOME PICS (hardcoded inside program)
# ----------------------------
# ✅ Option A: Direct image URLs (must be public direct link)
# ✅ Option B (BEST): Telegram file_id (recommended)

WELCOME_PICS = [
    # Put 2-5 photos here (URL or file_id)
    # Example URL:
    # "https://i.imgur.com/xxxxxxx.jpg",
    # Example file_id:
    # "AgACAgUAAxkBAAIB....",
]

# ----------------------------
# Render keep-alive web server
# ----------------------------
flask_app = Flask(__name__)

@flask_app.get("/")
def home():
    return "✅ Bot is alive", 200

def run_web():
    flask_app.run(host="0.0.0.0", port=PORT)

# ----------------------------
# Interval Buttons
# ----------------------------
INTERVALS = {
    "30s": 30,
    "1m": 60,
    "2m": 120,
    "5m": 300,
    "1h": 3600,
    "2h": 7200,
    "5h": 18000,
    "10h": 36000,
    "1Day": 86400,
    "2Day": 172800,
}

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Schedule (Reply /add)", callback_data="help_add")],
        [InlineKeyboardButton("📌 Active Schedules", callback_data="active")],
        [InlineKeyboardButton("🛑 Stop All", callback_data="stop_all")],
    ])

def interval_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ 30s", callback_data="int:30s"),
            InlineKeyboardButton("⏱ 1m", callback_data="int:1m"),
            InlineKeyboardButton("⏱ 2m", callback_data="int:2m"),
        ],
        [
            InlineKeyboardButton("⏱ 5m", callback_data="int:5m"),
            InlineKeyboardButton("🕐 1h", callback_data="int:1h"),
            InlineKeyboardButton("🕑 2h", callback_data="int:2h"),
        ],
        [
            InlineKeyboardButton("🕔 5h", callback_data="int:5h"),
            InlineKeyboardButton("🕙 10h", callback_data="int:10h"),
        ],
        [
            InlineKeyboardButton("📅 1 Day", callback_data="int:1Day"),
            InlineKeyboardButton("📅 2 Day", callback_data="int:2Day"),
        ],
        [
            InlineKeyboardButton("🛑 Stop This Chat", callback_data="stop"),
        ]
    ])

# ----------------------------
# Helper: extract message data
# ----------------------------
def serialize_message(msg: Message) -> dict:
    """
    Store minimal payload needed to resend same message.
    Supports text, photo, video, document, sticker.
    Supports inline keyboard (if message had it).
    """
    payload = {
        "text": msg.text_html if msg.text else None,
        "caption": msg.caption_html if msg.caption else None,
        "message_type": None,
        "file_id": None,
        "reply_markup": msg.reply_markup.to_dict() if msg.reply_markup else None,
    }

    if msg.text:
        payload["message_type"] = "text"
        return payload

    if msg.photo:
        payload["message_type"] = "photo"
        payload["file_id"] = msg.photo[-1].file_id
        return payload

    if msg.video:
        payload["message_type"] = "video"
        payload["file_id"] = msg.video.file_id
        return payload

    if msg.document:
        payload["message_type"] = "document"
        payload["file_id"] = msg.document.file_id
        return payload

    if msg.sticker:
        payload["message_type"] = "sticker"
        payload["file_id"] = msg.sticker.file_id
        return payload

    payload["message_type"] = "unknown"
    return payload


async def send_serialized(app: Application, chat_id: int, payload: dict):
    reply_markup = InlineKeyboardMarkup.de_json(payload.get("reply_markup"), app.bot) if payload.get("reply_markup") else None

    mtype = payload.get("message_type")
    text = payload.get("text")
    caption = payload.get("caption")

    if mtype == "text":
        await app.bot.send_message(
            chat_id=chat_id,
            text=text or "",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
        return

    if mtype == "photo":
        await app.bot.send_photo(
            chat_id=chat_id,
            photo=payload["file_id"],
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        return

    if mtype == "video":
        await app.bot.send_video(
            chat_id=chat_id,
            video=payload["file_id"],
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        return

    if mtype == "document":
        await app.bot.send_document(
            chat_id=chat_id,
            document=payload["file_id"],
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        return

    if mtype == "sticker":
        # Sticker cannot have inline buttons. So send sticker + optional message with buttons/text.
        await app.bot.send_sticker(chat_id=chat_id, sticker=payload["file_id"])
        if caption or reply_markup:
            await app.bot.send_message(
                chat_id=chat_id,
                text=caption or "✅",
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        return

    await app.bot.send_message(chat_id=chat_id, text="⚠️ Unsupported message type.")


# ----------------------------
# APScheduler job function
# ----------------------------
async def scheduled_job(app: Application, schedule_id: str):
    sch = schedules_col.find_one({"_id": schedule_id})
    if not sch or sch.get("is_active") is False:
        return

    msg_doc = messages_col.find_one({"_id": sch["message_id"]})
    if not msg_doc:
        return

    await send_serialized(app, sch["chat_id"], msg_doc["payload"])


def add_repeat_job(app: Application, schedule_id: str, seconds: int):
    job_id = f"repeat:{schedule_id}"
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass

    scheduler.add_job(
        lambda: asyncio.create_task(scheduled_job(app, schedule_id)),
        trigger=interval_trigger(seconds),
        id=job_id,
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60
    )
    return job_id


# ----------------------------
# Commands
# ----------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    # MULTIPLE PICS (album) — needs minimum 2 images
    if len(WELCOME_PICS) >= 2:
        media = []
        for i, item in enumerate(WELCOME_PICS[:5], start=1):
            if i == 1:
                media.append(InputMediaPhoto(
                    media=item,
                    caption=(
                        "🤖 <b>Scheduled Repeat Bot</b>\n\n"
                        "✅ Supports: Text / Photo / Video / Document / Sticker\n"
                        "✅ Repeat sending with interval buttons\n\n"
                        "<b>How to use:</b>\n"
                        "1) Send message in group\n"
                        "2) Reply with <code>/add</code>\n"
                        "3) Choose time\n"
                        "4) Stop with <code>/stop</code>\n\n"
                        "👇 Use buttons below"
                    ),
                    parse_mode=ParseMode.HTML
                ))
            else:
                media.append(InputMediaPhoto(media=item))
        await context.bot.send_media_group(chat_id=chat_id, media=media)

    # Always show menu
    await context.bot.send_message(
        chat_id=chat_id,
        text="⚙️ <b>Main Menu</b>\nChoose an option:",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard()
    )


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        await msg.reply_text("❌ <b>/add</b> must be used as <b>REPLY</b> to a message.", parse_mode=ParseMode.HTML)
        return

    target = msg.reply_to_message
    payload = serialize_message(target)

    if payload["message_type"] == "unknown":
        await msg.reply_text("❌ This message type not supported.")
        return

    # store captured message
    message_id = str(target.message_id) + ":" + str(target.chat_id)
    messages_col.update_one(
        {"_id": message_id},
        {"$set": {"payload": payload, "updated_at": datetime.now(timezone.utc)}},
        upsert=True
    )

    # create schedule placeholder
    schedule_id = f"{target.chat_id}:{target.message_id}"
    schedules_col.update_one(
        {"_id": schedule_id},
        {"$set": {
            "chat_id": target.chat_id,
            "message_id": message_id,
            "interval_seconds": None,
            "is_active": False,
            "created_by": msg.from_user.id,
            "updated_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )

    await msg.reply_text(
        "✅ <b>Message captured!</b>\n\n⏱ Select repeat interval:",
        parse_mode=ParseMode.HTML,
        reply_markup=interval_keyboard()
    )


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    schedules_col.update_many(
        {"chat_id": chat_id, "is_active": True},
        {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}}
    )

    for sch in schedules_col.find({"chat_id": chat_id}):
        job_id = f"repeat:{sch['_id']}"
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass

    await update.message.reply_text("🛑 <b>Stopped!</b>\nNo more scheduled messages in this chat.", parse_mode=ParseMode.HTML)


async def getid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        await msg.reply_text("❌ Reply to a photo/video/document/sticker and use /getid")
        return

    target = msg.reply_to_message
    payload = serialize_message(target)
    if payload["message_type"] == "unknown":
        await msg.reply_text("❌ Unsupported message type.")
        return

    await msg.reply_text(
        f"✅ <b>File ID:</b>\n\n<code>{payload.get('file_id')}</code>\n\n"
        f"Type: <b>{payload.get('message_type')}</b>",
        parse_mode=ParseMode.HTML
    )


# ----------------------------
# Callback query handler
# ----------------------------
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = query.message.chat_id

    if data == "help_add":
        await query.edit_message_text(
            "➕ <b>How to Add Schedule</b>\n\n"
            "1) Group-il message send cheyyuka\n"
            "2) Aa message reply cheythu <code>/add</code>\n"
            "3) Interval choose cheyyuka ✅",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard()
        )
        return

    if data == "active":
        active = list(schedules_col.find({"chat_id": chat_id, "is_active": True}))
        if not active:
            await query.edit_message_text(
                "📌 <b>Active Schedules</b>\n\n❌ No active schedules in this chat.",
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu_keyboard()
            )
            return

        txt = "📌 <b>Active Schedules</b>\n\n"
        for i, sch in enumerate(active, start=1):
            sec = sch.get("interval_seconds", 0)
            txt += f"{i}) 🔁 Every <b>{sec}</b> seconds\n"

        await query.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())
        return

    if data in ("stop_all", "stop"):
        schedules_col.update_many(
            {"chat_id": chat_id, "is_active": True},
            {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}}
        )
        for sch in schedules_col.find({"chat_id": chat_id}):
            job_id = f"repeat:{sch['_id']}"
            try:
                scheduler.remove_job(job_id)
            except Exception:
                pass

        await query.edit_message_text("🛑 <b>Stopped!</b>\nAll schedules cancelled ✅", parse_mode=ParseMode.HTML)
        return

    if data.startswith("int:"):
        key = data.split("int:")[1]
        seconds = INTERVALS.get(key)
        if not seconds:
            await query.edit_message_text("❌ Invalid interval.")
            return

        sch = schedules_col.find_one({"chat_id": chat_id}, sort=[("updated_at", -1)])
        if not sch:
            await query.edit_message_text("❌ Schedule not found.")
            return

        schedules_col.update_one(
            {"_id": sch["_id"]},
            {"$set": {
                "interval_seconds": seconds,
                "is_active": True,
                "updated_at": datetime.now(timezone.utc)
            }}
        )

        add_repeat_job(context.application, sch["_id"], seconds)

        await query.edit_message_text(
            f"✅ <b>Scheduled Successfully!</b>\n\n"
            f"📍 Chat: <code>{chat_id}</code>\n"
            f"🔁 Interval: <b>{key}</b>\n\n"
            f"🛑 Stop with: <code>/stop</code>",
            parse_mode=ParseMode.HTML
        )

# ----------------------------
# Restore schedules on startup
# ----------------------------
def restore_jobs(app: Application):
    for sch in schedules_col.find({"is_active": True, "interval_seconds": {"$ne": None}}):
        add_repeat_job(app, sch["_id"], int(sch["interval_seconds"]))
    logging.info("✅ Restored scheduled jobs from MongoDB")

# ----------------------------
# Main
# ----------------------------
async def post_init(app: Application):
    restore_jobs(app)
    scheduler.start()

def main():
    Thread(target=run_web, daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("add", add_cmd))
    application.add_handler(CommandHandler("stop", stop_cmd))
    application.add_handler(CommandHandler("getid", getid_cmd))
    application.add_handler(CallbackQueryHandler(on_button))

    logging.info("✅ Bot started")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
