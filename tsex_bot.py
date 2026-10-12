import os
import re
import sqlite3
import logging
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, ContextTypes, filters)

# ====== SOZLAMALAR ======
BOT_TOKEN = os.getenv("BOT_TOKEN", "BU_YERGA_BOT_TOKENNI_YOZING")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))   # Oybek akaning Telegram ID raqami
DEFAULT_HOURS = 24                           # boshlang'ich o'chish vaqti (soat)
MAX_HOURS = 47                               # Telegram 48 soatdan eski xabarni o'chirtirmaydi
# ========================

logging.basicConfig(level=logging.INFO)

db = sqlite3.connect(os.getenv("DB_PATH", "tsex.db"), check_same_thread=False)
db.executescript("""
CREATE TABLE IF NOT EXISTS workers (user_id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, name TEXT, text TEXT, created TEXT
);
CREATE TABLE IF NOT EXISTS pending (chat_id INTEGER, message_id INTEGER, sent_at TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
""")
db.commit()


# ---------- yordamchi funksiyalar ----------
def is_admin(update: Update):
    return update.effective_user.id == ADMIN_ID


def get_name(user_id):
    row = db.execute("SELECT name FROM workers WHERE user_id=?", (user_id,)).fetchone()
    return row[0] if row else None


def get_hours():
    row = db.execute("SELECT value FROM settings WHERE key='hours'").fetchone()
    return float(row[0]) if row else DEFAULT_HOURS


def set_hours(h):
    db.execute("INSERT OR REPLACE INTO settings VALUES ('hours', ?)", (str(h),))
    db.commit()


def hours_text(h):
    if h < 1:
        return f"{int(h * 60)} daqiqa"
    return f"{h:g} soat"


def add_pending(chat_id, message_id):
    db.execute("INSERT INTO pending VALUES (?,?,?)",
               (chat_id, message_id, datetime.now().isoformat()))
    db.commit()


async def delete_rows(bot, rows):
    count = 0
    for chat_id, message_id in rows:
        try:
            await bot.delete_message(chat_id, message_id)
            count += 1
        except Exception as e:
            logging.warning(f"O'chirib bo'lmadi {chat_id}/{message_id}: {e}")
        db.execute("DELETE FROM pending WHERE chat_id=? AND message_id=?", (chat_id, message_id))
    db.commit()
    return count


def settings_keyboard():
    h = get_hours()
    variants = [0.5, 1, 2, 6, 12, 24]
    buttons = [InlineKeyboardButton(("✅ " if v == h else "") + hours_text(v), callback_data=f"h:{v}")
               for v in variants]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton("🗑 Hozir hammasini o'chirish", callback_data="clear")])
    return InlineKeyboardMarkup(rows)


ADMIN_HELP = (
    "Buyruqlar:\n"
    "/sozlama – o'chish vaqtini tanlash yoki hozir o'chirish\n"
    "/vaqt 3 – o'zingiz soat yozasiz (masalan 3 soat)\n"
    "/tozala – ishchilardagi barcha yozuvlarni hozir o'chirish\n"
    "/bugun – bugungi hisobot\n"
    "/kecha – kechagi hisobot\n"
    "/ishchilar – ishchilar ro'yxati"
)


# ---------- buyruqlar ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await update.message.reply_text(
            "Assalomu alaykum, Oybek aka!\nIshchilar yozgan hamma narsa sizga keladi "
            "va sizda o'chmaydi.\n\n"
            f"Hozir ishchilarda {hours_text(get_hours())}dan keyin o'chadi.\n\n" + ADMIN_HELP
        )
        return
    name = get_name(update.effective_user.id)
    if name:
        await update.message.reply_text(
            f"{name}, xush kelibsiz!\nOrtgan yoki tushirgan narsangizni yozing.\n"
            "Masalan: 200 ta komplekt lesa ortdim"
        )
    else:
        await update.message.reply_text("Assalomu alaykum! Ism-familiyangizni yozing:")


async def sozlama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await update.message.reply_text(
        f"Hozirgi sozlama: ishchilarda yozgandan {hours_text(get_hours())} keyin o'chadi.\n"
        "Yangi vaqtni tanlang:",
        reply_markup=settings_keyboard()
    )


async def vaqt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    try:
        h = float(context.args[0].replace(",", "."))
        if h <= 0 or h > MAX_HOURS:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text(
            f"Soatni to'g'ri yozing, masalan: /vaqt 2\n"
            f"(0.5 = yarim soat, eng ko'pi {MAX_HOURS} soat)"
        )
        return
    set_hours(h)
    await update.message.reply_text(
        f"✅ Saqlandi. Endi ishchilarda yozgandan {hours_text(h)} keyin o'chadi."
    )


