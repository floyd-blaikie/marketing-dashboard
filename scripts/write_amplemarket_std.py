#!/usr/bin/env python3
"""
Writes standard Amplemarket sequence analytics to Google Sheets.

Reads a JSON file (or stdin) containing a list of pre-aggregated sequence rows:
  [
    {
      "sequence": "B2B Online Follow up",
      "enrollments": 120,
      "emails_sent": 480,
      "opens": 150,
      "replies": 18,
      "bounces": 5,
      "interested_count": 3,
      "meeting_count": 1
    },
    ...
  ]

Computes rates from raw counts, then writes to the 'Amplemarket - Std Sequences'
tab in Google Sheets.

Usage:
  python3 scripts/write_amplemarket_std.py /tmp/amplemarket_std_result.json
  echo '[...]' | python3 scripts/write_amplemarket_std.py
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


def format_rows(sequences: list) -> list[dict]:
    rows = []
    for s in sequences:
        sent = _int(s.get("emails_sent"))
        rows.append({
            "Sequence": s.get("sequence", ""),
            "Enrollments": _int(s.get("enrollments")),
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
            sequences = json.load(f)
    else:
        sequences = json.load(sys.stdin)

    if not sequences:
        print("ERROR: Empty sequence list.", file=sys.stderr)
        sys.exit(1)

    rows = format_rows(sequences)
    print(f"Formatted {len(rows)} standard sequences.")

    writer = SheetsWriter()
    writer.write(SHEET_TABS["amplemarket_std_sequences"], rows)
    print(f"Written to '{SHEET_TABS['amplemarket_std_sequences']}'.")


if __name__ == "__main__":
    main()
