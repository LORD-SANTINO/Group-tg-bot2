import os
import sqlite3
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# --- Setup ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_IDS = [123456789]  # Replace with your Telegram user ID
SPAM_TRIGGERS = ["badword", "http://", "https://"]  # Spam triggers
DB_NAME = "faqs.db"

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS faqs (
            question TEXT PRIMARY KEY,
            answer TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- Admin Check ---
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# --- Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome! Use /help for commands.")

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    commands = """
    📖 Commands:
    /help - Show this
    /faq <topic> - Get an FAQ
    /rules - Group rules
    """
    if is_admin(update.effective_user.id):
        commands += """
    ⚡ Admin:
    /ban <user_id> - Ban a user
    /addfaq <question> | <answer> - Add FAQ
    """
    await update.message.reply_text(commands)

# --- FAQ Database ---
async def add_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Admin only!")
        return

    args = update.message.text.split(" | ")
    if len(args) != 2:
        await update.message.reply_text("Usage: /addfaq question | answer")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO faqs VALUES (?, ?)", (args[0].strip(), args[1].strip()))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ FAQ added!")

async def get_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = " ".join(context.args)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT answer FROM faqs WHERE question=?", (question,))
    result = cursor.fetchone()
    conn.close()

    if result:
        await update.message.reply_text(result[0])
    else:
        await update.message.reply_text("❌ FAQ not found.")

# --- Anti-Spam ---
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Admin only!")
        return

    user_id = int(context.args[0]) if context.args else None
    if user_id:
        await context.bot.ban_chat_member(update.effective_chat.id, user_id)
        await update.message.reply_text(f"🔨 Banned user {user_id}")
    else:
        await update.message.reply_text("Usage: /ban <user_id>")

async def anti_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if any(trigger in update.message.text.lower() for trigger in SPAM_TRIGGERS):
        await update.message.delete()
        await context.bot.ban_chat_member(
            update.effective_chat.id,
            update.effective_user.id
        )
        await update.message.reply_text(f"🚨 Banned {update.effective_user.name} for spam.")

# --- Main ---
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help))
    app.add_handler(CommandHandler("addfaq", add_faq))
    app.add_handler(CommandHandler("faq", get_faq))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), anti_spam))

    print("Bot is running...")
    app.run_polling()
