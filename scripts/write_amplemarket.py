#!/usr/bin/env python3
"""
Writes Amplemarket signal-grouped analytics to Google Sheets.

Reads a JSON file (or stdin) containing a list of pre-aggregated signal rows:
  [
    {
      "signal": "Cold Outreach",
      "sequence_count": 1303,
      "enrollments": 500,
      "emails_sent": 2000,
      "opens": 800,
      "replies": 40,
      "bounces": 10,
      "interested_count": 5,
      "meeting_count": 2
    },
    ...
  ]

Computes rates from raw counts, then writes to the 'Amplemarket - Signal Analytics'
tab in Google Sheets.

Usage:
  python3 scripts/write_amplemarket.py /tmp/amplemarket_signals.json
  echo '[...]' | python3 scripts/write_amplemarket.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import SHEET_TABS
from writers.google_sheets import SheetsWriter


def _pct(numerator, denominator):
    try:
        return round(int(numerator) / int(denominator) * 100, 2) if int(denominator) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _int(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def format_rows(signals: list) -> list[dict]:
    rows = []
    for s in signals:
        sent = _int(s.get("emails_sent"))
        enr  = _int(s.get("enrollments"))
        rows.append({
            "Signal": s.get("signal", ""),
            "Sequences": _int(s.get("sequence_count")),
            "Enrollments": enr,
            "Emails Sent": sent,
            "Opens":   _int(s.get("opens")),
            "Replies": _int(s.get("replies")),
            "Bounces": _int(s.get("bounces")),
            "Open Rate %":   _pct(s.get("opens"),   sent),
            "Reply Rate %":  _pct(s.get("replies"), sent),
            "Bounce Rate %": _pct(s.get("bounces"), sent),
            "Interested": _int(s.get("interested_count")),
            "Meetings Booked": _int(s.get("meeting_count")),
        })
    return rows


def main():
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            signals = json.load(f)
    else:
        signals = json.load(sys.stdin)

    if not signals:
        print("ERROR: Empty signal list.", file=sys.stderr)
        sys.exit(1)

    rows = format_rows(signals)
    print(f"Formatted {len(rows)} signal groups.")

    writer = SheetsWriter()
    writer.write(SHEET_TABS["amplemarket_signals"], rows)
    print(f"Written to '{SHEET_TABS['amplemarket_signals']}'.")


if __name__ == "__main__":
    main()
