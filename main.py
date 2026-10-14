import os
import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from sports_skills import football

# ---------- Configuration ----------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
POLL_INTERVAL_SECONDS = 120  # Check every 2 minutes

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------- In-memory storage ----------
# In production, replace with a database (e.g., SQLite, PostgreSQL)
subscribed_chats = set()          # chat IDs that want goal alerts
last_scores = {}                  # match_id -> (home_score, away_score)


# ---------- Data Fetching ----------
def fetch_live_matches():
    """Fetch live football matches using sports-skills (no API key)."""
    try:
        # get_daily_schedule returns today's fixtures with live scores if available
        schedule = football.get_daily_schedule()
        matches = schedule.get("data", {}).get("matches", [])
        return matches
    except Exception as e:
        logger.error(f"Error fetching live matches: {e}")
        return []


def format_match(match):
    """Format a single match for display."""
    home = match.get("team1", "Unknown")
    away = match.get("team2", "Unknown")
    score = match.get("score", {})
    ft = score.get("ft")
    ht = score.get("ht")

    if ft:
        score_text = f"{ft[0]} - {ft[1]}"
    elif ht:
        score_text = f"HT: {ht[0]} - {ht[1]}"
    else:
        score_text = "Not started"

    return f"⚽ {home} vs {away} — {score_text}"


# ---------- Command Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message."""
    welcome = (
        "👋 *Welcome to the Football Update Bot!*\n\n"
        "I can give you:\n"
        "• `/today` — Today's fixtures\n"
        "• `/live` — Live scores right now\n"
        "• `/subscribe` — Get goal alerts\n"
        "• `/unsubscribe` — Stop goal alerts\n\n"
        "Use the commands above to stay updated!"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show today's fixtures."""
    matches = fetch_live_matches()
    if not matches:
        await update.message.reply_text("No matches found for today.")
        return

    lines = ["📅 *Today's Fixtures*\n"]
    for m in matches[:20]:  # Limit to 20 to avoid message length issues
        lines.append(format_match(m))

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show live scores."""
    matches = fetch_live_matches()
    live_matches = [
        m for m in matches
        if m.get("score", {}).get("ft") is None and m.get("status") == "inprogress"
    ]

    if not live_matches:
        await update.message.reply_text("No live matches right now.")
        return

    lines = ["🔴 *Live Scores*\n"]
    for m in live_matches:
        lines.append(format_match(m))

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Subscribe the chat to goal alerts."""
    chat_id = update.effective_chat.id
    subscribed_chats.add(chat_id)
    await update.message.reply_text(
        "✅ You are now subscribed to goal alerts!\n"
        "I will notify you when a goal is scored."
    )


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unsubscribe the chat from goal alerts."""
    chat_id = update.effective_chat.id
    subscribed_chats.discard(chat_id)
    await update.message.reply_text("❌ You have been unsubscribed from goal alerts.")


# ---------- Background Job: Goal Detection ----------
async def check_goals(context: ContextTypes.DEFAULT_TYPE):
    """Periodic job that checks for new goals and sends alerts."""
    global last_scores

    matches = fetch_live_matches()
    if not matches:
        return

    for match in matches:
        match_id = match.get("id") or f"{match.get('team1')}_{match.get('team2')}"
        score = match.get("score", {})
        ft = score.get("ft")

        if not ft:
            continue  # Match not started or no score yet

        current = (ft[0], ft[1])
        previous = last_scores.get(match_id)

        if previous is not None and current != previous:
            # Goal detected!
            home = match.get("team1", "Unknown")
            away = match.get("team2", "Unknown")
            goal_msg = (
                f"⚽ *GOAL!*\n"
                f"{home} {current[0]} - {current[1]} {away}\n"
                f"🏟️ {match.get('round', '')}"
            )
            for chat_id in subscribed_chats:
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=goal_msg,
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    logger.error(f"Failed to send goal alert to {chat_id}: {e}")

        last_scores[match_id] = current


# ---------- Main ----------
def main():
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN environment variable is not set!")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("live", live))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))

    # Background job: check for goals every POLL_INTERVAL_SECONDS
    job_queue = app.job_queue
    job_queue.run_repeating(check_goals, interval=POLL_INTERVAL_SECONDS, first=10)

    logger.info("Starting bot with long polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
