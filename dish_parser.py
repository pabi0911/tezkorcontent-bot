# -*- coding: utf-8 -*-
"""
dish_parser.py

Универсальный парсер сообщений для TezkorContent bot.

Цели:
- Вытаскивать поля: name, composition, weight, price/prices, ikpu
- Понимать "ключ: значение" и "ключ значение"
- Понимать "Состав" / "Состав:" как заголовок и состав "в столбик"
- Находить ИКПУ как 17 цифр в любом месте текста
- Работать на Python 3.9 (без `str | None`)
"""

import re
from typing import List, Dict, Any, Tuple, Optional

# -----------------------------
# Ключевые слова / алиасы
# -----------------------------
# Важно: тут специально много вариантов (RU + латиница + типичные опечатки для Узбекистана)
KEY_ALIASES: Dict[str, Tuple[str, ...]] = {
    "name": (
        "наименование", "название", "имя", "товар", "позиция",
        "nomi", "nom", "name", "title", "naming",
    ),
    "composition": (
        "состав", "ингредиенты", "ингр", "сост", "композиция",
        "tarkib", "tarkibi", "ingred", "ingredients",
    ),
    "description": (
        "описание", "опис", "описание товара",
        "tavsif", "ta'rif", "tarif", "description", "desc",
    ),
    "price": (
        "цена", "стоимость", "сумма", "цена сум", "цена (сум)",
        "narx", "price", "cost",
    ),
    "weight": (
        "вес", "масса", "объем", "объём", "порция", "выход",
        "og'irlik", "ogirlik", "vazn", "hajm", "weight", "size",
    ),
    "category": (
        "категория", "раздел", "группа",
        "kategoriya", "category",
    ),
    "ikpu": (
        "икпу", "ikpu", "ipku", "ипку"
    ),
}

# Эти ключи используются как стоп-слова при сборе многострочного блока
STOP_KEYS = tuple(sorted({k for vs in KEY_ALIASES.values() for k in vs}))

# -----------------------------
# Регулярки
# -----------------------------
_UNITS = r"(г|гр|g|gr|kg|кг|mg|мг|ml|мл|l|л|oz|шт|pcs|pc|piece|pieces|dona|ta)"
_WEIGHT_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*" + _UNITS + r"\b", re.IGNORECASE)
_WEIGHT_ATTR_RE = re.compile(
    r"(?i)\b(?:вес|вес\s*нетто|нетто|weight|massa|mass)\b\s*[:\-]?\s*(\d+(?:[.,]\d+)?(?:\s*[a-zа-яё\.]{0,6})?)"
)
# цена: строка из цифр/пробелов/точек/запятых (не слишком длинная)
_PRICE_LINE_RE = re.compile(r"^\s*\d[\d\s.,]{1,}\d\s*(?:сум|sum|som|so'm|uzs)?\s*$", re.IGNORECASE)

# ИКПУ — 17 цифр
_IKPU_LINE_RE = re.compile(r"^\s*\d{17}\s*$")
_IKPU_ANY_RE = re.compile(r"\b\d{17}\b")

# универсальная пара "вариант — цена" (вариант = вес/начинка/размер/что угодно)
_PAIR_RE = re.compile(
    r"^(?P<label>.+?)\s*[—\-–]\s*(?P<price>\d[\d\s.,]*\d)\s*$",
    re.IGNORECASE
)

# "ключ:" или "ключ -" или "ключ —"
_LABELED_RE = re.compile(
    r"^\s*(?P<key>[^\n\r:—\-–]{2,40}?)\s*[:—\-–]\s*(?P<value>.+?)\s*$",
    re.IGNORECASE
)

# "ключ значение" (без двоеточия) — только для известных коротких ключей
_LABELED_SPACE_RE = re.compile(
    r"^\s*(?P<key>[^\n\r:—\-–]{2,40}?)\s+(?P<value>.+?)\s*$",
    re.IGNORECASE
)

# Калорийность/прочие хвосты, на которых стоит остановить состав
_COMPOSITION_STOP_RE = re.compile(r"\b(ккал|калл|кал|kcal|cal)\b", re.IGNORECASE)


# -----------------------------
# Утилиты
# -----------------------------
def _canon_key(raw: str) -> Optional[str]:
    """Пытаемся сопоставить сырое имя ключа каноническому."""
    k = raw.strip().lower()
    k = re.sub(r"\s+", " ", k)
    for canon, aliases in KEY_ALIASES.items():
        for a in aliases:
            if k == a:
                return canon
    return None


