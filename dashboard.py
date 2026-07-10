"""
Pivotree Marketing Dashboard — full-funnel view

Local:  streamlit run dashboard.py
Cloud:  deploy to share.streamlit.io
"""

import os
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(
    page_title="Pivotree Marketing Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_creds():
    try:
        info = dict(st.secrets["gcp_service_account"])
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    except (KeyError, AttributeError):
        from dotenv import load_dotenv
        load_dotenv()
        return Credentials.from_service_account_file(
            os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"], scopes=SCOPES
        )


def _sheet_id():
    try:
        return st.secrets["GOOGLE_SHEETS_SPREADSHEET_ID"]
    except (KeyError, AttributeError):
        from dotenv import load_dotenv
        load_dotenv()
        return os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"]


@st.cache_data(ttl=300)
def _load(tab: str) -> pd.DataFrame:
    gc = gspread.authorize(_get_creds())
    ss = gc.open_by_key(_sheet_id())
    ws = ss.worksheet(tab)
    return pd.DataFrame(ws.get_all_records())


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_num(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df


def _drop_total(df, key="Campaign"):
    mask = (
        df[key].astype(str).str.startswith("TOTAL") |
        df[key].astype(str).str.startswith("PORTFOLIO") |
        df[key].astype(str).str.startswith("YTD")
    )
    total = df[mask].iloc[0] if mask.any() else None
    return df[~mask].copy(), total


def _kpi(col, label, value, prefix="", suffix="", decimals=0):
    try:
        v = float(value or 0)
        formatted = f"{prefix}{v:,.{decimals}f}{suffix}"
    except Exception:
        formatted = "—"
    col.metric(label, formatted)


# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("## Pivotree  |  Marketing Performance")
st.caption("Refreshes every 5 minutes · Pipeline = open deals · Bookings = Closed Won · Leads = Google Ads conversions + Amplemarket interested")

tab_funnel, tab_monthly, tab_channels = st.tabs([
    "📊 Campaign Performance",
    "📅 Monthly Trend",
    "📣 Channel Detail",
])


# ── Tab 1: Campaign Performance (Full Funnel) ─────────────────────────────────

with tab_funnel:

    # Load and merge KPI Dashboard (impressions) + Pipeline & Revenue (spend → revenue)
    kpi_df = _load("KPI Dashboard")
    pr_df  = _load("Pipeline & Revenue")

    if kpi_df.empty or pr_df.empty:
        st.info("No data yet — run `python3 main.py` then `python3 campaign_rollup.py`.")
    else:
        kpi_camps, kpi_total = _drop_total(kpi_df)
        pr_camps,  pr_total  = _drop_total(pr_df)

        kpi_num = ["Impressions", "Engagements", "Leads (proxy)", "Meetings",
                   "Opps", "Pipeline ($)", "Bookings ($)"]
        pr_num  = ["Spend ($)", "Meetings", "Leads (proxy)", "Opps",
                   "Pipeline ($)", "Bookings ($)", "Pipeline ROAS"]

        kpi_camps = _to_num(kpi_camps, kpi_num)
        pr_camps  = _to_num(pr_camps,  pr_num)

        # Merge: get Impressions + Engagements from KPI, everything else from P&R
        merged = pr_camps.merge(
            kpi_camps[["Campaign", "Impressions", "Engagements"]],
            on="Campaign", how="left"
        ).fillna(0)

        # ── Portfolio KPI cards ───────────────────────────────────────────────
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        _kpi(c1, "Total Spend",    pr_total.get("Spend ($)", 0)    if pr_total is not None else 0,  prefix="$")
        _kpi(c2, "Impressions",    kpi_total.get("Impressions", 0) if kpi_total is not None else 0)
        _kpi(c3, "Leads (proxy)",  kpi_total.get("Leads (proxy)", 0) if kpi_total is not None else 0)
        _kpi(c4, "Meetings",       kpi_total.get("Meetings", 0)    if kpi_total is not None else 0)
        _kpi(c5, "Open Pipeline",  kpi_total.get("Pipeline ($)", 0) if kpi_total is not None else 0, prefix="$")
        _kpi(c6, "Bookings",       kpi_total.get("Bookings ($)", 0) if kpi_total is not None else 0, prefix="$")

        st.divider()

        # ── Full-funnel table ─────────────────────────────────────────────────
        st.subheader("Full Funnel by Campaign")
        st.caption("Spend → Awareness → Engagement → Leads → Meetings → Pipeline → Revenue")

        funnel_cols = [
            "Campaign", "Status",
            "Spend ($)",        # investment
            "Impressions",      # awareness
            "Engagements",      # engagement
            "Leads (proxy)",    # leads
            "Meetings",         # meetings
            "Opps",             # opportunities
            "Pipeline ($)",     # open pipeline
            "Bookings ($)",     # closed won
            "Pipeline ROAS",    # efficiency
        ]
        display = merged[funnel_cols].copy()

        st.dataframe(
            display.style.format({
                "Spend ($)":      "${:,.0f}",
                "Impressions":    "{:,.0f}",
                "Engagements":    "{:,.0f}",
                "Leads (proxy)":  "{:,.0f}",
                "Meetings":       "{:,.0f}",
                "Opps":           "{:,.0f}",
                "Pipeline ($)":   "${:,.0f}",
                "Bookings ($)":   "${:,.0f}",
                "Pipeline ROAS":  "{:.1f}x",
            }).background_gradient(
                subset=["Pipeline ($)", "Bookings ($)"],
                cmap="Greens"
            ).background_gradient(
                subset=["Spend ($)"],
                cmap="Blues"
            ),
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        # ── Charts ────────────────────────────────────────────────────────────
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("Open Pipeline by Campaign")
            pipeline_chart = merged.set_index("Campaign")[["Pipeline ($)"]].sort_values("Pipeline ($)", ascending=False)
            st.bar_chart(pipeline_chart)

        with col_right:
            st.subheader("Spend vs Bookings")
            spend_vs = merged.set_index("Campaign")[["Spend ($)", "Bookings ($)"]].sort_values("Spend ($)", ascending=False)
            st.bar_chart(spend_vs)


# ── Tab 2: Monthly Trend ──────────────────────────────────────────────────────

with tab_monthly:
    df = _load("Monthly Trend")
    if df.empty:
        st.info("No data yet.")
    else:
        trend, _ = _drop_total(df, key="Month")
        num_cols = ["Paid Spend ($)", "LI Impressions", "LI Clicks", "LI Engagements",
                    "Ads Impressions", "Ads Clicks", "Website Sessions"]
        trend = _to_num(trend, num_cols)

        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("Paid Spend ($) by Month")
            st.bar_chart(trend.set_index("Month")[["Paid Spend ($)"]])
        with col_right:
            st.subheader("Website Sessions by Month")
            st.bar_chart(trend.set_index("Month")[["Website Sessions"]])

        st.subheader("Impressions by Month (LinkedIn vs Google Ads)")
        st.line_chart(trend.set_index("Month")[["LI Impressions", "Ads Impressions"]])

        st.subheader("Full Monthly Breakdown")
        st.dataframe(
            trend.style.format({
                "Paid Spend ($)":   "${:,.0f}",
                "LI Impressions":   "{:,.0f}",
                "LI Clicks":        "{:,.0f}",
                "LI Engagements":   "{:,.0f}",
                "Ads Impressions":  "{:,.0f}",
                "Ads Clicks":       "{:,.0f}",
                "Website Sessions": "{:,.0f}",
            }),
            use_container_width=True,
            hide_index=True,
        )


# ── Tab 3: Channel Detail ─────────────────────────────────────────────────────

with tab_channels:
    df = _load("Channel Metrics")
    if df.empty:
        st.info("No data yet.")
    else:
        camps, _ = _drop_total(df)
        num_cols  = ["Emails Sent", "Opens", "Replies", "Impressions",
                     "Clicks", "Engagements", "Sessions"]
        rate_cols = ["Open Rate", "Reply Rate", "CTR"]
        camps = _to_num(camps, num_cols + rate_cols)

        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("Email Performance")
            st.dataframe(
                camps[["Campaign", "Emails Sent", "Opens", "Open Rate",
                        "Replies", "Reply Rate"]].style.format({
                    "Emails Sent": "{:,.0f}",
                    "Opens":       "{:,.0f}",
                    "Replies":     "{:,.0f}",
                    "Open Rate":   "{:.1%}",
                    "Reply Rate":  "{:.1%}",
                }),
                use_container_width=True, hide_index=True,
            )
        with col_right:
            st.subheader("Paid & Web")
            st.dataframe(
                camps[["Campaign", "Impressions", "Clicks", "CTR",
                        "Engagements", "Sessions"]].style.format({
                    "Impressions":  "{:,.0f}",
                    "Clicks":       "{:,.0f}",
                    "Engagements":  "{:,.0f}",
                    "Sessions":     "{:,.0f}",
                    "CTR":          "{:.1%}",
                }),
                use_container_width=True, hide_index=True,
            )

        st.subheader("Impressions · Clicks · Engagements by Campaign")
        st.bar_chart(
            camps.set_index("Campaign")[["Impressions", "Clicks", "Engagements"]]
                 .sort_values("Impressions", ascending=False)
        )
