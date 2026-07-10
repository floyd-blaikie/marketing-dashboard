"""
exec_report.py — refreshes a SEPARATE, formatted, boss-facing Google Sheet.

It contains only the reporting tabs (no raw data, no Campaign Map / Tactic Ledger).
Each run READS the computed values from the working sheet's rollup tabs and WRITES
them as a formatted snapshot into the exec sheet — full Pivotree branding, locked in.

No IMPORTRANGE, no "allow access" step, no flakiness. The snapshot is exactly as
current as the last pipeline run, which is the point: main.py calls this at the end
of a full run, so the boss sheet refreshes weekly alongside the data.

    python exec_report.py        # refresh on demand (also runs automatically via main.py)

Set EXEC_SPREADSHEET_ID in .env to reuse a specific exec sheet; otherwise the first
run creates one (titled below), shares it with EXEC_SHARE_EMAIL, and prints its ID.
"""
import os
import time
import gspread
from gspread.exceptions import APIError
from google.oauth2.service_account import Credentials
from config import SheetsConfig


def _retry(fn, *args, **kwargs):
    """Call fn(*args, **kwargs), retrying up to 5x on 429 with exponential backoff."""
    delay = 15
    for attempt in range(6):
        try:
            return fn(*args, **kwargs)
        except APIError as e:
            if e.response.status_code == 429 and attempt < 5:
                print(f"  [rate limit] waiting {delay}s …")
                time.sleep(delay)
                delay = min(delay * 2, 120)
            else:
                raise

SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]

EXEC_TITLE = "Pivotree — Campaign Performance (Exec)"
EXEC_SHARE_EMAIL = "floyd.blaikie@pivotree.com"   # who should see it; change as needed
# Only these tabs go in the boss sheet — no raw data, no Map/Ledger:
EXEC_TABS = ["Exec Summary", "Campaign Registry", "KPI Dashboard",
             "Monthly Trend", "Pipeline & Revenue", "Channel Metrics",
             "Monthly KPI Dashboard"]

# ---- Pivotree palette (hex -> Sheets RGB) ----
def rgb(hex_):
    h = hex_.lstrip("#")
    return {"red": int(h[0:2],16)/255, "green": int(h[2:4],16)/255, "blue": int(h[4:6],16)/255}
NAVY_TITLE=rgb("0D1B3E"); NAVY_HEAD=rgb("0A2342"); SLATE=rgb("172032"); GRP=rgb("0A3060")
CYAN=rgb("00B4C5"); WHITE=rgb("FFFFFF"); GOLD=rgb("E8A33D")
ARIAL="Arial"

def col_letter(n):
    s=""
    while n>0:
        n,r=divmod(n-1,26); s=chr(65+r)+s
    return s

def fmt(bg=None, fg=WHITE, bold=False, size=9, align="CENTER", numpat=None, numtype="NUMBER"):
    f={"textFormat":{"foregroundColor":fg,"bold":bold,"fontFamily":ARIAL,"fontSize":size},
       "horizontalAlignment":align,"verticalAlignment":"MIDDLE","wrapStrategy":"CLIP"}
    if bg: f["backgroundColor"]=bg
    if numpat: f["numberFormat"]={"type":numtype,"pattern":numpat}
    return f

def numfmt_for(header):
    h=str(header or "").lower()
    if "roas" in h: return ('0.0"x"',"NUMBER")
    if "rate" in h or h.endswith("%") or "% budget" in h: return ("0.0%","PERCENT")
    if any(k in h for k in ["$","spend","pipeline","bookings","budget","opp value","cpl","cac","revenue"]):
        return ("$#,##0","CURRENCY")
    return ("#,##0","NUMBER")


def connect():
    cfg = SheetsConfig.load()
    creds = Credentials.from_service_account_file(cfg.service_account_json, scopes=SCOPES)
    return gspread.authorize(creds), cfg.spreadsheet_id


def get_exec_sheet(gc):
    sid = os.getenv("EXEC_SPREADSHEET_ID")
    if sid:
        return gc.open_by_key(sid)
    for f in gc.list_spreadsheet_files():
        if f["name"] == EXEC_TITLE:
            return gc.open_by_key(f["id"])
    ss = gc.create(EXEC_TITLE)
    try:
        ss.share(EXEC_SHARE_EMAIL, perm_type="user", role="writer")
    except Exception as e:
        print(f"  (could not auto-share with {EXEC_SHARE_EMAIL}: {e})")
    print(f"Created exec sheet — add this to .env as EXEC_SPREADSHEET_ID:\n  {ss.id}")
    return ss


def _is_label(v):  # truthy text cell
    return isinstance(v, str) and v.strip() != ""


