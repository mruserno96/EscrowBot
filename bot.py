"""
Manual Escrow Telegram Bot (Python, python-telegram-bot v20)
Features:
- /start message (exact formatting you provided)
- /escrow (creates an escrow record and gives instructions + deep link to add bot to group)
- After creating a group and adding the bot, run /initescrow <escrow_id> inside the group to bind it
- Group welcome message (the exact wording you gave)
- /dd message to ask for deal details
- /buyer <address> and /seller <address>
- /deposit <txid> to upload TXID (not verified on-chain; admin manually verifies)
- Admin commands: /mark_received, /release, /cancel
- /status, /dispute
- SQLite storage
"""

import logging
import sqlite3
import uuid
import html
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------- CONFIG - EDIT THESE BEFORE RUNNING ----------------
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
USDT_BEP20_ADDRESS = os.getenv("USDT_BEP20_ADDRESS")
BOT_USERNAME = "Easy_Escroww_Bot"   # without @
ESCROW_FEE_PERCENT = 1.0  # flat percent shown to users
# ---------------------------------------------------------------------

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# DB helper
DB_PATH = "escrow_bot.db"

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

# ---------------- Messages (exact text + small polishing) ----------------

START_TEXT = f"""💫 @{BOT_USERNAME} 💫
Your Trustworthy Telegram Escrow Service

Welcome to @{BOT_USERNAME}. This bot provides a reliable escrow service for your transactions on Telegram.

Avoid scams, your funds are safeguarded throughout your deals. If you run into any issues, simply type /dispute and an arbitrator will join the group chat within 24 hours.

🎟 ESCROW FEE: {ESCROW_FEE_PERCENT:.1f}% Flat
🌐 (UPDATES) - (VOUCHES) ☑️

💬 Proceed with /escrow (to start with a new escrow)

⚠️ IMPORTANT - Make sure coin is same of Buyer and Seller else you may loose your coin.

💡 Type /menu to summon a menu with all bot's features
"""

ESCROW_CREATED_TEXT = """Creating a safe trading place for you... please wait...
Escrow Group Created

Creator: {creator}

Join this escrow group and share the link with the buyer and seller:

{invite_link}

⚠️ Note: This link is for 2 members only — third parties are not allowed to join.
"""

GROUP_WELCOME = """📍 Hey there traders! Welcome to our escrow service.
⚠️ IMPORTANT - Make sure coin and network is same of Buyer and Seller else you may loose your coin.
⚠️ IMPORTANT - Make sure the /buyer address and /seller address are of same chain else you may loose your coin.
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
/status <escrow_id> - Check escrow status (admin or group)
/deposit <txid> - Buyer reports TXID (admin will manually verify)
/buyer <address> - Buyer sets their address
/seller <address> - Seller sets their address
"""

# ---------------- Handlers ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(START_TEXT, parse_mode="HTML")

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(MENU_TEXT)

async def escrow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    creator_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    escrow_id = create_escrow_record(user.id, creator_name)
    # Provide deep-link to add bot to a new group
    deep_link = f"https://t.me/{BOT_USERNAME}?startgroup={escrow_id}"
    text = ESCROW_CREATED_TEXT.format(creator=html.escape(creator_name), invite_link=deep_link)
    await update.message.reply_text(text, parse_mode="HTML")
    await update.message.reply_text("After creating the group and adding the other party, open the new group and run:\n"
                                    f"/initescrow {escrow_id}\n\n"
                                    "This will bind the group to the escrow and post the welcome message.")

async def initescrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This command must be used inside the group after bot is added
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Please use /initescrow <escrow_id> inside the newly created escrow GROUP.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /initescrow <escrow_id>")
        return
    escrow_id = args[0]
    escrow = get_escrow(escrow_id)
    if not escrow:
        await update.message.reply_text("Escrow ID not found. Make sure you used the same ID shown when you ran /escrow.")
        return
    group_id = update.effective_chat.id
    # Bind
    update_escrow(escrow_id, "group_id", group_id)
    update_escrow(escrow_id, "group_invite_link", f"https://t.me/joinchat/{str(uuid.uuid4())[:22]}")
    update_escrow(escrow_id, "status", "waiting_deposit")
    await update.message.reply_text(GROUP_WELCOME)
    await update.message.reply_text("Escrow initialized. Please use /dd to enter deal details.")

