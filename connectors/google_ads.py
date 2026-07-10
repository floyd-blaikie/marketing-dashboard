"""
Google Ads connector.

Pulls three datasets:
  1. Weekly totals     — impressions, clicks, spend, conversions across all campaigns
  2. Campaign summary  — per-campaign aggregate for the full report period
  3. Search terms      — top search terms by clicks (Search campaigns only)

Requires Basic Access on the developer token. Explorer Access only works
against test accounts and will return a permission error against live accounts.

Scopes: https://www.googleapis.com/auth/adwords
"""

from __future__ import annotations

from typing import Any

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

from config import DateConfig

_MICROS = 1_000_000


def _micros(value: Any) -> float:
    try:
        return round(float(value) / _MICROS, 2)
    except (TypeError, ValueError):
        return 0.0


def _pct(numerator: float, denominator: float) -> str:
    if not denominator:
        return "0.00%"
    return f"{numerator / denominator * 100:.2f}%"


def _cpc(spend: float, clicks: int) -> float:
    return round(spend / clicks, 2) if clicks else 0.0


def _build_client() -> tuple[GoogleAdsClient, str]:
    import os
    from dotenv import load_dotenv
    load_dotenv()

    config = {
        "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
        "use_proto_plus": True,
    }
    # If authenticating through an MCC, set this to the MCC customer ID:
    # config["login_customer_id"] = os.environ["GOOGLE_ADS_MCC_CUSTOMER_ID"]

    customer_id = os.environ["GOOGLE_ADS_CUSTOMER_ID"]
    return GoogleAdsClient.load_from_dict(config), customer_id


