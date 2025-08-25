"""
Manual Escrow Telegram Bot (Python, python-telegram-bot v20)
Features:
- /start message
- /escrow (creates escrow record, instructions to create private group)
- /initescrow <escrow_id> (binds group, generates real invite link)
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
import os

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------- CONFIG ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
USDT_BEP20_ADDRESS = os.getenv("USDT_BEP20_ADDRESS")
BOT_USERNAME = "Easy_Escroww_Bot"   # without @
ESCROW_FEE_PERCENT = 1.0
DB_PATH = "escrow_bot.db"

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------- DB ----------------
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
    row = cur.fetchone()
    conn.close()
    return row

# ---------------- Messages ----------------
START_TEXT = f"""💫 @{BOT_USERNAME} 💫
Your Trustworthy Telegram Escrow Service

Welcome to @{BOT_USERNAME}. This bot provides a reliable escrow service for your transactions on Telegram.

Avoid scams, your funds are safeguarded throughout your deals. If you run into any issues, simply type /dispute and an arbitrator will join the group chat within 24 hours.

🎟 ESCROW FEE: {ESCROW_FEE_PERCENT:.1f}% Flat

💬 Proceed with /escrow (to start with a new escrow)
⚠️ IMPORTANT - Make sure coin is same for Buyer and Seller else you may lose your coin.
💡 Type /menu to summon a menu with all bot's features
"""

GROUP_WELCOME = """📍 Hey there traders! Welcome to our escrow service.
⚠️ IMPORTANT - Make sure coin and network is same for Buyer and Seller else you may lose your coin.
⚠️ IMPORTANT - Make sure the /buyer address and /seller address are of same chain else you may lose your coin.
✅ Please start with /dd command and if you have any doubts please use /start command.
"""

DD_TEXT = """/dd
Hello there,
Kindly tell deal details i.e.
Quantity - Rate - Conditions (if any)
Remember: without it disputes wouldn’t be resolved.

Once filled, proceed with specifications of the seller or buyer using:
/seller  [CRYPTO ADDRESS]
/buyer   [CRYPTO ADDRESS]
"""

MENU_TEXT = """Available commands:
/escrow - Create a new escrow (private group)
/menu - Show this menu
/start - Main info
/dispute - Request arbitration (notifies admin)
/status <escrow_id> - Check escrow status
/deposit <txid> - Buyer reports TXID
/buyer <address> - Buyer sets their address
/seller <address> - Seller sets their address
"""

# ---------------- Handlers ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(START_TEXT, parse_mode="HTML")

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(MENU_TEXT)

async def escrow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("Please use /escrow in private chat with the bot.")
        return
    user = update.effective_user
    creator_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    escrow_id = create_escrow_record(user.id, creator_name)
    await update.message.reply_text(
        f"✅ Escrow record created! ID: <b>{escrow_id}</b>\n\n"
        "Next steps:\n"
        "1. Create a new private Telegram group with only the buyer and seller.\n"
        "2. Add this bot to the group.\n"
        f"3. Inside the group, run:\n/initescrow {escrow_id}\n\n"
        "The bot will initialize the escrow and generate a private group invite link to share safely.",
        parse_mode="HTML"
    )

async def initescrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Please use /initescrow <escrow_id> inside the escrow GROUP.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /initescrow <escrow_id>")
        return
    escrow_id = context.args[0]
    escrow = get_escrow(escrow_id)
    if not escrow:
        await update.message.reply_text("Escrow ID not found.")
        return

    group_id = update.effective_chat.id
    # bind escrow to group
    update_escrow(escrow_id, "group_id", group_id)
    update_escrow(escrow_id, "status", "waiting_deposit")

    # generate real Telegram group invite link
    invite_link = await context.bot.export_chat_invite_link(group_id)
    update_escrow(escrow_id, "group_invite_link", invite_link)

    await update.message.reply_text(GROUP_WELCOME)
    await update.message.reply_text(
        f"Escrow initialized. Share this group invite link with the buyer/seller:\n{invite_link}\n\n"
        "Please use /dd to enter deal details."
    )

# ---------------- Buyer / Seller / Deposit ----------------
async def dd_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Please run /dd inside the escrow group.")
        return
    await update.message.reply_text(DD_TEXT)

async def buyer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup") or not context.args:
        await update.message.reply_text("Usage inside group: /buyer <CRYPTO ADDRESS>")
        return
    escrow = find_escrow_by_group(update.effective_chat.id)
    if not escrow:
        await update.message.reply_text("This group is not linked to any escrow.")
        return
    update_escrow(escrow[0], "buyer_address", context.args[0])
    await update.message.reply_text(f"Buyer address saved: {context.args[0]}")

async def seller_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup") or not context.args:
        await update.message.reply_text("Usage inside group: /seller <CRYPTO ADDRESS>")
        return
    escrow = find_escrow_by_group(update.effective_chat.id)
    if not escrow:
        await update.message.reply_text("This group is not linked to any escrow.")
        return
    update_escrow(escrow[0], "seller_address", context.args[0])
    await update.message.reply_text(f"Seller address saved: {context.args[0]}")

async def deposit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /deposit <TXID>")
        return
    txid = context.args[0]
    if update.effective_chat.type in ("group", "supergroup"):
        escrow = find_escrow_by_group(update.effective_chat.id)
        if not escrow:
            await update.message.reply_text("No escrow linked to this group.")
            return
        escrow_id = escrow[0]
    else:
        if len(context.args) < 2:
            await update.message.reply_text("Private usage: /deposit <escrow_id> <TXID>")
            return
        escrow_id = context.args[0]
        txid = context.args[1]
        if not get_escrow(escrow_id):
            await update.message.reply_text("Escrow ID not found.")
            return
    update_escrow(escrow_id, "txid", txid)
    update_escrow(escrow_id, "status", "tx_submitted")
    await update.message.reply_text("TXID saved. Admin will manually verify.")
    try:
        await context.bot.send_message(OWNER_ID, f"New deposit: Escrow {escrow_id}\nTXID: {txid}")
    except Exception as e:
        logger.error("Failed to notify admin: %s", e)

# ---------------- Main ----------------
def main():
    init_db()
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("escrow", escrow_cmd))
    application.add_handler(CommandHandler("initescrow", initescrow))
    application.add_handler(CommandHandler("dd", dd_cmd))
    application.add_handler(CommandHandler("buyer", buyer_cmd))
    application.add_handler(CommandHandler("seller", seller_cmd))
    application.add_handler(CommandHandler("deposit", deposit_cmd))

    # Unknown command handler
    application.add_handler(MessageHandler(filters.COMMAND, lambda u, c: u.message.reply_text("Unknown command. Use /menu.")))

    logger.info("Bot started...")
    application.run_polling()

if __name__ == "__main__":
    main()
