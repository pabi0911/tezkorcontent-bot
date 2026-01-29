import asyncio
import re
from typing import Dict, Any, List, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

from config import BOT_TOKEN

import sessions
import dish_parser
import sheets

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# -------------------------
# UI
# -------------------------

def explain_meta(meta: dict) -> str:
    lines = []

    if meta.get("structured_detected"):
        lines.append("🔍 Сообщение распознано как структурированное")

    if meta.get("price_source"):
        price_map = {
            "multi_price_pairs": "нашел несколько вариантов цены (формат «вариант — цена»)",
            "explicit_price_attr": "нашел цену по ключу «Цена»",
            "fallback_from_text": "нашел цену в тексте",
        }
        lines.append("💰 Цена: " + price_map.get(meta["price_source"], meta["price_source"]))

    if meta.get("weight_source"):
        weight_map = {
            "explicit_weight_attr": "нашел вес по ключу «Вес»",
            "labeled_weight_block": "нашел вес в отдельном поле",
            "fallback_from_text": "определил вес из текста",
        }
        lines.append("⚖️ Вес: " + weight_map.get(meta["weight_source"], meta["weight_source"]))

    if meta.get("composition_source"):
        comp_map = {
            "composition_block": "взял состав из блока «Состав»",
            "explicit_composition_attr": "взял состав из строки",
            "description_used_as_composition": "использовал описание как состав",
            "fallback_from_text": "собрал состав из текста",
        }
        lines.append("🧾 Состав: " + comp_map.get(meta["composition_source"], meta["composition_source"]))

    if meta.get("ikpu_source"):
        ikpu_map = {
            "explicit_key": "нашел ИКПУ по ключу",
            "detected_anywhere": "нашел ИКПУ в тексте автоматически",
        }
        lines.append("🏷 ИКПУ: " + ikpu_map.get(meta["ikpu_source"], "найден"))

    return "\n".join(lines)

def render_dish_card(parsed: Dict[str, Any], photo_count: int) -> str:
    prices_text = "—"
    if parsed.get("prices"):
        prices_text = "\n".join(
        "{label} — {price}".format(
            label=p.get("label") or p.get("weight") or "—",
            price=str(p.get("price")).replace(",", " ")
        )
        for p in parsed["prices"]
    )
    elif parsed.get("price") is not None:
        prices_text = str(parsed["price"]).replace(",", " ")

    return (
        "📦 Блюдо разобрано\n\n"
        "Название: {name}\n"
        "Состав: {comp}\n"
        "Вес: {weight}\n"
        "Цены:\n{prices}\n"
        "ИКПУ: {ikpu}\n"
        "Фото: {photos}".format(
            name=parsed.get("name") or "—",
            comp=parsed.get("composition") or "—",
            weight=parsed.get("weight") or "—",
            prices=prices_text,
            ikpu=parsed.get("ikpu") or "—",
            photos=photo_count,
        )
    )


keyboard_start = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Ручной режим (по одному блюду)")],
        [KeyboardButton(text="📦 Массовая загрузка меню")],
        [KeyboardButton(text="ℹ️ Как пользоваться")],
    ],
    resize_keyboard=True
)

keyboard_manual_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Новое блюдо")],
        [KeyboardButton(text="✔️ Меню готово")],
        [KeyboardButton(text="🏠 Главное меню")],
    ],
    resize_keyboard=True
)

keyboard_bulk_collect = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✅ Меню загружено")],
        [KeyboardButton(text="🏠 Главное меню")],
    ],
    resize_keyboard=True
)

keyboard_dish_collect = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="✔️ Готово"), KeyboardButton(text="❌ Отменить")]],
    resize_keyboard=True
)

# inline edit (без "Завершить")
edit_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="✏️ Название", callback_data="edit_name"),
        InlineKeyboardButton(text="✏️ Состав", callback_data="edit_composition"),
    ],
    [
        InlineKeyboardButton(text="✏️ Вес", callback_data="edit_weight"),
        InlineKeyboardButton(text="✏️ Цены", callback_data="edit_prices"),
    ],
    [
        InlineKeyboardButton(text="✏️ ИКПУ", callback_data="edit_ikpu"),
    ],
])


# -------------------------
# Start / Home
# -------------------------

