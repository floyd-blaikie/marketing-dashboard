"""
One-time Google Ads OAuth2 authorization.

Run this once to get a refresh token, then it's stored in .env automatically.

Usage:
    python google_ads_auth.py
"""

import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv, set_key

SCOPES = ["https://www.googleapis.com/auth/adwords"]
CLIENT_SECRET = "credentials/google_ads_oauth_client.json"
ENV_FILE = ".env"


def main():
    if not Path(CLIENT_SECRET).exists():
        raise FileNotFoundError(f"Client secret not found at {CLIENT_SECRET}")

    print("Opening browser for Google authorization...")
    print("Log in with the Google account that has access to your Google Ads account.\n")

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, scopes=SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")

    client_info = json.loads(Path(CLIENT_SECRET).read_text())["installed"]

    load_dotenv(ENV_FILE)
    set_key(ENV_FILE, "GOOGLE_ADS_CLIENT_ID", client_info["client_id"])
    set_key(ENV_FILE, "GOOGLE_ADS_CLIENT_SECRET", client_info["client_secret"])
    set_key(ENV_FILE, "GOOGLE_ADS_REFRESH_TOKEN", creds.refresh_token)

    print("\nSuccess! Written to .env:")
    print(f"  GOOGLE_ADS_CLIENT_ID     = {client_info['client_id'][:20]}...")
    print(f"  GOOGLE_ADS_CLIENT_SECRET = {client_info['client_secret'][:10]}...")
    print(f"  GOOGLE_ADS_REFRESH_TOKEN = {creds.refresh_token[:20]}...")
    print("\nYou can delete google_ads_auth.py — it's only needed once.")


if __name__ == "__main__":
    main()
