#!/usr/bin/env python3
"""
Fetches standard (non-Duo Copilot) Amplemarket sequences that have run
in the past 90 days, via the REST API.

Duo Copilot sequences contain ' – ' (EN DASH with spaces) in their name.
Standard sequences are everything else.

"Run in the past 90 days" is approximated by updated_at >= (today - 90d)
since the REST API exposes no per-sequence analytics timestamps.

Outputs a JSON list of {"sequence": "..."} objects, sorted alphabetically.

Usage:
  python3 scripts/get_amplemarket_standard_sequences.py
"""

import json
import os
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from config import AmplemarketConfig

_BASE_URL = "https://api.amplemarket.com"
_DUO_COPILOT_SEP = " – "  # EN DASH with spaces — marks Duo Copilot sequences


def main():
    cfg = AmplemarketConfig.load()
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Accept": "application/json"}

    cutoff = (date.today() - timedelta(days=90)).isoformat()
    sequences, cursor = [], None

    while True:
        params = {"page[size]": 100}
        if cursor:
            params["page[after]"] = cursor
        r = requests.get(f"{_BASE_URL}/sequences", headers=headers,
                         params=params, timeout=30)
        r.raise_for_status()
        data = r.json()

        for seq in data.get("sequences", []):
            name = seq.get("name", "").strip()
            if _DUO_COPILOT_SEP in name:
                continue
            if seq.get("updated_at", "")[:10] >= cutoff:
                sequences.append({"sequence": name})

        next_href = data.get("_links", {}).get("next", {}).get("href", "")
        match = re.search(r"page\[after\]=([^&]+)", next_href)
        cursor = match.group(1) if match else None
        if not cursor:
            break

    sequences.sort(key=lambda x: x["sequence"])
    print(json.dumps(sequences, indent=2))


if __name__ == "__main__":
    main()
