import logging import sqlite3 from telegram import Update, ReplyKeyboardMarkup from telegram.ext import ( Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters, )

================= CONFIG =================
BOT_TOKEN = "8051955868:AAFXhrj69_sNA2Riw-1qyQjVwG1dA2T6qHo" ADMIN_ID = 7357160729 # replace with your Telegram ID USDT_ADDRESS = "YOUR_USDT_ADDRESS"

DB setup

conn = sqlite3.connect("escrow.db", check_same_thread=False) c = conn.cursor() c.execute(""" CREATE TABLE IF NOT EXISTS deals ( id INTEGER PRIMARY KEY AUTOINCREMENT, buyer_id INTEGER, buyer_username TEXT, seller_username TEXT, amount REAL, status TEXT ) """) conn.commit()

logging

logging.basicConfig(level=logging.INFO)

States for Conversation

ASK_AMOUNT, ASK_SELLER = range(2)

================= COMMANDS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): kb = [["/newdeal", "/mydeals"], ["/help"]] await update.message.reply_text( "Welcome to Escrow Bot!\nCreate safe deals using USDT.", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True), )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text( "Commands:\n" "/newdeal - Create a new deal\n" "/mydeals - View your deals\n" "(Admin only) /alldeals - List all deals\n" "(Admin only) /release <deal_id> - Release funds\n" "(Admin only) /refund <deal_id> - Refund buyer" )

Start new deal

async def newdeal(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("Enter deal amount (in USDT):") return ASK_AMOUNT

async def ask_amount(update: Update, context: ContextTypes.DEFAULT_TYPE): try: amount = float(update.message.text) context.user_data["amount"] = amount await update.message.reply_text("Enter seller's @username:") return ASK_SELLER except ValueError: await update.message.reply_text("Invalid amount. Try again:") return ASK_AMOUNT

async def ask_seller(update: Update, context: ContextTypes.DEFAULT_TYPE): seller = update.message.text.strip() amount = context.user_data["amount"] buyer = update.effective_user

c.execute(
    "INSERT INTO deals (buyer_id, buyer_username, seller_username, amount, status) VALUES (?,?,?,?,?)",
    (buyer.id, buyer.username, seller, amount, "pending"),
)
conn.commit()

deal_id = c.lastrowid
await update.message.reply_text(
    f"✅ Deal #{deal_id} created!\n"
    f"Buyer: @{buyer.username}\nSeller: {seller}\nAmount: {amount} USDT\n"
    f"Please send {amount} USDT to this address:\n<code>{USDT_ADDRESS}</code>",
    parse_mode="HTML",
)
return ConversationHandler.END

List user deals

async def mydeals(update: Update, context: ContextTypes.DEFAULT_TYPE): uid = update.effective_user.id c.execute("SELECT id, seller_username, amount, status FROM deals WHERE buyer_id=?", (uid,)) deals = c.fetchall() if not deals: await update.message.reply_text("You have no deals yet.") else: msg = "Your deals:\n" for d in deals: msg += f"#{d[0]} - Seller: {d[1]}, Amount: {d[2]} USDT, Status: {d[3]}\n" await update.message.reply_text(msg)

Admin: List all deals

async def alldeals(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.effective_user.id != ADMIN_ID: return c.execute("SELECT id, buyer_username, seller_username, amount, status FROM deals") deals = c.fetchall() if not deals: await update.message.reply_text("No deals in system.") else: msg = "All deals:\n" for d in deals: msg += f"#{d[0]} - Buyer: @{d[1]}, Seller: {d[2]}, Amount: {d[3]} USDT, Status: {d[4]}\n" await update.message.reply_text(msg)

Admin: Release funds

async def release(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.effective_user.id != ADMIN_ID: return try: deal_id = int(context.args[0]) c.execute("UPDATE deals SET status=? WHERE id=?", ("released", deal_id)) conn.commit() await update.message.reply_text(f"✅ Deal #{deal_id} marked as released. Pay seller manually.") except: await update.message.reply_text("Usage: /release <deal_id>")

Admin: Refund

async def refund(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.effective_user.id != ADMIN_ID: return try: deal_id = int(context.args[0]) c.execute("UPDATE deals SET status=? WHERE id=?", ("refunded", deal_id)) conn.commit() await update.message.reply_text(f"🔄 Deal #{deal_id} marked as refunded. Pay buyer manually.") except: await update.message.reply_text("Usage: /refund <deal_id>")

================= MAIN =================

def main(): app = Application.builder().token(BOT_TOKEN).build()

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
app.add_handler(CommandHandler("alldeals", alldeals))
app.add_handler(CommandHandler("release", release))
app.add_handler(CommandHandler("refund", refund))

app.run_polling()

if name == "main": main()

