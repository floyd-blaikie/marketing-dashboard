"""
campaign_rollup.py — builds the campaign-rollup layer in the LIVE Google Sheet.

Reads the mapping from campaign_map.csv and the campaign list from campaigns.csv
(both produced from Floyd's filled-in worksheet), then writes:

  • Campaign Map           — seeded from campaign_map.csv ONLY if the tab is missing,
                             so your hand-edits are never overwritten on re-run.
  • Tactic Ledger          — (re)written each run. Computed join layer.
  • Campaign Registry      — (re)written each run. 12 campaigns + Live/Ended + auto spend.
  • KPI Dashboard          — (re)written each run. Per-campaign rollup off the ledger/deals.
  • Pipeline & Revenue     — (re)written each run. Meetings, leads, opps, pipeline, bookings.
  • Channel Metrics        — (re)written each run. Email, paid, web engagement per campaign.
  • Monthly Trend          — (re)written each run. All-up marketing totals by month.
  • Exec Summary           — (re)written each run. Leadership skim + per-campaign table.
  • Monthly KPI Dashboard  — (re)written each run. Campaign × month spend + sessions.

All tabs above live OUTSIDE writers/google_sheets.py's SHEET_TABS list, so the weekly
refresh (which clears only its own raw tabs) can never wipe them. They recompute on
open because they reference the raw tabs by formula.

    python campaign_rollup.py            # build / refresh the rollup tabs
    python campaign_rollup.py --reseed   # overwrite Campaign Map from the CSV too

RULE: spend never duplicates. Each spend-bearing tactic maps to exactly one campaign
(spend_owner=Y). Only shared non-spend assets (a landing page for two campaigns) may
appear twice, with spend_owner=N — engagement duplicates, spend does not.

------------------------------------------------------------------------------
COLS below are the LIVE sheet's real column letters (verified June 2026). If the
pipeline changes a raw tab's column order, update COLS and re-run.
------------------------------------------------------------------------------
"""
import argparse, csv, os
from datetime import date
import gspread
from google.oauth2.service_account import Credentials
from config import SheetsConfig, DateConfig

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
HERE = os.path.dirname(os.path.abspath(__file__))

# raw tab names (must match writers SHEET_TABS) + real column letters in the LIVE sheet
LI="LinkedIn - Campaigns"; GA="Google Ads - Campaigns"
SIG="Amplemarket - Signal Analytics"; STD="Amplemarket - Std Sequences"
WEB="GA4 - Top Pages"; HS="HubSpot - Sequences"; DEALS="HubSpot - Deals"
COLS = {
  "LI":  {"key":"A","spend":"C","impr":"D","clicks":"E","eng":"F"},
  "GA":  {"key":"A","impr":"D","clicks":"E","spend":"F","conv":"G"},
  "SIG": {"key":"A","enroll":"C","emails":"D","opens":"E","replies":"F","interested":"K","meetings":"L"},
  "STD": {"key":"A","enroll":"B","emails":"C","opens":"D","replies":"E","interested":"J","meetings":"K"},
  "WEB": {"key":"A","sessions":"C"},
  "HS":  {"key":"A","enroll":"C"},
  "DEALS": {"name":"A","stage":"B","amount":"C","campaign":"F"},  # 'campaign' = the new deal tag
}
MAP_HEADERS = ["Tactic ID","Platform","Native Name (exact)","Marketing Campaign","Spend Owner?","Notes"]


def q(t): return f"'{t}'"


def _ytd_months(start_iso=None):
    """Returns ['YYYY-MM', ...] from report start month through current month."""
    try:
        cfg = DateConfig.load()
        start = date.fromisoformat(cfg.start_date)
    except Exception:
        start = date(date.today().year, 1, 1)
    today = date.today()
    months = []
    y, m = start.year, start.month
    while date(y, m, 1) <= today:
        months.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def load_csv(name):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        raise SystemExit(f"Missing {name} next to this script. Re-export it from the mapping worksheet.")
    with open(path, newline="") as f:
        return list(csv.reader(f))


