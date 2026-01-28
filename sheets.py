import os
import json
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def get_client():
    raw = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON is not set")

    info = json.loads(raw)

    creds = Credentials.from_service_account_info(
        info,
        scopes=SCOPES
    )

    return gspread.authorize(creds)
# =========================
# GOOGLE SHEETS CORE
# =========================

def get_client():
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def open_sheet_by_url(sheet_url: str):
    client = get_client()
    spreadsheet = client.open_by_url(sheet_url)
    return spreadsheet.sheet1  # MVP: первый лист


# =========================
# FIXED EXPORT LOGIC
# =========================

def build_fixed_row(values: Dict[str, Any]) -> List[Any]:
    """
    Строгий порядок колонок:
    Название → Описание → Цена → Вес → ИКПУ → Фото
    """
    return [
        values.get("Позиция", ""),
        values.get("Описание", ""),
        values.get("Цена", ""),
        values.get("Вес", ""),
        values.get("Код ИКПУ", ""),
        values.get("Картинка", ""),
    ]


def export_rows(sheet_url: str, items: List[Dict[str, Any]]) -> None:
    """
    items: список dict-ов вида:
    {
        "Позиция": "...",
        "Описание": "...",
        "Цена": 10000,
        "Вес": "200 мл",
        "Код ИКПУ": "...",
        "Картинка": "https://..."
    }
    """
    if not items:
        return

    sheet = open_sheet_by_url(sheet_url)

    rows: List[List[Any]] = []
    for it in items:
        rows.append(build_fixed_row(it))

    sheet.append_rows(rows, value_input_option="USER_ENTERED")