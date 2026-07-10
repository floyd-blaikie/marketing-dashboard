"""
Marketing data pipeline — main entry point.

Usage:
    python main.py                  # run all enabled connectors
    python main.py --only hubspot   # run a single connector by name
"""

import argparse
import csv
import os
import sys

from config import SHEET_TABS
from connectors.hubspot import HubSpotConnector
from connectors.google_ads import GoogleAdsConnector
from connectors.ga4 import GA4Connector
from connectors.fibbler import FibblerConnector
from connectors.amplemarket import AmplemarketConnector
from writers.google_sheets import SheetsWriter

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_campaign_lookup() -> dict[str, str]:
    """
    Returns {native_name: marketing_campaign} from campaign_map.csv.
    When a native name maps to multiple campaigns, the spend_owner=Y row wins;
    otherwise the first row seen is used.
    """
    path = os.path.join(_HERE, "campaign_map.csv")
    if not os.path.exists(path):
        return {}
    lookup: dict[str, str] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            name = row.get("native_name", "").strip()
            camp = row.get("marketing_campaign", "").strip()
            owner = row.get("spend_owner", "").strip().upper()
            if name and camp:
                if owner == "Y" or name not in lookup:
                    lookup[name] = camp
    return lookup


def run_hubspot(writer: SheetsWriter) -> None:
    print("\n[HubSpot] Fetching data...")
    hs = HubSpotConnector()

    print("  Pulling email campaign performance...")
    try:
        emails = hs.get_email_campaigns()
        writer.write(SHEET_TABS["hubspot_emails"], emails)
    except Exception:
        print("  [skipped] Marketing emails not available — requires Marketing Hub Pro scope.")

    print("  Pulling contact acquisition...")
    contacts = hs.get_contact_acquisition()
    writer.write(SHEET_TABS["hubspot_contacts"], contacts)

    print("  Pulling deal pipeline...")
    deals = hs.get_deal_pipeline()
    writer.write(SHEET_TABS["hubspot_deals"], deals)

    print("  Pulling 1:1 email activity by user...")
    user_emails = hs.get_email_activity_by_user()
    writer.write(SHEET_TABS["hubspot_user_emails"], user_emails)

    print("  Pulling Sales Sequences performance...")
    sequences = hs.get_sequence_performance()
    writer.write(SHEET_TABS["hubspot_sequences"], sequences)

    print("  Pulling lifecycle stage progression (weekly)...")
    lifecycle = hs.get_lifecycle_stage_progression_weekly()
    writer.write(SHEET_TABS["hubspot_lifecycle"], lifecycle)

    print("  Pulling engaged accounts (weekly)...")
    engaged = hs.get_engaged_accounts_weekly()
    writer.write(SHEET_TABS["hubspot_engaged"], engaged)

    print("  Pulling intent spikes (weekly)...")
    intent = hs.get_intent_spikes_weekly()
    writer.write(SHEET_TABS["hubspot_intent"], intent)

    print("  Pulling calls by rep...")
    calls = hs.get_calls_by_rep()
    writer.write(SHEET_TABS["hubspot_calls"], calls)

    print("  Pulling LinkedIn engagement by company (Fibbler)...")
    linkedin = hs.get_linkedin_engagement_by_company()
    writer.write(SHEET_TABS["hubspot_linkedin"], linkedin)

    print("[HubSpot] Done.")



def run_linkedin(writer: SheetsWriter) -> None:
    print("\n[LinkedIn / Fibbler] Fetching data...")
    fb = FibblerConnector()

    print("  Pulling campaign performance...")
    campaigns = fb.get_campaign_performance()
    writer.write(SHEET_TABS["linkedin_campaigns"], campaigns)

    print("  Pulling monthly trend...")
    trend = fb.get_monthly_trend()
    writer.write(SHEET_TABS["linkedin_trend"], trend)

    print("[LinkedIn / Fibbler] Done.")


def run_google_ads(writer: SheetsWriter, monthly_rows: list) -> None:
    print("\n[Google Ads] Fetching data...")
    ads = GoogleAdsConnector()

    print("  Pulling weekly totals...")
    weekly = ads.get_weekly_totals()
    writer.write(SHEET_TABS["google_ads_weekly"], weekly)

    print("  Pulling campaign summary...")
    campaigns = ads.get_campaign_summary()
    writer.write(SHEET_TABS["google_ads_campaigns"], campaigns)

    print("  Pulling top search terms...")
    terms = ads.get_top_search_terms()
    writer.write(SHEET_TABS["google_ads_search_terms"], terms)

    print("  Pulling campaign monthly breakdown...")
    campaign_map = _load_campaign_lookup()
    for row in ads.get_campaign_monthly():
        row["Marketing Campaign"] = campaign_map.get(row["Campaign (native)"], "")
        monthly_rows.append(row)

    print("[Google Ads] Done.")


