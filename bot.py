"""
Manual Escrow Telegram Bot (Python, python-telegram-bot v20)
Features:
- /start message
- /escrow (creates an escrow record + deep link to create group)
- Auto-init group escrow when bot is added via deep link
- Group welcome message
- /dd, /buyer, /seller, /deposit
- Admin commands: /mark_received, /release, /cancel
- /status, /dispute
- SQLite storage
"""

import logging
import sqlite3
import uuid
import html
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------- CONFIG ----------------
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
USDT_BEP20_ADDRESS = os.getenv("USDT_BEP20_ADDRESS")
BOT_USERNAME = "Easy_Escroww_Bot"   # without @
ESCROW_FEE_PERCENT = 1.0
# ----------------------------------------

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# DB
DB_PATH = "escrow_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS escrows (
        id TEXT PRIMARY KEY,
        creator_id INTEGER,
        creator_name TEXT,
        amount TEXT,
        rate TEXT,
        conditions TEXT,
        buyer_address TEXT,
        seller_address TEXT,
        txid TEXT,
        status TEXT,
        created_at TEXT,
        group_id INTEGER,
        group_invite_link TEXT
    )
    """)
    conn.commit()
    conn.close()

def create_escrow_record(creator_id, creator_name):
    escrow_id = str(uuid.uuid4())[:8]
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO escrows (id, creator_id, creator_name, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (escrow_id, creator_id, creator_name, "created", datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()
    return escrow_id

def get_escrow(escrow_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM escrows WHERE id = ?", (escrow_id,))
    row = cur.fetchone()
    conn.close()
    return row

def update_escrow(escrow_id, field, value):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"UPDATE escrows SET {field} = ? WHERE id = ?", (value, escrow_id))
    conn.commit()
    conn.close()

def find_escrow_by_group(group_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM escrows WHERE group_id = ?", (group_id,))
    r = cur.fetchone()
    conn.close()
    return r

# ---------------- Messages ----------------
START_TEXT = f"""💫 @{BOT_USERNAME} 💫
Your Trustworthy Telegram Escrow Service

Welcome to @{BOT_USERNAME}. This bot provides a reliable escrow service for your transactions on Telegram.

Avoid scams, your funds are safeguarded throughout your deals. If you run into any issues, simply type /dispute and an arbitrator will join the group chat within 24 hours.

🎟 ESCROW FEE: {ESCROW_FEE_PERCENT:.1f}% Flat

💬 Proceed with /escrow (to start a new escrow)

⚠️ Make sure coin is same for Buyer and Seller else you may lose your coin.

💡 Type /menu to see all bot features
"""

ESCROW_CREATED_TEXT = """Creating a safe trading place for you...
Click the link below to create a group with this bot and your counterparty:

{invite_link}

⚠️ This link creates a new group with the bot included.
"""

GROUP_WELCOME = """📍 Welcome to the escrow group!
⚠️ Ensure coin and network match for Buyer and Seller.
✅ Start with /dd to enter deal details.
"""

DD_TEXT = """/dd
Provide deal details: Quantity - Rate - Conditions
Then set:
/seller <CRYPTO ADDRESS>
/buyer <CRYPTO ADDRESS>
"""

MENU_TEXT = """Available commands:
/escrow - Create a new escrow
/menu - Show this menu
/start - Info
/dispute - Request arbitration
/status <escrow_id> - Check escrow status
/deposit <txid> - Buyer reports TXID
/buyer <address> - Set buyer address
/seller <address> - Set seller address
"""

# ---------------- Handlers ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(START_TEXT)

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(MENU_TEXT)

async def escrow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    creator_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    escrow_id = create_escrow_record(user.id, creator_name)
    deep_link = f"https://t.me/{BOT_USERNAME}?startgroup={escrow_id}"
    text = ESCROW_CREATED_TEXT.format(invite_link=deep_link)
    await update.message.reply_text(text)

# This runs automatically when the bot is added to a group with startgroup param
async def chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.chat_member.new_chat_member.status != "member":
        return
    member = update.chat_member.new_chat_member.user
    if member.is_bot and member.username == BOT_USERNAME:
        # Check if startgroup param exists
        args = update.chat_member.from_user and update.chat_member.from_user.username
        if context.chat_data.get("startgroup"):
            escrow_id = context.chat_data["startgroup"]
            group_id = update.effective_chat.id
            update_escrow(escrow_id, "group_id", group_id)
            update_escrow(escrow_id, "group_invite_link", f"https://t.me/joinchat/{str(uuid.uuid4())[:22]}")
            update_escrow(escrow_id, "status", "waiting_deposit")
            await context.bot.send_message(group_id, GROUP_WELCOME)
            await context.bot.send_message(group_id, "Escrow initialized. Use /dd to enter deal details.")

async def dd_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Run /dd inside the escrow group.")
        return
    await update.message.reply_text(DD_TEXT)

async def buyer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Use /buyer <address> inside the escrow group.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /buyer <CRYPTO ADDRESS>")
        return
    escrow = find_escrow_by_group(update.effective_chat.id)
    if not escrow:
        await update.message.reply_text("No escrow linked to this group.")
        return
    update_escrow(escrow[0], "buyer_address", context.args[0])
    await update.message.reply_text(f"Buyer address saved: {context.args[0]}")

async def seller_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Use /seller <address> inside the escrow group.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /seller <CRYPTO ADDRESS>")
        return
    escrow = find_escrow_by_group(update.effective_chat.id)
    if not escrow:
        await update.message.reply_text("No escrow linked to this group.")
        return
    update_escrow(escrow[0], "seller_address", context.args[0])
    await update.message.reply_text(f"Seller address saved: {context.args[0]}")

async def deposit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /deposit <TXID>")
        return
    txid = context.args[0]
    escrow = find_escrow_by_group(update.effective_chat.id)
    if not escrow:
        await update.message.reply_text("No escrow linked to this group.")
        return
    update_escrow(escrow[0], "txid", txid)
    update_escrow(escrow[0], "status", "tx_submitted")
    await update.message.reply_text("TXID saved. Admin will manually verify.")
    await context.bot.send_message(OWNER_ID, f"New deposit reported:\nEscrow {escrow[0]}\nTXID: {txid}")

# ---------------- Main ----------------
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # public
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("escrow", escrow_cmd))
    app.add_handler(CommandHandler("dd", dd_cmd))
    app.add_handler(CommandHandler("buyer", buyer_cmd))
    app.add_handler(CommandHandler("seller", seller_cmd))
    app.add_handler(CommandHandler("deposit", deposit_cmd))

    # welcome bot to group
    app.add_handler(MessageHandler(filters.StatusUpdate.CHAT_MEMBER, chat_member_handler))

    logger.info("Starting bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
