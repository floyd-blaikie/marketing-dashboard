"""
HubSpot connector.

Pulls nine datasets:
  1. Marketing email campaign performance (bulk sends)
  2. New contact acquisition (by month)
  3. Deal pipeline summary (by stage)
  4. 1:1 outbound email activity per HubSpot user (CRM email engagements)
  5. Sales Sequences performance per sequence
  6. Lifecycle stage progression (companies entering each stage, by week)
  7. Engaged accounts (companies with engagement score >= 30, by week)
  8. Intent spikes (companies with new product intent signals, by week)
  9. Calls logged per rep

Requires a HubSpot Service Key with scopes:
  - crm.objects.contacts.read
  - crm.objects.companies.read
  - crm.objects.deals.read
  - crm.objects.emails.read
  - crm.objects.owners.read
  - automation.sequences.read
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import hubspot
from hubspot.crm.objects import (
    PublicObjectSearchRequest,
    Filter,
    FilterGroup,
    ApiException as ObjectsApiException,
)

from config import HubSpotConfig, DateConfig


_MS = 1000  # HubSpot timestamps are in milliseconds


def _epoch_ms(iso_date: str) -> int:
    dt = datetime.fromisoformat(iso_date).replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * _MS)


def _month_label(epoch_ms: int) -> str:
    dt = datetime.fromtimestamp(epoch_ms / _MS, tz=timezone.utc)
    return dt.strftime("%Y-%m")


def _pct(numerator: int, denominator: int) -> str:
    if not denominator:
        return "0.00%"
    return f"{(numerator / denominator * 100):.2f}%"


def _format_ts(ts: Any) -> str:
    if ts is None:
        return ""
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d")
    try:
        return datetime.fromtimestamp(int(ts) / _MS, tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OSError):
        return str(ts)


def _in_range(date_str: str, start_ms: int, end_ms: int) -> bool:
    if not date_str:
        return False
    try:
        dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        return start_ms <= int(dt.timestamp() * _MS) <= end_ms
    except ValueError:
        return False


def _prop_to_epoch_ms(value: Any) -> int:
    """Convert a HubSpot property value to epoch milliseconds.

    Handles both integer-ms strings ('1234567890000') and ISO strings
    ('2026-01-12T04:06:47.954Z'), which different SDK versions return.
    """
    if not value:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        pass
    try:
        iso = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * _MS)
    except (ValueError, TypeError):
        return 0


class HubSpotConnector:
    def __init__(self):
        cfg = HubSpotConfig.load()
        self._token = cfg.access_token
        self.client = hubspot.Client.create(access_token=self._token)
        dates = DateConfig.load()
        self.start_date = dates.start_date
        self.end_date = dates.end_date
        self.start_ms = _epoch_ms(dates.start_date)
        self.end_ms = _epoch_ms(dates.end_date + "T23:59:59")

    # ------------------------------------------------------------------
    # Lookup helpers (called once and cached per run)
    # ------------------------------------------------------------------

    def _get_owners(self) -> dict[str, str]:
        """Returns {owner_id: 'First Last <email>'} for all HubSpot users."""
        owners: dict[str, str] = {}
        after = None
        while True:
            kwargs: dict[str, Any] = {"limit": 100}
            if after:
                kwargs["after"] = after
            resp = self.client.crm.owners.owners_api.get_page(**kwargs)
            for owner in resp.results or []:
                name = f"{owner.first_name or ''} {owner.last_name or ''}".strip()
                if name and owner.email:
                    label = f"{name} <{owner.email}>"
                elif owner.email:
                    label = owner.email
                else:
                    label = name or str(owner.id)
                owners[str(owner.id)] = label
            paging = getattr(resp, "paging", None)
            if paging and getattr(paging, "next", None):
                after = paging.next.after
            else:
                break
        return owners

    def _get_sequence_names(self) -> dict[str, str]:
        """Returns {sequence_id: sequence_name} by paging the sequences object type."""
        names: dict[str, str] = {}
        after = None
        while True:
            kwargs: dict[str, Any] = {
                "object_type": "sequences",
                "limit": 100,
                "properties": ["hs_name"],
            }
            if after:
                kwargs["after"] = after
            try:
                resp = self.client.crm.objects.basic_api.get_page(**kwargs)
                for obj in resp.results or []:
                    seq_name = (obj.properties or {}).get("hs_name") or f"Sequence {obj.id}"
                    names[str(obj.id)] = seq_name
                paging = getattr(resp, "paging", None)
                if paging and getattr(paging, "next", None):
                    after = paging.next.after
                else:
                    break
            except ObjectsApiException:
                # Sequences API may not be available on all plans — return empty dict
                break
        return names

    # ------------------------------------------------------------------
    # 1. Marketing email campaign performance
    # ------------------------------------------------------------------

    def get_email_campaigns(self) -> list[dict[str, Any]]:
        """One row per bulk marketing email with send/engagement stats."""
        rows = []
        after = None

        while True:
            params: dict[str, Any] = {"limit": 100}
            if after:
                params["after"] = after

            resp = self.client.marketing.emails.emails_api.get_page(**params)
            for email in resp.results or []:
                stats = email.stats or {}
                sent = stats.get("sent", 0) or 0
                delivered = stats.get("delivered", 0) or 0
                opens = stats.get("open", 0) or 0
                clicks = stats.get("click", 0) or 0
                unsubscribes = stats.get("unsubscribed", 0) or 0
                bounces = (stats.get("bounce", 0) or 0) + (stats.get("softbounce", 0) or 0)

                rows.append({
                    "Email Name": email.name or "",
                    "Subject": email.subject or "",
                    "Send Date": _format_ts(email.publish_date),
                    "Sent": sent,
                    "Delivered": delivered,
                    "Opens": opens,
                    "Clicks": clicks,
                    "Unsubscribes": unsubscribes,
                    "Bounces": bounces,
                    "Open Rate": _pct(opens, delivered),
                    "Click Rate": _pct(clicks, delivered),
                    "Unsubscribe Rate": _pct(unsubscribes, delivered),
                })

            paging = getattr(resp, "paging", None)
            if paging and paging.next:
                after = paging.next.after
            else:
                break

        rows = [r for r in rows if _in_range(r["Send Date"], self.start_ms, self.end_ms)]
        rows.sort(key=lambda r: r["Send Date"])
        return rows

    # ------------------------------------------------------------------
    # 2. Contact acquisition
    # ------------------------------------------------------------------

    def get_contact_acquisition(self) -> list[dict[str, Any]]:
        """
        Monthly new-contact counts for the report period.
        Makes one API call per month (reads total only) to avoid the
        HubSpot search API's 10,000-result paging limit.
        """
        from datetime import date
        import calendar

        start = date.fromisoformat(self.start_date)
        end = date.fromisoformat(self.end_date)

        rows = []
        year, month = start.year, start.month

        while date(year, month, 1) <= end:
            last_day = calendar.monthrange(year, month)[1]
            month_start = f"{year}-{month:02d}-01"
            month_end = f"{year}-{month:02d}-{last_day:02d}"

            search_req = PublicObjectSearchRequest(
                filter_groups=[FilterGroup(filters=[
                    Filter(property_name="createdate", operator="GTE", value=month_start),
                    Filter(property_name="createdate", operator="LTE", value=month_end),
                    Filter(property_name="hs_analytics_source", operator="NEQ", value="OFFLINE"),
                ])],
                properties=["createdate"],
                limit=1,
            )
            try:
                resp = self.client.crm.objects.search_api.do_search(
                    object_type="contacts",
                    public_object_search_request=search_req,
                )
                rows.append({"Month": f"{year}-{month:02d}", "New Contacts": resp.total or 0})
            except ObjectsApiException as e:
                raise RuntimeError(f"HubSpot contacts search failed: {e}") from e

            time.sleep(0.1)
            month += 1
            if month > 12:
                month = 1
                year += 1

        return rows

    # ------------------------------------------------------------------
    # 3. Deal pipeline — one row per deal
    # ------------------------------------------------------------------

    def _get_deal_stage_labels(self) -> dict[str, str]:
        """Returns {stage_id: label} for all deal stages across all pipelines."""
        import requests as _requests
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            r = _requests.get(
                "https://api.hubapi.com/crm/v3/pipelines/deals",
                headers=headers,
                timeout=15,
            )
            r.raise_for_status()
            labels: dict[str, str] = {}
            for pipeline in r.json().get("results", []):
                for stage in pipeline.get("stages", []):
                    labels[stage["id"]] = stage.get("label") or stage["id"]
            return labels
        except Exception:
            return {}

    def get_deal_pipeline(self) -> list[dict[str, Any]]:
        """
        One row per deal — the layout campaign_rollup.py expects:
          A: Deal Name  B: Stage  C: Amount ($)  D: Owner  E: Close Date  F: Campaign

        The Campaign column maps to COLS["DEALS"]["campaign"] = "F" in campaign_rollup.py.
        Values come from the 'marketing_campaign' HubSpot deal property, which the team
        added to match names in campaigns.csv. Populates once the Salesforce integration
        is complete; until then it will be blank and pipeline/bookings formulas return 0.

        A deal touched by multiple campaigns stores them as a semicolon-separated string
        (matching HubSpot's multi-value property format). Single-campaign deals match
        exactly, so SUMIFS works correctly for those.
        """
        owners = self._get_owners()
        stage_labels = self._get_deal_stage_labels()

        search_req = PublicObjectSearchRequest(
            filter_groups=[FilterGroup(filters=[
                Filter(property_name="closedate", operator="GTE", value=self.start_date),
            ])],
            properties=["dealname", "dealstage", "amount", "hubspot_owner_id",
                        "closedate", "marketing_campaign"],
            limit=100,
        )

        rows: list[dict[str, Any]] = []
        after = None

        while True:
            if after:
                search_req.after = after
            try:
                resp = self.client.crm.objects.search_api.do_search(
                    object_type="deals",
                    public_object_search_request=search_req,
                )
            except ObjectsApiException as e:
                raise RuntimeError(f"HubSpot deals search failed: {e}") from e

            for deal in resp.results or []:
                props = deal.properties or {}
                stage_id = props.get("dealstage") or ""
                stage_label = stage_labels.get(stage_id, stage_id)
                owner_id = props.get("hubspot_owner_id") or ""
                rows.append({
                    "Deal Name": props.get("dealname") or "",
                    "Stage": stage_label,
                    "Amount ($)": round(float(props.get("amount") or 0), 2),
                    "Owner": owners.get(owner_id, owner_id) if owner_id else "",
                    "Close Date": _format_ts(props.get("closedate")),
                    "Campaign": props.get("marketing_campaign") or "",
                })

            paging = getattr(resp, "paging", None)
            if paging and getattr(paging, "next", None):
                after = paging.next.after
            else:
                break
            time.sleep(0.1)

        rows.sort(key=lambda r: (r["Close Date"] or "", r["Deal Name"]))
        return rows

    # ------------------------------------------------------------------
    # 4. 1:1 outbound email activity per HubSpot user
    # ------------------------------------------------------------------

    def get_email_activity_by_user(self) -> list[dict[str, Any]]:
        """
        Returns one row per HubSpot user with their CRM email engagement count.

        Makes one search call per owner (reads total only) to avoid pagination
        and HAS_PROPERTY filter limitations. Owners with zero emails are omitted.
        """
        owners = self._get_owners()
        rows = []

        for owner_id, owner_name in owners.items():
            search_req = PublicObjectSearchRequest(
                filter_groups=[FilterGroup(filters=[
                    Filter(property_name="hubspot_owner_id", operator="EQ", value=owner_id),
                    Filter(property_name="hs_timestamp", operator="GTE", value=self.start_date),
                    Filter(property_name="hs_timestamp", operator="LTE", value=self.end_date),
                ])],
                properties=["hubspot_owner_id"],
                limit=1,
            )
            try:
                resp = self.client.crm.objects.search_api.do_search(
                    object_type="emails",
                    public_object_search_request=search_req,
                )
                count = resp.total or 0
                if count > 0:
                    rows.append({
                        "User": owner_name,
                        "Emails Logged": count,
                    })
            except ObjectsApiException:
                continue
            time.sleep(0.1)

        rows.sort(key=lambda r: r["Emails Logged"], reverse=True)
        return rows

    # ------------------------------------------------------------------
    # 5. Sales Sequences performance per sequence
    # ------------------------------------------------------------------

    def get_sequence_performance(self) -> list[dict[str, Any]]:
        """
        Returns one row per (sequence, enrolling owner) with enrollment stats.

        Strategy:
        - /automation/v4/sequences requires a userId param; loop all owners to
          build the deduplicated sequence list.
        - Enrollment data lives on contact properties (hs_latest_sequence_enrolled,
          hs_sequences_is_enrolled). Fetch all enrolled contacts in the date range
          (typically a few hundred) and aggregate in Python — far fewer API calls
          than one query per (sequence × owner) combo.

        Requires scopes: automation.sequences.read, crm.objects.contacts.read
        """
        import requests as _requests
        from collections import defaultdict

        owners = self._get_owners()  # owner_id -> display name
        headers = {"Authorization": f"Bearer {self._token}"}
        base = "https://api.hubapi.com"

        # Step 1: fetch all sequences — the endpoint requires userId, so loop owners
        sequences: dict[str, str] = {}  # seq_id -> seq_name
        seen_user_ids: set[str] = set()
        owners_after = None
        while True:
            r = _requests.get(
                f"{base}/crm/v3/owners",
                headers=headers,
                params={"limit": 100, **({"after": owners_after} if owners_after else {})},
            )
            r.raise_for_status()
            owners_page = r.json()
            for o in owners_page.get("results", []):
                uid = str(o.get("userId") or "")
                if not uid or uid in seen_user_ids:
                    continue
                seen_user_ids.add(uid)
                sr = _requests.get(
                    f"{base}/automation/v4/sequences",
                    headers=headers,
                    params={"userId": uid, "limit": 100},
                )
                if sr.status_code == 403:
                    raise RuntimeError(
                        "Sequences require 'automation.sequences.read' scope — "
                        "add it to your Service Key and re-run."
                    )
                if sr.status_code == 200:
                    for seq in sr.json().get("results", []):
                        seq_id = str(seq["id"])
                        if seq_id not in sequences:
                            sequences[seq_id] = seq.get("name") or f"Sequence {seq_id}"
                time.sleep(0.05)
            next_after = (
                owners_page.get("paging", {}).get("next", {}).get("after")
            )
            if not next_after:
                break
            owners_after = next_after

        if not sequences:
            return []

        # Step 2: fetch all contacts enrolled in a sequence during the report period
        all_enrolled: list[dict[str, Any]] = []
        after = None
        while True:
            search_req = PublicObjectSearchRequest(
                filter_groups=[FilterGroup(filters=[
                    Filter(
                        property_name="hs_sequences_enrolled_count",
                        operator="GTE",
                        value="1",
                    ),
                    Filter(
                        property_name="hs_latest_sequence_enrolled_date",
                        operator="GTE",
                        value=self.start_date,
                    ),
                    Filter(
                        property_name="hs_latest_sequence_enrolled_date",
                        operator="LTE",
                        value=self.end_date,
                    ),
                ])],
                properties=[
                    "hubspot_owner_id",
                    "hs_latest_sequence_enrolled",
                    "hs_sequences_is_enrolled",
                ],
                limit=100,
            )
            if after:
                search_req.after = after
            try:
                resp = self.client.crm.objects.search_api.do_search(
                    object_type="contacts",
                    public_object_search_request=search_req,
                )
            except ObjectsApiException as e:
                raise RuntimeError(f"HubSpot sequence contacts search failed: {e}") from e

            for contact in resp.results or []:
                props = contact.properties or {}
                seq_id = str(props.get("hs_latest_sequence_enrolled") or "")
                owner_id = str(props.get("hubspot_owner_id") or "")
                is_active = (props.get("hs_sequences_is_enrolled") or "").lower() == "true"
                if seq_id and owner_id:
                    all_enrolled.append({
                        "seq_id": seq_id,
                        "owner_id": owner_id,
                        "active": is_active,
                    })

            paging = getattr(resp, "paging", None)
            if paging and getattr(paging, "next", None):
                after = paging.next.after
            else:
                break
            time.sleep(0.1)

        # Step 3: aggregate in Python
        stats: dict[tuple[str, str], dict[str, Any]] = defaultdict(
            lambda: {"enrolled": 0, "active": 0, "completed": 0}
        )
        for item in all_enrolled:
            key = (item["seq_id"], item["owner_id"])
            stats[key]["enrolled"] += 1
            if item["active"]:
                stats[key]["active"] += 1
            else:
                stats[key]["completed"] += 1

        rows = []
        for (seq_id, owner_id), s in sorted(
            stats.items(),
            key=lambda kv: kv[1]["enrolled"],
            reverse=True,
        ):
            rows.append({
                "Sequence Name": sequences.get(seq_id, f"Sequence {seq_id}"),
                "Enrolled By": owners.get(owner_id, owner_id),
                "Total Enrolled": s["enrolled"],
                "Active": s["active"],
                "Completed": s["completed"],
            })
        return rows

    # ------------------------------------------------------------------
    # 6. Lifecycle stage progression (weekly)
    # ------------------------------------------------------------------

    def get_lifecycle_stage_progression_weekly(self) -> list[dict[str, Any]]:
        """
        Weekly count of companies that entered each lifecycle stage.

        Uses hs_date_entered_{stage} date-stamp properties on companies — one
        count query per (week × stage). Stages tracked: Lead → MQL → SQL → Opportunity.
        """
        from datetime import date, timedelta

        STAGES = {
            "Lead": "hs_date_entered_lead",
            "MQL": "hs_date_entered_marketingqualifiedlead",
            "SQL": "hs_date_entered_salesqualifiedlead",
            "Opportunity": "hs_date_entered_opportunity",
        }

        start = date.fromisoformat(self.start_date)
        end = date.fromisoformat(self.end_date)
        # Align to the Monday of the first partial/full week
        week_start = start - timedelta(days=start.weekday())

        rows = []
        while week_start <= end:
            week_end = week_start + timedelta(days=6)
            ws = week_start.isoformat()
            we = min(week_end, end).isoformat()

            row: dict[str, Any] = {"Week": ws}
            for stage_label, prop in STAGES.items():
                search_req = PublicObjectSearchRequest(
                    filter_groups=[FilterGroup(filters=[
                        Filter(property_name=prop, operator="GTE", value=ws),
                        Filter(property_name=prop, operator="LTE", value=we),
                    ])],
                    properties=[prop],
                    limit=1,
                )
                try:
                    resp = self.client.crm.objects.search_api.do_search(
                        object_type="companies",
                        public_object_search_request=search_req,
                    )
                    row[stage_label] = resp.total or 0
                except ObjectsApiException:
                    row[stage_label] = 0
                time.sleep(0.05)

            rows.append(row)
            week_start += timedelta(weeks=1)

        return rows

    # ------------------------------------------------------------------
    # 7. Engaged accounts (weekly)
    # ------------------------------------------------------------------

    def get_engaged_accounts_weekly(self) -> list[dict[str, Any]]:
        """
        Weekly count of companies whose account_engagement_score was updated
        to >= 30 within each week.

        account_engagement_score is a calculated field that HubSpot refreshes
        periodically; account_engagement_score_last_updated is the timestamp of
        the most recent calculation.
        """
        from datetime import date, timedelta

        start = date.fromisoformat(self.start_date)
        end = date.fromisoformat(self.end_date)
        week_start = start - timedelta(days=start.weekday())

        rows = []
        while week_start <= end:
            week_end = week_start + timedelta(days=6)
            ws = week_start.isoformat()
            we = min(week_end, end).isoformat()

            search_req = PublicObjectSearchRequest(
                filter_groups=[FilterGroup(filters=[
                    Filter(
                        property_name="account_engagement_score",
                        operator="GTE",
                        value="30",
                    ),
                    Filter(
                        property_name="account_engagement_score_last_updated",
                        operator="GTE",
                        value=ws,
                    ),
                    Filter(
                        property_name="account_engagement_score_last_updated",
                        operator="LTE",
                        value=we,
                    ),
                ])],
                properties=["account_engagement_score"],
                limit=1,
            )
            try:
                resp = self.client.crm.objects.search_api.do_search(
                    object_type="companies",
                    public_object_search_request=search_req,
                )
                count = resp.total or 0
            except ObjectsApiException:
                count = 0

            rows.append({"Week": ws, "Engaged Accounts (Score ≥ 30)": count})
            time.sleep(0.05)
            week_start += timedelta(weeks=1)

        return rows

    # ------------------------------------------------------------------
    # 8. Intent spikes (weekly)
    # ------------------------------------------------------------------

    _INTENT_PROPS: list[tuple[str, str]] = [
        ("retail_integrations_intent", "Retail Integrations"),
        ("ais_intent", "AIS"),
        ("ascend_intent", "Ascend"),
        ("imd_integrations_intent", "IMD Integrations"),
        ("imd_product_catalog_intent", "IMD Product Catalog"),
    ]

    def get_intent_spikes_weekly(self) -> list[dict[str, Any]]:
        """
        Weekly count of companies that had a NEW intent signal (property set to
        'true') for each product line.

        Strategy:
        - Search for companies that currently have any intent flag = true (OR).
        - Batch-read their property history to find when each flag was set to
          'true', then group by ISO week.
        - Only counts entries whose timestamp falls within the report date range.

        Requires scope: crm.objects.companies.read
        """
        import requests as _requests
        from datetime import date, timedelta
        from collections import defaultdict

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        base = "https://api.hubapi.com"
        intent_prop_names = [p for p, _ in self._INTENT_PROPS]

        # Step 1: collect IDs of companies with any intent = true (OR across props)
        company_ids: list[str] = []
        after = None
        while True:
            search_req = PublicObjectSearchRequest(
                filter_groups=[
                    FilterGroup(filters=[
                        Filter(property_name=prop, operator="EQ", value="true")
                    ])
                    for prop in intent_prop_names
                ],
                properties=["name"],
                limit=100,
            )
            if after:
                search_req.after = after
            try:
                resp = self.client.crm.objects.search_api.do_search(
                    object_type="companies",
                    public_object_search_request=search_req,
                )
            except ObjectsApiException as e:
                raise RuntimeError(f"Intent spike search failed: {e}") from e

            for c in resp.results or []:
                company_ids.append(c.id)

            paging = getattr(resp, "paging", None)
            if paging and getattr(paging, "next", None):
                after = paging.next.after
            else:
                break
            time.sleep(0.1)

        if not company_ids:
            return []

        # Deduplicate (OR search may return the same company via multiple matches)
        company_ids = list(dict.fromkeys(company_ids))

        start_d = date.fromisoformat(self.start_date)
        end_d = date.fromisoformat(self.end_date)

        # Step 2: batch-read property history in chunks of 100
        spike_counts: dict[tuple[str, str], int] = defaultdict(int)

        for i in range(0, len(company_ids), 50):
            batch = company_ids[i : i + 50]
            r = _requests.post(
                f"{base}/crm/v3/objects/companies/batch/read",
                headers=headers,
                json={
                    "inputs": [{"id": cid} for cid in batch],
                    "properties": [],
                    "propertiesWithHistory": intent_prop_names,
                },
            )
            r.raise_for_status()
            for company in r.json().get("results", []):
                hist = company.get("propertiesWithHistory", {})
                for prop_name, prop_label in self._INTENT_PROPS:
                    for entry in hist.get(prop_name, []):
                        if entry.get("value") != "true":
                            continue
                        ts = entry.get("timestamp", "")
                        if not ts:
                            continue
                        try:
                            dt = datetime.fromisoformat(
                                ts.replace("Z", "+00:00")
                            ).date()
                        except ValueError:
                            continue
                        if not (start_d <= dt <= end_d):
                            continue
                        # Key by week-start (Monday) + product label
                        week_mon = dt - timedelta(days=dt.weekday())
                        spike_counts[(week_mon.isoformat(), prop_label)] += 1
            time.sleep(0.1)

        if not spike_counts:
            return []

        # Step 3: pivot into one row per week
        all_weeks = sorted({w for w, _ in spike_counts})
        prop_labels = [label for _, label in self._INTENT_PROPS]

        rows = []
        for week in all_weeks:
            row: dict[str, Any] = {"Week": week}
            for label in prop_labels:
                row[label] = spike_counts.get((week, label), 0)
            rows.append(row)
        return rows

    # ------------------------------------------------------------------
    # 9. Calls logged per rep
    # ------------------------------------------------------------------

    def get_calls_by_rep(self) -> list[dict[str, Any]]:
        """
        Total completed calls per HubSpot user in the report date range.
        One count query per owner; reps with zero calls are omitted.
        """
        owners = self._get_owners()
        rows = []

        for owner_id, owner_name in owners.items():
            search_req = PublicObjectSearchRequest(
                filter_groups=[FilterGroup(filters=[
                    Filter(
                        property_name="hubspot_owner_id",
                        operator="EQ",
                        value=owner_id,
                    ),
                    Filter(
                        property_name="hs_timestamp",
                        operator="GTE",
                        value=self.start_date,
                    ),
                    Filter(
                        property_name="hs_timestamp",
                        operator="LTE",
                        value=self.end_date,
                    ),
                    Filter(
                        property_name="hs_call_status",
                        operator="EQ",
                        value="COMPLETED",
                    ),
                ])],
                properties=["hubspot_owner_id"],
                limit=1,
            )
            try:
                resp = self.client.crm.objects.search_api.do_search(
                    object_type="calls",
                    public_object_search_request=search_req,
                )
                count = resp.total or 0
                if count > 0:
                    rows.append({"Rep": owner_name, "Calls Logged": count})
            except ObjectsApiException:
                continue
            time.sleep(0.1)

        rows.sort(key=lambda r: r["Calls Logged"], reverse=True)
        return rows

    # ------------------------------------------------------------------
    # 10. LinkedIn ad engagement by company (Fibbler)
    # ------------------------------------------------------------------

    _FIBBLER_ACCT = "508009199"
    _ENGAGEMENT_RANK = {"VERY_HIGH": 5, "HIGH": 4, "MEDIUM": 3, "LOW": 2, "VERY_LOW": 1}

    def get_linkedin_engagement_by_company(self) -> list[dict[str, Any]]:
        """
        Companies showing LinkedIn ad engagement via Fibbler, filtered to
        LOW engagement level or above (excludes the VERY_LOW noise tier).

        Data is a rolling snapshot (7-day and 30-day windows), not historical.
        Sorted by engagement level (VERY_HIGH → LOW) then by 30-day impressions.

        Requires scope: crm.objects.companies.read
        """
        acct = self._FIBBLER_ACCT
        props = [
            "name", "domain", "lifecyclestage", "hubspot_owner_id",
            f"fibbler_linkedin_engagement_level_{acct}_7_days",
            f"fibbler_linkedin_engagement_level_{acct}_30_days",
            f"fibbler_linkedin_ad_impressions_{acct}_7_days",
            f"fibbler_linkedin_ad_impressions_{acct}_30_days",
            f"fibbler_linkedin_ad_clicks_{acct}_7_days",
            f"fibbler_linkedin_ad_clicks_{acct}_30_days",
            f"fibbler_linkedin_ad_engagements_{acct}_7_days",
            f"fibbler_linkedin_ad_engagements_{acct}_30_days",
            f"fibbler_linkedin_organic_impressions_{acct}_30_days",
            f"fibbler_linkedin_organic_engagements_{acct}_30_days",
        ]

        # OR across all meaningful engagement levels (excludes VERY_LOW)
        search_req = PublicObjectSearchRequest(
            filter_groups=[
                FilterGroup(filters=[Filter(
                    property_name=f"fibbler_linkedin_engagement_level_{acct}_30_days",
                    operator="EQ",
                    value=level,
                )])
                for level in ("VERY_HIGH", "HIGH", "MEDIUM", "LOW")
            ],
            properties=props,
            limit=100,
        )

        owners = self._get_owners()
        all_companies: list[dict[str, Any]] = []
        after = None

        while True:
            if after:
                search_req.after = after
            try:
                resp = self.client.crm.objects.search_api.do_search(
                    object_type="companies",
                    public_object_search_request=search_req,
                )
            except ObjectsApiException as e:
                raise RuntimeError(f"Fibbler company search failed: {e}") from e

            for c in resp.results or []:
                p = c.properties or {}
                level_30 = p.get(f"fibbler_linkedin_engagement_level_{acct}_30_days") or "VERY_LOW"
                level_7  = p.get(f"fibbler_linkedin_engagement_level_{acct}_7_days") or ""
                owner_id = p.get("hubspot_owner_id") or ""
                all_companies.append({
                    "Company": p.get("name") or "",
                    "Domain": p.get("domain") or "",
                    "Lifecycle Stage": (p.get("lifecyclestage") or "").replace("marketingqualifiedlead", "MQL").replace("salesqualifiedlead", "SQL"),
                    "Owner": owners.get(owner_id, owner_id) if owner_id else "",
                    "Engagement Level (30d)": level_30.replace("_", " ").title(),
                    "Engagement Level (7d)": level_7.replace("_", " ").title(),
                    "Ad Impressions (7d)": int(p.get(f"fibbler_linkedin_ad_impressions_{acct}_7_days") or 0),
                    "Ad Impressions (30d)": int(p.get(f"fibbler_linkedin_ad_impressions_{acct}_30_days") or 0),
                    "Ad Clicks (7d)": int(p.get(f"fibbler_linkedin_ad_clicks_{acct}_7_days") or 0),
                    "Ad Clicks (30d)": int(p.get(f"fibbler_linkedin_ad_clicks_{acct}_30_days") or 0),
                    "Ad Engagements (30d)": int(p.get(f"fibbler_linkedin_ad_engagements_{acct}_30_days") or 0),
                    "Organic Impressions (30d)": int(p.get(f"fibbler_linkedin_organic_impressions_{acct}_30_days") or 0),
                    "Organic Engagements (30d)": int(p.get(f"fibbler_linkedin_organic_engagements_{acct}_30_days") or 0),
                    "_rank": self._ENGAGEMENT_RANK.get(level_30, 0),
                })

            paging = getattr(resp, "paging", None)
            if paging and getattr(paging, "next", None):
                after = paging.next.after
            else:
                break
            time.sleep(0.1)

        all_companies.sort(
            key=lambda r: (r["_rank"], r["Ad Impressions (30d)"]),
            reverse=True,
        )
        for r in all_companies:
            del r["_rank"]
        return all_companies
