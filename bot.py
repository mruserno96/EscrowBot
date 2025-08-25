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
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    level=logging.INFO)
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
    )""")
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
    sql = f"UPDATE escrows SET {field} = ? WHERE id = ?"
    cur.execute(sql, (value, escrow_id))
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

💬 Proceed with /escrow to start a new escrow group.

💡 Type /menu to see all bot features
"""

ESCROW_CREATED_TEXT = """Creating a safe trading place for you... please wait...
Escrow Group Created

Creator: {creator}

Click this link to create your private escrow group with the bot:
{invite_link}
"""

GROUP_WELCOME = """📍 Hey there traders! Welcome to our escrow service.
⚠️ IMPORTANT - Make sure coin and network is same for Buyer and Seller.
✅ Start with /dd command and follow instructions.
"""

DD_TEXT = """/dd
Please provide deal details:
Quantity - Rate - Conditions (if any)
Then set addresses using:
/seller <CRYPTO ADDRESS>
/buyer <CRYPTO ADDRESS>
"""

MENU_TEXT = """Available commands:
/escrow - Start new escrow
/menu - Show this menu
/start - Main info
/dispute - Request arbitration
/status <escrow_id> - Check escrow status
/deposit <txid> - Report TXID
/buyer <address> - Set buyer address
/seller <address> - Set seller address
/address - Show deposit address
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
    text = ESCROW_CREATED_TEXT.format(creator=creator_name, invite_link=deep_link)
    await update.message.reply_text(text)

async def initescrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # used in group after bot is added
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Use /initescrow inside a group where bot was added.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /initescrow <escrow_id>")
        return
    escrow_id = args[0]
    escrow = get_escrow(escrow_id)
    if not escrow:
        await update.message.reply_text("Escrow ID not found.")
        return
    group_id = update.effective_chat.id
    link = await context.bot.export_chat_invite_link(group_id)
    update_escrow(escrow_id, "group_id", group_id)
    update_escrow(escrow_id, "group_invite_link", link)
    update_escrow(escrow_id, "status", "waiting_deposit")
    await update.message.reply_text(GROUP_WELCOME)
    await update.message.reply_text(f"Escrow initialized. Group invite link: {link}")

async def dd_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Run /dd inside the escrow group.")
        return
    await update.message.reply_text(DD_TEXT)

# ---------------- Main ----------------
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("escrow", escrow_cmd))
    app.add_handler(CommandHandler("initescrow", initescrow))
    app.add_handler(CommandHandler("dd", dd_cmd))

    logger.info("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
