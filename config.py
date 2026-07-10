import os
from datetime import date
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Missing required environment variable: {key}")
    return value


class HubSpotConfig:
    access_token: str = ""

    @classmethod
    def load(cls):
        cls.access_token = _require("HUBSPOT_ACCESS_TOKEN")
        return cls


class SheetsConfig:
    spreadsheet_id: str = ""
    service_account_json: str = ""

    @classmethod
    def load(cls):
        cls.spreadsheet_id = _require("GOOGLE_SHEETS_SPREADSHEET_ID")
        cls.service_account_json = _require("GOOGLE_SERVICE_ACCOUNT_JSON")
        return cls


class AmplemarketConfig:
    api_key: str = ""

    @classmethod
    def load(cls):
        cls.api_key = _require("AMPLEMARKET_API_KEY")
        return cls


class FibblerConfig:
    api_key: str = ""

    @classmethod
    def load(cls):
        cls.api_key = _require("FIBBLER_API_KEY")
        return cls


class GA4Config:
    property_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""

    @classmethod
    def load(cls):
        cls.property_id = _require("GA4_PROPERTY_ID")
        cls.client_id = _require("GA4_CLIENT_ID")
        cls.client_secret = _require("GA4_CLIENT_SECRET")
        cls.refresh_token = _require("GA4_REFRESH_TOKEN")
        return cls


class DateConfig:
    start_date: str = ""
    end_date: str = ""

    @classmethod
    def load(cls):
        cls.start_date = os.getenv("REPORT_START_DATE", "2026-01-01")
        cls.end_date = os.getenv("REPORT_END_DATE", date.today().isoformat())
        return cls


# Tab names in the Google Sheet — change these to match your sheet layout
SHEET_TABS = {
    "hubspot_emails": "HubSpot - Emails",
    "hubspot_contacts": "HubSpot - Contacts",
    "hubspot_deals": "HubSpot - Deals",
    "hubspot_user_emails": "HubSpot - User Email Activity",
    "hubspot_sequences": "HubSpot - Sequences",
    "hubspot_lifecycle": "HubSpot - Lifecycle Stages",
    "hubspot_engaged": "HubSpot - Engaged Accounts",
    "hubspot_intent": "HubSpot - Intent Spikes",
    "hubspot_calls": "HubSpot - Calls by Rep",
    "hubspot_linkedin": "HubSpot - LinkedIn Engagement",
    "linkedin_campaigns": "LinkedIn - Campaigns",
    "linkedin_trend": "LinkedIn - Monthly Trend",
    "google_ads_weekly": "Google Ads - Weekly",
    "google_ads_campaigns": "Google Ads - Campaigns",
    "google_ads_search_terms": "Google Ads - Search Terms",
    "amplemarket_sequences": "Amplemarket - Sequences",
    "amplemarket_signals": "Amplemarket - Signal Analytics",
    "amplemarket_std_sequences": "Amplemarket - Std Sequences",
    "ga4_traffic": "GA4 - Traffic",
    "ga4_channels": "GA4 - Channels",
    "ga4_pages": "GA4 - Top Pages",
    "campaign_x_month": "Campaign x Month",
}