def run_ga4(writer: SheetsWriter, monthly_rows: list) -> None:
    print("\n[GA4] Fetching data...")
    ga4 = GA4Connector()

    print("  Pulling weekly traffic overview...")
    traffic = ga4.get_weekly_traffic()
    writer.write(SHEET_TABS["ga4_traffic"], traffic)

    print("  Pulling channel breakdown...")
    channels = ga4.get_channel_breakdown()
    writer.write(SHEET_TABS["ga4_channels"], channels)

    print("  Pulling top pages...")
    pages = ga4.get_top_pages()
    writer.write(SHEET_TABS["ga4_pages"], pages)

    print("  Pulling pages by month...")
    campaign_map = _load_campaign_lookup()
    for row in ga4.get_pages_by_month():
        row["Marketing Campaign"] = campaign_map.get(row["Campaign (native)"], "")
        monthly_rows.append(row)

    print("[GA4] Done.")


def run_amplemarket(writer: SheetsWriter) -> None:
    print("\n[Amplemarket] Fetching data...")
    am = AmplemarketConnector()

    print("  Pulling sequence performance (this may take ~60s for analytics)...")
    sequences = am.get_sequence_performance()
    writer.write(SHEET_TABS["amplemarket_sequences"], sequences)

    print("[Amplemarket] Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Marketing data pipeline")
    parser.add_argument(
        "--only",
        choices=["hubspot", "google_ads", "ga4", "linkedin", "amplemarket"],
        help="Run a single connector instead of all.",
    )
    args = parser.parse_args()

    writer = SheetsWriter()
    targets = (
        [args.only] if args.only
        else ["hubspot", "google_ads", "ga4", "linkedin", "amplemarket"]
    )

    # Campaign x Month is written at the end, after collecting rows from all connectors
    monthly_rows: list[dict] = []

    for name in targets:
        try:
            if name == "hubspot":
                run_hubspot(writer)
            elif name == "google_ads":
                run_google_ads(writer, monthly_rows)
            elif name == "ga4":
                run_ga4(writer, monthly_rows)
            elif name == "linkedin":
                run_linkedin(writer)
            elif name == "amplemarket":
                run_amplemarket(writer)
        except NotImplementedError:
            print(f"[{name}] Skipped — not yet implemented.")
        except Exception as e:
            print(f"[{name}] ERROR: {e}", file=sys.stderr)
            raise

    if monthly_rows:
        _write_campaign_x_month(writer, monthly_rows)

    # On a full run, rebuild the campaign rollups and refresh the boss-facing
    # exec sheet. Skipped for --only runs (rollups need all raw tabs fresh).
    if not args.only:
        try:
            import campaign_rollup
            print("\n[Rollups] Rebuilding campaign rollup tabs...")
            campaign_rollup.build(reseed=False)
        except Exception as e:
            print(f"[Rollups] ERROR: {e}", file=sys.stderr)
        try:
            import exec_report
            print("\n[Exec report] Refreshing boss-facing sheet...")
            exec_report.build()
        except Exception as e:
            print(f"[Exec report] ERROR: {e}", file=sys.stderr)

    print("\nAll done. Check your Google Sheet.")


def _write_campaign_x_month(writer: SheetsWriter, rows: list[dict]) -> None:
    """
    Writes the Campaign x Month long-format tab, with columns ordered so the
    Campaign Map can resolve native names to marketing campaigns via SUMIFS.

    Column order:
      Campaign (native) | Marketing Campaign | Month | Platform |
      Spend ($) | Impressions | Clicks | Engagements | Conversions |
      Enrollments | Emails | Replies | Interested | Meetings | Sessions
    """
    ORDERED_COLS = [
        "Campaign (native)", "Marketing Campaign", "Month", "Platform",
        "Spend ($)", "Impressions", "Clicks", "Engagements", "Conversions",
        "Enrollments", "Emails", "Replies", "Interested", "Meetings", "Sessions",
    ]
    normalized = [{col: row.get(col, 0) for col in ORDERED_COLS} for row in rows]
    writer.write(SHEET_TABS["campaign_x_month"], normalized)
    print(f"\n[Campaign x Month] Wrote {len(rows)} rows.")


if __name__ == "__main__":
    main()
