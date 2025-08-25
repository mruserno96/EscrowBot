#!/usr/bin/env python3
"""
Easy Escrow Bot — full single-file implementation.

Requirements:
  Python 3.10+
  pip install python-telegram-bot==20.7

Environment variables:
  TG_TOKEN        - Telegram bot token
  ADMIN_IDS       - comma-separated numeric Telegram IDs (e.g. 12345,67890)
  USDT_ADDRESS    - your fixed USDT address (TRC20 or ERC20)
  ESCROW_GROUP    - optional group invite link
  ADMIN_CONTACT   - optional admin contact handle (e.g. @Admin)
"""
from __future__ import annotations

import json
import os
import random
import re
import sqlite3
import string
from datetime import datetime
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler

# -------------------- CONFIG --------------------
TG_TOKEN = os.getenv("TG_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
USDT_ADDRESS = os.getenv("USDT_ADDRESS", "TRC20_or_ERC20_wallet_address_here")
ESCROW_GROUP = os.getenv("ESCROW_GROUP", "https://t.me/yourgroup")
ADMIN_CONTACT = os.getenv("ADMIN_CONTACT", "@YourAdmin")

DB_FILE = "escrow.db"
SUPPORTED_TOKENS = ["USDT-TRC20", "USDT-ERC20", "USDC-ERC20", "ETH", "BTC"]
DEFAULT_FEE_BPS = 100  # 1%

# quick guard
if not TG_TOKEN:
    raise SystemExit("TG_TOKEN environment variable is required")

# -------------------- DB HELPERS --------------------
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    conn = db()
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY,
          username TEXT,
          first_name TEXT,
          referrals INTEGER DEFAULT 0,
          referred_by INTEGER,
          saved_json TEXT DEFAULT '{}',
          created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS deals (
          id TEXT PRIMARY KEY,
          chat_id INTEGER,
          creator_id INTEGER,
          buyer_id INTEGER,
          seller_id INTEGER,
          token TEXT,
          amount REAL,
          fee_bps INTEGER,
          status TEXT,
          deposit_address TEXT,
          balance REAL DEFAULT 0,
          details_json TEXT DEFAULT '{}',
          created_at TEXT,
          updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS vouches (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER,
          text TEXT,
          created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS disputes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          deal_id TEXT,
          raised_by INTEGER,
          reason TEXT,
          status TEXT,
          created_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()

def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")

def new_deal_id() -> str:
    return "DL-" + "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(8))

# -------------------- UTILS --------------------
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def verify_address_format(token: str, address: str) -> bool:
    token = token.upper()
    if token.endswith("ERC20") or token == "ETH":
        return bool(re.fullmatch(r"0x[a-fA-F0-9]{24,64}", address))
    if token.startswith("USDT-TRC20") or token == "TRX":
        return bool(re.fullmatch(r"T[1-9A-HJ-NP-Za-km-z]{24,50}", address))
    if token == "BTC":
        return bool(re.fullmatch(r"(bc1|[13])[a-zA-HJ-NP-Z0-9]{20,59}", address))
    return False

# -------------------- DB OPERATIONS --------------------
def upsert_user(user, referred_by: Optional[int] = None) -> None:
    conn = db(); cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (id, username, first_name, created_at) VALUES (?, ?, ?, ?)",
                (user.id, user.username or "", user.first_name or "", now_iso()))
    cur.execute("UPDATE users SET username=?, first_name=? WHERE id=?",
                (user.username or "", user.first_name or "", user.id))
    if referred_by and referred_by != user.id:
        cur.execute("SELECT referred_by FROM users WHERE id=?", (user.id,))
        row = cur.fetchone()
        if row and row["referred_by"] is None:
            cur.execute("UPDATE users SET referred_by=? WHERE id=?", (referred_by, user.id))
            cur.execute("UPDATE users SET referrals = COALESCE(referrals,0)+1 WHERE id=?", (referred_by,))
    conn.commit(); conn.close()

def create_deal(chat_id: int, creator_id: int) -> str:
    deal_id = new_deal_id()
    conn = db(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO deals (id, chat_id, creator_id, status, deposit_address, fee_bps, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (deal_id, chat_id, creator_id, "NEW", USDT_ADDRESS, DEFAULT_FEE_BPS, now_iso(), now_iso())
    )
    conn.commit(); conn.close()
    return deal_id

def get_latest_deal(chat_id: int):
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT * FROM deals WHERE chat_id=? ORDER BY created_at DESC LIMIT 1", (chat_id,))
    row = cur.fetchone(); conn.close(); return row

def get_deal_by_id(deal_id: str):
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT * FROM deals WHERE id=?", (deal_id,))
    row = cur.fetchone(); conn.close(); return row

def update_deal(deal_id: str, **fields):
    if not fields:
        return
    fields["updated_at"] = now_iso()
    conn = db(); cur = conn.cursor()
    sets = ",".join([f"{k}=?" for k in fields.keys()])
    cur.execute(f"UPDATE deals SET {sets} WHERE id=?", (*fields.values(), deal_id))
    conn.commit(); conn.close()

# -------------------- UI --------------------
MAIN_MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("➕ New Deal", callback_data="menu:newdeal"), InlineKeyboardButton("📜 Terms", callback_data="menu:terms")],
    [InlineKeyboardButton("📚 What is Escrow?", callback_data="menu:whatisescrow")],
    [InlineKeyboardButton("⚙️ Commands", callback_data="menu:commands"), InlineKeyboardButton("📊 Stats", callback_data="menu:stats")]
])

