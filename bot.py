
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
    application.adcancel", cancel_cmd))

    # welcome handler
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_member))

    # unknown
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    logger.info...")
    application.run_polling(allowed_updates=["message", "edited_message", "chat_member", "my_chat_member"])

if __name__ == "__main__":
    main()