async def dd_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only in group
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Please run /dd inside the escrow group.")
        return
    await update.message.reply_text(DD_TEXT)

async def buyer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Please set buyer address inside the escrow group using /buyer <address>")
        return
    if not context.args:
        await update.message.reply_text("Usage: /buyer <CRYPTO ADDRESS>")
        return
    address = context.args[0]
    group_id = update.effective_chat.id
    escrow = find_escrow_by_group(group_id)
    if not escrow:
        await update.message.reply_text("This group is not linked to any escrow. Use /initescrow <escrow_id> first.")
        return
    escrow_id = escrow[0]
    update_escrow(escrow_id, "buyer_address", address)
    await update.message.reply_text(f"Buyer address saved: {address}\nMake sure buyer and seller use the same chain.")

async def seller_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Please set seller address inside the escrow group using /seller <address>")
        return
    if not context.args:
        await update.message.reply_text("Usage: /seller <CRYPTO ADDRESS>")
        return
    address = context.args[0]
    group_id = update.effective_chat.id
    escrow = find_escrow_by_group(group_id)
    if not escrow:
        await update.message.reply_text("This group is not linked to any escrow. Use /initescrow <escrow_id> first.")
        return
    escrow_id = escrow[0]
    update_escrow(escrow_id, "seller_address", address)
    await update.message.reply_text(f"Seller address saved: {address}\nMake sure buyer and seller use the same chain.")

async def deposit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # deposit TXID reported in group
    if not context.args:
        await update.message.reply_text("Usage: /deposit <TXID>")
        return
    txid = context.args[0]
    # If used in group, bind to group escrow. If private, require escrow id.
    if update.effective_chat.type in ("group", "supergroup"):
        escrow = find_escrow_by_group(update.effective_chat.id)
        if not escrow:
            await update.message.reply_text("No escrow linked to this group. Use /initescrow <escrow_id> first.")
            return
        escrow_id = escrow[0]
    else:
        # private chat: expect escrow id first arg and txid second
        if len(context.args) < 2:
            await update.message.reply_text("Usage in private chat: /deposit <escrow_id> <TXID>")
            return
        escrow_id = context.args[0]
        txid = context.args[1]
        escrow = get_escrow(escrow_id)
        if not escrow:
            await update.message.reply_text("Escrow ID not found.")
            return
    update_escrow(escrow_id, "txid", txid)
    update_escrow(escrow_id, "status", "tx_submitted")
    await update.message.reply_text("TXID saved. Admin will manually verify and mark as received when confirmed.")
    # notify admin
    notify_admin_text = f"🔔 New deposit reported\nEscrow: {escrow_id}\nTXID: {txid}\nCheck and /mark_received {escrow_id} when you confirm."
    try:
        await context.bot.send_message(OWNER_ID, notify_admin_text)
    except Exception as e:
        logger.error("Failed to notify admin: %s", e)

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /status <escrow_id>  OR in group
    if update.effective_chat.type in ("group", "supergroup"):
        escrow = find_escrow_by_group(update.effective_chat.id)
        if not escrow:
            await update.message.reply_text("No escrow bound to this group.")
            return
        escrow_id = escrow[0]
    else:
        if not context.args:
            await update.message.reply_text("Usage: /status <escrow_id>")
            return
        escrow_id = context.args[0]
    e = get_escrow(escrow_id)
    if not e:
        await update.message.reply_text("Escrow not found.")
        return
    # unpack fields
    (eid, creator_id, creator_name, amount, rate, conditions, buyer_addr, seller_addr, txid, status, created_at, group_id, group_link) = e
    reply = (
        f"Escrow {eid}\n"
        f"Creator: {creator_name} ({creator_id})\n"
        f"Amount: {amount or '—'}\n"
        f"Rate: {rate or '—'}\n"
        f"Conditions: {conditions or '—'}\n"
        f"Buyer: {buyer_addr or '—'}\n"
        f"Seller: {seller_addr or '—'}\n"
        f"TXID: {txid or '—'}\n"
        f"Status: {status}\n"
        f"Group: {group_id or '—'}\n"
        f"Created at (UTC): {created_at}"
    )
    await update.message.reply_text(reply)

# Admin-only command helpers
def is_admin(user_id):
    return user_id == OWNER_ID

