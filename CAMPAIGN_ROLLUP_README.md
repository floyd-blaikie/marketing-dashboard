# Campaign rollup layer — how it works

This adds a per-campaign view on top of the platform-shaped data your pipeline
already writes. Your boss wants to see each marketing campaign as one line —
spend, leads, meetings, pipeline, bookings — even though the tactics behind a
campaign are scattered across Google Ads, LinkedIn, Amplemarket, and HubSpot.

## The one idea that makes it work: the Campaign Map

A marketing campaign isn't a platform object. It's a bundle of tactics: a Google
Ads search campaign, two Amplemarket sequences, a LinkedIn campaign. Nothing in
any single platform knows they belong together. The **Campaign Map** tab is where
you say so. One row per tactic: its native name exactly as it appears in the raw
tab, its platform, and the marketing campaign it belongs to.

That tab is the only thing you hand-edit. Everything else computes off it.

This is also why we're not leaning on HubSpot Campaigns for attribution. HubSpot
still locks a landing page or form to a single campaign — adding it to a second
campaign rips it out of the first (only workflows, lists, and now marketing emails
escape that rule; pages and forms are still "in development" as of June 2026). The
Campaign Map has no such limit, because it's your lookup table. A shared tactic
just gets a second row.

## The duplication rule: spend never doubles

Spend is sacred. Every spend-bearing tactic maps to exactly one campaign, so the
money always ties — sum of campaigns equals company actual, and Finance never has
to wonder whether you can do math. The `Spend Owner?` column enforces it: a paid
tactic is `Y` on its one row.

The only thing that duplicates is a genuinely shared, non-spend asset — a landing
page or form pulling double-duty for two campaigns. Those get a row per campaign
with `Spend Owner? = N`, so their engagement (sessions, form fills) shows up under
both, but no spend or paid-lead count is ever doubled. Going forward, separate
assets per campaign keep even that clean.

So the money rolls up with no gap, and the one place duplication can appear —
shared-asset engagement on the **Channel Metrics** tab — carries two bottom lines:

- **TOTAL (sum of campaigns)** — adds the campaign rows.
- **COMPANY ACTUAL (de-duped)** — counts each asset once, straight from the raw
  web tab.

In the prototype, spend reads $13,200 summed and $13,200 actual (no gap). Sessions
read 3,440 summed vs 2,040 actual — that 1,400 gap is the one landing page serving
two campaigns. Pipeline and bookings never double-count either, since a deal
carries one campaign tag.

## The tabs

- **Exec Summary** — the leadership skim. De-duped company KPIs across the top,
  then one line per campaign: budget, spend, leads, meetings, opps, pipeline,
  bookings, pipeline ROAS, and a plain-language health flag.
- **Campaign Map** — the crosswalk. You maintain this.
- **Tactic Ledger** — computed. Pulls each mapped tactic's metrics out of the raw
  tabs. This is the join layer; it lives in its own tab so a weekly refresh can't
  touch it.
- **KPI Dashboard / Pipeline & Revenue / Channel Metrics** — your boss's example
  tabs, now alive. Each campaign row sums off the ledger; pipeline and bookings
  come from tagged deals.
- **Campaign Registry / Benchmarks & Targets** — registry now auto-fills actual
  spend and % of budget; benchmarks pull current actuals where we have them.

## Why a weekly refresh won't wipe any of this

`writers/google_sheets.py` clears and rewrites only the tabs in its `SHEET_TABS`
list — the raw platform tabs. Every tab above sits outside that list, so the
refresh never sees them. They read the raw tabs by formula, so when the pipeline
drops fresh numbers in, the rollups recompute on open. Don't add a helper column
*inside* a raw tab — that one would get wiped.

## The one thing still missing: deal → campaign

Spend, clicks, leads, and meetings roll up cleanly today. Pipeline dollars and
bookings can't, until a deal knows which campaign it came from. The infrastructure
is built and waiting:

1. In HubSpot, add a deal property — call it **Marketing Campaign** — with values
   that match the Campaign Registry names exactly.
2. Extend `connectors/hubspot.py` → `get_deal_pipeline()` to include that property,
   so the `HubSpot - Deals` tab gains a **Campaign** column.
3. Confirm that column's letter matches `COLS["DEALS"]["campaign"]` in
   `campaign_rollup.py` (default `F`).

Once deals carry the tag, pipeline and bookings populate per campaign with no other
change. Until then they read $0 — by design, not by bug.

## What's mapped (v3)

Built from your filled-in worksheet: 12 campaigns (5 live, 7 ended), 36 assets
mapped, legacy and core-site pages excluded. The mapping lives in two data files
next to the script — `campaign_map.csv` (asset → campaign) and `campaigns.csv`
(campaign → Live/Ended). Edit those, or the live Campaign Map tab, to change it.

Corrected for the real sheet: LinkedIn rolls up **engagements** (it has no leads
column), Google Ads columns are read in their real order, and "Leads (proxy)" =
Google Ads conversions + Amplemarket "interested."

## Running it against the live sheet

`campaign_rollup.py` reads the two CSVs and builds Campaign Map, Tactic Ledger,
Campaign Registry, and KPI Dashboard in the live sheet, using the same service
account the pipeline uses.

```bash
cd marketing-data-pipeline
python campaign_rollup.py            # build / refresh
python campaign_rollup.py --reseed   # also overwrite Campaign Map from the CSV
```

It's safe to re-run: the Campaign Map is seeded once and never overwritten (unless
`--reseed`), so hand-edits survive. The computed tabs get rewritten each run.

**Before the first run**, confirm the live raw tabs' column letters match the
`COLS` block at the top of `campaign_rollup.py` (they're set to the verified
June-2026 layout). Pipeline & Revenue, Channel Metrics, and Exec Summary are fully
built in `PVT_Campaign_Tracker_v3.xlsx` and port with the same SUMIF pattern — add
them here once deal tags land and the mapping is final.

## Monthly views

`PVT_Campaign_Tracker_v3.xlsx` includes a **Monthly Trend** tab — total marketing
by month (paid spend, LinkedIn reach, web sessions, HubSpot funnel), rolled from
the weekly/monthly time-series tabs. It's aggregate only: the data isn't broken out
by campaign, and the Google Ads weekly feed currently covers a partial range. True
per-campaign-by-month needs a pipeline change — see `MONTHLY_BREAKDOWN_PLAN.md`.

## The prototype

`PVT_Campaign_Tracker_v3.xlsx` is the whole thing, working, populated with your
real YTD-2026 data so you can sanity-check every number. Open the Campaign Map,
change a mapping, watch the rollups and Exec Summary move. That's the spec.
