#!/usr/bin/env python3
"""
Fetches all Amplemarket sequence names via the REST API and extracts
unique Duo Copilot signal labels (the part after " – " in each name).

Outputs a JSON list of {signal, sequence_count} objects, sorted by
sequence count descending.

Usage:
  python3 scripts/get_amplemarket_signals.py
"""

import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from config import AmplemarketConfig

_BASE_URL = "https://api.amplemarket.com"
_SEP = " – "  # EN DASH with spaces

# Custom CRM signals to report on. Add to this list when new signals are created.
CUSTOM_SIGNALS = {
    "AIS intent retail",
    "[Retail] Agentic Search Lane",
    "Engaged with a post about Shoptalk",
    "High Ascend intent from LinkedIn Ads",
}


def main():
    cfg = AmplemarketConfig.load()
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Accept": "application/json"}

    signals: Counter = Counter()
    cursor = None

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
            if _SEP in name:
                signal = name.split(_SEP, 1)[1].strip()
                if signal in CUSTOM_SIGNALS:
                    signals[signal] += 1

        next_href = data.get("_links", {}).get("next", {}).get("href", "")
        match = re.search(r"page\[after\]=([^&]+)", next_href)
        cursor = match.group(1) if match else None
        if not cursor:
            break

    result = [
        {"signal": sig, "sequence_count": count}
        for sig, count in signals.most_common()
    ]
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