def normalize_texts(texts: List[str]) -> List[str]:
    lines: List[str] = []
    for text in texts:
        if not text:
            continue
        for line in str(text).splitlines():
            line = line.strip()
            if line:
                lines.append(line)
    return lines


def _digits_to_int(s: str) -> Optional[int]:
    digits = re.sub(r"\D", "", s or "")
    if 3 <= len(digits) <= 9:
        try:
            return int(digits)
        except Exception:
            return None
    return None



def _normalize_weight_value(raw: str) -> Optional[str]:
    """
    Нормализует значение веса/объема.
    Поддерживает:
    - '450 г', '450гр', '0,25л', '1.5 кг'
    - '450' (без единиц) -> '450 г' (по умолчанию)
    """
    if not raw:
        return None

    raw = str(raw).strip()
    if not raw:
        return None

    m = _WEIGHT_RE.search(raw)
    if m:
        return m.group(0).strip()

    # если единиц нет — возьмем число и по умолчанию считаем граммами
    m2 = re.search(r"\b\d+(?:[.,]\d+)?\b", raw)
    if m2:
        val = m2.group(0)
        return f"{val} г"

    return None

def _extract_labeled_fields(lines: List[str]) -> Tuple[Dict[str, str], List[str]]:
    """
    Достает пары ключ->значение из строк.

    Поддерживает:
    - "ключ: значение"
    - "ключ - значение"
    - "ключ значение" (для коротких ключей типа "цена 9000", "икпу 1020...", "вес 120гр")
    - "Состав" / "Состав:" как заголовок без значения — заголовок вынимаем, а состав оставляем
      для дальнейшего чтения блоком.
    """
    labeled: Dict[str, str] = {}
    remaining: List[str] = []

    # заранее — множество всех алиасов (для быстрого сравнения)
    all_aliases = {a for vs in KEY_ALIASES.values() for a in vs}

    for line in lines:
        low = line.strip().lower()

        # 1) ключ: значение / ключ - значение
        m = _LABELED_RE.match(line)
        if m:
            raw_key = m.group("key")
            value = m.group("value").strip()
            canon = _canon_key(raw_key)
            if canon:
                # особый случай: "состав:" может начинаться блоком и продолжаться ниже
                if canon == "composition" and not value:
                    # заголовок состава — убираем строку из remaining, но ничего не кладем
                    continue
                labeled[canon] = value
                continue

        # 2) ключ значение (без двоеточия) — только если первый токен = известный алиас
        # Пример: "цена 9.000" / "икпу 10202003001000000" / "категория гарнир"
        # Важно: это может быть и "состав" без ":" — тогда это заголовок состава.
        parts = low.split()
        if parts:
            first = parts[0]
            if first in all_aliases:
                canon = _canon_key(first)
                if canon:
                    if canon == "composition" and len(parts) == 1:
                        # "состав" как заголовок
                        continue
                    if len(parts) >= 2:
                        value = line.strip()[len(parts[0]):].strip()
                        labeled[canon] = value
                        continue

        remaining.append(line)

    return labeled, remaining


def collect_block(lines: List[str], header_key: str) -> List[str]:
    """
    Собирает многострочный блок после строки 'Ключ' или 'Ключ:' до следующего ключа.
    Устойчиво к 'Ключ' / 'Ключ:' / 'Ключ :'
    """
    result: List[str] = []
    collecting = False

    # алиасы для заголовка
    header_key = header_key.strip().lower()
    header_aliases = KEY_ALIASES.get(header_key, (header_key,))

    for line in lines:
        low = line.lower().strip()

        # старт блока:
        # - "состав:" или "состав :"
        # - "состав" (в одиночку)
        is_header = False
        for a in header_aliases:
            if re.match(r"^\s*{0}\s*:\s*".format(re.escape(a)), low):
                is_header = True
                collecting = True
                rest = line.split(":", 1)[1].strip()
                if rest:
                    result.append(rest)
                break
            if low == a:
                is_header = True
                collecting = True
                break

        if is_header:
            continue

        if collecting:
            # стоп по любому другому ключу
            if any(re.match(r"^\s*{0}\s*[:—\-–]".format(re.escape(k)), low) for k in STOP_KEYS):
                break
            if low.split(" ", 1)[0] in STOP_KEYS and len(low.split()) >= 2:
                # "цена 9000", "категория гарнир"
                break
            result.append(line)

    return result


