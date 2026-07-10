"""
Fibbler connector — LinkedIn Ads performance via Fibbler's MCP API.

Pulls two datasets:
  1. Campaign performance  — per-campaign spend, impressions, clicks, engagements,
                             CTR, engagement rate, companies reached/engaged
  2. Monthly trend         — month-by-month impressions, clicks, engagements,
                             companies reached/engaged with MoM change %

Fibbler exposes a JSON-RPC MCP endpoint (SSE response format).
Authentication: Bearer token from FIBBLER_API_KEY in .env.
"""

from __future__ import annotations

import json
from typing import Any

import requests

from config import FibblerConfig, DateConfig

_MCP_URL = "https://app.fibbler.co/mcp"
_HEADERS_BASE = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _parse_sse(text: str) -> Any:
    """Extract the JSON payload from an SSE data line."""
    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise ValueError(f"No SSE data line found in response: {text[:200]}")


class FibblerConnector:
    def __init__(self):
        cfg = FibblerConfig.load()
        self._headers = {**_HEADERS_BASE, "Authorization": f"Bearer {cfg.api_key}"}
        dates = DateConfig.load()
        # Convert YYYY-MM-DD → YYYY-MM for Fibbler's month-based API
        self._start_month = dates.start_date[:7]
        self._end_month = dates.end_date[:7]

    def _call(self, tool: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a Fibbler MCP tool and return the parsed text content."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}},
        }
        r = requests.post(_MCP_URL, headers=self._headers, json=payload, timeout=30)
        r.raise_for_status()
        resp = _parse_sse(r.text)
        content = resp.get("result", {}).get("content", [])
        if not content:
            raise RuntimeError(f"Fibbler tool '{tool}' returned no content")
        text = content[0].get("text", "")
        return json.loads(text)

    # ------------------------------------------------------------------
    # 1. Campaign performance for the report period
    # ------------------------------------------------------------------

    def get_campaign_performance(self) -> list[dict[str, Any]]:
        """
        One row per LinkedIn campaign: spend, impressions, clicks, engagements,
        CTR, engagement rate, and company reach/engagement for the report period.
        Sorted by spend descending.
        """
        data = self._call("get_campaign_performance", {
            "start_month": self._start_month,
            "end_month": self._end_month,
            "sort_by": "spend",
            "limit": 50,
        })

        currency = data.get("currency", "")
        rows = []
        for c in data.get("campaigns", []):
            rows.append({
                "Campaign": c.get("name", ""),
                "Format": c.get("format", "").replace("$UNKNOWN", "Unknown"),
                f"Spend ({currency})": c.get("spend", 0),
                "Impressions": c.get("impressions", 0),
                "Clicks": c.get("clicks", 0),
                "Engagements": c.get("engagements", 0),
                "CTR": c.get("ctr", ""),
                "Engagement Rate": c.get("engagementRate", ""),
                "Companies Reached": c.get("companiesReached", 0),
                "Companies Engaged": c.get("companiesEngaged", 0),
            })

        # Append totals row
        totals = data.get("totals", {})
        if totals:
            rows.append({
                "Campaign": "TOTAL",
                "Format": "",
                f"Spend ({currency})": totals.get("spend", 0),
                "Impressions": totals.get("impressions", 0),
                "Clicks": totals.get("clicks", 0),
                "Engagements": totals.get("engagements", 0),
                "CTR": "",
                "Engagement Rate": "",
                "Companies Reached": totals.get("companiesReached", 0),
                "Companies Engaged": totals.get("companiesEngaged", 0),
            })

        return rows

    # ------------------------------------------------------------------
    # 2. Monthly trend
    # ------------------------------------------------------------------

    def get_monthly_trend(self) -> list[dict[str, Any]]:
        """
        Month-by-month LinkedIn ad performance with MoM change percentages.
        Covers the report period (up to 24 months).
        """
        from datetime import date

        # Calculate months between start and end
        start = date.fromisoformat(self._start_month + "-01")
        end = date.fromisoformat(self._end_month + "-01")
        months = (end.year - start.year) * 12 + (end.month - start.month) + 1

        data = self._call("get_trend_data", {
            "months": min(months, 24),
            "metrics": "all",
        })

        rows = []
        for m in data.get("adMetrics", []):
            month = m.get("month", "")
            # Filter to report range
            if month < self._start_month or month > self._end_month:
                continue
            rows.append({
                "Month": month,
                "Impressions": m.get("impressions", 0),
                "Impressions MoM": m.get("impressionsChange") or "",
                "Clicks": m.get("clicks", 0),
                "Clicks MoM": m.get("clicksChange") or "",
                "Engagements": m.get("engagements", 0),
                "Engagements MoM": m.get("engagementsChange") or "",
                "Companies Reached": m.get("companiesReached", 0),
                "Companies Reached MoM": m.get("companiesReachedChange") or "",
                "Companies Engaged": m.get("companiesEngaged", 0),
                "Companies Engaged MoM": m.get("companiesEngagedChange") or "",
            })

        return rows