async def tozala(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    rows = db.execute("SELECT chat_id, message_id FROM pending").fetchall()
    n = await delete_rows(context.bot, rows)
    await update.message.reply_text(f"🗑 Ishchilardan {n} ta xabar o'chirildi. Sizda hammasi turibdi.")


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer()
        return
    if q.data == "clear":
        rows = db.execute("SELECT chat_id, message_id FROM pending").fetchall()
        n = await delete_rows(context.bot, rows)
        await q.answer(f"{n} ta xabar o'chirildi")
        await q.edit_message_text(f"🗑 Ishchilardan {n} ta xabar o'chirildi. Sizda hammasi turibdi.")
        return
    h = float(q.data.split(":")[1])
    set_hours(h)
    await q.answer("Saqlandi")
    await q.edit_message_text(
        f"✅ Saqlandi. Endi ishchilarda yozgandan {hours_text(h)} keyin o'chadi.",
        reply_markup=settings_keyboard()
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = update.effective_user.id
    text = msg.text.strip()

    if uid == ADMIN_ID:
        await msg.reply_text(ADMIN_HELP)
        return

    name = get_name(uid)
    if not name:  # birinchi yozgani — ismi
        db.execute("INSERT INTO workers VALUES (?,?)", (uid, text))
        db.commit()
        await msg.reply_text(
            f"Rahmat, {text}! Endi ortgan yoki tushirgan narsangizni yozing.\n"
            "Masalan: 56 ta komplekt lesa tushirdim"
        )
        return

    now = datetime.now()
    db.execute("INSERT INTO reports (user_id,name,text,created) VALUES (?,?,?,?)",
               (uid, name, text, now.isoformat()))
    db.commit()

    # Oybek akaga (u yerda o'chmaydi)
    await context.bot.send_message(ADMIN_ID, f"👷 {name}\n🕒 {now:%d.%m.%Y %H:%M}\n\n{text}")

    reply = await msg.reply_text("✅ Qabul qilindi, Oybek akaga yuborildi")
    add_pending(msg.chat_id, msg.message_id)
    add_pending(reply.chat_id, reply.message_id)


async def cleanup(context: ContextTypes.DEFAULT_TYPE):
    limit = (datetime.now() - timedelta(hours=get_hours())).isoformat()
    rows = db.execute("SELECT chat_id, message_id FROM pending WHERE sent_at<=?", (limit,)).fetchall()
    if rows:
        await delete_rows(context.bot, rows)


# ---------- hisobotlar ----------
def make_report(day):
    start = datetime(day.year, day.month, day.day)
    end = start + timedelta(days=1)
    rows = db.execute(
        "SELECT name, text, created FROM reports WHERE created>=? AND created<? ORDER BY created",
        (start.isoformat(), end.isoformat())).fetchall()
    if not rows:
        return f"📅 {day:%d.%m.%Y} — hech narsa yozilmagan."

    lines = [f"📅 {day:%d.%m.%Y} hisobot\n"]
    totals = {}
    for name, text, created in rows:
        t = datetime.fromisoformat(created)
        lines.append(f"{t:%H:%M} | {name}: {text}")
        nums = re.findall(r"\d+", text)
        if nums:
            n = int(nums[0])
            low = text.lower()
            tot = totals.setdefault(name, [0, 0])
            if "ort" in low:
                tot[0] += n
            elif "tush" in low:
                tot[1] += n
    if totals:
        lines.append("\n📊 Jami (taxminiy):")
        for name, (o, t) in totals.items():
            lines.append(f"{name}: ortdi {o}, tushirdi {t}")
    return "\n".join(lines)


async def send_long(update, text):
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i:i + 4000])


async def bugun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await send_long(update, make_report(datetime.now()))


async def kecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await send_long(update, make_report(datetime.now() - timedelta(days=1)))


async def ishchilar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    rows = db.execute("SELECT name FROM workers ORDER BY name").fetchall()
    text = ("👷 Ishchilar:\n" + "\n".join(f"{i}. {r[0]}" for i, r in enumerate(rows, 1))
            if rows else "Hali ishchi yo'q.")
    await update.message.reply_text(text)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("sozlama", sozlama))
    app.add_handler(CommandHandler("vaqt", vaqt))
    app.add_handler(CommandHandler("tozala", tozala))
    app.add_handler(CommandHandler("bugun", bugun))
    app.add_handler(CommandHandler("kecha", kecha))
    app.add_handler(CommandHandler("ishchilar", ishchilar))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.job_queue.run_repeating(cleanup, interval=60, first=10)  # har daqiqada tekshiradi
    print("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
