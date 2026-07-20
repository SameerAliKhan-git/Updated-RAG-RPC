"""Corpus — Telegram Bot.

Secondary channel for quick lookup of research papers.
Connects to the same backend API (/ask-agentic) or directly to the DB.
Reads configuration from TELEGRAM__BOT_TOKEN and TELEGRAM__ENABLED.
"""

from __future__ import annotations

import logging
import os
import sys

# Ensure project root is in path
from pathlib import Path

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

project_root = str(Path(__file__).resolve().parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.config import get_settings

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

API_BASE = os.getenv("CORPUS_API_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "")


def _get_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    return headers


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    welcome_text = (
        f"Hi {user.first_name if user else 'there'}!\n\n"
        "Welcome to *Corpus* — your Agentic Research Paper Curator.\n"
        "You can ask me questions about the research papers in the corpus, and "
        "I will answer with grounded claims and working links back to the papers.\n\n"
        "Available commands:\n"
        "/ask <your question> — Ask the agent a research question.\n"
        "/recent — List the 5 most recently indexed papers.\n"
        "/help — Get help using the bot."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    help_text = (
        "How to use *Corpus* Telegram Bot:\n\n"
        "Type `/ask <query>` to ask a research question.\n"
        "Example: `/ask Compare self-attention vs cross-attention mechanisms`\n\n"
        "Type `/recent` to see recently added papers.\n\n"
        "All answers are grounded and verified against cited source chunks."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Call the backend `/ask-agentic` API and return response to the user."""
    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text(
            "Please provide a question. Example: `/ask What are neural scaling laws?`", parse_mode="Markdown"
        )
        return

    chat_id = update.effective_chat.id if update.effective_chat else "unknown"
    status_msg = await update.message.reply_text("Thinking... 🔍", parse_mode="Markdown")

    payload = {
        "query": query,
        "session_id": f"telegram_{chat_id}",
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{API_BASE}/api/v1/ask-agentic",
                json=payload,
                headers=_get_headers(),
            )

        if resp.status_code == 200:
            data = resp.json()
            answer = data.get("answer_markdown", "")
            citations = data.get("citations", [])
            grounding_note = data.get("grounding_note", "")

            # Format answer and append citations as links
            formatted_answer = answer

            # Simple conversion of [N] to hyperlinked [N](url) in telegram
            import re

            for c in citations:
                cid = c.get("id")
                pdf_url = c.get("pdf_url")
                if pdf_url:
                    # Escape title characters for telegram markdown v2 if necessary, but v1 is simpler
                    # Let's use standard Markdown
                    formatted_answer = re.sub(rf"\[({cid})\]", f"[[\\1]]({pdf_url})", formatted_answer)

            if citations:
                formatted_answer += "\n\n*Sources:*\n"
                for c in citations:
                    title, section = c.get("paper_title"), c.get("section")
                    formatted_answer += f"• [{c.get('id')}] [{title}]({c.get('pdf_url')}) (Section: {section})\n"

            if grounding_note:
                formatted_answer += f"\n\n_{grounding_note}_"

            await status_msg.edit_text(formatted_answer, parse_mode="Markdown", disable_web_page_preview=True)
        else:
            await status_msg.edit_text(f"API Error ({resp.status_code}): {resp.text[:200]}")

    except Exception as e:
        logger.error(f"Error calling ask API: {e}")
        await status_msg.edit_text(f"Failed to get response: {str(e)}")


async def recent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetch recent papers list from the API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{API_BASE}/api/v1/papers?page=1&per_page=5",
                headers=_get_headers(),
            )

        if resp.status_code == 200:
            data = resp.json()
            papers = data.get("papers", [])
            if not papers:
                await update.message.reply_text("No papers indexed yet.")
                return

            text = "*Recently Indexed Papers:*\n\n"
            for p in papers:
                title = p.get("title")
                arxiv_id = p.get("arxiv_id")
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
                text += f"• *{title}* (arXiv: [{arxiv_id}]({pdf_url}))\n"

            await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)
        else:
            await update.message.reply_text(f"API Error ({resp.status_code})")
    except Exception as e:
        logger.error(f"Error fetching recent papers: {e}")
        await update.message.reply_text(f"Failed to fetch recent papers: {str(e)}")


def main() -> None:
    """Start the bot."""
    settings = get_settings()

    token = settings.telegram.bot_token
    if not token or "your_telegram_bot_token" in token:
        logger.error("TELEGRAM__BOT_TOKEN is not configured. Exiting.")
        return

    if not settings.telegram.enabled:
        logger.info("Telegram bot is disabled in configuration. Exiting.")
        return

    # Build application
    application = Application.builder().token(token).build()

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("ask", ask))
    application.add_handler(CommandHandler("recent", recent))

    # Run the bot
    logger.info("Starting Telegram Bot poll loop...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
