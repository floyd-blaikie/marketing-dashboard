# Per-campaign monthly — what it takes

## Where we are

Two views ship today. The YTD per-campaign rollups (KPI Dashboard, Pipeline &
Revenue, Channel Metrics) and a new **Monthly Trend** tab that shows total
marketing by month — paid spend, LinkedIn reach, web sessions, and the HubSpot
funnel.

What's missing is the intersection: each campaign, broken down by month. We can't
build it from the sheet as it stands, because of how the data is shaped:

- The per-campaign tabs (LinkedIn Campaigns, Google Ads Campaigns, Amplemarket)
  are **YTD snapshots** — one cumulative row per campaign, no month attached.
- The time-series tabs (LinkedIn Monthly Trend, Google Ads Weekly, GA4 Traffic,
  HubSpot Lifecycle) carry months, but only **aggregated across everything** — no
  campaign dimension.

Neither half has both campaign *and* month. That's a pull problem, not a sheet
problem — the platform APIs all report by date; the pipeline just isn't asking.

A second thing the Monthly Trend tab makes visible: the Google Ads Weekly tab only
covers five weeks (May 11–Jun 8), so its monthly spend ($5,158) doesn't reconcile
with the campaign-level YTD total ($10,617). The monthly pull below fixes that too,
because it pulls the full date range segmented by month.

## The change

Add one connector method per platform that pulls campaign metrics **segmented by
month**, and write them to a single long-format tab.

### New tab: `Campaign x Month` (long format)

One row per campaign × month × platform:

| Campaign (native) | Month | Platform | Spend | Impressions | Clicks | Engagements | Conversions | Enrollments | Emails | Replies | Interested | Meetings | Sessions |

"Campaign (native)" is the platform's own name, exactly as in the existing raw
tabs — so the **same Campaign Map crosswalk** resolves it to a marketing campaign.
No second mapping to maintain.

### Connector work (in rough order of effort)

1. **Google Ads** (`connectors/google_ads.py`) — easiest. GAQL already supports
   `segments.month`. Add `get_campaign_monthly()`: same query as the campaign
   summary, grouped by campaign + `segments.month`. This alone fixes the spend
   reconciliation gap.
2. **GA4** (`connectors/ga4.py`) — add a `month` dimension alongside `landingPage`
   (or page path) so campaign landing pages roll up by month. Straightforward.
3. **LinkedIn / Fibbler** (`connectors/fibbler.py`) — request the campaign
   analytics finder with a monthly time granularity (`timeGranularity=MONTHLY`).
   Confirm Fibbler passes the granularity param through; if not, page by month.
4. **Amplemarket** (`connectors/amplemarket.py`) — the analytics endpoint is the
   slow one. Pull sequence/signal analytics bucketed by month if the API exposes a
   date range; otherwise this stays YTD-only and we note outbound as a known gap.

Each writes to `Campaign x Month` via the existing `SheetsWriter` (add the tab to
`SHEET_TABS`). The weekly refresh then keeps it current like any other raw tab.

### Rollup

A **Monthly KPI Dashboard** reads the long tab with `SUMIFS(metric, campaign, X,
month, Y)` — campaigns down the rows, months across, or a campaign filter up top.
Same pattern as the YTD dashboard, one extra criterion. The Campaign Map and Tactic
Ledger don't change; the ledger just gains a month-aware sibling.

## Sequencing suggestion

Google Ads + GA4 first — they segment cleanly by month and cover spend and web,
the two an exec asks about. LinkedIn next. Amplemarket last, since outbound monthly
is the least certain and the lowest stakes for a spend/pipeline view.
