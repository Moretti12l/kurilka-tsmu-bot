import asyncio
import os
import sqlite3
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ChatJoinRequest
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()
GROUP_ID_RAW = os.getenv("GROUP_ID", "").strip()
DB_PATH = os.getenv("DB_PATH", "kurilka.sqlite3")

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN")
# На первом запуске ADMIN_ID и GROUP_ID можно оставить равными 0.
# Команды /myid и /chatid помогут узнать значения, затем задайте их в окружении.
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW else 0
GROUP_ID = int(GROUP_ID_RAW) if GROUP_ID_RAW else 0

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT NOT NULL,
                photo_file_id TEXT NOT NULL,
                invite_link TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_app_user_status
            ON applications(user_id, status)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id INTEGER PRIMARY KEY,
                stage TEXT NOT NULL,
                full_name TEXT
            )
        """)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def set_stage(user_id: int, stage: str, full_name: str = None):
    with db() as conn:
        conn.execute("""
            INSERT INTO user_sessions(user_id, stage, full_name)
            VALUES(?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET stage=excluded.stage,
                full_name=excluded.full_name
        """, (user_id, stage, full_name))


def get_stage(user_id: int):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM user_sessions WHERE user_id=?", (user_id,)
        ).fetchone()


def clear_stage(user_id: int):
    with db() as conn:
        conn.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))


def active_application(user_id: int):
    with db() as conn:
        return conn.execute("""
            SELECT * FROM applications
            WHERE user_id=? AND status IN ('link_sent', 'waiting_review')
            ORDER BY id DESC LIMIT 1
        """, (user_id,)).fetchone()


def create_application(user_id, username, full_name, photo_file_id, invite_link):
    timestamp = now()
    with db() as conn:
        cur = conn.execute("""
            INSERT INTO applications
            (user_id, username, full_name, photo_file_id, invite_link,
             status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'link_sent', ?, ?)
        """, (user_id, username, full_name, photo_file_id,
              invite_link, timestamp, timestamp))
        return cur.lastrowid


def get_application(app_id: int):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM applications WHERE id=?", (app_id,)
        ).fetchone()


def update_status(app_id: int, status: str):
    with db() as conn:
        conn.execute("""
            UPDATE applications SET status=?, updated_at=? WHERE id=?
        """, (status, now(), app_id))


def stats_text():
    with db() as conn:
        rows = conn.execute("""
            SELECT status, COUNT(*) AS amount
            FROM applications GROUP BY status
        """).fetchall()
    counts = {r["status"]: r["amount"] for r in rows}
    total = sum(counts.values())
    return (
        "📊 <b>Статистика «Курилка (Чистая)»</b>\n\n"
        f"Всего анкет: <b>{total}</b>\n"
        f"Ожидают решения: <b>{counts.get('waiting_review', 0)}</b>\n"
        f"Ссылка выдана, заявка ещё не подана: <b>{counts.get('link_sent', 0)}</b>\n"
        f"Одобрено: <b>{counts.get('approved', 0)}</b>\n"
        f"Отклонено: <b>{counts.get('rejected', 0)}</b>"
    )


def review_keyboard(app_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve:{app_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{app_id}")
    ]])


@dp.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    if ADMIN_ID and user_id == ADMIN_ID:
        await message.answer(
            "Панель администратора «Курилка (Чистая)»\n\n"
            "/stats — статистика\n"
            "/pending — ожидающие проверки\n"
            "/myid — ваш Telegram ID"
        )
        return

    existing = active_application(user_id)
    if existing:
        if existing["status"] == "waiting_review":
            await message.answer("Ваша заявка уже поступила администратору и ожидает проверки.")
        else:
            await message.answer(
                "Вы уже заполнили анкету. Используйте ранее полученную ссылку "
                "для подачи заявки на вступление."
            )
        return

    set_stage(user_id, "name")
    await message.answer(
        "Здравствуйте! Чтобы подать заявку в группу «Курилка (Чистая)», "
        "заполните короткую анкету.\n\n"
        "✍️ Напишите ваши <b>Фамилию, Имя и Отчество полностью</b>."
    )


@dp.message(Command("cancel"))
async def cancel(message: Message):
    clear_stage(message.from_user.id)
    await message.answer("Заполнение анкеты отменено. Чтобы начать заново, отправьте /start.")


@dp.message(Command("myid"))
async def myid(message: Message):
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


@dp.message(Command("chatid"))
async def chatid(message: Message):
    await message.answer(f"ID этого чата: <code>{message.chat.id}</code>")


@dp.message(Command("stats"))
async def stats(message: Message):
    if not ADMIN_ID or message.from_user.id != ADMIN_ID:
        return
    await message.answer(stats_text())


@dp.message(Command("pending"))
async def pending(message: Message):
    if not ADMIN_ID or message.from_user.id != ADMIN_ID:
        return
    with db() as conn:
        rows = conn.execute("""
            SELECT id, full_name, username, status, created_at
            FROM applications
            WHERE status='waiting_review'
            ORDER BY id DESC LIMIT 20
        """).fetchall()
    if not rows:
        await message.answer("Сейчас нет заявок, ожидающих проверки.")
        return
    for row in rows:
        username = f"@{row['username']}" if row["username"] else "не указан"
        await message.answer(
            f"Заявка <b>#{row['id']}</b>\n"
            f"ФИО: {row['full_name']}\n"
            f"Telegram: {username}\n"
            f"Создана: {row['created_at']}",
            reply_markup=review_keyboard(row["id"])
        )


@dp.message(F.text)
async def receive_name(message: Message):
    user_id = message.from_user.id
    if user_id == ADMIN_ID:
        return
    session = get_stage(user_id)
    if not session or session["stage"] != "name":
        return
    full_name = " ".join(message.text.split()).strip()
    if len(full_name) < 5 or len(full_name) > 150 or len(full_name.split()) < 2:
        await message.answer("Пожалуйста, укажите ФИО полностью (как минимум имя и фамилию).")
        return
    set_stage(user_id, "photo", full_name)
    await message.answer(
        "Спасибо! Теперь прикрепите <b>скриншот личного кабинета TSMU</b>.\n\n"
        "Отправьте его именно как фотографию или изображение. "
        "Перед отправкой скройте пароли и лишние персональные данные."
    )


@dp.message(F.photo)
async def receive_photo(message: Message):
    user_id = message.from_user.id
    if user_id == ADMIN_ID:
        return
    session = get_stage(user_id)
    if not session or session["stage"] != "photo":
        return

    photo_file_id = message.photo[-1].file_id
    full_name = session["full_name"]
    username = message.from_user.username

    try:
        invite = await bot.create_chat_invite_link(
            chat_id=GROUP_ID,
            name=f"Анкета пользователя {user_id}",
            creates_join_request=True
        )
    except Exception:
        await message.answer(
            "Не удалось создать ссылку для вступления. "
            "Пожалуйста, сообщите администратору или попробуйте позже."
        )
        await bot.send_message(
            ADMIN_ID,
            "⚠️ Не удалось создать пригласительную ссылку. "
            "Проверьте права бота в группе и правильность GROUP_ID."
        )
        return

    app_id = create_application(
        user_id, username, full_name, photo_file_id, invite.invite_link
    )
    clear_stage(user_id)

    await message.answer(
        "✅ Анкета заполнена!\n\n"
        "Теперь нажмите на ссылку ниже и отправьте заявку на вступление. "
        "В группу вы попадёте после проверки администратором.\n\n"
        f"🔗 <a href=\"{invite.invite_link}\">Подать заявку на вступление</a>\n\n"
        "Не пересылайте эту ссылку другим людям."
    )


@dp.message(F.document)
async def reject_document(message: Message):
    session = get_stage(message.from_user.id)
    if session and session["stage"] == "photo":
        await message.answer("Пожалуйста, отправьте скриншот как фотографию, а не как файл.")


@dp.chat_join_request()
async def on_join_request(request: ChatJoinRequest):
    if not GROUP_ID or request.chat.id != GROUP_ID:
        return

    link = request.invite_link.invite_link if request.invite_link else None
    if not link:
        await bot.decline_chat_join_request(GROUP_ID, request.from_user.id)
        return

    with db() as conn:
        app = conn.execute("""
            SELECT * FROM applications
            WHERE invite_link=? AND user_id=? AND status='link_sent'
            ORDER BY id DESC LIMIT 1
        """, (link, request.from_user.id)).fetchone()

    if not app:
        # В группу допускаются только пользователи, прошедшие анкету.
        await bot.decline_chat_join_request(GROUP_ID, request.from_user.id)
        return

    update_status(app["id"], "waiting_review")
    username = f"@{app['username']}" if app["username"] else "не указан"

    caption = (
        f"🆕 <b>Новая заявка #{app['id']}</b>\n\n"
        f"<b>ФИО:</b> {app['full_name']}\n"
        f"<b>Telegram:</b> {username}\n"
        f"<b>ID:</b> <code>{app['user_id']}</code>\n\n"
        "Проверьте скриншот личного кабинета и примите решение."
    )
    await bot.send_photo(
        chat_id=ADMIN_ID,
        photo=app["photo_file_id"],
        caption=caption,
        reply_markup=review_keyboard(app["id"])
    )


@dp.callback_query(F.data.startswith("approve:"))
async def approve_application(callback: CallbackQuery):
    if not ADMIN_ID or callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    app_id = int(callback.data.split(":")[1])
    app = get_application(app_id)
    if not app or app["status"] != "waiting_review":
        await callback.answer("Заявка уже обработана или не найдена.", show_alert=True)
        return
    try:
        await bot.approve_chat_join_request(GROUP_ID, app["user_id"])
    except Exception as exc:
        await callback.answer("Не удалось одобрить заявку. Проверьте её статус.", show_alert=True)
        return

    update_status(app_id, "approved")
    try:
        await bot.send_message(app["user_id"], "🎉 Ваша заявка одобрена! Добро пожаловать в «Курилка (Чистая)».")
    except Exception:
        pass
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Заявка одобрена.")
    await callback.message.answer(f"✅ Заявка #{app_id} одобрена.")


@dp.callback_query(F.data.startswith("reject:"))
async def reject_application(callback: CallbackQuery):
    if not ADMIN_ID or callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    app_id = int(callback.data.split(":")[1])
    app = get_application(app_id)
    if not app or app["status"] != "waiting_review":
        await callback.answer("Заявка уже обработана или не найдена.", show_alert=True)
        return
    try:
        await bot.decline_chat_join_request(GROUP_ID, app["user_id"])
    except Exception:
        # Если заявка уже исчезла, решение всё равно фиксируется в журнале.
        pass

    update_status(app_id, "rejected")
    try:
        await bot.send_message(app["user_id"], "Ваша заявка в «Курилка (Чистая)» отклонена.")
    except Exception:
        pass
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Заявка отклонена.")
    await callback.message.answer(f"❌ Заявка #{app_id} отклонена.")


async def main():
    init_db()
    print("KurilkaTSMU_bot запущен.")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
