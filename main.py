import os
import logging
from http import HTTPStatus

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ---------- logging ----------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("linkmaxxer-webhook")

# ---------- config ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("Missing BOT_TOKEN env var.")

# Channel IDs you collected earlier
ENTRY_CHANNEL_ID = -1002563211320   # @Linkmaxxer (public)
MAIN_CHANNEL_ID  = -1002265900301   # Linkmaxxer Main (private)
LOG_CHANNEL_ID   = -1002508610031   # Private log

# ---------- PTB application (no Updater -> webhook mode) ----------
ptb = Application.builder().token(BOT_TOKEN).updater(None).build()

# ---------- handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Open Entry Channel", url="https://t.me/Linkmaxxer")],
        [InlineKeyboardButton("I've Joined ✅", callback_data="verify")]
    ])
    await update.message.reply_text(
        "🚀 Welcome!\n\nJoin the Entry channel first, then tap **I've Joined ✅**.",
        reply_markup=kb
    )

async def verify_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    # Check membership in ENTRY channel
    ok = False
    try:
        member = await context.bot.get_chat_member(ENTRY_CHANNEL_ID, user.id)
        status = getattr(member, "status", None)
        ok = status in ("member", "administrator", "creator")
    except Exception as e:
        log.error(f"get_chat_member failed: {e}")

    if not ok:
        await query.edit_message_text(
            "❌ You haven't joined the Entry channel yet.\n\nJoin @Linkmaxxer and try again."
        )
        return

    # Create one-time invite to MAIN
    try:
        invite = await context.bot.create_chat_invite_link(
            MAIN_CHANNEL_ID, member_limit=1
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Join ✅", url=invite.invite_link)]])
        await query.edit_message_text(
            "✅ Thanks for verification! Use the button below to join the main channel:",
            reply_markup=kb
        )
        uname = f"@{user.username}" if user.username else f"(no username, id {user.id})"
        await context.bot.send_message(LOG_CHANNEL_ID, f"New verification: {uname}")
    except Exception as e:
        log.error(f"create_chat_invite_link failed: {e}")
        await query.edit_message_text(
            "⚠️ I couldn't create an invite link. Ask admin to grant the bot “Invite Users via Link” in the main channel."
        )

ptb.add_handler(CommandHandler("start", start))
ptb.add_handler(CallbackQueryHandler(verify_cb, pattern="^verify$"))

# ---------- Starlette webhook server ----------
async def home(_: Request):
    return PlainTextResponse("Linkmaxxer bot webhook is live")

async def health(_: Request):
    return PlainTextResponse("ok", status_code=HTTPStatus.OK)

async def telegram_update(request: Request):
    data = await request.json()
    await ptb.update_queue.put(Update.de_json(data=data, bot=ptb.bot))
    return Response(status_code=HTTPStatus.OK)

starlette_app = Starlette(
    routes=[
        Route("/", home, methods=["GET"]),
        Route("/healthcheck", health, methods=["GET"]),
        Route("/telegram", telegram_update, methods=["POST"]),
    ]
)

# Start/stop PTB app + set webhook when the ASGI app starts/stops
async def _on_startup():
    base_url = (os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PUBLIC_URL") or "").rstrip("/")
    if not base_url:
        log.warning("No public URL env set. On Render this will be RENDER_EXTERNAL_URL. Else set PUBLIC_URL.")
    webhook_url = f"{base_url}/telegram" if base_url else None

    await ptb.initialize()
    if webhook_url:
        await ptb.bot.set_webhook(
            url=webhook_url,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        log.info(f"Webhook set to {webhook_url}")
    await ptb.start()

async def _on_shutdown():
    try:
        await ptb.stop()
    except Exception:
        pass

starlette_app.add_event_handler("startup", _on_startup)
starlette_app.add_event_handler("shutdown", _on_shutdown)

# Optional: local dev with `python main.py`
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:starlette_app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))