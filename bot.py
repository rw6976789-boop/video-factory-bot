"""bot.py — Telegram front-end.

Flow: user sends SCRIPT (text / .txt) + VOICE (voice note / audio / mp3).
When both are in, the factory runs: finder -> editor -> delivery.
Status updates keep the user posted; the finished video comes back in chat.
"""
import asyncio
import logging
import time
from pathlib import Path

from telegram import Update
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          filters, ContextTypes)

import config as C
import brain
import finder
import editor
import delivery

log = logging.getLogger("bot")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

sessions = {}  # chat_id -> {"script": str|None, "voice": str|None, "busy": bool}

WELCOME = (
    "Assalam-o-Alaikum Ustad g! \U0001f3ac\n\n"
    "Main aapka Video Factory hoon.\n"
    "1) Apna *script* bhejein (text message ya .txt file)\n"
    "2) Apni *voice* bhejein (voice note ya MP3)\n\n"
    "Dono milte hi main aapke LOCKED STYLE mein video edit karke "
    "yahiin bhej dunga.\n\n"
    "/cancel — session reset"
)


def sess(chat_id):
    return sessions.setdefault(chat_id, {"script": None, "voice": None,
                                        "busy": False})


def job_dir(chat_id):
    d = Path(C.INCOMING) / str(chat_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME, parse_mode="Markdown")


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sessions.pop(update.effective_chat.id, None)
    await update.message.reply_text("Session reset ho gaya. Script + voice dobara bhejein.")


async def _accept_script(chat_id, text, reply):
    s = sess(chat_id)
    if s["busy"]:
        await reply("Ek video abhi process ho rahi hai — thoda intezar karein.")
        return
    if len(text) < 200:
        await reply("Ye script lag nahi raha — poora script text bhejein (ya .txt file).")
        return
    (job_dir(chat_id) / "script.txt").write_text(text, encoding="utf-8")
    s["script"] = text
    await reply(f"Script mil gaya ✅ ({len(text.split())} words). Ab voice bhejein.")


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text or ""
    if txt.startswith("/"):
        return
    await _accept_script(update.effective_chat.id, txt,
                         update.message.reply_text)
    await maybe_start(update.effective_chat.id, ctx)


async def on_txt_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    f = await doc.get_file()
    tmp = job_dir(update.effective_chat.id) / "script_up.txt"
    await f.download_to_drive(tmp)
    try:
        text = tmp.read_text(encoding="utf-8", errors="replace")
    except Exception:
        await update.message.reply_text("Ye .txt parh nahi saka — text message mein script bhejein.")
        return
    await _accept_script(update.effective_chat.id, text,
                         update.message.reply_text)
    await maybe_start(update.effective_chat.id, ctx)


async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    s = sess(chat_id)
    if s["busy"]:
        await update.message.reply_text("Ek video abhi process ho rahi hai — thoda intezar karein.")
        return
    msg = update.message
    tg_file = msg.voice or msg.audio or msg.document
    f = await tg_file.get_file()
    job = job_dir(chat_id)
    src = job / "voice_in.bin"
    await f.download_to_drive(src)
    dst = job / "voice.mp3"
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", str(src), "-acodec", "libmp3lame", "-ar", "44100",
        str(dst), stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL)
    await proc.wait()
    if not dst.exists():
        await msg.reply_text("Voice convert nahi ho saki — MP3 bhejein.")
        return
    s["voice"] = str(dst)
    await msg.reply_text("Voice mil gayi ✅.")
    await maybe_start(chat_id, ctx)


async def maybe_start(chat_id, ctx):
    s = sess(chat_id)
    if s["script"] and s["voice"] and not s["busy"]:
        s["busy"] = True
        asyncio.create_task(run_pipeline(chat_id, ctx))


async def run_pipeline(chat_id, ctx):
    bot = ctx.bot
    job = job_dir(chat_id)
    status = await bot.send_message(
        chat_id, "\U0001f9e0 Gemini brain script parh raha hai — entries nikal raha hoon...")
    try:
        manifest = await asyncio.to_thread(
            finder.run, sessions[chat_id]["script"], str(job / "work"))
        await status.edit_text(
            f"\U0001f3ac {len(manifest['entries'])} entries, "
            f"{len(manifest['beats'])} beats, "
            f"{len(manifest['montage_clips'])} clips (vision-checked) — "
            "locked style mein edit ho raha hai (thoda waqt lagega)...")
        out = str(Path(C.OUTPUT) / f"video_{chat_id}_{int(time.time())}.mp4")
        await asyncio.to_thread(
            editor.render_job, manifest, sessions[chat_id]["voice"], out, print)
        await status.edit_text("\U0001f4e4 Video tayyar — bhej raha hoon...")
        await delivery.deliver(bot, chat_id, out)
        await status.edit_text("Ho gaya Ustad g ✅")
    except Exception as e:  # never die silently
        log.exception("pipeline failed for %s", chat_id)
        await status.edit_text(
            f"⚠️ Error aaya: {e}\n/cancel karke dobara try karein.")
    finally:
        sessions.pop(chat_id, None)


def main():
    if not C.BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN env var missing — set it and restart.")
    app = Application.builder().token(C.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.Document.MimeType("text/plain"), on_txt_file))
    app.add_handler(MessageHandler(
        filters.VOICE | filters.AUDIO | filters.Document.AUDIO, on_voice))
    log.info("bot polling started")
    app.run_polling()


if __name__ == "__main__":
    main()