async def mark_received_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Only admin can use this command.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /mark_received <escrow_id>")
        return
    escrow_id = context.args[0]
    e = get_escrow(escrow_id)
    if not e:
        await update.message.reply_text("Escrow not found.")
        return
    update_escrow(escrow_id, "status", "funds_received")
    await update.message.reply_text(f"Escrow {escrow_id} marked as funds received.")
    # notify group
    group_id = e[11]
    if group_id:
        try:
            await context.bot.send_message(group_id, f"Admin has marked funds as received for escrow {escrow_id}.")
        except Exception:
            pass

async def release_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Only admin can release funds.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /release <escrow_id>")
        return
    escrow_id = context.args[0]
    e = get_escrow(escrow_id)
    if not e:
        await update.message.reply_text("Escrow not found.")
        return
    # In manual flow, releasing means admin has sent USDT from their address to seller. We just mark state.
    update_escrow(escrow_id, "status", "released")
    await update.message.reply_text(f"Escrow {escrow_id} marked as RELEASED.")
    # notify group
    group_id = e[11]
    if group_id:
        try:
            await context.bot.send_message(group_id, f"Admin has RELEASED funds for escrow {escrow_id}. Thank you for using the service.")
        except Exception:
            pass

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Only admin can cancel an escrow.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /cancel <escrow_id>")
        return
    escrow_id = context.args[0]
    e = get_escrow(escrow_id)
    if not e:
        await update.message.reply_text("Escrow not found.")
        return
    update_escrow(escrow_id, "status", "cancelled")
    await update.message.reply_text(f"Escrow {escrow_id} cancelled.")
    group_id = e[11]
    if group_id:
        try:
            await context.bot.send_message(group_id, f"Escrow {escrow_id} has been cancelled by admin.")
        except Exception:
            pass

async def dispute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Notify admin to join group as arbitrator
    if update.effective_chat.type in ("group", "supergroup"):
        escrow = find_escrow_by_group(update.effective_chat.id)
        group_id = update.effective_chat.id
        group_title = update.effective_chat.title or "Escrow Group"
        if escrow:
            escrow_id = escrow[0]
        else:
            escrow_id = "—"
        text = f"⚠️ Dispute requested in group {group_title} (id {group_id})\nEscrow: {escrow_id}\nPlease join the group to arbitrate."
        await update.message.reply_text("Dispute noted. An arbitrator will be notified.")
    else:
        text = f"⚠️ Dispute requested by user {update.effective_user.id} in private chat."
        await update.message.reply_text("Dispute noted. Admin will be notified.")
    try:
        await context.bot.send_message(OWNER_ID, text)
    except Exception as e:
        logger.error("Failed to notify admin for dispute: %s", e)

# Utility to show deposit address
async def deposit_address_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"Our fixed USDT BEP20 deposit address (use BEP20 / BSC network):\n\n"
        f"`{USDT_BEP20_ADDRESS}`\n\n"
        "Make sure buyer sends EXACTLY USDT BEP20 to this address. After sending, report the TXID with /deposit <TXID>."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# welcome new members (optional)
async def new_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # if bot added to group, give small tip message
    for member in update.message.new_chat_members:
        if member.is_bot and member.username == BOT_USERNAME:
            await update.message.reply_text("Hello! I'm the escrow bot. To finish setup, run /initescrow <escrow_id> (the ID shown when you used /escrow).")

# generic unknown command handler
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Unknown command. Type /menu to see available commands.")

# ---------------- Main application ----------------

def main():
    init_db()
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # public commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("escrow", escrow_cmd))
    application.add_handler(CommandHandler("initescrow", initescrow))
    application.add_handler(CommandHandler("dd", dd_cmd))
    application.add_handler(CommandHandler("buyer", buyer_cmd))
    application.add_handler(CommandHandler("seller", seller_cmd))
    application.add_handler(CommandHandler("deposit", deposit_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CommandHandler("dispute", dispute_cmd))
    application.add_handler(CommandHandler("address", deposit_address_cmd))
    # admin
    application.add_handler(CommandHandler("mark_received", mark_received_cmd))
    application.add_handler(CommandHandler("release", release_cmd))
    application.add_handler(CommandHandler("cancel", cancel_cmd))

    # welcome handler
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_member))

    # unknown
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    logger.info("Starting bot...")
    application.run_polling(allowed_updates=["message", "edited_message", "chat_member", "my_chat_member"])

if __name__ == "__main__":
    main()
