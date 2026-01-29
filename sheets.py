import json
import gspread
from google.oauth2.service_account import Credentials

from config import GOOGLE_CREDENTIALS_JSON

    return gspread.authorize(creds)


def open_sheet_by_url(sheet_url: str):
    client = get_client()
    spreadsheet = client.open_by_url(sheet_url)
    return spreadsheet.sheet1


# =========================
# FIXED EXPORT LOGIC
# =========================

def build_fixed_row(values: Dict[str, Any]) -> List[Any]:
    return [
        values.get("Позиция", ""),
        values.get("Описание", ""),
        values.get("Цена", ""),
        values.get("Вес", ""),
        values.get("Код ИКПУ", ""),
        values.get("Картинка", ""),
    ]


def export_rows(sheet_url: str, items: List[Dict[str, Any]]) -> None:
    if not items:
        return

    sheet = open_sheet_by_url(sheet_url)
    rows = [build_fixed_row(it) for it in items]
    sheet.append_rows(rows, value_input_option="USER_ENTERED")