def build(reseed):
    cfg = SheetsConfig.load()
    gc = gspread.authorize(Credentials.from_service_account_file(cfg.service_account_json, scopes=SCOPES))
    ss = gc.open_by_key(cfg.spreadsheet_id)
    existing = {w.title: w for w in ss.worksheets()}

    def tab(title, rows=200, cols=30):
        if title in existing: return existing[title]
        ws = ss.add_worksheet(title=title, rows=rows, cols=cols); existing[title] = ws; return ws

    map_rows = load_csv("campaign_map.csv")[1:]          # skip header
    camp_rows = load_csv("campaigns.csv")[1:]
    campaigns = [r[0] for r in camp_rows]
    n = len(map_rows)

    # ---- Campaign Map: seed only if missing (or --reseed) ----
    cm = tab("Campaign Map")
    if "Campaign Map" not in {w.title for w in ss.worksheets()} or reseed or not cm.acell("A2").value:
        cm.clear()
        cm.update([MAP_HEADERS] + [[r[0], r[1], r[2], r[3], r[4], r[5] if len(r) > 5 else ""] for r in map_rows],
                  value_input_option="USER_ENTERED")
        print(f"Campaign Map seeded from CSV ({n} rows).")
    else:
        print("Campaign Map exists — left untouched (use --reseed to overwrite).")
    MAPq = q("Campaign Map")

    # ---- Tactic Ledger ----
    tl = tab("Tactic Ledger"); tl.clear()
    li, ga, sg, st, wb_, hs = COLS["LI"], COLS["GA"], COLS["SIG"], COLS["STD"], COLS["WEB"], COLS["HS"]
    def sif(tabname, keycol, crit, sumcol):
        return f"SUMIF({q(tabname)}!${keycol}:${keycol},{crit},{q(tabname)}!${sumcol}:${sumcol})"
    head = ["Marketing Campaign","Platform","Native Name","Spend","Impressions","Clicks","Engagements",
            "Conversions","Enrollments","Emails","Opens","Replies","Interested","Meetings","Sessions"]
    grid = [head]
    for i in range(n):
        r = i + 2  # ledger + map data start at row 2
        P, N = f"{MAPq}!$B{r}", f"{MAPq}!$C{r}"
        so = f"IF({MAPq}!$E{r}=\"Y\",1,0)"
        grid.append([
          f"={MAPq}!D{r}", f"={P}", f"={N}",
          f"=({so})*(IF({P}=\"LinkedIn\",{sif(LI,li['key'],N,li['spend'])},IF({P}=\"Google Ads\",{sif(GA,ga['key'],N,ga['spend'])},0)))",
          f"=IF({P}=\"LinkedIn\",{sif(LI,li['key'],N,li['impr'])},IF({P}=\"Google Ads\",{sif(GA,ga['key'],N,ga['impr'])},0))",
          f"=IF({P}=\"LinkedIn\",{sif(LI,li['key'],N,li['clicks'])},IF({P}=\"Google Ads\",{sif(GA,ga['key'],N,ga['clicks'])},0))",
          f"=IF({P}=\"LinkedIn\",{sif(LI,li['key'],N,li['eng'])},0)",
          f"=IF({P}=\"Google Ads\",{sif(GA,ga['key'],N,ga['conv'])},0)",
          f"=IF({P}=\"Amplemarket (Signal)\",{sif(SIG,sg['key'],N,sg['enroll'])},IF({P}=\"Amplemarket (Std)\",{sif(STD,st['key'],N,st['enroll'])},IF({P}=\"HubSpot Seq\",{sif(HS,hs['key'],N,hs['enroll'])},0)))",
          f"=IF({P}=\"Amplemarket (Signal)\",{sif(SIG,sg['key'],N,sg['emails'])},IF({P}=\"Amplemarket (Std)\",{sif(STD,st['key'],N,st['emails'])},0))",
          f"=IF({P}=\"Amplemarket (Signal)\",{sif(SIG,sg['key'],N,sg['opens'])},IF({P}=\"Amplemarket (Std)\",{sif(STD,st['key'],N,st['opens'])},0))",
          f"=IF({P}=\"Amplemarket (Signal)\",{sif(SIG,sg['key'],N,sg['replies'])},IF({P}=\"Amplemarket (Std)\",{sif(STD,st['key'],N,st['replies'])},0))",
          f"=IF({P}=\"Amplemarket (Signal)\",{sif(SIG,sg['key'],N,sg['interested'])},IF({P}=\"Amplemarket (Std)\",{sif(STD,st['key'],N,st['interested'])},0))",
          f"=IF({P}=\"Amplemarket (Signal)\",{sif(SIG,sg['key'],N,sg['meetings'])},IF({P}=\"Amplemarket (Std)\",{sif(STD,st['key'],N,st['meetings'])},0))",
          f"=IF({P}=\"Web Asset\",{sif(WEB,wb_['key'],N,wb_['sessions'])},0)",
        ])
    tl.update(grid, value_input_option="USER_ENTERED")
    LR = n + 1
    print(f"Tactic Ledger written ({n} rows).")

    def SL(col, c):  # roll a ledger metric up to a campaign
        return f"SUMIF({q('Tactic Ledger')}!$A$2:$A${LR},{c},{q('Tactic Ledger')}!${col}$2:${col}${LR})"
    dc = COLS["DEALS"]; da, ds, dcamp = dc["amount"], dc["stage"], dc["campaign"]

    # ---- Campaign Registry ----
    reg = tab("Campaign Registry"); reg.clear()
    rgrid = [["#","Campaign Name","Status","Owner","Budget ($)","Actual Spend ($)","% Budget"]]
    for i, (name, status) in enumerate(camp_rows):
        r = i + 2; nm = f"$B{r}"
        rgrid.append([i+1, name, status, "", "", f"={SL('D', nm)}", f"=IFERROR(F{r}/E{r},0)"])
    reg.update(rgrid, value_input_option="USER_ENTERED")
    print("Campaign Registry written.")

    # ---- KPI Dashboard ----
    kpi = tab("KPI Dashboard"); kpi.clear()
    kh = ["Campaign","Impressions","Engagements","Website Sessions","Open Rate","CTR","Eng. Rate",
          "Leads (proxy)","Meetings","Opps","Pipeline ($)","Bookings ($)","CPL ($)","Conv. Rate"]
    kgrid = [kh]
    for i, name in enumerate(campaigns):
        r = i + 2; A = f"$A{r}"
        pipe = f"SUMIFS({q(DEALS)}!${da}:${da},{q(DEALS)}!${dcamp}:${dcamp},{A},{q(DEALS)}!${ds}:${ds},\"<>Closed Won\",{q(DEALS)}!${ds}:${ds},\"<>Closed Lost\")"
        book = f"SUMIFS({q(DEALS)}!${da}:${da},{q(DEALS)}!${dcamp}:${dcamp},{A},{q(DEALS)}!${ds}:${ds},\"Closed Won\")"
        opps = f"COUNTIFS({q(DEALS)}!${dcamp}:${dcamp},{A})"
        kgrid.append([name,
          f"={SL('E',A)}", f"={SL('G',A)}", f"={SL('O',A)}",
          f"=IFERROR({SL('K',A)}/{SL('J',A)},0)", f"=IFERROR({SL('F',A)}/{SL('E',A)},0)",
          f"=IFERROR({SL('G',A)}/{SL('E',A)},0)", f"={SL('H',A)}+{SL('M',A)}",
          f"={SL('N',A)}", f"={opps}", f"={pipe}", f"={book}",
          f"=IFERROR({SL('D',A)}/({SL('H',A)}+{SL('M',A)}),0)",
          f"=IFERROR({SL('N',A)}/({SL('H',A)}+{SL('M',A)}),0)"])
    tr = len(campaigns) + 2
    kgrid.append(["TOTAL (mapped campaigns)"] + [
        f"=SUM({chr(66+i)}2:{chr(66+i)}{tr-1})" if i in (0,1,2,6,7,8,9,10) else "" for i in range(13)])
    kpi.update(kgrid, value_input_option="USER_ENTERED")
    print("KPI Dashboard written.")

    kpi_tr = len(campaigns) + 2   # row number of the KPI Dashboard TOTAL row

    # ---- Pipeline & Revenue ----
    pr = tab("Pipeline & Revenue"); pr.clear()
    pr_head = ["Campaign","Status","Meetings","Leads (proxy)","Opps",
               "Opp Value ($)","Pipeline ($)","Close Rate",
               "Weighted Pipeline ($)","Bookings ($)","Spend ($)","Pipeline ROAS"]
    prgrid = [pr_head]
    for i, (name, status) in enumerate(camp_rows):
        r = i + 2; A = f"$A{r}"
        pipeline  = f"SUMIFS({q(DEALS)}!${da}:${da},{q(DEALS)}!${dcamp}:${dcamp},{A},{q(DEALS)}!${ds}:${ds},\"<>Closed Won\",{q(DEALS)}!${ds}:${ds},\"<>Closed Lost\")"
        opp_value = f"SUMIFS({q(DEALS)}!${da}:${da},{q(DEALS)}!${dcamp}:${dcamp},{A})"
        bookings  = f"SUMIFS({q(DEALS)}!${da}:${da},{q(DEALS)}!${dcamp}:${dcamp},{A},{q(DEALS)}!${ds}:${ds},\"Closed Won\")"
        opps      = f"COUNTIFS({q(DEALS)}!${dcamp}:${dcamp},{A})"
        prgrid.append([
            name, status,
            f"={SL('N',A)}",                              # C: Meetings
            f"={SL('H',A)}+{SL('M',A)}",                  # D: Leads proxy
            f"={opps}",                                    # E: Opps
            f"={opp_value}",                               # F: Opp Value
            f"={pipeline}",                                # G: Pipeline
            0.2,                                           # H: Close Rate
            f"=G{r}*H{r}",                                 # I: Weighted Pipeline
            f"={bookings}",                                # J: Bookings
            f"={SL('D',A)}",                               # K: Spend
            f"=IFERROR(G{r}/K{r},0)",                      # L: Pipeline ROAS
        ])
    pr_tr = len(campaigns) + 2
    prgrid.append(["TOTAL (mapped campaigns)", ""] + [
        f"=SUM({chr(67+i)}2:{chr(67+i)}{pr_tr-1})" if i in (0,1,2,3,4,6,7,8) else ""
        for i in range(10)
    ])
    pr.update(prgrid, value_input_option="USER_ENTERED")
    print("Pipeline & Revenue written.")

    # ---- Channel Metrics ----
    cm = tab("Channel Metrics"); cm.clear()
    cm_head = ["Campaign","Emails Sent","Opens","Open Rate","Replies","Reply Rate",
               "Impressions","Clicks","CTR","Engagements","Sessions"]
    cmgrid = [cm_head]
    for i, (name, _) in enumerate(camp_rows):
        r = i + 2; A = f"$A{r}"
        cmgrid.append([
            name,
            f"={SL('J',A)}",                              # B: Emails
            f"={SL('K',A)}",                              # C: Opens
            f"=IFERROR(C{r}/B{r},0)",                      # D: Open Rate
            f"={SL('L',A)}",                              # E: Replies
            f"=IFERROR(E{r}/B{r},0)",                      # F: Reply Rate
            f"={SL('E',A)}",                              # G: Impressions
            f"={SL('F',A)}",                              # H: Clicks
            f"=IFERROR(H{r}/G{r},0)",                      # I: CTR
            f"={SL('G',A)}",                              # J: Engagements
            f"={SL('O',A)}",                              # K: Sessions
        ])
    cm_tr = len(campaigns) + 2
    cmgrid.append(["TOTAL (mapped campaigns)"] + [
        f"=SUM({chr(66+i)}2:{chr(66+i)}{cm_tr-1})" if i in (0,1,3,5,6,8) else ""
        for i in range(10)
    ])
    cm.update(cmgrid, value_input_option="USER_ENTERED")
    print("Channel Metrics written.")

    # ---- Monthly Trend ----
    mt = tab("Monthly Trend"); mt.clear()
    months = _ytd_months()
    LI_TREND  = "LinkedIn - Monthly Trend"
    GA_WEEKLY = "Google Ads - Weekly"
    GA4_TRAF  = "GA4 - Traffic"
    mt_head = ["Month","Paid Spend ($)","LI Impressions","LI Clicks","LI Engagements",
               "Ads Impressions","Ads Clicks","Website Sessions"]
    mtgrid = [mt_head]
    for i, mo in enumerate(months):
        r = i + 2
        # Use SUMPRODUCT to avoid needing a Month helper column in the raw tabs
        ga_sp  = f"SUMPRODUCT((LEFT({q(GA_WEEKLY)}!$A$2:$A$5000,7)=A{r})*({q(GA_WEEKLY)}!$D$2:$D$5000))"
        ga_im  = f"SUMPRODUCT((LEFT({q(GA_WEEKLY)}!$A$2:$A$5000,7)=A{r})*({q(GA_WEEKLY)}!$B$2:$B$5000))"
        ga_cl  = f"SUMPRODUCT((LEFT({q(GA_WEEKLY)}!$A$2:$A$5000,7)=A{r})*({q(GA_WEEKLY)}!$C$2:$C$5000))"
        ga4_ss = f"SUMPRODUCT((LEFT({q(GA4_TRAF)}!$A$2:$A$5000,7)=A{r})*({q(GA4_TRAF)}!$B$2:$B$5000))"
        li_im  = f"SUMIF({q(LI_TREND)}!$A:$A,A{r},{q(LI_TREND)}!$B:$B)"
        li_cl  = f"SUMIF({q(LI_TREND)}!$A:$A,A{r},{q(LI_TREND)}!$C:$C)"
        li_en  = f"SUMIF({q(LI_TREND)}!$A:$A,A{r},{q(LI_TREND)}!$D:$D)"
        mtgrid.append([mo, f"={ga_sp}", f"={li_im}", f"={li_cl}", f"={li_en}",
                       f"={ga_im}", f"={ga_cl}", f"={ga4_ss}"])
    mt_tr = len(months) + 2
    mtgrid.append(["YTD TOTAL"] + [
        f"=SUM({chr(66+i)}2:{chr(66+i)}{mt_tr-1})" for i in range(7)
    ])
    mt.update(mtgrid, value_input_option="USER_ENTERED")
    print("Monthly Trend written.")

    # ---- Exec Summary ----
    es = tab("Exec Summary"); es.clear()
    tl_spend = f"SUM({q('Tactic Ledger')}!$D$2:$D${LR})"
    KPI = "KPI Dashboard"
    PR  = "Pipeline & Revenue"
    es_kpi_row = [
        "TOTAL SPEND", "", "MEETINGS", "", "LEADS (PROXY)", "",
        "OPEN PIPELINE", "", "BOOKINGS", "", "PIPELINE ROAS",
    ]
    es_val_row = [
        f"={tl_spend}", "",
        f"={q(KPI)}!I{kpi_tr}", "",
        f"={q(KPI)}!H{kpi_tr}", "",
        f"={q(KPI)}!K{kpi_tr}", "",
        f"={q(KPI)}!L{kpi_tr}", "",
        f"=IFERROR({q(KPI)}!K{kpi_tr}/{tl_spend},0)",
    ]
    es_hdr = ["Campaign","Status","Spend ($)","Leads","Meetings","Opps",
              "Open Pipeline ($)","Bookings ($)","Pipeline ROAS"]
    esgrid = [
        ["PIVOTREE  |  Campaign Performance — Executive Summary (YTD 2026)"],
        [],
        es_kpi_row,
        es_val_row,
        [],
        [],
        es_hdr,
    ]
    camp_start_row = 8
    for i, (name, status) in enumerate(camp_rows):
        r = camp_start_row + i; A = f"$A{r}"
        def _idx(sheet, col):
            return f"IFERROR(INDEX({q(sheet)}!${col}:${col},MATCH({A},{q(sheet)}!$A:$A,0)),0)"
        esgrid.append([
            name, status,
            f"={_idx(PR,'K')}",             # C: Spend (from Pipeline & Revenue col K)
            f"={_idx(KPI,'H')}",            # D: Leads
            f"={_idx(KPI,'I')}",            # E: Meetings
            f"={_idx(KPI,'J')}",            # F: Opps
            f"={_idx(KPI,'K')}",            # G: Open Pipeline
            f"={_idx(KPI,'L')}",            # H: Bookings
            f"=IFERROR(G{r}/C{r},0)",        # I: Pipeline ROAS
        ])
    es_tr = camp_start_row + len(campaigns)
    esgrid.append([
        "PORTFOLIO TOTAL", "",
        f"=SUM(C{camp_start_row}:C{es_tr-1})",
        f"=SUM(D{camp_start_row}:D{es_tr-1})",
        f"=SUM(E{camp_start_row}:E{es_tr-1})",
        f"=SUM(F{camp_start_row}:F{es_tr-1})",
        f"=SUM(G{camp_start_row}:G{es_tr-1})",
        f"=SUM(H{camp_start_row}:H{es_tr-1})",
        f"=IFERROR(G{es_tr}/C{es_tr},0)",
    ])
    es.update(esgrid, value_input_option="USER_ENTERED")
    print("Exec Summary written.")

    # ---- Monthly KPI Dashboard ----
    mkpi = tab("Monthly KPI Dashboard"); mkpi.clear()
    CXM = "Campaign x Month"
    month_cols = [chr(66 + i) for i in range(len(months))]  # B, C, D, ...
    ytd_col = chr(66 + len(months))                          # column after last month

    def _msum(metric_col, camp_ref, month_ref):
        return (f"SUMIFS({q(CXM)}!${metric_col}:${metric_col},"
                f"{q(CXM)}!$B:$B,{camp_ref},"
                f"{q(CXM)}!$C:$C,{month_ref})")

    # Build header rows: title + section headers + month labels
    mkpi_months_row = ["Campaign"] + months + ["YTD"]
    sections = [
        ("SPEND ($)", "E"),
        ("SESSIONS", "O"),
        ("IMPRESSIONS", "F"),
    ]
    mkgrid = [["MONTHLY KPI DASHBOARD  |  by Campaign × Month"], []]

    section_start = 3  # row index (1-based) where first section begins
    for sec_label, metric_col in sections:
        mkgrid.append([sec_label])
        mkgrid.append(mkpi_months_row)
        hdr_row = len(mkgrid)  # 1-based row of month headers for this section
        data_start = hdr_row + 1
        camp_rows_section = []
        for i, name in enumerate(campaigns):
            r = data_start + i
            A = f"$A{r}"
            cells = [name]
            for j, mo in enumerate(months):
                month_cell = f"{month_cols[j]}${hdr_row}"
                cells.append(f"={_msum(metric_col, A, month_cell)}")
            ytd_range = f"{month_cols[0]}{r}:{month_cols[-1]}{r}"
            cells.append(f"=SUM({ytd_range})")
            camp_rows_section.append(cells)
            mkgrid.append(cells)
        total_r = data_start + len(campaigns)
        total_row = ["TOTAL"]
        for j in range(len(months)):
            col = month_cols[j]
            total_row.append(f"=SUM({col}{data_start}:{col}{total_r-1})")
        total_row.append(f"=SUM({month_cols[0]}{total_r}:{month_cols[-1]}{total_r})")
        mkgrid.append(total_row)
        mkgrid.append([])  # blank separator

    mkpi.update(mkgrid, value_input_option="USER_ENTERED")
    print("Monthly KPI Dashboard written.")

    print("\nDone. Pipeline/Bookings stay 0 until deals carry a Campaign tag in "
          f"'{DEALS}' column {dcamp}. See CAMPAIGN_ROLLUP_README.md.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reseed", action="store_true", help="overwrite Campaign Map from campaign_map.csv")
    build(ap.parse_args().reseed)