@dp.message(F.text == "/start")
async def start_cmd(message: Message):
    sessions.ensure_session(message.from_user.id)
    await message.answer("Привет! Выбери сценарий 👇", reply_markup=keyboard_start)


@dp.message(F.text == "🏠 Главное меню")
async def go_home(message: Message):
    sessions.clear_session(message.from_user.id)
    sessions.ensure_session(message.from_user.id)
    await message.answer("Ок, вернул в главное меню 👇", reply_markup=keyboard_start)


@dp.message(F.text == "ℹ️ Как пользоваться")
async def help_message(message: Message):
    await message.answer(
        "ℹ️ Как пользоваться\n\n"
        "1) Ручной режим — добавляешь блюда по одному, редактируешь, затем «Меню готово».\n"
        "2) Массовая загрузка — скидываешь всё меню подряд. Каждая позиция начинается с ФОТО.\n\n"
        "В обоих сценариях сначала нужна ссылка на Google Таблицу.",
        reply_markup=keyboard_start
    )


# -------------------------
# Scenario A (manual)
# -------------------------

@dp.message(F.text == "➕ Ручной режим (по одному блюду)")
async def manual_start(message: Message):
    sessions.start_manual_flow(message.from_user.id)
    await message.answer("Ок, ручной режим.\nПришли ссылку на Google Таблицу:")


# -------------------------
# Scenario B (bulk)
# -------------------------

@dp.message(F.text == "📦 Массовая загрузка меню")
async def bulk_start(message: Message):
    sessions.start_bulk_flow(message.from_user.id)
    await message.answer("Ок, массовая загрузка.\nПришли ссылку на Google Таблицу:")


# -------------------------
# Sheet link (routes by mode)
# -------------------------

@dp.message(F.text.startswith("https://docs.google.com/spreadsheets"))
async def set_sheet(message: Message):
    if not sessions.get_session(message.from_user.id):
        sessions.ensure_session(message.from_user.id)

    mode = sessions.get_mode(message.from_user.id)
    url = message.text.strip()
    sessions.set_sheet_url(message.from_user.id, url)

    if mode == "manual_wait_sheet":
        sessions.set_mode(message.from_user.id, "manual_menu")
        await message.answer("✅ Таблица привязана.\nТеперь добавляй блюда.", reply_markup=keyboard_manual_menu)
        return

    if mode == "bulk_wait_sheet":
        sessions.set_mode(message.from_user.id, "bulk_collect")
        await message.answer(
            "✅ Таблица привязана.\n\n"
            "Теперь отправь ВСЁ меню подряд:\n"
            "Фото → Название → Описание → Цена → Вес → ИКПУ\n\n"
            "• каждое блюдо начинается с фото\n"
            "• ИКПУ может отсутствовать\n\n"
            "Когда закончишь — нажми «✅ Меню загружено».",
            reply_markup=keyboard_bulk_collect
        )
        return

    await message.answer("Ссылка принята, но сначала выбери режим в главном меню.", reply_markup=keyboard_start)


# -------------------------
# Manual: New dish / cancel
# -------------------------

@dp.message(F.text == "➕ Новое блюдо")
async def manual_new_dish(message: Message):
    s = sessions.get_session(message.from_user.id)
    if not s or not s.get("menu", {}).get("sheet_url"):
        await message.answer("Сначала выбери режим и укажи ссылку на таблицу.", reply_markup=keyboard_start)
        return

    sessions.reset_dish(message.from_user.id)
    sessions.set_mode(message.from_user.id, "dish_collect")
    await message.answer(
        "Перешли данные и фото блюда.\nКогда закончишь — нажми «✔️ Готово».",
        reply_markup=keyboard_dish_collect
    )


@dp.message(F.text == "❌ Отменить")
async def cancel_dish(message: Message):
    mode = sessions.get_mode(message.from_user.id)
    if mode in ("dish_collect", "bulk_review"):
        sessions.reset_dish(message.from_user.id)
        if mode == "bulk_review":
            await message.answer("Ок, отменил правки. Нажми «✔️ Готово», чтобы перейти дальше.")
        else:
            await message.answer("❌ Блюдо отменено", reply_markup=keyboard_manual_menu)
        return

    await message.answer("Нечего отменять.", reply_markup=keyboard_start)


# -------------------------
# Collectors (manual + bulk)
# -------------------------

