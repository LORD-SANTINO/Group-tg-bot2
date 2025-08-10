import os
import sqlite3
from telegram import Update
from telegram.ext import CallbackQueryHandler
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# --- Config ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DB_NAME = "group_bot.db"
SPAM_TRIGGERS = ["badword", "http://", "spam.com"]  # Customize this list

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Group tracking table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tracked_groups (
            group_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            owner_id INTEGER NOT NULL,
            date_added TEXT NOT NULL,
            member_count INTEGER DEFAULT 0
        )
    """)
    
    # Group features table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS group_features (
            group_id INTEGER,
            feature TEXT NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            PRIMARY KEY (group_id, feature),
            FOREIGN KEY (group_id) REFERENCES tracked_groups(group_id)
        )
    """)
    
    # FAQs table (keep your existing but fixed syntax)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS faqs (
            chat_id INTEGER,
            question TEXT,
            answer TEXT,
            PRIMARY KEY (chat_id, question)
        )
    """)
    
    # Group rules table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS group_rules (
            chat_id INTEGER PRIMARY KEY,
            rules_text TEXT
        )
    """)
    
    # Insert default features if not exists
    cursor.execute("""
        INSERT OR IGNORE INTO group_features (group_id, feature, is_active)
        VALUES 
            (0, 'welcome_message', 1),
            (0, 'anti_spam', 1),
            (0, 'mute_new_members', 0)
    """)
    
    conn.commit()
    conn.close()

init_db()

def track_new_group(chat_id: int, title: str, owner_id: int):
    """Record when bot joins a new group"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT OR REPLACE INTO tracked_groups 
        (group_id, title, owner_id, date_added) 
        VALUES (?, ?, ?, ?)
    """, (chat_id, title, owner_id, datetime.now().isoformat()))
    
    # Activate default features
    cursor.execute("""
        INSERT INTO group_features (group_id, feature, is_active)
        SELECT ?, feature, is_active FROM group_features WHERE group_id = 0
    """, (chat_id,))
    
    conn.commit()
    conn.close()

def get_group_features(group_id: int) -> dict:
    """Get all active features for a group"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT feature, is_active FROM group_features WHERE group_id = ?
    """, (group_id,))
    return {row[0]: bool(row[1]) for row in cursor.fetchall()}

# --- Helper Functions ---
async def is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int = None) -> bool:
    """Check if user is a group admin."""
    if not update.effective_chat:
        return False
    
    user_id = user_id or update.effective_user.id
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
        return member.status in ["administrator", "creator"]
    except Exception:
        return False