def extract_composition_from_lines(
    lines: List[str],
    *,
    stop_on_keys: bool = True
) -> Optional[str]:
    """
    Универсально извлекает состав из последовательности строк:
    - поддерживает состав в столбик
    - останавливается на цене / ИКПУ / других атрибутах / калорийности
    """
    ingredients: List[str] = []

    for line in lines:
        low = line.lower().strip()
        if not low:
            continue

        # стоп-условия
        if _IKPU_ANY_RE.search(line):
            break
        if _PAIR_RE.match(line):
            break
        if _PRICE_LINE_RE.match(line):
            break
        if _COMPOSITION_STOP_RE.search(line):
            break

        if stop_on_keys:
            # если встречаем начало другого атрибута — заканчиваем
            if any(re.match(r"^\s*{0}\s*[:—\-–]".format(re.escape(k)), low) for k in STOP_KEYS):
                break
            if low.split(" ", 1)[0] in STOP_KEYS and len(low.split()) >= 2:
                break

        # берем только строки с буквами
        if any(ch.isalpha() for ch in line):
            ingredients.append(line.strip())

    if ingredients:
        # если прислали в столбик — превращаем в список через запятую
        return ", ".join(ingredients)

    return None


def _detect_structured(labeled: Dict[str, str], lines: List[str]) -> bool:
    """
    Авто-детект "структурированного" сообщения.
    Идея: если в тексте явно присутствуют атрибуты — используем labeled/blocks,
    иначе работаем как со свободным текстом.
    """
    if labeled:
        # если есть хоть 2 поля, или есть "категория/икпу/цена" — это точно структура
        if len(labeled) >= 2:
            return True
        if any(k in labeled for k in ("price", "ikpu", "category", "weight")):
            return True

    # "состав" заголовком (без двоеточия) тоже считаем структурой
    low_lines = [l.lower().strip() for l in lines]
    if any(l in KEY_ALIASES["composition"] for l in low_lines):
        return True

    return False


