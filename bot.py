import os
import io
import sqlite3
import asyncio
import logging
from datetime import datetime

import qrcode
from aiohttp import web
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()}
PORT = int(os.getenv("PORT", "10000"))
DB_PATH = os.getenv("DB_PATH", "crm.db")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger("crm")

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row

def db(sql, params=(), fetch=False, many=False):
    cur = conn.cursor()
    if many:
        cur.executemany(sql, params)
    else:
        cur.execute(sql, params)
    conn.commit()
    if fetch:
        return cur.fetchall()
    return cur.lastrowid

def init_db():
    db("""CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        role TEXT NOT NULL DEFAULT 'manager',
        created_at TEXT NOT NULL
    )""")
    db("""CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT,
        note TEXT,
        created_at TEXT NOT NULL
    )""")
    db("""CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER,
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'new',
        note TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(client_id) REFERENCES clients(id)
    )""")
    db("""CREATE TABLE IF NOT EXISTS qr_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(client_id) REFERENCES clients(id)
    )""")

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def is_admin(uid):
    return uid in ADMIN_IDS or bool(db("SELECT 1 FROM users WHERE telegram_id=? AND role='admin'", (uid,), True))

def ensure_user(update):
    u = update.effective_user
    if not u:
        return
    role = "admin" if u.id in ADMIN_IDS else "manager"
    existing = db("SELECT telegram_id FROM users WHERE telegram_id=?", (u.id,), True)
    if not existing:
        db("INSERT INTO users VALUES (?, ?, ?, ?, ?)",
           (u.id, u.username or "", u.full_name or "", role, now()))
    elif u.id in ADMIN_IDS:
        db("UPDATE users SET role='admin' WHERE telegram_id=?", (u.id,))

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Клієнти", callback_data="clients"),
         InlineKeyboardButton("➕ Додати клієнта", callback_data="add_client")],
        [InlineKeyboardButton("📋 Заявки", callback_data="requests"),
         InlineKeyboardButton("➕ Нова заявка", callback_data="add_request")],
        [InlineKeyboardButton("🔎 Пошук", callback_data="search"),
         InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("🔳 QR-коди", callback_data="qr")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update)
    context.user_data.clear()
    await update.message.reply_text(
        "🤖 *LLL CRM*\n\nГотово до роботи. Обери дію:",
        parse_mode="Markdown", reply_markup=menu()
    )

async def help_cmd(update, context):
    await update.message.reply_text(
        "/start — головне меню\n"
        "/clients — клієнти\n"
        "/requests — заявки\n"
        "/stats — статистика\n"
        "/cancel — скасувати поточну дію"
    )

async def cancel(update, context):
    context.user_data.clear()
    await update.message.reply_text("Дію скасовано.", reply_markup=menu())

async def show_clients(update, context):
    rows = db("SELECT * FROM clients ORDER BY id DESC LIMIT 30", fetch=True)
    if not rows:
        text = "👥 Клієнтів поки немає."
    else:
        text = "👥 *Останні клієнти:*\n\n"
        for r in rows:
            text += f"#{r['id']} — *{r['name']}*"
            if r["phone"]: text += f" | {r['phone']}"
            text += "\n"
    kb = [[InlineKeyboardButton("➕ Додати", callback_data="add_client")],
          [InlineKeyboardButton("⬅️ Меню", callback_data="menu")]]
    await send_ui(update, text, kb)

async def show_requests(update, context):
    rows = db("""SELECT r.*, c.name AS client_name
                 FROM requests r LEFT JOIN clients c ON c.id=r.client_id
                 ORDER BY r.id DESC LIMIT 30""", fetch=True)
    if not rows:
        text = "📋 Заявок поки немає."
    else:
        text = "📋 *Останні заявки:*\n\n"
        for r in rows:
            client = r["client_name"] or "без клієнта"
            text += f"#{r['id']} — *{r['title']}*\n👤 {client} | {r['status']}\n\n"
    kb = [[InlineKeyboardButton("➕ Нова заявка", callback_data="add_request")],
          [InlineKeyboardButton("⬅️ Меню", callback_data="menu")]]
    await send_ui(update, text, kb)

async def show_stats(update, context):
    clients = db("SELECT COUNT(*) n FROM clients", fetch=True)[0]["n"]
    total = db("SELECT COUNT(*) n FROM requests", fetch=True)[0]["n"]
    new = db("SELECT COUNT(*) n FROM requests WHERE status='new'", fetch=True)[0]["n"]
    work = db("SELECT COUNT(*) n FROM requests WHERE status='in_work'", fetch=True)[0]["n"]
    done = db("SELECT COUNT(*) n FROM requests WHERE status='done'", fetch=True)[0]["n"]
    text = (f"📊 *Статистика CRM*\n\n"
            f"👥 Клієнтів: *{clients}*\n"
            f"📋 Заявок: *{total}*\n"
            f"🆕 Нових: *{new}*\n"
            f"🔧 В роботі: *{work}*\n"
            f"✅ Виконано: *{done}*")
    await send_ui(update, text, [[InlineKeyboardButton("⬅️ Меню", callback_data="menu")]])