# --- Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Track group if not private chat
    if update.effective_chat.type != "private":
        track_new_group(
            update.effective_chat.id,
            update.effective_chat.title,
            update.effective_user.id
        )
        
    # Welcome message
    welcome_msg = """
    👋 *Hi, I'm your Group Helper!* 
    I am capable of managing your groups to your standards.
    """

    # Inline buttons
    keyboard = [
        [
            InlineKeyboardButton("➕ Add me to your group", 
                                url="https://t.me/grphelper_bot?startgroup=true")
        ],
        [
            InlineKeyboardButton("📊 My groups", callback_data="my_groups"),
            InlineKeyboardButton("❓ Help", callback_data="help")
        ],
        [
            InlineKeyboardButton("🆘 Support", url="https://t.me/dax_channel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        welcome_msg,
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

# Callback handler for buttons
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "my_groups":
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT group_id, title FROM tracked_groups 
            WHERE owner_id = ?
        """, (query.from_user.id,))
        
        groups = cursor.fetchall()
        conn.close()
        
        if not groups:
            await query.edit_message_text("❌ You haven't added me to any groups yet!")
            return
            
        buttons = [
            [InlineKeyboardButton(
                f"{title} {'✅' if get_group_features(gid)['anti_spam'] else '❌'}",
                callback_data=f"group_{gid}"
            )]
            for gid, title in groups
        ]
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="start_menu")])
        
        await query.edit_message_text(
            f"📊 Your Groups ({len(groups)}):",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    
    elif query.data.startswith("group_"):
        group_id = int(query.data.split("_")[1])
        features = get_group_features(group_id)
        
        buttons = [
            [
                InlineKeyboardButton(
                    f"{'🔴' if features['mute_new_members'] else '🟢'} Mute New",
                    callback_data=f"toggle_mute_{group_id}"
                ),
                InlineKeyboardButton(
                    f"{'🔴' if not features['anti_spam'] else '🟢'} Anti-Spam",
                    callback_data=f"toggle_spam_{group_id}"
                )
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="my_groups")]
        ]
        
        await query.edit_message_text(
            f"⚙️ Settings for Group {group_id}:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    
async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
    🛠️ *Commands*:
    /help - Show this
    /rules - Show group rules
    /faq <question> - Get an answer
    
    ⚡ *Admin Commands*:
    /setrules <text> - Set group rules
    /addfaq <question> | <answer> - Add FAQ
    /ban <user_id> - Ban a user
    /warn <user_id> - Warn a user
    """
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "my_groups":
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT group_id, title FROM tracked_groups 
            WHERE owner_id = ?
        """, (query.from_user.id,))
        
        groups = cursor.fetchall()
        conn.close()
        
        if not groups:
            await query.edit_message_text("❌ You haven't added me to any groups yet!")
            return
            
        buttons = [
            [InlineKeyboardButton(
                f"{title} {'✅' if get_group_features(gid)['anti_spam'] else '❌'}",
                callback_data=f"group_{gid}"
            )]
            for gid, title in groups
        ]
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="start_menu")])
        
        await query.edit_message_text(
            f"📊 Your Groups ({len(groups)}):",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    
    elif query.data.startswith("group_"):
        group_id = int(query.data.split("_")[1])
        features = get_group_features(group_id)
        
        buttons = [
            [
                InlineKeyboardButton(
                    f"{'🔴' if features['mute_new_members'] else '🟢'} Mute New",
                    callback_data=f"toggle_mute_{group_id}"
                ),
                InlineKeyboardButton(
                    f"{'🔴' if not features['anti_spam'] else '🟢'} Anti-Spam",
                    callback_data=f"toggle_spam_{group_id}"
                )
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="my_groups")]
        ]
        
        await query.edit_message_text(
            f"⚙️ Settings for Group {group_id}:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

# --- Rules Management ---
async def set_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_group_admin(update, context):
        await update.message.reply_text("🚫 *Admin only!*", parse_mode="Markdown")
        return

    rules_text = " ".join(context.args)
    if not rules_text:
        await update.message.reply_text("ℹ️ Usage: /setrules <text>")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO group_rules VALUES (?, ?)",
        (update.effective_chat.id, rules_text)
    )
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ *Rules updated!*", parse_mode="Markdown")

async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT rules_text FROM group_rules WHERE chat_id=?",
        (update.effective_chat.id,)
    )
    rules = cursor.fetchone()
    conn.close()
    await update.message.reply_text(
        rules[0] if rules else "📜 No rules set yet. Admins: use /setrules",
        parse_mode="Markdown"
    )

# --- FAQ System ---
async def add_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_group_admin(update, context):
        await update.message.reply_text("🚫 *Admin only!*", parse_mode="Markdown")
        return

    args = update.message.text.split(" | ", 1)
    if len(args) != 2:
        await update.message.reply_text("ℹ️ Usage: /addfaq <question> | <answer>")
        return

    question, answer = args[0].strip(), args[1].strip()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO faqs VALUES (?, ?, ?)",
        (update.effective_chat.id, question, answer)
    )
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ FAQ added: *{question}*", parse_mode="Markdown")

async def get_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = " ".join(context.args)
    if not question:
        await update.message.reply_text("ℹ️ Usage: /faq <question>")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT answer FROM faqs WHERE chat_id=? AND question=?",
        (update.effective_chat.id, question)
    )
    answer = cursor.fetchone()
    conn.close()
    await update.message.reply_text(
        answer[0] if answer else "❌ FAQ not found. Admins: use /addfaq",
        parse_mode="Markdown"
    )

# --- Moderation ---
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_group_admin(update, context):
        await update.message.reply_text("🚫 Admin only!")
        return

    if not context.args:
        await update.message.reply_text("ℹ️ Usage: `/ban <user_id>` or reply to a message with `/ban`", parse_mode="Markdown")
        return

    try:
        user_id = int(context.args[0])
        await context.bot.ban_chat_member(update.effective_chat.id, user_id)
        await update.message.reply_text(f"🔨 Banned user: `{user_id}`", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ Invalid ID. Use `/userinfo @username` to get the ID.")
        
async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_group_admin(update, context):
        await update.message.reply_text("🚫 *Admin only!*", parse_mode="Markdown")
        return

    try:
        user_id = int(context.args[0])
        await update.message.reply_text(f"⚠️ Warned user: {user_id}")
    except (IndexError, ValueError):
        await update.message.reply_text("ℹ️ Usage: /warn <user_id>")

# --- Anti-Spam ---
async def anti_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if any(trigger in update.message.text.lower() for trigger in SPAM_TRIGGERS):
        await update.message.delete()
        await context.bot.ban_chat_member(
            update.effective_chat.id,
            update.effective_user.id
        )
        await update.message.reply_text(
            f"🚨 Banned {update.effective_user.name} for spam."
        )

async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_group_admin(update, context):
        await update.message.reply_text("🚫 Admin only!")
        return

    # Check if user replied to a message or tagged someone
    target_user = None
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    elif context.args:
        try:
            # Extract user ID from mention (e.g., @username)
            mention = context.args[0].strip("@")
            if mention.isdigit():  # Direct ID provided
                target_user = await context.bot.get_chat_member(update.effective_chat.id, int(mention))
                target_user = target_user.user
            else:
                # Search by username (Note: Works only if user has interacted in the group)
                chat_members = await context.bot.get_chat_members(update.effective_chat.id)
                for member in chat_members:
                    if member.user.username and member.user.username.lower() == mention.lower():
                        target_user = member.user
                        break
        except Exception as e:
            print(f"Error fetching user: {e}")

    if not target_user:
        await update.message.reply_text("❌ User not found. Reply to their message or tag them (@username).")
        return

    # Send user details
    response = (
        f"👤 *User Info*\n"
        f"Name: `{target_user.full_name}`\n"
        f"Username: `@{target_user.username}`\n"
        f"ID: `{target_user.id}`\n\n"
        f"⚠️ *Pro Tip*: Use `/ban {target_user.id}`"
    )
    await update.message.reply_text(response, parse_mode="Markdown")

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_group_admin(update, context):
        await update.message.reply_text("🚫 Admin only!")
        return

    try:
        # Parse arguments
        user_id = int(context.args[0])
        duration = None
        
        # Check for duration (e.g., "30m", "2h", "1d")
        if len(context.args) > 1:
            time_unit = context.args[1][-1].lower()
            time_value = int(context.args[1][:-1])
            
            if time_unit == 'm':  # Minutes
                duration = timedelta(minutes=time_value)
            elif time_unit == 'h':  # Hours
                duration = timedelta(hours=time_value)
            elif time_unit == 'd':  # Days
                duration = timedelta(days=time_value)
        
        # Apply mute
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False
        )
        
        until_date = datetime.now() + duration if duration else None
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            permissions=permissions,
            until_date=until_date
        )
        
        # Confirmation message
        if duration:
            await update.message.reply_text(
                f"⏳ Muted user `{user_id}` for {context.args[1]}",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"🔇 Permanently muted user `{user_id}`",
                parse_mode="Markdown"
            )
            
    except (IndexError, ValueError, AttributeError):
        await update.message.reply_text(
            "ℹ️ Usage:\n"
            "• `/mute <user_id>` - Permanent mute\n"
            "• `/mute <user_id> 30m` - 30 minutes\n"
            "• `/mute <user_id> 2h` - 2 hours\n"
            "• `/mute <user_id> 1d` - 1 day",
            parse_mode="Markdown"
        )

async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unmute a user (restore default permissions)"""
    if not await is_group_admin(update, context):
        await update.message.reply_text("🚫 Admin only!")
        return

    try:
        user_id = int(context.args[0])
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
        await update.message.reply_text(f"🔊 Unmuted user: `{user_id}`", parse_mode="Markdown")
    except (IndexError, ValueError):
        await update.message.reply_text("ℹ️ Usage: `/unmute <user_id>` or reply with `/unmute`", parse_mode="Markdown")

# --- Main ---
if __name__ == "__main__":
    init_db()
    
    app = ApplicationBuilder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help))
    app.add_handler(CommandHandler("rules", show_rules))
    app.add_handler(CommandHandler("setrules", set_rules))
    app.add_handler(CommandHandler("addfaq", add_faq))
    app.add_handler(CommandHandler("faq", get_faq))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("warn", warn_user))
    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("mute", mute_user))
    app.add_handler(CommandHandler("unmute", unmute_user))

    # Anti-spam
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, anti_spam))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CallbackQueryHandler(toggle_feature, pattern="^toggle_"))
    

    print("Bot is running...")
    app.run_polling()