class GoogleAdsConnector:
    def __init__(self):
        self.client, self.customer_id = _build_client()
        self.service = self.client.get_service("GoogleAdsService")
        dates = DateConfig.load()
        self.start_date = dates.start_date
        self.end_date = dates.end_date

    def _run(self, query: str) -> list[Any]:
        try:
            stream = self.service.search_stream(
                customer_id=self.customer_id, query=query
            )
            rows = []
            for batch in stream:
                rows.extend(batch.results)
            return rows
        except GoogleAdsException as ex:
            for error in ex.failure.errors:
                if "DEVELOPER_TOKEN_NOT_APPROVED" in str(error.error_code):
                    raise RuntimeError(
                        "Google Ads Basic Access not yet approved — "
                        "check your developer token application and re-run once approved."
                    ) from ex
            raise RuntimeError(
                f"Google Ads API error: {ex.failure.errors[0].message}"
            ) from ex

    # ------------------------------------------------------------------
    # 1. Weekly totals across all active campaigns
    # ------------------------------------------------------------------

    def get_weekly_totals(self) -> list[dict[str, Any]]:
        """
        One row per week: impressions, clicks, spend, conversions, CTR,
        avg CPC, and ROAS summed across all enabled campaigns.
        """
        query = f"""
            SELECT
                segments.week,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value
            FROM campaign
            WHERE segments.date BETWEEN '{self.start_date}' AND '{self.end_date}'
              AND campaign.status = 'ENABLED'
            ORDER BY segments.week ASC
        """
        raw = self._run(query)

        from collections import defaultdict
        weeks: dict[str, dict[str, float]] = defaultdict(
            lambda: {"impressions": 0.0, "clicks": 0.0, "spend": 0.0,
                     "conversions": 0.0, "conv_value": 0.0}
        )
        for row in raw:
            w = weeks[row.segments.week]
            w["impressions"] += row.metrics.impressions
            w["clicks"] += row.metrics.clicks
            w["spend"] += _micros(row.metrics.cost_micros)
            w["conversions"] += row.metrics.conversions
            w["conv_value"] += row.metrics.conversions_value

        rows = []
        for week, w in sorted(weeks.items()):
            impressions = int(w["impressions"])
            clicks = int(w["clicks"])
            spend = w["spend"]
            conversions = round(w["conversions"], 1)
            conv_value = round(w["conv_value"], 2)
            rows.append({
                "Week": week,
                "Impressions": impressions,
                "Clicks": clicks,
                "Spend ($)": spend,
                "Conversions": conversions,
                "Conversion Value ($)": conv_value,
                "CTR": _pct(clicks, impressions),
                "Avg CPC ($)": _cpc(spend, clicks),
                "ROAS": round(conv_value / spend, 2) if spend else 0.0,
            })
        return rows

    # ------------------------------------------------------------------
    # 2. Per-campaign breakdown for the full period
    # ------------------------------------------------------------------

    def get_campaign_summary(self) -> list[dict[str, Any]]:
        """
        One row per campaign: aggregate spend, clicks, conversions, and
        key efficiency metrics for the full report period, sorted by spend.
        """
        query = f"""
            SELECT
                campaign.name,
                campaign.status,
                campaign.advertising_channel_type,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value
            FROM campaign
            WHERE segments.date BETWEEN '{self.start_date}' AND '{self.end_date}'
              AND campaign.status != 'REMOVED'
            ORDER BY metrics.cost_micros DESC
        """
        raw = self._run(query)

        from collections import defaultdict
        campaigns: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"status": "", "type": "", "impressions": 0.0, "clicks": 0.0,
                     "spend": 0.0, "conversions": 0.0, "conv_value": 0.0}
        )
        for row in raw:
            name = row.campaign.name
            c = campaigns[name]
            c["status"] = row.campaign.status.name
            c["type"] = row.campaign.advertising_channel_type.name
            c["impressions"] += row.metrics.impressions
            c["clicks"] += row.metrics.clicks
            c["spend"] += _micros(row.metrics.cost_micros)
            c["conversions"] += row.metrics.conversions
            c["conv_value"] += row.metrics.conversions_value

        rows = []
        for name, c in sorted(
            campaigns.items(), key=lambda kv: kv[1]["spend"], reverse=True
        ):
            impressions = int(c["impressions"])
            clicks = int(c["clicks"])
            spend = c["spend"]
            conversions = round(c["conversions"], 1)
            conv_value = round(c["conv_value"], 2)
            rows.append({
                "Campaign": name,
                "Type": c["type"].replace("_", " ").title(),
                "Status": c["status"].title(),
                "Impressions": impressions,
                "Clicks": clicks,
                "Spend ($)": spend,
                "Conversions": conversions,
                "Conversion Value ($)": conv_value,
                "CTR": _pct(clicks, impressions),
                "Avg CPC ($)": _cpc(spend, clicks),
                "ROAS": round(conv_value / spend, 2) if spend else 0.0,
            })
        return rows

    # ------------------------------------------------------------------
    # 3. Per-campaign monthly breakdown
    # ------------------------------------------------------------------

    def get_campaign_monthly(self) -> list[dict[str, Any]]:
        """
        One row per campaign × month for the full report period.
        Uses segments.month so a single GAQL query covers the entire date range,
        fixing the spend-reconciliation gap in the weekly feed (which only covers
        the last ~5 weeks).
        """
        query = f"""
            SELECT
                campaign.name,
                segments.month,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions
            FROM campaign
            WHERE segments.date BETWEEN '{self.start_date}' AND '{self.end_date}'
              AND campaign.status != 'REMOVED'
            ORDER BY segments.month ASC, campaign.name ASC
        """
        raw = self._run(query)

        from collections import defaultdict
        agg: dict[tuple[str, str], dict[str, Any]] = defaultdict(
            lambda: {"impressions": 0.0, "clicks": 0.0, "spend": 0.0, "conversions": 0.0}
        )
        for row in raw:
            key = (row.campaign.name, row.segments.month)
            d = agg[key]
            d["impressions"] += row.metrics.impressions
            d["clicks"] += row.metrics.clicks
            d["spend"] += _micros(row.metrics.cost_micros)
            d["conversions"] += row.metrics.conversions

        rows = []
        for (name, month), d in sorted(agg.items()):
            rows.append({
                "Campaign (native)": name,
                "Month": month,
                "Platform": "Google Ads",
                "Spend ($)": d["spend"],
                "Impressions": int(d["impressions"]),
                "Clicks": int(d["clicks"]),
                "Engagements": 0,
                "Conversions": round(d["conversions"], 1),
                "Enrollments": 0,
                "Emails": 0,
                "Replies": 0,
                "Interested": 0,
                "Meetings": 0,
                "Sessions": 0,
            })
        return rows

    # ------------------------------------------------------------------
    # 4. Top search terms
    # ------------------------------------------------------------------

    def get_top_search_terms(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        Top search terms by clicks for Search campaigns in the report period.
        Useful for identifying intent signals and negative keyword candidates.
        """
        query = f"""
            SELECT
                search_term_view.search_term,
                campaign.name,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions
            FROM search_term_view
            WHERE segments.date BETWEEN '{self.start_date}' AND '{self.end_date}'
              AND metrics.impressions > 0
            ORDER BY metrics.clicks DESC
            LIMIT {limit}
        """
        raw = self._run(query)

        rows = []
        for row in raw:
            impressions = row.metrics.impressions
            clicks = row.metrics.clicks
            spend = _micros(row.metrics.cost_micros)
            rows.append({
                "Search Term": row.search_term_view.search_term,
                "Campaign": row.campaign.name,
                "Impressions": int(impressions),
                "Clicks": int(clicks),
                "Spend ($)": spend,
                "Conversions": round(row.metrics.conversions, 1),
                "CTR": _pct(clicks, impressions),
                "Avg CPC ($)": _cpc(spend, int(clicks)),
            })
        return rows
