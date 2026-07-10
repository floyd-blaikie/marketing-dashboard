"""
Pivotree Marketing Dashboard

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


# ── Credentials ───────────────────────────────────────────────────────────────

def _get_creds():
    """Streamlit Cloud: reads from st.secrets. Locally: reads from .env file."""
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


def _split_total(df, key_col="Campaign"):
    """Split a tab into (campaign rows, total row). Total row has 'TOTAL' in key column."""
    is_total = df[key_col].astype(str).str.startswith("TOTAL") | \
               df[key_col].astype(str).str.startswith("PORTFOLIO") | \
               df[key_col].astype(str).str.startswith("YTD")
    total = df[is_total].iloc[0] if is_total.any() else None
    return df[~is_total].copy(), total


def _metric(label, value, fmt="$"):
    if fmt == "$":
        return label, f"${float(value or 0):,.0f}"
    if fmt == "%":
        return label, f"{float(value or 0):.1%}"
    return label, f"{int(float(value or 0)):,}"


# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("## Pivotree  |  Marketing Performance Dashboard")
st.caption(
    "Data refreshes every 5 minutes from the live Google Sheet. "
    "Pipeline = open deals only. Bookings = Closed Won."
)

tab_overview, tab_pipeline, tab_channels, tab_monthly, tab_cxm = st.tabs([
    "📊 Overview",
    "💰 Pipeline & Revenue",
    "📣 Channel Performance",
    "📅 Monthly Trend",
    "🗓️ Campaign × Month",
])


# ── Overview ──────────────────────────────────────────────────────────────────

with tab_overview:
    df = _load("KPI Dashboard")
    if df.empty:
        st.info("No data yet — run `python3 main.py` then `python3 campaign_rollup.py`.")
    else:
        camps, total = _split_total(df)
        num_cols = ["Impressions", "Engagements", "Website Sessions", "Leads (proxy)",
                    "Meetings", "Opps"]
        curr_cols = ["Pipeline ($)", "Bookings ($)", "CPL ($)"]
        pct_cols  = ["Open Rate", "CTR", "Eng. Rate", "Conv. Rate"]
        camps = _to_num(camps, num_cols + curr_cols + pct_cols)

        if total is not None:
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("Impressions",    f"{int(float(total.get('Impressions', 0) or 0)):,}")
            c2.metric("Leads (proxy)",  f"{int(float(total.get('Leads (proxy)', 0) or 0)):,}")
            c3.metric("Meetings",       f"{int(float(total.get('Meetings', 0) or 0)):,}")
            c4.metric("Opps",           f"{int(float(total.get('Opps', 0) or 0)):,}")
            c5.metric("Open Pipeline",  f"${float(total.get('Pipeline ($)', 0) or 0):,.0f}")
            c6.metric("Bookings",       f"${float(total.get('Bookings ($)', 0) or 0):,.0f}")

        st.divider()
        st.subheader("All Campaigns")
        st.dataframe(
            camps[["Campaign", "Impressions", "Leads (proxy)", "Meetings",
                   "Opps", "Pipeline ($)", "Bookings ($)", "CPL ($)"]].style.format({
                "Impressions":   "{:,.0f}",
                "Leads (proxy)": "{:,.0f}",
                "Meetings":      "{:,.0f}",
                "Opps":          "{:,.0f}",
                "Pipeline ($)":  "${:,.0f}",
                "Bookings ($)":  "${:,.0f}",
                "CPL ($)":       "${:,.0f}",
            }),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Impressions by Campaign")
        st.bar_chart(camps.set_index("Campaign")[["Impressions"]])


# ── Pipeline & Revenue ────────────────────────────────────────────────────────

with tab_pipeline:
    df = _load("Pipeline & Revenue")
    if df.empty:
        st.info("No data yet — run the pipeline first.")
    else:
        camps, total = _split_total(df)
        num_cols  = ["Meetings", "Leads (proxy)", "Opps"]
        curr_cols = ["Opp Value ($)", "Pipeline ($)", "Weighted Pipeline ($)",
                     "Bookings ($)", "Spend ($)"]
        camps = _to_num(camps, num_cols + curr_cols + ["Close Rate", "Pipeline ROAS"])

        if total is not None:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Open Pipeline", f"${float(total.get('Pipeline ($)', 0) or 0):,.0f}")
            c2.metric("Bookings",      f"${float(total.get('Bookings ($)', 0) or 0):,.0f}")
            c3.metric("Total Spend",   f"${float(total.get('Spend ($)', 0) or 0):,.0f}")
            c4.metric("Meetings",      f"{int(float(total.get('Meetings', 0) or 0)):,}")

        st.divider()
        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("Open Pipeline by Campaign")
            st.bar_chart(camps.set_index("Campaign")[["Pipeline ($)"]])
        with col_right:
            st.subheader("Bookings by Campaign")
            st.bar_chart(camps.set_index("Campaign")[["Bookings ($)"]])

        st.subheader("Full Breakdown")
        st.dataframe(
            camps[["Campaign", "Status", "Meetings", "Leads (proxy)", "Opps",
                   "Pipeline ($)", "Bookings ($)", "Spend ($)", "Pipeline ROAS"]].style.format({
                "Meetings":       "{:,.0f}",
                "Leads (proxy)":  "{:,.0f}",
                "Opps":           "{:,.0f}",
                "Pipeline ($)":   "${:,.0f}",
                "Bookings ($)":   "${:,.0f}",
                "Spend ($)":      "${:,.0f}",
                "Pipeline ROAS":  "{:.1f}x",
            }),
            use_container_width=True,
            hide_index=True,
        )


# ── Channel Performance ────────────────────────────────────────────────────────

with tab_channels:
    df = _load("Channel Metrics")
    if df.empty:
        st.info("No data yet — run the pipeline first.")
    else:
        camps, _ = _split_total(df)
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
        st.bar_chart(camps.set_index("Campaign")[["Impressions", "Clicks", "Engagements"]])


# ── Monthly Trend ─────────────────────────────────────────────────────────────

with tab_monthly:
    df = _load("Monthly Trend")
    if df.empty:
        st.info("No data yet — run the pipeline first.")
    else:
        trend, _ = _split_total(df, key_col="Month")
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

        st.subheader("Impression Trends (LinkedIn vs Google Ads)")
        st.line_chart(trend.set_index("Month")[["LI Impressions", "Ads Impressions"]])

        st.subheader("Monthly Detail")
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
            use_container_width=True, hide_index=True,
        )


# ── Campaign × Month ──────────────────────────────────────────────────────────

with tab_cxm:
    df = _load("Campaign x Month")
    if df.empty:
        st.info("No Campaign × Month data yet — run `python3 main.py` with Google Ads or GA4.")
    else:
        num_cols = ["Spend ($)", "Impressions", "Clicks", "Engagements", "Conversions",
                    "Enrollments", "Emails", "Replies", "Interested", "Meetings", "Sessions"]
        df = _to_num(df, num_cols)

        all_campaigns = sorted([c for c in df["Marketing Campaign"].unique() if c])
        all_platforms = sorted(df["Platform"].unique().tolist())

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            sel_camp = st.multiselect("Campaign", all_campaigns, default=all_campaigns)
        with col_f2:
            sel_plat = st.multiselect("Platform", all_platforms, default=all_platforms)

        filtered = df[
            df["Marketing Campaign"].isin(sel_camp) &
            df["Platform"].isin(sel_plat)
        ]

        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("Spend ($) by Month")
            st.bar_chart(filtered.groupby("Month")["Spend ($)"].sum())
        with col_right:
            st.subheader("Sessions by Month")
            st.bar_chart(filtered.groupby("Month")["Sessions"].sum())

        st.subheader("Data Table")
        display_cols = ["Marketing Campaign", "Month", "Platform", "Spend ($)",
                        "Impressions", "Clicks", "Meetings", "Sessions"]
        st.dataframe(
            filtered[display_cols].style.format({
                "Spend ($)":    "${:,.0f}",
                "Impressions":  "{:,.0f}",
                "Clicks":       "{:,.0f}",
                "Meetings":     "{:,.0f}",
                "Sessions":     "{:,.0f}",
            }),
            use_container_width=True, hide_index=True,
        )
