from typing import Dict, Any, List, Optional

_SESSIONS: Dict[int, Dict[str, Any]] = {}


# =========================
# SESSION CORE
# =========================

def _new_session() -> Dict[str, Any]:
    return {
        "mode": "idle",  # idle | manual_wait_sheet | manual_menu | dish_collect | edit | bulk_wait_sheet | bulk_collect | bulk_review
        "menu": {
            "sheet_url": None,
            "rows": [],
        },
        "texts": [],
        "photos": [],
        "parsed": None,
        "edit_mode": None,
        "bulk": {
            "active": False,
            "buffer": [],        # [{type: "photo"/"text", ...}]
            "positions": [],     # [{photo, texts, parsed}]
            "current_index": 0,
        },
    }


def get_session(user_id: int) -> Optional[Dict[str, Any]]:
    return _SESSIONS.get(user_id)


def ensure_session(user_id: int) -> Dict[str, Any]:
    if user_id not in _SESSIONS:
        _SESSIONS[user_id] = _new_session()
    return _SESSIONS[user_id]


def clear_session(user_id: int) -> None:
    _SESSIONS.pop(user_id, None)


def set_mode(user_id: int, mode: str) -> None:
    ensure_session(user_id)["mode"] = mode


def get_mode(user_id: int) -> str:
    s = get_session(user_id)
    return s["mode"] if s else "idle"


# =========================
# MENU / SHEET
# =========================

def start_manual_flow(user_id: int) -> None:
    s = ensure_session(user_id)
    s["menu"] = {"sheet_url": None, "rows": []}
    reset_dish(user_id)
    stop_bulk(user_id)
    set_mode(user_id, "manual_wait_sheet")


def start_bulk_flow(user_id: int) -> None:
    s = ensure_session(user_id)
    s["menu"] = {"sheet_url": None, "rows": []}
    reset_dish(user_id)
    start_bulk(user_id)
    set_mode(user_id, "bulk_wait_sheet")


def set_sheet_url(user_id: int, url: str) -> None:
    ensure_session(user_id)["menu"]["sheet_url"] = url.strip()


def add_menu_rows(user_id: int, rows: List[Any]) -> None:
    ensure_session(user_id)["menu"]["rows"].extend(rows)


# =========================
# MANUAL DISH
# =========================

def reset_dish(user_id: int) -> None:
    s = ensure_session(user_id)
    s["texts"] = []
    s["photos"] = []
    s["parsed"] = None
    s["edit_mode"] = None


def add_text(user_id: int, text: str) -> None:
    if not text:
        return
    ensure_session(user_id)["texts"].append(text.strip())


def add_photo(user_id: int, file_id: str) -> None:
    if file_id:
        ensure_session(user_id)["photos"].append(file_id)


def set_parsed(user_id: int, parsed: Dict[str, Any]) -> None:
    ensure_session(user_id)["parsed"] = parsed


def set_edit_mode(user_id: int, field: Optional[str]) -> None:
    ensure_session(user_id)["edit_mode"] = field


# =========================
# BULK MODE (FIXED LOGIC)
# =========================

def start_bulk(user_id: int) -> None:
    s = ensure_session(user_id)
    s["bulk"] = {
        "active": True,
        "buffer": [],
        "positions": [],
        "current_index": 0,
    }


def stop_bulk(user_id: int) -> None:
    ensure_session(user_id)["bulk"]["active"] = False


def bulk_is_active(user_id: int) -> bool:
    s = get_session(user_id)
    return bool(s and s["bulk"]["active"])


# ---------- COLLECT (ONLY BUFFER) ----------

def bulk_add_photo(user_id: int, photo_obj: Any) -> None:
    """
    photo_obj:
      - {"file_id": "...", "kind": "photo"} или {"file_id": "...", "kind": "document"}
      - либо строка file_id (на всякий случай для старого кода)
    """
    s = get_session(user_id)
    if not s:
        return

    if isinstance(photo_obj, str):
        photo_obj = {"file_id": photo_obj, "kind": "photo"}

    s["bulk"]["buffer"].append({
        "type": "photo",
        "photo": photo_obj,
        "photo_message_id": photo_obj.get("message_id"),  # 👈 ДОБАВИЛИ
    })


def bulk_add_text(user_id: int, text: str) -> None:
    if not text:
        return
    s = get_session(user_id)
    if not s:
        return
    s["bulk"]["buffer"].append({
        "type": "text",
        "value": text.strip(),
    })


# ---------- SPLIT AFTER "МЕНЮ ЗАГРУЖЕНО" ----------

def bulk_split_into_positions(user_id: int) -> List[Dict[str, Any]]:
    s = ensure_session(user_id)
    buffer = s["bulk"]["buffer"]

    positions: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    for item in buffer:
        if item["type"] == "photo":
            if current:
                positions.append(current)

            current = {
                "photo": item["photo"],
                "photo_message_id": item.get("photo_message_id"),  # 👈 ДОБАВИЛИ
                "texts": [],
                "parsed": None,
            }
        else:  # text
            if current is None:
                continue
            current["texts"].append(item["value"])

    if current:
        positions.append(current)

    s["bulk"]["positions"] = positions
    s["bulk"]["current_index"] = 0
    return positions


# ---------- REVIEW FLOW ----------

def bulk_total(user_id: int) -> int:
    return len(ensure_session(user_id)["bulk"]["positions"])


def bulk_get_current(user_id: int) -> Optional[Dict[str, Any]]:
    s = ensure_session(user_id)
    idx = s["bulk"]["current_index"]
    pos = s["bulk"]["positions"]
    if 0 <= idx < len(pos):
        return pos[idx]
    return None


def bulk_set_current_parsed(user_id: int, parsed: Dict[str, Any]) -> None:
    s = ensure_session(user_id)
    idx = s["bulk"]["current_index"]
    if 0 <= idx < len(s["bulk"]["positions"]):
        s["bulk"]["positions"][idx]["parsed"] = parsed


def bulk_next(user_id: int) -> None:
    ensure_session(user_id)["bulk"]["current_index"] += 1