@dp.message(F.photo)
async def collect_photo(message: Message):
    user_id = message.from_user.id
    sessions.ensure_session(user_id)  # ✅ добавь

    mode = sessions.get_mode(user_id)

    if not message.photo:
        return

    file_id = message.photo[-1].file_id

    if mode == "dish_collect":
        sessions.add_photo(user_id, file_id)
        if message.caption:
            sessions.add_text(user_id, message.caption)
        return

    if mode == "bulk_collect":
        sessions.bulk_add_photo(user_id, {
            "file_id": file_id,
            "kind": "photo",
            "message_id": message.message_id,  # 👈 добавили
        })
        if message.caption:
            sessions.bulk_add_text(user_id, message.caption)
        return


@dp.message(F.document)
async def collect_document(message: Message):
    mode = sessions.get_mode(message.from_user.id)
    doc = message.document

    if not (doc and doc.mime_type and doc.mime_type.startswith("image/")):
        return

    if mode == "dish_collect":
        sessions.add_photo(message.from_user.id, doc.file_id)
        if message.caption:
            sessions.add_text(message.from_user.id, message.caption)
        return

    if mode == "bulk_collect":
        sessions.bulk_add_photo(message.from_user.id, {
            "file_id": doc.file_id,
            "kind": "document",
            "message_id": message.message_id,  # 👈 добавили
        })
        if message.caption:
            sessions.bulk_add_text(message.from_user.id, message.caption)
        return


# -------------------------
# Manual: Finish collect -> show card (edit)
# Bulk: Finish step -> confirm current position and move next
# -------------------------

@dp.message(F.text == "✔️ Готово")
async def ready_button(message: Message):
    mode = sessions.get_mode(message.from_user.id)

    # BULK REVIEW: подтвердить текущую позицию и показать следующую
    if mode == "bulk_review":
        await bulk_confirm_and_next(message)
        return

    # MANUAL dish_collect: собрать карточку
    if mode == "dish_collect":
        s = sessions.get_session(message.from_user.id)
        if not s:
            return

        parsed = dish_parser.parse(s["texts"])
        sessions.set_parsed(message.from_user.id, parsed)
        sessions.set_mode(message.from_user.id, "edit")

        card = render_dish_card(parsed, photo_count=len(s["photos"]))
        explanation = explain_meta(parsed["_meta"])

        await message.answer(
            f"{card}\n\n📌 Как я это понял:\n{explanation}",
            reply_markup=edit_keyboard
        )
        return


# -------------------------
# Inline edit
# -------------------------

@dp.callback_query(F.data.in_({"edit_name", "edit_composition", "edit_weight", "edit_prices", "edit_ikpu"}))
async def edit_field(callback: CallbackQuery):
    key_map = {
        "edit_name": ("name", "✏️ Введи новое название:"),
        "edit_composition": ("composition", "✏️ Введи новый состав/описание:"),
        "edit_weight": ("weight", "✏️ Введи вес/объем (например: 200 мл) или «—» чтобы очистить:"),
        "edit_prices": ("prices", "✏️ Введи цены построчно (каждая строка = вес - цена)\nНапр:\n400 г - 60000\n1000 г - 135000\n\nЧтобы очистить — «—»."),
        "edit_ikpu": ("ikpu", "✏️ Введи ИКПУ или «—» чтобы очистить:"),
    }

    field, prompt = key_map[callback.data]
    sessions.set_edit_mode(callback.from_user.id, field)
    await callback.message.answer(prompt)
    await callback.answer()


