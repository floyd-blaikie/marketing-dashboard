# Handoff prompt — paste into Claude Code (in the marketing-data-pipeline project)

---

You're working in the `marketing-data-pipeline` project. It already pulls 5 platforms
into a live Google Sheet weekly via `writers/google_sheets.py` (a service-account
gspread writer that clears and rewrites only the tabs listed in `config.py`'s
`SHEET_TABS`).

I've designed and validated a **campaign-rollup layer** on top of it (in a separate
session, against real data). Your job is to implement the live + pipeline pieces.
Read these first — they're in the project root:

- `CAMPAIGN_ROLLUP_README.md` — how the rollup layer works and why.
- `MONTHLY_BREAKDOWN_PLAN.md` — the per-campaign-monthly pipeline change, sequenced.
- `campaign_rollup.py` — builds the rollup tabs in the live sheet (Campaign Map,
  Tactic Ledger, Campaign Registry, KPI Dashboard) from the two CSVs.
- `campaign_map.csv` / `campaigns.csv` — the asset→campaign mapping and campaign list.
- `PVT_Campaign_Tracker_v3.xlsx` — the validated spec. The formulas in its tabs are
  exactly what the live sheet should reproduce. Open it if a formula is unclear.

## Core design rules — do not break these

1. **Never add a helper column inside a raw pipeline tab.** `SheetsWriter.write()`
   clears and rewrites each raw tab every run, so any helper column gets wiped. All
   computed tabs live OUTSIDE `SHEET_TABS` for this reason.
2. **Spend never duplicates.** Each spend-bearing tactic maps to exactly one campaign
   (`spend_owner=Y` in the map). Only non-spend shared assets may map to two.
3. LinkedIn measures **engagements, not leads**. "Leads (proxy)" = Google Ads
   conversions + Amplemarket "interested." Don't invent a LinkedIn leads column.

## Tasks, in order

### 1. Deal → campaign tag (unlocks pipeline/bookings; live deal data lands this week)
- In HubSpot, the team is adding a deal property named **"Marketing Campaign"** whose
  values match the campaign names in `campaigns.csv` exactly.
- Update `connectors/hubspot.py` → `get_deal_pipeline()` to include that property, so
  the `HubSpot - Deals` tab gains a **Campaign** column. Confirm its column letter
  matches `COLS["DEALS"]["campaign"]` in `campaign_rollup.py` (default `F`).

### 2. Stand up the rollup layer in the live sheet
- First verify the raw-tab column letters in the `COLS` block at the top of
  `campaign_rollup.py` against the actual live tabs (open the sheet, check headers).
  They're set to the June-2026 layout; fix any that drifted.
- Run `python campaign_rollup.py`. It creates Campaign Map (seeded once, never
  overwritten on re-run), Tactic Ledger, Campaign Registry, KPI Dashboard.
- Then port Pipeline & Revenue, Channel Metrics, Monthly Trend, and Exec Summary
  using the same SUMIF/SUMIFS pattern — the formulas are in `PVT_Campaign_Tracker_v3.xlsx`.

### 3. Per-campaign monthly (from MONTHLY_BREAKDOWN_PLAN.md)
- Add a `Campaign x Month` long-format tab (one row per campaign × month × platform).
  Add it to `SHEET_TABS` so the weekly refresh maintains it.
- Implement the month-segmented pulls, easiest first:
  - **Google Ads** (`connectors/google_ads.py`): `get_campaign_monthly()` using
    `segments.month`. (This also fixes the spend-reconciliation gap — the current
    Google Ads Weekly feed only covers ~5 weeks.)
  - **GA4** (`connectors/ga4.py`): add a `month` dimension alongside landing page.
  - LinkedIn/Fibbler and Amplemarket next, per the plan.
- The existing Campaign Map resolves native names → campaigns; no second mapping.
- Build a Monthly KPI Dashboard that reads the long tab with
  `SUMIFS(metric, campaign, X, month, Y)`.

### 4. Separate boss-facing report sheet (`exec_report.py`)
A separate, formatted, boss-only Google Sheet holding just the reporting tabs (Exec
Summary, Campaign Registry, KPI Dashboard, Monthly Trend, Pipeline & Revenue, Channel
Metrics, Monthly KPI Dashboard — no raw data, no Map/Ledger). Each run reads the
computed values from the working sheet and writes them as a formatted snapshot with
the Pivotree branding. It is chained to run automatically at the end of a full
`python main.py` (after the rollups rebuild), so the boss sheet refreshes weekly with
the pipeline. No IMPORTRANGE, no "allow access" step.

- First run: set `EXEC_SHARE_EMAIL` to the right address. The script creates the exec
  sheet, shares it, and prints the spreadsheet ID — add it to `.env` as
  `EXEC_SPREADSHEET_ID` so subsequent runs reuse the same sheet.
- Run order on a full pipeline: connectors → `Campaign x Month` → `campaign_rollup`
  → `exec_report` (the last two are now invoked from `main.py` automatically). To
  refresh the boss sheet on its own: `python exec_report.py`.
- It only reads the working sheet; safe to re-run.
- If a column's number format looks off, the heuristic in `numfmt_for()` decides
  currency/percent/multiple by header name — adjust there. The Monthly KPI Dashboard's
  month columns default to integer (the metric lives in the section label, not the
  column header), so its spend section shows plain numbers — tweak there if you want
  currency.

## Verify as you go
- After any change, run the pipeline (`python main.py --only <connector>`) and check
  the sheet. The rollup tabs should recompute on open.
- Sanity figures from the validated prototype: mapped YTD spend ≈ $53,394; IM&D
  Ascend ≈ 281,277 impressions; B2BOnline = 9 meetings. If your live numbers differ,
  it's fresh data — but the shape should match.