# -----------------------------
# Основной парсер (старый режим / ручной)
# -----------------------------
def parse(texts: List[str]) -> Dict[str, Any]:
    """
    Универсальный парсер (ручной режим): понимает ключи 'Состав', 'Цена' и т.п.,
    и умеет fallback на свободный текст.
    """
    result: Dict[str, Any] = {
        "name": None,
        "composition": None,
        "weight": None,     # если вес один
        "price": None,      # минимальная цена
        "prices": [],       # [{weight, price}]
        "ikpu": None,
        "_meta": {
            "weight_source": None,
            "price_source": None,
            "composition_source": None,
            "ikpu_source": None,
            "structured_detected": False,
            }
    }

    lines = normalize_texts(texts)
    if not lines:
        return result

    labeled, remaining_lines = _extract_labeled_fields(lines)
    structured = _detect_structured(labeled, lines)
    result["_meta"]["structured_detected"] = structured

    full_text = "\n".join(lines).lower()

    # --- IKPU (17 цифр в любом месте) ---
    m_any = _IKPU_ANY_RE.search("\n".join(lines))
    if m_any:
        result["ikpu"] = m_any.group(0)
        result["_meta"]["ikpu_source"] = "detected_anywhere"

    # --- MULTI PRICE (вариант — цена) ---
    for line in lines:
        m = _PAIR_RE.match(line)
        if not m:
            continue
        price_val = _digits_to_int(m.group("price"))
        if price_val is not None:
            result["prices"].append({"weight": m.group("label").strip(), "price": price_val})

    if result["prices"]:
        result["price"] = min(p["price"] for p in result["prices"])
        result["weight"] = None
        result["_meta"]["price_source"] = "multi_price_pairs"

    # --- цена / вес из labeled (если структурировано) ---
    if structured:
        if not result["price"] and "price" in labeled:
            pv = _digits_to_int(labeled["price"])
            if pv is not None:
                result["price"] = pv
                result["_meta"]["price_source"] = "explicit_price_attr"

        if not result["weight"] and "weight" in labeled:
            mw = _WEIGHT_RE.search(labeled["weight"])
            if mw:
                result["weight"] = mw.group(0).strip()
                result["_meta"]["weight_source"] = "explicit_weight_attr"

    # --- название ---
    if "name" in labeled and labeled["name"]:
        result["name"] = labeled["name"].strip()
    else:
        for line in lines:
            low = line.lower().strip()
            if not low:
                continue
            if any(char.isdigit() for char in low):
                continue
            # не берем строки-ключи
            if low in STOP_KEYS:
                continue
            if any(re.match(r"^\s*{0}\s*[:—\-–]".format(re.escape(k)), low) for k in STOP_KEYS):
                continue
            result["name"] = line.strip()
            break

    # --- состав ---
    # 1) если есть "Состав/Таркиб" блоком — читаем блок
    comp_block = collect_block(lines, "composition")
    if comp_block:
        comp = extract_composition_from_lines(comp_block)
        if comp:
            result["composition"] = comp
            result["_meta"]["composition_source"] = "composition_block"
            

    # 2) если нет состава, но labeled composition есть
    if not result["composition"] and "composition" in labeled and labeled["composition"]:
        # может быть перечисление через пробел/запятую в одной строке
        result["composition"] = labeled["composition"].strip()
        result["_meta"]["composition_source"] = "explicit_composition_attr"

    # 3) если нет состава, но есть описание — кладем в composition (чтобы не терять)
    if not result["composition"] and "description" in labeled and labeled["description"]:
        result["composition"] = labeled["description"].strip()
        result["_meta"]["composition_source"] = "description_used_as_composition"

    # 4) fallback состава (со всего текста)
    if not result["composition"]:
        comp = extract_composition_from_lines(remaining_lines if structured else lines)
        if comp:
            result["composition"] = comp
            result["_meta"]["composition_source"] = "fallback_from_text"
        else:
            # старый fallback: возьмем самую длинную "буквенную" строку, которая не похожа на цену/вес/икпу
            candidates: List[str] = []
            for line in (remaining_lines if structured else lines):
                low = line.lower()
                if line == result["name"]:
                    continue
                if _IKPU_ANY_RE.search(line):
                    continue
                if _PAIR_RE.match(line):
                    continue
                if _PRICE_LINE_RE.match(line):
                    continue
                if _WEIGHT_RE.search(line):
                    continue
                if any(k in low for k in STOP_KEYS):
                    continue
                if any(ch.isalpha() for ch in line):
                    candidates.append(line)
            if candidates:
                candidates.sort(key=len, reverse=True)
                result["composition"] = candidates[0].strip()
                result["_meta"]["composition_source"] = "legacy_longest_line_fallback"

    # --- цены / вес (если не нашли выше) ---
    if not result["prices"] and not result["price"]:
        # один вес
        if not result["weight"]:
            mw = _WEIGHT_RE.search(full_text)
            if mw:
                result["weight"] = mw.group(0).strip()
                result["_meta"]["weight_source"] = "fallback_from_text"

        # одна цена
        candidates_int: List[int] = []
        for line in lines:
            l = line.lower().strip()
            if _IKPU_ANY_RE.search(l):
                continue
            if _WEIGHT_RE.search(l):
                continue
            if _PRICE_LINE_RE.match(l):
                pv = _digits_to_int(l)
                if pv is not None:
                    candidates_int.append(pv)
                continue
            for p in re.findall(r"\d[\d\s.,]{2,}\d", l):
                pv = _digits_to_int(p)
                if pv is not None:
                    candidates_int.append(pv)
        if candidates_int:
            result["price"] = min(candidates_int)
            result["_meta"]["price_source"] = "fallback_from_text"

    return result