TOKEN_MENU = InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=f"token:{t}")] for t in SUPPORTED_TOKENS])

# -------------------- HANDLERS --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # supports referral: /start ref-<id>
    ref_by = None
    if context.args:
        m = re.fullmatch(r"ref-(\d+)", context.args[0])
        if m:
            ref_by = int(m.group(1))
    upsert_user(update.effective_user, referred_by=ref_by)
    await update.message.reply_text(
        "👋 Welcome to Easy Escrow Bot!\nUse /commands to view features.",
        reply_markup=MAIN_MENU
    )

async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    data = update.callback_query.data
    if data == "menu:newdeal":
        await newdeal(update, context)
    elif data == "menu:terms":
        await terms(update, context)
    elif data == "menu:whatisescrow":
        await whatis(update, context)
    elif data == "menu:commands":
        await commands_cmd(update, context)
    elif data == "menu:stats":
        await stats(update, context)
    elif data.startswith("token:"):
        await token_cmd(update, context)

async def whatis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🔐 Escrow holds funds until both parties fulfil the deal.\nFlow: /newdeal → set parties → /token → /dd → /deposit → admin confirms → /release"
    )

async def instructions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "📘 How to use:\n1) /newdeal\n2) /seller and /buyer\n3) /token (choose)\n4) /dd amount:100 item:Info\n5) /deposit to see address\n6) Admin uses /confirmfund <amount>\n7) Admin /release or /refund"
    )

async def terms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "📄 Terms: This bot coordinates escrow records. Funds are controlled by admin wallet. Admin decisions are final."
    )

async def commands_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📌 AVAILABLE COMMANDS\n"
        "/start\n/whatisescrow\n/instructions\n/terms\n/dispute\n/menu\n/contact\n/commands\n/stats\n/vouch\n"
        "/newdeal\n/tradeid\n/dd\n/escrow\n/token\n/deposit\n/verify\n/balance\n/release\n/refund\n/seller\n/buyer\n/setfee\n/save\n/saved\n/referral\n/confirmfund\n"
    )
    await update.effective_message.reply_text(msg)

async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(f"📮 Admin contact: {ADMIN_CONTACT}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) c FROM deals"); total = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM deals WHERE status='RELEASED'"); rel = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM deals WHERE status='REFUNDED'"); ref = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM disputes WHERE status='OPEN'"); dis = cur.fetchone()["c"]
    conn.close()
    await update.effective_message.reply_text(f"📊 Total deals: {total}\nReleased: {rel}\nRefunded: {ref}\nOpen disputes: {dis}")

async def vouch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.effective_message.reply_text("Usage: /vouch I had a great trade because ...")
        return
    conn = db(); cur = conn.cursor()
    cur.execute("INSERT INTO vouches (user_id, text, created_at) VALUES (?, ?, ?)",
                (update.effective_user.id, text, now_iso()))
    conn.commit(); conn.close()
    await update.effective_message.reply_text("🙏 Thanks — your vouch was saved.")

# ---- Deals ----
async def newdeal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    creator = update.effective_user.id
    deal_id = create_deal(chat_id, creator)
    await update.effective_message.reply_text(f"🆕 New deal created: <b>{deal_id}</b>\nUse /seller and /buyer to set parties, /token to set token and /dd for details.",
                                             parse_mode="HTML")

async def tradeid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = get_latest_deal(update.effective_chat.id)
    if not row:
        await update.effective_message.reply_text("No active deal. Start one with /newdeal")
        return
    await update.effective_message.reply_text(f"🔖 Current Trade ID: <b>{row['id']}</b>", parse_mode="HTML")