async def apply_edit(message: Message, edit_mode: str, parsed: Dict[str, Any]) -> None:
    s = sessions.get_session(message.from_user.id)
    text = (message.text or "").strip()

    if text in ("—", "-", ""):
        if edit_mode == "prices":
            parsed["prices"] = []
            parsed["price"] = None
        else:
            parsed[edit_mode] = None
    else:
        if edit_mode == "prices":
            new_prices: List[Dict[str, Any]] = []
            for line in text.splitlines():
                if "-" not in line:
                    continue
                left, right = line.split("-", 1)
                price_digits = re.sub(r"\D", "", right)
                if not price_digits:
                    continue
                new_prices.append({
                    "weight": left.strip(),
                    "price": int(price_digits)
                })

            parsed["prices"] = new_prices
            parsed["price"] = min(p["price"] for p in new_prices) if new_prices else None
            parsed["weight"] = None
        else:
            parsed[edit_mode] = text

    sessions.set_edit_mode(message.from_user.id, None)

    if sessions.get_mode(message.from_user.id) == "bulk_review":
        sessions.bulk_set_current_parsed(message.from_user.id, parsed)

    await message.answer("✅ Обновлено")

    user_id = message.from_user.id
    mode = sessions.get_mode(user_id)

    # ---------- BULK REVIEW ----------
    if mode == "bulk_review":
        pos = sessions.bulk_get_current(user_id)
        if pos and pos.get("photo"):
            photo_obj = pos["photo"]    
            reply_to_id = pos.get("photo_message_id")
            if isinstance(photo_obj, str):
                photo_obj = {"file_id": photo_obj, "kind": "photo"}

            card = render_dish_card(parsed, photo_count=1)
            explanation = explain_meta(parsed["_meta"])
            caption = f"{card}\n\n📌 Как я это понял:\n{explanation}"

            if photo_obj.get("kind") == "document":
                await bot.send_document(
                    chat_id=message.chat.id,
                    document=photo_obj["file_id"],
                    caption=caption,
                    reply_markup=edit_keyboard,
                    reply_to_message_id=reply_to_id,
                )
            else:
                await bot.send_photo(
                    chat_id=message.chat.id,
                    photo=photo_obj["file_id"],
                    caption=caption,
                    reply_markup=edit_keyboard,
                    reply_to_message_id=reply_to_id,
                )
            return
    
    # ---------- MANUAL MODE ----------
    if s and s.get("photos"):
        card = render_dish_card(parsed, photo_count=len(s["photos"]))
        explanation = explain_meta(parsed["_meta"])

        await bot.send_photo(
            chat_id=message.chat.id,
            photo=s["photos"][0],
            caption=f"{card}\n\n📌 Как я это понял:\n{explanation}",
            reply_markup=edit_keyboard
            )
        return

    # ---------- FALLBACK ----------
    await message.answer(
        render_dish_card(parsed, photo_count=0),
        reply_markup=edit_keyboard
    )
# -------------------------
# Export menu
# -------------------------

@dp.message(F.text == "✔️ Меню готово")
async def menu_ready(message: Message):
    s = sessions.get_session(message.from_user.id)
    if not s or not s.get("menu", {}).get("sheet_url"):
        await message.answer("Нет привязанной таблицы.", reply_markup=keyboard_start)
        return

    await message.answer("⏳ Выгружаю меню в Google Sheets…")
    sheet_url = s["menu"]["sheet_url"]
    rows_items = s["menu"]["rows"]

    sheets.export_rows(sheet_url, rows_items)

    sessions.clear_session(message.from_user.id)
    sessions.ensure_session(message.from_user.id)

    await message.answer("🎉 Меню успешно выгружено в Google Sheets", reply_markup=keyboard_start)


# -------------------------
# Bulk: done -> split(buffer) -> review first
# -------------------------

@dp.message(F.text == "✅ Меню загружено")
async def bulk_done(message: Message):
    user_id = message.from_user.id
    mode = sessions.get_mode(user_id)

    if mode != "bulk_collect":
        await message.answer("Сейчас массовая загрузка не активна.", reply_markup=keyboard_start)
        return

    # КЛЮЧЕВО: режем buffer -> positions (сверху вниз)
    positions = sessions.bulk_split_into_positions(user_id)

    if not positions:
        await message.answer(
            "Не нашёл ни одной позиции.\n"
            "Проверь, что каждое блюдо начинается с фото.",
            reply_markup=keyboard_start
        )
        return

    sessions.stop_bulk(user_id)           # больше не собираем новые элементы
    sessions.set_mode(user_id, "bulk_review")

    await message.answer("✅ Меню принято. Начинаю проверку позиций…", reply_markup=keyboard_dish_collect)
    await show_bulk_current(message)