# -----------------------------
# Парсер позиции в "массовом" режиме
# -----------------------------
def parse_bulk_position(texts: List[str]) -> Dict[str, Any]:
    """
    Массовый режим: тот же словарь, но чуть более "агрессивно" использует структуру,
    если она обнаружена.
    """
    parsed: Dict[str, Any] = {
        "name": None,
        "composition": None,
        "weight": None,
        "price": None,
        "prices": [],
        "ikpu": None,
        "_meta": {
            "weight_source": None,
            "price_source": None,
            "composition_source": None,
            "ikpu_source": None,
            "structured_detected": False,
            }
    }

    lines = normalize_texts(texts)
    if not lines:
        return parsed

    labeled, remaining_lines = _extract_labeled_fields(lines)
    structured = _detect_structured(labeled, lines)
    parsed["_meta"]["structured_detected"] = structured

    # ---------- IKPU (17 цифр в любом месте) ----------
    m_any = _IKPU_ANY_RE.search("\n".join(lines))
    if m_any:
        parsed["ikpu"] = m_any.group(0)
        parsed["_meta"]["ikpu_source"] = "explicit_key"

    # ---------- MULTI PRICE (ЛЮБОЙ АТРИБУТ — ЦЕНА) ----------
    for line in lines:
        m = _PAIR_RE.match(line)
        if not m:
            continue
        pv = _digits_to_int(m.group("price"))
        if pv is not None:
            parsed["prices"].append({"weight": m.group("label").strip(), "price": pv})
        if parsed["prices"]:
            parsed["_meta"]["price_source"] = "multi_price_pairs"

    if parsed["prices"]:
        parsed["price"] = min(p["price"] for p in parsed["prices"])
        parsed["weight"] = None
        parsed["_meta"]["price_source"] = "multi_price_pairs"
    else:
        # ---------- SINGLE PRICE ----------
        if "price" in labeled and labeled["price"]:
            pv = _digits_to_int(labeled["price"])
            if pv is not None:
                parsed["price"] = pv
                parsed["_meta"]["price_source"] = "explicit_price_attr"

        if not parsed["price"]:
            # ищем строку-прайс
            for line in lines:
                if _IKPU_ANY_RE.search(line):
                    continue
                if _PRICE_LINE_RE.match(line):
                    pv = _digits_to_int(line)
                    if pv is not None:
                        parsed["price"] = pv
                        parsed["_meta"]["price_source"] = "fallback_from_text"
                        break

    # --- ЯВНЫЙ ВЕС (вес 1000 / вес:1000 / weight 1kg и т.д.) ---
    weight_key_present = False

    # 1. Сначала ищем явный атрибут веса в тексте
    for line in lines:
        m = _WEIGHT_ATTR_RE.search(line)
        if m:
            weight_key_present = True
            w = _normalize_weight_value(m.group(1))
            if w:
                parsed["weight"] = w
                parsed["_meta"]["weight_source"] = "explicit_weight_attr"
            break

    # 2. Потом — вес из labeled (если он был распознан ранее)
    if not parsed["weight"] and "weight" in labeled and labeled["weight"]:
        weight_key_present = True
        w = _normalize_weight_value(labeled["weight"])
        if w:
            parsed["weight"] = w
            parsed["_meta"]["weight_source"] = "labeled_weight_block"

    # 3. И ТОЛЬКО если явного веса НЕ БЫЛО — подхватываем из текста (0.25л и т.п.)
    if not parsed["weight"] and not weight_key_present:
        for line in lines:
            if _IKPU_ANY_RE.search(line):
                continue
            mw = _WEIGHT_RE.search(line)
            if mw:
                parsed["weight"] = mw.group(0).strip()
                parsed["_meta"]["weight_source"] = "fallback_from_text"
                break

    # ---------- NAME ----------
    if "name" in labeled and labeled["name"]:
        parsed["name"] = labeled["name"].strip()
    else:
        # если первое "человеческое" без цифр — считаем названием
        for line in lines:
            low = line.lower().strip()
            if not low:
                continue
            if any(k == low for k in KEY_ALIASES["composition"]):
                # не берем "состав" заголовком
                continue
            if any(char.isdigit() for char in low):
                continue
            if any(k in low for k in STOP_KEYS):
                continue
            parsed["name"] = line.strip()
            break

    # ---------- COMPOSITION ----------
    # 1) блок после "Состав/Таркиб" — даже если без двоеточия
    comp_block = collect_block(lines, "composition")
    if comp_block:
        comp = extract_composition_from_lines(comp_block)
        if comp:
            parsed["composition"] = comp
            parsed["_meta"]["composition_source"] = "composition_block"

    # 2) labeled composition
    if not parsed["composition"] and "composition" in labeled and labeled["composition"]:
        parsed["composition"] = labeled["composition"].strip()
        parsed["_meta"]["composition_source"] = "explicit_composition_attr"

    # 3) labeled description -> composition
    if not parsed["composition"] and "description" in labeled and labeled["description"]:
        parsed["composition"] = labeled["description"].strip()
        parsed["_meta"]["composition_source"] = "description_used_as_composition"

    # 4) fallback
    if not parsed["composition"]:
        comp = extract_composition_from_lines(remaining_lines if structured else lines)
        if comp: 
            parsed["composition"] = comp
            parsed["_meta"]["composition_source"] = "fallback_from_text"

    return parsed
