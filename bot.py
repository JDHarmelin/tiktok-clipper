"""
Telegram bot entry point. Receives YouTube URLs and triggers the clipping pipeline.
Run with: python bot.py
"""
import re
import asyncio
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from config import TELEGRAM_BOT_TOKEN, ALLOWED_USER_ID
from orchestrator import run_pipeline

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

YT_PATTERN = re.compile(
    r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)[\w\-]+"
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "TikTok Clipper Bot\n\n"
        "Send me a YouTube URL and I'll:\n"
        "1. Download the video\n"
        "2. Find the most viral moments\n"
        "3. Create vertical clips with captions\n"
        "4. Post them to TikTok\n\n"
        "Just paste a YouTube link to get started!",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running and ready for URLs.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages -- detect YouTube URLs and trigger pipeline."""
    if ALLOWED_USER_ID and update.effective_user.id != ALLOWED_USER_ID:
        await update.message.reply_text("Unauthorized. This bot is private.")
        return

    text = update.message.text or ""
    match = YT_PATTERN.search(text)

    if not match:
        await update.message.reply_text(
            "Please send a valid YouTube URL.\n"
            "Supported formats:\n"
            "- youtube.com/watch?v=...\n"
            "- youtu.be/...\n"
            "- youtube.com/shorts/..."
        )
        return

    url = match.group(0)
    if not url.startswith("http"):
        url = "https://" + url

    chat_id = update.effective_chat.id
    bot = context.bot

    status_msg = await update.message.reply_text(
        f"Received URL\n{url}\n\nStarting pipeline...",
    )

    progress_stages = []
    main_loop = asyncio.get_running_loop()

    async def async_progress(stage, message):
        indicator = "X" if stage == "error" else ">"
        progress_stages.append(f"[{indicator}] {message}")
        progress_text = "\n".join(progress_stages[-8:])
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg.message_id,
                text=f"Processing...\n\n{progress_text}",
            )
        except Exception:
            pass

    def sync_progress(stage, message):
        asyncio.run_coroutine_threadsafe(async_progress(stage, message), main_loop)

    try:
        result = await main_loop.run_in_executor(
            None, lambda: run_pipeline(url, progress_callback=sync_progress)
        )

        summary = (
            f"Pipeline Complete!\n\n"
            f"Clips generated: {result.get('clip_count', 0)}\n"
            f"Posted to TikTok: {result.get('posted_count', 0)}\n"
        )

        if result.get("errors"):
            summary += f"\nErrors: {', '.join(result['errors'][:3])}\n"

        if result.get("summary"):
            agent_summary = result["summary"][:500]
            summary += f"\nAgent Summary:\n{agent_summary}"

        await bot.send_message(chat_id=chat_id, text=summary)

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        await bot.send_message(
            chat_id=chat_id,
            text=f"Pipeline Error\n\n{str(e)[:200]}",
        )


def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting in polling mode...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
