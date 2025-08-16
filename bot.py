import os
import sqlite3
import asyncio
import time
import random
import json
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions, Poll
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    PollAnswerHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from datetime import datetime, timedelta
from telegram.constants import ChatMemberStatus
from PIL import Image, ImageDraw

# --- Config ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DB_NAME = "group_bot.db"  # Make sure to use this consistently
SPAM_TRIGGERS = [
    "http://", "https://", "t.me/", ".com",
    "badword", "spam", "advertise",
    "earn money", "make money fast",
    "bit.ly", "goo.gl"
]
QUESTIONS = [
    {
        "question": "Would you rather...\nA) Have unlimited battery but no internet\nB) Have unlimited internet but 1 hour battery?",
        "options": ["Option A", "Option B", "Skip"],
        "correct": random.randint(0, 1)
    },
    {
        "question": "Would you rather...\nA) Always say what you're thinking\nB) Never speak again?",
        "options": ["Option A", "Option B", "Skip"],
        "correct": random.randint(0, 1)
    }
]

# Help message constant
HELP_MESSAGE = """
🛠️ *Commands*:
/start - Show the bot introduction
/help - Show this message
/rules - Show group rules
/games - Show available games
/faq <question> - Get an answer

⚡ *Admin Commands*:
/setrules <text> - Set group rules
/addfaq <question> | <answer> - Add FAQ
/ban <user_id> - Ban a user
/kick <user_id> - Kick a user
/mute <user_id> [duration] - Mute a user
/unmute <user_id> - Unmute a user
/warn <user_id> - Warn a user
/userinfo @username - Get user information
/antispam - Toggle anti-spam system
/kickall - Kick all non-admin members (with confirmation)

*Game Commands*:
/truthordare - Start game
/meme - Share memes
/joke  - Tell jokes
/wcg
"""

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect(DB_NAME)  # FIXED: Use DB_NAME once
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tracked_groups (
            group_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            owner_id INTEGER NOT NULL,
            date_added TEXT NOT NULL,
            member_count INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS group_features (
            group_id INTEGER,
            feature TEXT NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            PRIMARY KEY (group_id, feature),
            FOREIGN KEY (group_id) REFERENCES tracked_groups(group_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS faqs (
            chat_id INTEGER,
            question TEXT,
            answer TEXT,
            PRIMARY KEY (chat_id, question)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS anti_spam_settings (
            group_id INTEGER PRIMARY KEY,
            is_active BOOLEAN DEFAULT 1,
            ban_instead_of_delete BOOLEAN DEFAULT 1,
            max_warnings INTEGER DEFAULT 3
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS group_rules (
            chat_id INTEGER PRIMARY KEY,
            rules_text TEXT
        )
    """)

    cursor.execute("""
        INSERT OR IGNORE INTO group_features (group_id, feature, is_active)
        VALUES 
            (0, 'welcome_message', 1),
            (0, 'anti_spam', 1),
            (0, 'mute_new_members', 0)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            wins INTEGER DEFAULT 0,
            games_played INTEGER DEFAULT 0,
            last_played TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS games (
            poll_id TEXT PRIMARY KEY,
            chat_id INTEGER,
            question TEXT,
            correct_option INTEGER,
            participants TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def track_new_group(chat_id: int, title: str, owner_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT 1 FROM tracked_groups WHERE group_id = ?", (chat_id,))
        exists = cursor.fetchone()

        if exists:
            cursor.execute("""
                UPDATE tracked_groups 
                SET title = ?, owner_id = ?, date_added = ?
                WHERE group_id = ?
            """, (title, owner_id, datetime.now().isoformat(), chat_id))
        else:
            cursor.execute("""
                INSERT INTO tracked_groups 
                (group_id, title, owner_id, date_added) 
                VALUES (?, ?, ?, ?)
            """, (chat_id, title, owner_id, datetime.now().isoformat()))

            # Insert default features from group_id = 0 template
            cursor.execute("""
                INSERT INTO group_features (group_id, feature, is_active)
                SELECT ?, feature, is_active FROM group_features WHERE group_id = 0
            """, (chat_id,))

        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error in track_new_group: {e}")
    finally:
        conn.close()

def get_group_features(group_id: int) -> dict:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT feature, is_active FROM group_features WHERE group_id = ?
    """, (group_id,))
    features = {row[0]: bool(row[1]) for row in cursor.fetchall()}
    conn.close()
    return features

# --- Helper Functions ---
async def is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int = None) -> bool:
    if not update.effective_chat:
        return False

    user_id = user_id or update.effective_user.id
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
        return member.status in ["administrator", "creator"]
    except Exception:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        track_new_group(
            update.effective_chat.id,
            update.effective_chat.title,
            update.effective_user.id
        )

    welcome_msg = """
    👋 *Hi, I'm your Group Helper Bot!*

    *Main Commands:*
    /help - Show all commands
    /rules - Group rules
    /games - Fun games

    Need help?"""

    keyboard = [
        [InlineKeyboardButton("➕ Add to Group",
                            url="https://t.me/grphelper_bot?startgroup=true")],
        [InlineKeyboardButton("🆘 Support", url="https://t.me/dax_channel01")]
    ]

    try:
        await update.message.reply_text(
            welcome_msg,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"Error sending start message: {e}")
        await update.message.reply_text(
            "👋 Hi! I'm your Group Helper Bot!\nUse /help for commands.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# HELP_MESSAGE already defined above

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_MESSAGE, parse_mode="Markdown")

# --- Merged button_handler to fix duplicate ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    try:
        await query.answer()

        if query.data == "help_commands":
            await query.edit_message_text(
                HELP_MESSAGE,
                parse_mode="Markdown"
            )

        elif query.data == "show_games":
            await show_games_menu(update, context)

        elif query.data == "back_to_main":
            await start(update, context)

        elif query.data.startswith("toggle_"):
            await toggle_feature(update, context)

        else:
            await query.edit_message_text("❌ Unknown command")

    except Exception as e:
        await query.answer("⚠️ Error: Please try again")
        print(f"Button handler error: {e}")

async def toggle_feature(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle feature toggle callbacks"""

    query = update.callback_query
    await query.answer()

    if not await is_group_admin(update, context):
        await query.edit_message_text("🚫 Admin only!")
        return

    # FIXED: Updated parsing format - expected "toggle_<feature>_<groupid>"
    parts = query.data.split("_", 2)
    if len(parts) != 3:
        await query.edit_message_text("❌ Invalid toggle command format.")
        return

    _, feature, group_id_str = parts
    try:
        group_id = int(group_id_str)
    except ValueError:
        await query.edit_message_text("❌ Invalid group ID.")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE group_features
        SET is_active = NOT is_active
        WHERE group_id = ? AND feature = ?
    """, (group_id, feature))
    conn.commit()
    conn.close()

    # Refresh menu after toggling
    await button_handler(update, context)

async def games_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Truth or Dare", callback_data="game_truthordare")],
        [InlineKeyboardButton("Meme Battle", callback_data="game_memebattle")],
        [InlineKeyboardButton("Back", callback_data="back_to_main")]
    ]

    await update.message.reply_text(
        "🎮 *Available Games*\nSelect one:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_games_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    game_keyboard = [
        [InlineKeyboardButton("Truth or Dare", switch_inline_query_current_chat="/truthordare ")],
        [InlineKeyboardButton("Meme Battle", switch_inline_query_current_chat="/meme ")],
        [InlineKeyboardButton("Joke Contest", switch_inline_query_current_chat="/joke ")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
    ]

    await query.edit_message_text(
        text="🎮 *Select a Game*\n\nYou'll need to tag someone to play!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(game_keyboard)
    )

async def truth_or_dare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Please tag someone: /truthordare @username")
        return

    questions = [
        "Truth: What's your most embarrassing moment?",
        "Dare: Send a voice message singing for 30 seconds!"
    ]
    await update.message.reply_text(random.choice(questions))

async def start_wcg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /wcg @user1 @user2")
        return

    participants = {
        "ids": [update.effective_user.id],
        "names": [update.effective_user.first_name]
    }

    for entity in update.message.entities:
        if entity.type == "mention":
            mention_text = update.message.text[entity.offset:entity.offset+entity.length]

            try:
                # Note: This may fail if username is not accessible; common limitation.
                member = await context.bot.get_chat_member(
                    update.effective_chat.id,
                    mention_text[1:]  # Remove @ symbol
                )
                participants["ids"].append(member.user.id)
                participants["names"].append(member.user.first_name)
            except Exception as e:
                print(f"Error processing mention {mention_text}: {e}")
                continue

    if len(participants["ids"]) < 2:
        await update.message.reply_text(
            "❌ Need at least 2 players! Make sure you mentioned valid users.\n"
            "Example: /wcg @username1 @username2"
        )
        return

    question = random.choice(QUESTIONS)
    poll = await context.bot.send_poll(
        chat_id=update.effective_chat.id,
        question=question["question"],
        options=question["options"],
        is_anonymous=False,
        allows_multiple_answers=False,
        correct_option_id=question["correct"],
        explanation="See results with /wcg_results"
    )

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO games VALUES (?, ?, ?, ?, ?, ?)""",
        (
            poll.poll.id,
            update.effective_chat.id,
            question["question"],
            question["correct"],
            json.dumps(participants),
            datetime.now().isoformat()
        )
    )
    conn.commit()
    conn.close()

async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_answer = update.poll_answer
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM games WHERE poll_id = ?", (poll_answer.poll_id,))
    game = cursor.fetchone()

    if game:
        cursor.execute(
            """INSERT OR IGNORE INTO players 
            (user_id, username, last_played) 
            VALUES (?, ?, ?)""",
            (
                poll_answer.user.id,
                poll_answer.user.username or str(poll_answer.user.id),
                datetime.now().isoformat()
            )
        )
        cursor.execute(
            """UPDATE players 
            SET games_played = games_played + 1 
            WHERE user_id = ?""",
            (poll_answer.user.id,)
        )
        conn.commit()
    conn.close()

async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """SELECT * FROM games 
        WHERE chat_id = ? 
        ORDER BY created_at DESC LIMIT 1""",
        (update.effective_chat.id,)
    )
    game = cursor.fetchone()

    if not game:
        await update.message.reply_text("No recent game found!")
        conn.close()
        return

    poll_id, chat_id, question, correct_option, participants, created_at = game
    participants = json.loads(participants)

    try:
        poll = await context.bot.stop_poll(chat_id, poll_id)
    except Exception:
        await update.message.reply_text("Couldn't retrieve poll results")
        conn.close()
        return

    # Note: `poll.options` does not expose voter user IDs in the library.
    # To find winners, you'd need to track votes yourself in `handle_vote`.

    # Here, just announce correct answer and no names (privacy limitation).
    result_msg = (
        f"🏆 *WCG Results* 🏆\n\n"
        f"Question: {question}\n"
        f"Correct answer: {poll.options[correct_option].text}\n\n"
        "Winners tracking unavailable due to Telegram API limitations."
    )

    await update.message.reply_text(result_msg, parse_mode="Markdown")
    conn.close()

async def logo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Grab user text after /logo command
    description = ' '.join(context.args) if context.args else "default"

    # For demo: just change circle color based on description text length
    color = "#0088cc" if len(description) % 2 == 0 else "#00aaff"
    size = 256

    # Create a Telegram-style logo (circle + paper plane polygon)
    img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([(0, 0), (size, size)], fill=color)

    # Paper plane shape
    plane_points = [
        (size // 2, size // 4),
        (size // 4, size * 3 // 4),
        (size // 2, size // 2),
        (size * 3 // 4, size * 3 // 4)
    ]
    draw.polygon(plane_points, fill="white")

    # Save image to buffer
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    # Send image with caption
    await update.message.reply_photo(photo=buf, caption=f"Logo generated for: {description}")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """SELECT username, wins, games_played 
        FROM players 
        ORDER BY wins DESC 
        LIMIT 10"""
    )
    top_players = cursor.fetchall()

    if not top_players:
        await update.message.reply_text("No players yet!")
        conn.close()
        return

    leaderboard_msg = "🏆 *WCG Leaderboard* 🏆\n\n"
    for i, (username, wins, games) in enumerate(top_players, 1):
        win_rate = (wins/games)*100 if games > 0 else 0
        leaderboard_msg += (
            f"{i}. {username}: {wins} wins ({win_rate:.1f}% win rate)\n"
        )

    await update.message.reply_text(leaderboard_msg, parse_mode="Markdown")
    conn.close()


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
    if update.effective_chat.type == "private":
        return
    
    # Get group settings
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT is_active, ban_instead_of_delete 
        FROM anti_spam_settings 
        WHERE group_id = ?
    """, (update.effective_chat.id,))
    
    settings = cursor.fetchone()
    conn.close()
    
    # Skip if anti-spam is disabled
    if not settings or not settings[0]:
        return
    
    # Check for spam triggers
    message_text = update.message.text.lower() if update.message.text else ""
    is_spam = any(trigger in message_text for trigger in SPAM_TRIGGERS)
    
    if is_spam:
        try:
            await update.message.delete()
            
            if settings[1]:  # ban_instead_of_delete
                await context.bot.ban_chat_member(
                    chat_id=update.effective_chat.id,
                    user_id=update.effective_user.id
                )
                action = "banned"
            else:
                action = "message deleted"
                
            admin_notice = (
                f"🚨 Anti-Spam Action:\n"
                f"User: {update.effective_user.mention_markdown()}\n"
                f"Action: {action}\n"
                f"Content: {message_text[:100]}..."
            )
            
            # Send notice to admins (optional)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=admin_notice,
                parse_mode="Markdown"
            )
            
        except Exception as e:
            print(f"Anti-spam error: {e}")

async def toggle_antispam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_group_admin(update, context):
        await update.message.reply_text("🚫 Admin only!")
        return
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Toggle the setting
    cursor.execute("""
        INSERT OR REPLACE INTO anti_spam_settings 
        (group_id, is_active) 
        VALUES (?, COALESCE((SELECT NOT is_active FROM anti_spam_settings WHERE group_id = ?), 1))
    """, (update.effective_chat.id, update.effective_chat.id))
    
    conn.commit()
    
    # Get new status
    cursor.execute("""
        SELECT is_active FROM anti_spam_settings WHERE group_id = ?
    """, (update.effective_chat.id,))
    is_active = cursor.fetchone()[0]
    conn.close()
    
    status = "✅ enabled" if is_active else "❌ disabled"
    await update.message.reply_text(f"Anti-spam is now {status}")

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

async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kick a single user"""
    if not await is_group_admin(update, context):
        await update.message.reply_text("🚫 Admin only!")
        return

    try:
        user_id = int(context.args[0])
        await context.bot.ban_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            until_date=int(time.time()) + 60  # Ban for 60 seconds (effectively a kick)
        )
        await update.message.reply_text(f"👢 Kicked user: `{user_id}`", parse_mode="Markdown")
    except (IndexError, ValueError):
        await update.message.reply_text("ℹ️ Usage: /kick <user_id>")

# --- Main ---
if __name__ == "__main__":
    init_db()
    
    app = ApplicationBuilder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("rules", show_rules))
    app.add_handler(CommandHandler("setrules", set_rules))
    app.add_handler(CommandHandler("addfaq", add_faq))
    app.add_handler(CommandHandler("faq", get_faq))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("warn", warn_user))
    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("mute", mute_user))
    app.add_handler(CommandHandler("unmute", unmute_user))
    app.add_handler(CommandHandler("antispam", toggle_antispam))
    app.add_handler(CommandHandler("kick", kick_user))
    app.add_handler(CommandHandler("truthordare", truth_or_dare))
    app.add_handler(CommandHandler("meme", ...))
    app.add_handler(CommandHandler("games", games_command))  # Make sure this exists
    app.add_handler(CommandHandler("wcg", start_wcg))
    app.add_handler(CommandHandler("wcg_results", show_results))
    app.add_handler(CommandHandler("wcg_leaderboard", leaderboard))
    application.add_handler(CommandHandler("logo", logo_command))
    
    app.add_handler(PollAnswerHandler(handle_vote))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, anti_spam))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CallbackQueryHandler(toggle_feature, pattern="^toggle_"))
    

    print("Bot is running...")
    app.run_polling()