async def dd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = get_latest_deal(update.effective_chat.id)
    if not row:
        await update.effective_message.reply_text("Start a deal first with /newdeal")
        return
    raw = update.effective_message.text.replace("/dd", "", 1).strip()
    if not raw:
        await update.effective_message.reply_text("Usage: /dd amount:100 item:Description deadline:2025-09-01")
        return
    details = json.loads(row["details_json"]) if row["details_json"] else {}
    for chunk in re.findall(r"(\w+:[^\s]+)", raw):
        k, v = chunk.split(":", 1)
        details[k.lower()] = v
        if k.lower() == "amount":
            try:
                update_deal(row["id"], amount=float(v))
            except Exception:
                pass
    update_deal(row["id"], details_json=json.dumps(details))
    await update.effective_message.reply_text(f"✅ Deal details updated: {details}")

async def escrow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(f"🔗 Escrow group: {ESCROW_GROUP}")

async def token_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # supports both callback and /token <TOKEN>
    if context.args:
        chosen = context.args[0].upper()
        if chosen not in SUPPORTED_TOKENS:
            await update.effective_message.reply_text(f"Unsupported token. Choose: {', '.join(SUPPORTED_TOKENS)}")
            return
        row = get_latest_deal(update.effective_chat.id)
        if not row:
            await update.effective_message.reply_text("Start a deal first with /newdeal")
            return
        update_deal(row["id"], token=chosen)
        await update.effective_message.reply_text(f"✅ Token set to {chosen}")
        return
    await update.effective_message.reply_text("Choose token:", reply_markup=TOKEN_MENU)

async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = get_latest_deal(update.effective_chat.id)
    if not row:
        await update.effective_message.reply_text("Start a deal first with /newdeal")
        return
    if row["status"] == "NEW":
        update_deal(row["id"], status="AWAITING_DEPOSIT")
    await update.effective_message.reply_text(
        f"💳 Send the agreed USDT to this address (admin wallet):\n<code>{USDT_ADDRESS}</code>\n\nTrade ID: <b>{row['id']}</b>\nAfter sending, notify admin and provide TXID.",
        parse_mode="HTML"
    )

async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.effective_message.reply_text("Usage: /verify <TOKEN> <ADDRESS>")
        return
    token = context.args[0]
    address = context.args[1]
    ok = verify_address_format(token, address)
    await update.effective_message.reply_text("✅ Address format looks valid." if ok else "❌ Address format looks invalid.")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = get_latest_deal(update.effective_chat.id)
    if not row:
        await update.effective_message.reply_text("No active deal.")
        return
    await update.effective_message.reply_text(f"Balance for {row['id']}: {row['balance']} {row['token'] or 'USDT'} (status: {row['status']})")

# ---- Parties ----
async def seller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = get_latest_deal(update.effective_chat.id)
    if not row:
        await update.effective_message.reply_text("Start a deal first.")
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /seller <telegram_user_id> or /seller @username (id recommended)")
        return
    arg = context.args[0].lstrip("@")
    try:
        seller_id = int(arg)
    except ValueError:
        seller_id = None
    update_deal(row["id"], seller_id=seller_id)
    await update.effective_message.reply_text("✅ Seller set.")

async def buyer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = get_latest_deal(update.effective_chat.id)
    if not row:
        await update.effective_message.reply_text("Start a deal first.")
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /buyer <telegram_user_id> or /buyer @username (id recommended)")
        return
    arg = context.args[0].lstrip("@")
    try:
        buyer_id = int(arg)
    except ValueError:
        buyer_id = None
    update_deal(row["id"], buyer_id=buyer_id)
    await update.effective_message.reply_text("✅ Buyer set.")

# ---- Fees & saved addresses ----
async def setfee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("Only admins can set fees.")
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /setfee <basis_points> (100 = 1%)")
        return
    try:
        bps = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("Enter a number, e.g., 100")
        return
    row = get_latest_deal(update.effective_chat.id)
    if not row:
        await update.effective_message.reply_text("No deal in this chat.")
        return
    update_deal(row["id"], fee_bps=bps)
    await update.effective_message.reply_text(f"✅ Fee set to {bps} bps")

async def save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.effective_message.reply_text("Usage: /save <CHAIN> <ADDRESS>")
        return
    chain = context.args[0].upper()
    addr = context.args[1]
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT saved_json FROM users WHERE id=?", (update.effective_user.id,))
    row = cur.fetchone()
    saved = json.loads(row["saved_json"]) if row and row["saved_json"] else {}
    saved[chain] = addr
    cur.execute("UPDATE users SET saved_json=? WHERE id=?", (json.dumps(saved), update.effective_user.id))
    conn.commit(); conn.close()
    await update.effective_message.reply_text(f"✅ Saved {chain} address.")

async def saved_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT saved_json FROM users WHERE id=?", (update.effective_user.id,))
    row = cur.fetchone(); conn.close()
    saved = json.loads(row["saved_json"]) if row and row["saved_json"] else {}
    if not saved:
        await update.effective_message.reply_text("No saved addresses.")
        return
    pretty = "\n".join(f"• {k}: {v}" for k, v in saved.items())
    await update.effective_message.reply_text(f"Saved addresses:\n{pretty}")

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = f"ref-{update.effective_user.id}"
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT referrals FROM users WHERE id=?", (update.effective_user.id,))
    row = cur.fetchone(); conn.close()
    refs = row["referrals"] if row else 0
    await update.effective_message.reply_text(f"Your referral code: {code}\nReferrals: {refs}")

