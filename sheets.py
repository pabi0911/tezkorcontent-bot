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


def open_sheet_by_url(sheet_url: str):
    client = get_client()
    spreadsheet = client.open_by_url(sheet_url)
    return spreadsheet.sheet1


def export_rows(sheet_url: str, items):
    if not items:
        return

    sheet = open_sheet_by_url(sheet_url)
    rows = []

    for it in items:
        rows.append([
            it.get("Позиция", ""),
            it.get("Описание", ""),
            it.get("Цена", ""),
            it.get("Вес", ""),
            it.get("Код ИКПУ", ""),
            it.get("Картинка", ""),
        ])

    sheet.append_rows(rows, value_input_option="USER_ENTERED")