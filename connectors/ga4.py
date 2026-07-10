"""
Google Analytics 4 connector.

Pulls three datasets:
  1. Weekly traffic overview  — sessions, users, new users, page views, bounce rate
  2. Channel breakdown        — sessions + conversions by default channel group
  3. Top landing pages        — top 25 pages by sessions for the report period

Authentication: OAuth2 refresh token (run ga4_auth.py once to set up credentials).

Requires scope: analytics.readonly
"""

from __future__ import annotations

from typing import Any

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
    OrderBy,
)
from google.oauth2.credentials import Credentials

from config import GA4Config, DateConfig


def _build_client() -> tuple[BetaAnalyticsDataClient, str]:
    cfg = GA4Config.load()
    creds = Credentials(
        token=None,
        refresh_token=cfg.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=cfg.client_id,
        client_secret=cfg.client_secret,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
    )
    client = BetaAnalyticsDataClient(credentials=creds)
    return client, f"properties/{cfg.property_id}"


def _pct(value: str) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (ValueError, TypeError):
        return value


def _fmt(value: str, decimals: int = 0) -> Any:
    try:
        f = float(value)
        return round(f, decimals) if decimals else int(f)
    except (ValueError, TypeError):
        return value


class GA4Connector:
    def __init__(self):
        self.client, self.property = _build_client()
        dates = DateConfig.load()
        self.start_date = dates.start_date
        self.end_date = dates.end_date

    # ------------------------------------------------------------------
    # 1. Weekly traffic overview
    # ------------------------------------------------------------------

    def get_weekly_traffic(self) -> list[dict[str, Any]]:
        """
        One row per week: sessions, users, new users, page views, bounce rate,
        avg session duration (seconds).
        """
        from datetime import date, timedelta

        start = date.fromisoformat(self.start_date)
        end = date.fromisoformat(self.end_date)
        week_start = start - timedelta(days=start.weekday())

        rows = []
        while week_start <= end:
            week_end = min(week_start + timedelta(days=6), end)
            ws = week_start.isoformat()
            we = week_end.isoformat()

            req = RunReportRequest(
                property=self.property,
                date_ranges=[DateRange(start_date=ws, end_date=we)],
                metrics=[
                    Metric(name="sessions"),
                    Metric(name="totalUsers"),
                    Metric(name="newUsers"),
                    Metric(name="screenPageViews"),
                    Metric(name="bounceRate"),
                    Metric(name="averageSessionDuration"),
                ],
            )
            resp = self.client.run_report(req)

            if resp.rows:
                v = [c.value for c in resp.rows[0].metric_values]
                rows.append({
                    "Week": ws,
                    "Sessions": _fmt(v[0]),
                    "Users": _fmt(v[1]),
                    "New Users": _fmt(v[2]),
                    "Page Views": _fmt(v[3]),
                    "Bounce Rate": _pct(v[4]),
                    "Avg Session Duration (s)": _fmt(v[5], 1),
                })
            else:
                rows.append({
                    "Week": ws,
                    "Sessions": 0, "Users": 0, "New Users": 0,
                    "Page Views": 0, "Bounce Rate": "0.0%",
                    "Avg Session Duration (s)": 0,
                })

            week_start += timedelta(weeks=1)

        return rows

    # ------------------------------------------------------------------
    # 2. Channel breakdown
    # ------------------------------------------------------------------

    def get_channel_breakdown(self) -> list[dict[str, Any]]:
        """
        Sessions, users, and conversions by default channel group for the full
        report period, sorted by sessions descending.
        """
        req = RunReportRequest(
            property=self.property,
            date_ranges=[DateRange(
                start_date=self.start_date,
                end_date=self.end_date,
            )],
            dimensions=[Dimension(name="sessionDefaultChannelGroup")],
            metrics=[
                Metric(name="sessions"),
                Metric(name="totalUsers"),
                Metric(name="newUsers"),
                Metric(name="conversions"),
                Metric(name="bounceRate"),
            ],
            order_bys=[OrderBy(
                metric=OrderBy.MetricOrderBy(metric_name="sessions"),
                desc=True,
            )],
        )
        resp = self.client.run_report(req)

        rows = []
        for row in resp.rows:
            channel = row.dimension_values[0].value
            v = [c.value for c in row.metric_values]
            rows.append({
                "Channel": channel,
                "Sessions": _fmt(v[0]),
                "Users": _fmt(v[1]),
                "New Users": _fmt(v[2]),
                "Conversions": _fmt(v[3]),
                "Bounce Rate": _pct(v[4]),
            })
        return rows

    # ------------------------------------------------------------------
    # 3. Top landing pages
    # ------------------------------------------------------------------

    def get_pages_by_month(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        Top pages broken down by month. Used to populate the Campaign x Month tab so
        per-campaign web sessions can be tracked over time. Each row is one
        page path × month combination.
        """
        req = RunReportRequest(
            property=self.property,
            date_ranges=[DateRange(
                start_date=self.start_date,
                end_date=self.end_date,
            )],
            dimensions=[
                Dimension(name="yearMonth"),
                Dimension(name="pagePath"),
            ],
            metrics=[Metric(name="sessions")],
            order_bys=[OrderBy(
                metric=OrderBy.MetricOrderBy(metric_name="sessions"),
                desc=True,
            )],
            limit=limit * 12,
        )
        resp = self.client.run_report(req)

        rows = []
        for row in resp.rows:
            ym = row.dimension_values[0].value   # "202601"
            path = row.dimension_values[1].value
            sessions = _fmt(row.metric_values[0].value)
            month = f"{ym[:4]}-{ym[4:]}"        # "2026-01"
            rows.append({
                "Campaign (native)": path,
                "Month": month,
                "Platform": "Web Asset",
                "Spend ($)": 0,
                "Impressions": 0,
                "Clicks": 0,
                "Engagements": 0,
                "Conversions": 0,
                "Enrollments": 0,
                "Emails": 0,
                "Replies": 0,
                "Interested": 0,
                "Meetings": 0,
                "Sessions": sessions,
            })
        return rows

    def get_top_pages(self, limit: int = 25) -> list[dict[str, Any]]:
        """
        Top pages by sessions for the report period.
        """
        req = RunReportRequest(
            property=self.property,
            date_ranges=[DateRange(
                start_date=self.start_date,
                end_date=self.end_date,
            )],
            dimensions=[
                Dimension(name="pagePath"),
                Dimension(name="pageTitle"),
            ],
            metrics=[
                Metric(name="sessions"),
                Metric(name="totalUsers"),
                Metric(name="screenPageViews"),
                Metric(name="averageSessionDuration"),
                Metric(name="bounceRate"),
                Metric(name="conversions"),
            ],
            order_bys=[OrderBy(
                metric=OrderBy.MetricOrderBy(metric_name="sessions"),
                desc=True,
            )],
            limit=limit,
        )
        resp = self.client.run_report(req)

        rows = []
        for row in resp.rows:
            path = row.dimension_values[0].value
            title = row.dimension_values[1].value
            v = [c.value for c in row.metric_values]
            rows.append({
                "Page Path": path,
                "Page Title": title,
                "Sessions": _fmt(v[0]),
                "Users": _fmt(v[1]),
                "Page Views": _fmt(v[2]),
                "Avg Session Duration (s)": _fmt(v[3], 1),
                "Bounce Rate": _pct(v[4]),
                "Conversions": _fmt(v[5]),
            })
        return rows
