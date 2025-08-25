"""
Manual Escrow Telegram Bot (Python, python-telegram-bot v20)
Features:
- /start message
- /escrow (creates escrow record and gives private group invite link)
- /initescrow (auto when bot added, binds group)
- /dd, /buyer, /seller, /deposit, /status, /dispute
- Admin: /mark_received, /release, /cancel
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
BOT_USERNAME = "Easy_Escroww_Bot"
ESCROW_FEE_PERCENT = 1.0
# ---------------------------------------

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

DB_PATH = "escrow_bot.db"

# ---------------- DATABASE ----------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
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
    """
    )
    conn.commit()
    conn.close()


def create_escrow_record(creator_id, creator_name):
    escrow_id = str(uuid.uuid4())[:8]
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO escrows (id, creator_id, creator_name, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (escrow_id, creator_id, creator_name, "created", datetime.utcnow().isoformat()),
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


# ---------------- MESSAGES ----------------
START_TEXT = f"""💫 @{BOT_USERNAME} 💫
Your Trustworthy Telegram Escrow Service

Welcome! This bot provides reliable escrow service for your Telegram transactions.

Avoid scams: your funds are safeguarded throughout your deals. Type /dispute to notify an arbitrator if needed.

🎟 ESCROW FEE: {ESCROW_FEE_PERCENT:.1f}% Flat
💬 Proceed with /escrow to start a new escrow.
"""

ESCROW_CREATED_TEXT = """✅ Escrow record created!

Join the escrow group with this private link:
{invite_link}

⚠️ Note: Only you and the other party should join this group.
"""

GROUP_WELCOME = """📍 Welcome to the escrow service!
⚠️ Make sure buyer and seller use the same coin and network.
✅ Start with /dd to enter deal details.
"""

DD_TEXT = """/dd
Enter deal details:
Quantity - Rate - Conditions (if any)

Then specify addresses:
/buyer [CRYPTO ADDRESS]
/seller [CRYPTO ADDRESS]
"""

MENU_TEXT = """Available commands:
/escrow - Create a new escrow
/menu - Show this menu
/start - Info
/dispute - Request arbitration
/status <escrow_id> - Check status
/deposit <txid> - Report TXID
/buyer <address> - Buyer address
/seller <address> - Seller address
"""


# ---------------- HANDLERS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(START_TEXT)


# Escrow command
async def escrow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    creator_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    escrow_id = create_escrow_record(user.id, creator_name)

    # Generate private group invite link from an existing bot group
    # Admin must set EXISTING_GROUP_ID in env
    EXISTING_GROUP_ID = int(os.getenv("EXISTING_GROUP_ID"))
    try:
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=EXISTING_GROUP_ID, member_limit=2, name=f"Escrow {escrow_id}"
        )
        update_escrow(escrow_id, "group_id", EXISTING_GROUP_ID)
        update_escrow(escrow_id, "group_invite_link", invite_link.invite_link)
        await update.message.reply_text(
            ESCROW_CREATED_TEXT.format(invite_link=invite_link.invite_link)
        )
    except Exception as e:
        await update.message.reply_text("Failed to generate group link. Contact admin.")
        logger.error(e)


async def initescrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    # bind first "created" escrow for this group (admin may manage multiple)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM escrows WHERE group_id=? AND status='created' ORDER BY created_at ASC LIMIT 1",
        (group_id,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        await update.message.reply_text("No escrow to initialize in this group.")
        return
    escrow_id = row[0]
    update_escrow(escrow_id, "status", "waiting_deposit")
    await update.message.reply_text(GROUP_WELCOME)


async def dd_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(DD_TEXT)


async def buyer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /buyer <CRYPTO ADDRESS>")
        return
    address = context.args[0]
    escrow = find_escrow_by_group(update.effective_chat.id)
    if not escrow:
        await update.message.reply_text("No escrow found for this group.")
        return
    update_escrow(escrow[0], "buyer_address", address)
    await update.message.reply_text(f"Buyer address saved: {address}")


async def seller_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /seller <CRYPTO ADDRESS>")
        return
    address = context.args[0]
    escrow = find_escrow_by_group(update.effective_chat.id)
    if not escrow:
        await update.message.reply_text("No escrow found for this group.")
        return
    update_escrow(escrow[0], "seller_address", address)
    await update.message.reply_text(f"Seller address saved: {address}")


async def deposit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /deposit <TXID>")
        return
    txid = context.args[0]
    escrow = find_escrow_by_group(update.effective_chat.id)
    if not escrow:
        await update.message.reply_text("No escrow found for this group.")
        return
    update_escrow(escrow[0], "txid", txid)
    update_escrow(escrow[0], "status", "tx_submitted")
    await update.message.reply_text("TXID saved. Admin will verify.")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    escrow = None
    if context.args:
        escrow = get_escrow(context.args[0])
    else:
        escrow = find_escrow_by_group(update.effective_chat.id)
    if not escrow:
        await update.message.reply_text("No escrow found.")
        return
    (eid, creator_id, creator_name, amount, rate, conditions, buyer, seller, txid, status, created_at, group_id, group_link) = escrow
    await update.message.reply_text(
        f"Escrow {eid}\nStatus: {status}\nBuyer: {buyer or '—'}\nSeller: {seller or '—'}\nTXID: {txid or '—'}\nGroup link: {group_link or '—'}"
    )


async def dispute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    escrow = find_escrow_by_group(update.effective_chat.id)
    text = f"⚠️ Dispute requested in group {update.effective_chat.title or 'Escrow Group'}"
    if escrow:
        text += f"\nEscrow: {escrow[0]}"
    await update.message.reply_text("Dispute noted. Admin will be notified.")
    await context.bot.send_message(OWNER_ID, text)


# ---------------- ADMIN ----------------
def is_admin(user_id):
    return user_id == OWNER_ID


async def mark_received_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        return
    escrow_id = context.args[0]
    update_escrow(escrow_id, "status", "funds_received")


async def release_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        return
    escrow_id = context.args[0]
    update_escrow(escrow_id, "status", "released")


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        return
    escrow_id = context.args[0]
    update_escrow(escrow_id, "status", "cancelled")


# ---------------- MAIN ----------------
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", lambda u, c: u.message.reply_text(MENU_TEXT)))
    app.add_handler(CommandHandler("escrow", escrow_cmd))
    app.add_handler(CommandHandler("initescrow", initescrow))
    app.add_handler(CommandHandler("dd", dd_cmd))
    app.add_handler(CommandHandler("buyer", buyer_cmd))
    app.add_handler(CommandHandler("seller", seller_cmd))
    app.add_handler(CommandHandler("deposit", deposit_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("dispute", dispute_cmd))
    app.add_handler(CommandHandler("mark_received", mark_received_cmd))
    app.add_handler(CommandHandler("release", release_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))

    logger.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
