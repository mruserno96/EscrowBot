import os
import logging
import sqlite3
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))   # your Telegram ID
USDT_ADDRESS = os.getenv("USDT_ADDRESS")  # your wallet

# DB setup
conn = sqlite3.connect("escrow.db", check_same_thread=False)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer_id INTEGER,
    buyer_username TEXT,
    seller_username TEXT,
    amount REAL,
    status TEXT
)
""")
conn.commit()

# logging
logging.basicConfig(level=logging.INFO)

# States for Conversation
ASK_AMOUNT, ASK_SELLER = range(2)

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [["/newdeal", "/mydeals"], ["/help"]]
    if update.effective_user.id == ADMIN_ID:
        kb.append(["/admin"])
    await update.message.reply_text(
        "🤝 Welcome to Escrow Bot!\nCreate safe deals using USDT.\n\n"
        "Use /newdeal to start.",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True),
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/newdeal - Create a new deal\n"
        "/mydeals - View your deals\n"
        "(Admin only) /admin - Admin menu"
    )

# Start new deal
async def newdeal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Enter deal amount (in USDT):")
    return ASK_AMOUNT

async def ask_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
        context.user_data["amount"] = amount
        await update.message.reply_text("Enter seller's @username:")
        return ASK_SELLER
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Try again:")
        return ASK_AMOUNT

async def ask_seller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seller = update.message.text.strip()
    amount = context.user_data["amount"]
    buyer = update.effective_user

    c.execute(
        "INSERT INTO deals (buyer_id, buyer_username, seller_username, amount, status) VALUES (?,?,?,?,?)",
        (buyer.id, buyer.username, seller, amount, "pending"),
    )
    conn.commit()

    deal_id = c.lastrowid
    await update.message.reply_text(
        f"✅ Deal #{deal_id} created!\n"
        f"Buyer: @{buyer.username}\nSeller: {seller}\nAmount: {amount} USDT\n\n"
        f"👉 Please send {amount} USDT to this address:\n<code>{USDT_ADDRESS}</code>",
        parse_mode="HTML",
    )
    return ConversationHandler.END

# List user deals
async def mydeals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    c.execute("SELECT id, seller_username, amount, status FROM deals WHERE buyer_id=?", (uid,))
    deals = c.fetchall()
    if not deals:
        await update.message.reply_text("You have no deals yet.")
    else:
        msg = "📋 Your deals:\n"
        for d in deals:
            msg += f"#{d[0]} - Seller: {d[1]}, Amount: {d[2]} USDT, Status: {d[3]}\n"
        await update.message.reply_text(msg)

# Admin Menu
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    c.execute("SELECT id, buyer_username, seller_username, amount, status FROM deals")
    deals = c.fetchall()
    if not deals:
        await update.message.reply_text("No deals in system.")
    else:
        for d in deals:
            buttons = [
                [
                    InlineKeyboardButton(f"✅ Release #{d[0]}", callback_data=f"release_{d[0]}"),
                    InlineKeyboardButton(f"🔄 Refund #{d[0]}", callback_data=f"refund_{d[0]}"),
                ]
            ]
            msg = (
                f"📌 Deal #{d[0]}\n"
                f"Buyer: @{d[1]}\nSeller: {d[2]}\nAmount: {d[3]} USDT\nStatus: {d[4]}"
            )
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons))

# Callback for admin buttons
async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, deal_id = query.data.split("_")
    deal_id = int(deal_id)

    if action == "release":
        c.execute("UPDATE deals SET status=? WHERE id=?", ("released", deal_id))
        conn.commit()
        await query.edit_message_text(f"✅ Deal #{deal_id} marked as released. (Pay seller manually)")

    elif action == "refund":
        c.execute("UPDATE deals SET status=? WHERE id=?", ("refunded", deal_id))
        conn.commit()
        await query.edit_message_text(f"🔄 Deal #{deal_id} marked as refunded. (Pay buyer manually)")

# ================= MAIN =================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("newdeal", newdeal)],
        states={
            ASK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_amount)],
            ASK_SELLER: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_seller)],
        },
        fallbacks=[],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(conv)
    app.add_handler(CommandHandler("mydeals", mydeals))
    app.add_handler(CommandHandler("admin", admin_menu))
    app.add_handler(CallbackQueryHandler(admin_action))

    app.run_polling()

if __name__ == "__main__":
    main()