async def show_bulk_current(message: Message) -> None:
    user_id = message.from_user.id
    pos = sessions.bulk_get_current(user_id)
    total = sessions.bulk_total(user_id)

    if not pos:
        sessions.set_mode(user_id, "manual_menu")
        await message.answer("✅ Позиции закончились. Нажми «Меню готово» для выгрузки.", reply_markup=keyboard_manual_menu)
        return

    s = sessions.get_session(user_id)
    idx = (s["bulk"]["current_index"] + 1) if s else 1
    texts = pos.get("texts", [])

    parsed = dish_parser.parse_bulk_position(texts)
    sessions.set_parsed(user_id, parsed)
    sessions.bulk_set_current_parsed(user_id, parsed)

    card = render_dish_card(parsed, photo_count=1)
    explanation = explain_meta(parsed["_meta"])

    caption = (
        f"📋 Проверка позиции {idx} из {total}\n\n"
        f"{card}\n\n"
        f"📌 Как я это понял:\n{explanation}"
    )
    

    photo_obj = pos["photo"]
    reply_to_id = pos.get("photo_message_id")

    # старые позиции могли сохраниться как строка (file_id) — подстрахуемся
    if isinstance(photo_obj, str):
        photo_obj = {"file_id": photo_obj, "kind": "photo"}

    if photo_obj.get("kind") == "document":
        await bot.send_document(
            chat_id=message.chat.id,
            document=photo_obj["file_id"],
            caption=caption,
            reply_markup=edit_keyboard,
            reply_to_message_id=reply_to_id,  # 👈 ВАЖНО
        )
    else:
        await bot.send_photo(
            chat_id=message.chat.id,
            photo=photo_obj["file_id"],
            caption=caption,
            reply_markup=edit_keyboard,
            reply_to_message_id=reply_to_id,  # 👈 ВАЖНО
        )

    await message.answer("Нажми «✔️ Готово», чтобы подтвердить и перейти к следующей.", reply_markup=keyboard_dish_collect)


async def bulk_confirm_and_next(message: Message) -> None:
    user_id = message.from_user.id
    pos = sessions.bulk_get_current(user_id)
    s = sessions.get_session(user_id)
    if not pos or not s:
        await message.answer("Нет позиции для подтверждения.", reply_markup=keyboard_start)
        return

    parsed = pos.get("parsed") or s.get("parsed") or {}

    # photo url
    photo_url = None
    photo_obj = pos.get("photo")
    file_id = None

    if isinstance(photo_obj, dict):
        file_id = photo_obj.get("file_id")
    elif isinstance(photo_obj, str):
        file_id = photo_obj

    if file_id:
        f = await bot.get_file(file_id)
        photo_url = "https://api.telegram.org/file/bot{token}/{path}".format(token=BOT_TOKEN, path=f.file_path)

    items = build_sheet_items(parsed, photo_url)
    sessions.add_menu_rows(user_id, items)

    sessions.bulk_next(user_id)
    await show_bulk_current(message)


def build_sheet_items(parsed: Dict[str, Any], photo_url: Optional[str]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    if parsed.get("prices"):
        for p in parsed["prices"]:
            items.append({
                "Позиция": parsed.get("name"),
                "Описание": parsed.get("composition"),
                "Вес": p.get("label") or p.get("weight"),
                "Цена": p.get("price"),
                "Код ИКПУ": parsed.get("ikpu"),
                "Картинка": photo_url,
            })
    else:
        items.append({
            "Позиция": parsed.get("name"),
            "Описание": parsed.get("composition"),
            "Вес": parsed.get("weight"),
            "Цена": parsed.get("price"),
            "Код ИКПУ": parsed.get("ikpu"),
            "Картинка": photo_url,
        })

    return items


# -------------------------
# Text collector + edit apply
# -------------------------

@dp.message(F.text)
async def collect_text(message: Message):
    user_id = message.from_user.id
    sessions.ensure_session(user_id)  # ✅ добавь

    mode = sessions.get_mode(user_id)
    text = (message.text or "").strip()
    if not text:
        return

    if mode == "bulk_collect":
        if text in ("✅ Меню загружено", "🏠 Главное меню"):
            return
        sessions.bulk_add_text(user_id, text)
        return

    if mode == "dish_collect":
        if text in ("✔️ Готово", "❌ Отменить"):
            return
        sessions.add_text(user_id, text)
        return

    s = sessions.get_session(user_id)
    if not s:
        return

    edit_mode = s.get("edit_mode")
    parsed = s.get("parsed")
    if edit_mode and parsed:
        await apply_edit(message, edit_mode, parsed)
        return

async def main():
    print("🤖 Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())