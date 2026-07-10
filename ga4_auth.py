"""
One-time GA4 OAuth2 authorization.

Run this once to get a refresh token, then add it to .env.
After that the GA4 connector runs headlessly — no browser needed again.

Usage:
    python ga4_auth.py
"""

import json
import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv, set_key

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
CLIENT_SECRET = "credentials/ga4_oauth_client.json"
ENV_FILE = ".env"


def main():
    if not Path(CLIENT_SECRET).exists():
        raise FileNotFoundError(f"Client secret not found at {CLIENT_SECRET}")

    print("Opening browser for Google authorization...")
    print("Log in with the Google account that has access to your GA4 property.\n")

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, scopes=SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")

    client_info = json.loads(Path(CLIENT_SECRET).read_text())["installed"]

    load_dotenv(ENV_FILE)
    set_key(ENV_FILE, "GA4_CLIENT_ID", client_info["client_id"])
    set_key(ENV_FILE, "GA4_CLIENT_SECRET", client_info["client_secret"])
    set_key(ENV_FILE, "GA4_REFRESH_TOKEN", creds.refresh_token)

    print("\nSuccess! The following values have been written to .env:")
    print(f"  GA4_CLIENT_ID     = {client_info['client_id'][:20]}...")
    print(f"  GA4_CLIENT_SECRET = {client_info['client_secret'][:10]}...")
    print(f"  GA4_REFRESH_TOKEN = {creds.refresh_token[:20]}...")
    print("\nYou can delete ga4_auth.py — it's only needed once.")


if __name__ == "__main__":
    main()
