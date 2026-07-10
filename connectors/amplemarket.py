"""
Amplemarket connector — sequence list via Amplemarket's public REST API.

The public API (api.amplemarket.com) provides sequence metadata only.
Analytics (opens, replies, bounces, enrollment counts) are not exposed in
the public API — they require a browser session JWT that Amplemarket's MCP
server uses internally.

What this connector provides:
  - Sequence name, status (active / paused / draft), owner email
  - Created / last-updated timestamps

Auth: Bearer <AMPLEMARKET_API_KEY> in Authorization header.
Pagination: cursor-based via _links.next.href (page[after] / page[size]).
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests

from config import AmplemarketConfig

_BASE_URL = "https://api.amplemarket.com"


class AmplemarketConnector:
    def __init__(self):
        cfg = AmplemarketConfig.load()
        self._headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "Accept": "application/json",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        r = requests.get(f"{_BASE_URL}{path}", headers=self._headers,
                         params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Sequence list
    # ------------------------------------------------------------------

    def get_sequence_performance(self) -> list[dict[str, Any]]:
        """
        All sequences with status and owner. Sorted active-first then by name.

        NOTE: The Amplemarket public API does not expose analytics metrics
        (enrollment counts, open rates, reply rates, etc.). Those are only
        accessible via Amplemarket's analytics backend which requires a
        browser session token. To get per-sequence analytics, Amplemarket
        would need to add analytics endpoints to their public API.
        """
        sequences: list[dict] = []
        cursor = None

        while True:
            params: dict[str, Any] = {"page[size]": 100}
            if cursor:
                params["page[after]"] = cursor
            data = self._get("/sequences", params=params)
            sequences.extend(data.get("sequences", []))

            next_link = data.get("_links", {}).get("next", {}).get("href", "")
            match = re.search(r"page\[after\]=([^&]+)", next_link)
            cursor = match.group(1) if match else None
            if not cursor:
                break

        rows = []
        for seq in sequences:
            rows.append({
                "Sequence": seq.get("name", "").strip(),
                "Status": seq.get("status", ""),
                "Priority": seq.get("priority", ""),
                "Owner": seq.get("created_by_user_email", ""),
                "Created": seq.get("created_at", "")[:10],
                "Last Updated": seq.get("updated_at", "")[:10],
                "URL": seq.get("url", ""),
            })

        # Sort: active first, then alphabetically
        _STATUS_RANK = {"active": 0, "paused": 1, "draft": 2}
        rows.sort(key=lambda r: (_STATUS_RANK.get(r["Status"], 9), r["Sequence"]))
        return rows
