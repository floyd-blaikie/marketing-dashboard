"""
Google Sheets writer.

Uses a service account for auth — no OAuth browser flow needed for automated runs.
The service account email must be shared on the target spreadsheet with Editor access.
"""

from __future__ import annotations

from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from config import SheetsConfig

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


class SheetsWriter:
    def __init__(self):
        cfg = SheetsConfig.load()
        creds = Credentials.from_service_account_file(cfg.service_account_json, scopes=_SCOPES)
        self.gc = gspread.authorize(creds)
        self.spreadsheet = self.gc.open_by_key(cfg.spreadsheet_id)

    def write(self, tab_name: str, rows: list[dict[str, Any]]) -> None:
        """
        Writes rows to a tab, creating it if it doesn't exist.
        Clears existing content first, then writes header + data rows.
        """
        if not rows:
            print(f"  [sheets] No data for tab '{tab_name}' — skipping.")
            return

        worksheet = self._get_or_create_tab(tab_name)
        worksheet.clear()

        headers = list(rows[0].keys())
        data = [headers] + [[row.get(h, "") for h in headers] for row in rows]

        worksheet.update(data, value_input_option="USER_ENTERED")
        print(f"  [sheets] Wrote {len(rows)} rows to '{tab_name}'.")

    def _get_or_create_tab(self, tab_name: str) -> gspread.Worksheet:
        try:
            return self.spreadsheet.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            return self.spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=30)