# ---- Disputes ----
async def dispute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = get_latest_deal(update.effective_chat.id)
    reason = " ".join(context.args) if context.args else "(no details)"
    conn = db(); cur = conn.cursor()
    cur.execute("INSERT INTO disputes (deal_id, raised_by, reason, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (row["id"] if row else None, update.effective_user.id, reason, "OPEN", now_iso()))
    conn.commit(); conn.close()
    # notify admins
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(aid, f"🚩 Dispute opened for deal {row['id'] if row else '(none)'} by {update.effective_user.id}\nReason: {reason}")
        except Exception:
            pass
    await update.effective_message.reply_text("✅ Dispute recorded. Admins notified.")

# ---- Admin: confirm funds, release, refund ----
async def confirmfund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("Admins only.")
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /confirmfund <amount>")
        return
    try:
        amt = float(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("Enter a numeric amount.")
        return
    row = get_latest_deal(update.effective_chat.id)
    if not row:
        await update.effective_message.reply_text("No deal in this chat.")
        return
    new_bal = (row["balance"] or 0.0) + amt
    update_deal(row["id"], balance=new_bal, status="FUNDED")
    await update.effective_message.reply_text(f"✅ Marked funded: {amt}. New balance: {new_bal} (deal {row['id']})")

async def release(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("Admins only.")
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /release <deal_id>")
        return
    deal_id = context.args[0]
    d = get_deal_by_id(deal_id)
    if not d:
        await update.effective_message.reply_text("Deal not found.")
        return
    if (d["balance"] or 0) <= 0:
        await update.effective_message.reply_text("No funds recorded for this deal.")
        return
    update_deal(deal_id, status="RELEASED")
    await update.effective_message.reply_text(f"✅ Deal {deal_id} set to RELEASED. (Please pay seller from your wallet)")

async def refund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("Admins only.")
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /refund <deal_id>")
        return
    deal_id = context.args[0]
    d = get_deal_by_id(deal_id)
    if not d:
        await update.effective_message.reply_text("Deal not found.")
        return
    if (d["balance"] or 0) <= 0:
        await update.effective_message.reply_text("No funds recorded for this deal.")
        return
    update_deal(deal_id, status="REFUNDED")
    await update.effective_message.reply_text(f"✅ Deal {deal_id} set to REFUNDED. (Please refund buyer from your wallet)")

# Error handler
async def on_error(update_obj, context: ContextTypes.DEFAULT_TYPE):
    print("ERROR:", context.error)
    try:
        if update_obj and getattr(update_obj, "effective_message", None):
            await update_obj.effective_message.reply_text("⚠️ An error occurred. Please try again.")
    except Exception:
        pass

# -------------------- BOOT --------------------
def main():
    init_db()
    app = ApplicationBuilder().token(TG_TOKEN).build()

    # Public
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(CommandHandler("whatisescrow", whatis))
    app.add_handler(CommandHandler("instructions", instructions))
    app.add_handler(CommandHandler("terms", terms))
    app.add_handler(CommandHandler("menu", lambda u,c: u.message.reply_text("Main menu:", reply_markup=MAIN_MENU)))
    app.add_handler(CommandHandler("contact", contact))
    app.add_handler(CommandHandler("commands", commands_cmd))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("vouch", vouch))

    # Deals
    app.add_handler(CommandHandler("newdeal", newdeal))
    app.add_handler(CommandHandler("tradeid", tradeid))
    app.add_handler(CommandHandler("dd", dd))
    app.add_handler(CommandHandler("escrow", escrow_cmd))
    app.add_handler(CommandHandler("token", token_cmd))
    app.add_handler(CommandHandler("deposit", deposit))
    app.add_handler(CommandHandler("verify", verify))
    app.add_handler(CommandHandler("balance", balance))

    # Parties & config
    app.add_handler(CommandHandler("seller", seller))
    app.add_handler(CommandHandler("buyer", buyer))
    app.add_handler(CommandHandler("setfee", setfee))
    app.add_handler(CommandHandler("save", save))
    app.add_handler(CommandHandler("saved", saved_cmd))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("dispute", dispute))

    # Admin: fund confirm & payouts
    app.add_handler(CommandHandler("confirmfund", confirmfund))
    app.add_handler(CommandHandler("release", release))
    app.add_handler(CommandHandler("refund", refund))

    app.add_error_handler(on_error)

    print("Easy Escrow Bot — running (long polling)...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