def build():
    gc, src_id = connect()
    src = gc.open_by_key(src_id)
    exec_ss = get_exec_sheet(gc)
    src_titles = {w.title for w in src.worksheets()}

    for tname in EXEC_TABS:
        if tname not in src_titles:
            print(f"  [skip] '{tname}' not in source — run campaign_rollup.py first.")
            continue

        # read computed values (numbers as numbers, not formatted strings)
        resp = src.values_get(f"'{tname}'", params={"valueRenderOption": "UNFORMATTED_VALUE"})
        data = resp.get("values", [])
        nrows = len(data)
        if nrows == 0:
            continue
        ncols = max(len(r) for r in data)
        data = [list(r) + [""] * (ncols - len(r)) for r in data]   # pad ragged rows

        # destination tab
        try:
            ws = exec_ss.worksheet(tname)
            _retry(ws.clear)
        except gspread.WorksheetNotFound:
            ws = _retry(exec_ss.add_worksheet, title=tname, rows=max(nrows+5,20), cols=max(ncols+2,12))

        last = f"{col_letter(ncols)}{nrows}"
        _retry(ws.update, values=data, range_name=f"A1:{last}", value_input_option="RAW")

        # ---- formatting ----
        full = f"A1:{last}"
        _retry(ws.format, full, fmt(bg=SLATE, align="LEFT"))

        hdr_idx = next((i for i,r in enumerate(data)
                        if _is_label(r[0]) and r[0].strip().lower() in
                        ("campaign","month","#","campaign name")), 0)
        headers = data[hdr_idx]

        # title banner (row 1 lone label sitting above the real header)
        if hdr_idx > 0 and _is_label(data[0][0]) and sum(1 for c in data[0] if _is_label(c)) == 1:
            _retry(ws.merge_cells, f"A1:{col_letter(ncols)}1")
            _retry(ws.format, f"A1:{col_letter(ncols)}1", fmt(bg=NAVY_TITLE, bold=True, size=14, align="LEFT"))

        # per-column number formats (data rows under the header)
        hr = hdr_idx + 1
        for ci, h in enumerate(headers, 1):
            if ci == 1:
                continue
            pat, typ = numfmt_for(h)
            _retry(ws.format, f"{col_letter(ci)}{hr+1}:{col_letter(ci)}{nrows}",
                   fmt(bg=SLATE, numpat=pat, numtype=typ))

        # every literal header row (handles multi-section Monthly KPI too)
        for i, r in enumerate(data):
            first = r[0].strip().lower() if _is_label(r[0]) else ""
            if first in ("campaign","month","#","campaign name"):
                _retry(ws.format, f"A{i+1}:{col_letter(ncols)}{i+1}", fmt(bg=NAVY_HEAD, fg=CYAN, bold=True))

        # section sub-banners (a lone label row that isn't a header/total)
        for i, r in enumerate(data):
            if (sum(1 for c in r if _is_label(c)) == 1 and _is_label(r[0])
                    and i != 0
                    and r[0].strip().lower() not in ("campaign","month","#","campaign name")
                    and not r[0].strip().upper().startswith(("TOTAL","PORTFOLIO","YTD"))):
                _retry(ws.format, f"A{i+1}:{col_letter(ncols)}{i+1}", fmt(bg=GRP, fg=CYAN, bold=True, align="LEFT"))

        # total / portfolio / ytd rows
        for i, r in enumerate(data):
            if _is_label(r[0]) and r[0].strip().upper().startswith(("TOTAL","PORTFOLIO","YTD")):
                _retry(ws.format, f"A{i+1}:{col_letter(ncols)}{i+1}", fmt(bg=NAVY_HEAD, fg=GOLD, bold=True, align="LEFT"))

        # Exec Summary KPI strip
        for i, r in enumerate(data):
            if "TOTAL SPEND" in [str(c).strip().upper() for c in r]:
                _retry(ws.format, f"A{i+1}:{col_letter(ncols)}{i+1}", fmt(bg=GRP, fg=CYAN, bold=True, size=8))
                if i+1 < nrows:
                    _retry(ws.format, f"A{i+2}:{col_letter(ncols)}{i+2}", fmt(bg=SLATE, fg=WHITE, bold=True, size=14))

        # freeze through header, widen label column, hide gridlines
        sid_ = ws.id
        _retry(exec_ss.batch_update, {"requests":[
            {"updateSheetProperties":{"properties":{"sheetId":sid_,
                "gridProperties":{"frozenRowCount":hr,"hideGridlines":True}},
                "fields":"gridProperties.frozenRowCount,gridProperties.hideGridlines"}},
            {"updateDimensionProperties":{"range":{"sheetId":sid_,"dimension":"COLUMNS",
                "startIndex":0,"endIndex":1},"properties":{"pixelSize":230},"fields":"pixelSize"}},
            {"updateDimensionProperties":{"range":{"sheetId":sid_,"dimension":"COLUMNS",
                "startIndex":1,"endIndex":ncols},"properties":{"pixelSize":96},"fields":"pixelSize"}},
        ]})
        print(f"  refreshed '{tname}' ({nrows}x{ncols})")

    # drop the default empty Sheet1 if a real tab exists
    try:
        s1 = exec_ss.worksheet("Sheet1")
        if len(exec_ss.worksheets()) > 1:
            exec_ss.del_worksheet(s1)
    except gspread.WorksheetNotFound:
        pass

    print(f"\nExec report refreshed: {exec_ss.url}")


if __name__ == "__main__":
    build()