async def send_ui(update, text, keyboard):
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown",
                                                       reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode="Markdown",
                                        reply_markup=InlineKeyboardMarkup(keyboard))

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ensure_user(update)
    data = q.data
    if data == "menu":
        context.user_data.clear()
        await q.edit_message_text("🤖 *LLL CRM*\n\nОбери дію:", parse_mode="Markdown", reply_markup=menu())
    elif data == "clients":
        await show_clients(update, context)
    elif data == "requests":
        await show_requests(update, context)
    elif data == "stats":
        await show_stats(update, context)
    elif data == "add_client":
        context.user_data.clear()
        context.user_data["state"] = "client_name"
        await q.edit_message_text("👤 Введи *ім'я/назву клієнта*.\n\n/cancel — скасувати", parse_mode="Markdown")
    elif data == "add_request":
        context.user_data.clear()
        context.user_data["state"] = "request_client"
        await q.edit_message_text("📋 Введи ID клієнта або `0`, якщо заявка без клієнта.", parse_mode="Markdown")
    elif data == "search":
        context.user_data.clear()
        context.user_data["state"] = "search"
        await q.edit_message_text("🔎 Введи ім'я, телефон або текст для пошуку.")
    elif data == "qr":
        context.user_data.clear()
        context.user_data["state"] = "qr"
        await q.edit_message_text("🔳 Введи текст/посилання, яке потрібно закодувати в QR.\nНаприклад: ID клієнта, адресу або посилання.")
    elif data.startswith("status:"):
        rid, status = data.split(":", 2)[1:]
        if not is_admin(update.effective_user.id):
            await q.answer("Змінювати статус може адміністратор.", show_alert=True)
            return
        db("UPDATE requests SET status=?, updated_at=? WHERE id=?", (status, now(), int(rid)))
        await q.edit_message_text(f"✅ Статус заявки #{rid} змінено на *{status}*.",
                                  parse_mode="Markdown",
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Заявки", callback_data="requests")]]))

async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update)
    state = context.user_data.get("state")
    if not state:
        await update.message.reply_text("Обери дію в меню:", reply_markup=menu())
        return
    text = update.message.text.strip()
    if state == "client_name":
        context.user_data["client_name"] = text
        context.user_data["state"] = "client_phone"
        await update.message.reply_text("📞 Введи телефон клієнта або `-`.", parse_mode="Markdown")
    elif state == "client_phone":
        phone = "" if text == "-" else text
        name = context.user_data["client_name"]
        cid = db("INSERT INTO clients(name,phone,note,created_at) VALUES(?,?,?,?)",
                 (name, phone, "", now()))
        context.user_data.clear()
        await update.message.reply_text(f"✅ Клієнта *{name}* додано. ID: `{cid}`",
                                        parse_mode="Markdown", reply_markup=menu())
    elif state == "request_client":
        try:
            cid = int(text)
        except ValueError:
            await update.message.reply_text("Введи числовий ID клієнта або 0.")
            return
        if cid and not db("SELECT id FROM clients WHERE id=?", (cid,), True):
            await update.message.reply_text("❌ Клієнта з таким ID не знайдено. Спробуй ще раз.")
            return
        context.user_data["client_id"] = cid or None
        context.user_data["state"] = "request_title"
        await update.message.reply_text("✏️ Введи назву/суть заявки.")
    elif state == "request_title":
        cid = context.user_data["client_id"]
        rid = db("""INSERT INTO requests(client_id,title,status,note,created_at,updated_at)
                    VALUES(?,?, 'new','',?,?)""", (cid, text, now(), now()))
        context.user_data.clear()
        await update.message.reply_text(f"✅ Заявку #{rid} створено.", reply_markup=menu())
    elif state == "search":
        pattern = f"%{text}%"
        clients = db("SELECT * FROM clients WHERE name LIKE ? OR phone LIKE ? LIMIT 15",
                     (pattern, pattern), True)
        requests = db("""SELECT r.*, c.name client_name FROM requests r
                         LEFT JOIN clients c ON c.id=r.client_id
                         WHERE r.title LIKE ? OR r.note LIKE ? LIMIT 15""",
                      (pattern, pattern), True)
        out = "🔎 *Результати пошуку*\n\n"
        if clients:
            out += "👥 *Клієнти:*\n" + "\n".join(f"#{r['id']} {r['name']} {r['phone']}" for r in clients) + "\n\n"
        if requests:
            out += "📋 *Заявки:*\n" + "\n".join(f"#{r['id']} {r['title']} — {r['status']}" for r in requests)
        if not clients and not requests:
            out += "Нічого не знайдено."
        context.user_data.clear()
        await update.message.reply_text(out, parse_mode="Markdown", reply_markup=menu())
    elif state == "qr":
        img = qrcode.make(text)
        bio = io.BytesIO()
        bio.name = "qr.png"
        img.save(bio, "PNG")
        bio.seek(0)
        context.user_data.clear()
        await update.message.reply_photo(bio, caption=f"🔳 QR-код\n{text}", reply_markup=menu())

async def clients_cmd(update, context):
    ensure_user(update)
    await show_clients(update, context)

async def requests_cmd(update, context):
    ensure_user(update)
    await show_requests(update, context)

async def stats_cmd(update, context):
    ensure_user(update)
    await show_stats(update, context)

async def health(request):
    return web.Response(text="OK")

async def start_http():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Health server listening on port %s", PORT)
    return runner

async def run_bot():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("clients", clients_cmd))
    application.add_handler(CommandHandler("requests", requests_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    log.info("Telegram bot started")
    return application

async def main():
    init_db()
    runner = await start_http()
    application = await run_bot()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        await runner.cleanup()
        conn.close()

if __name__ == "__main__":
    asyncio.run(main())
