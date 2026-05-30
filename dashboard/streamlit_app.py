"""Voltus Residential VPP — Partnerships Team Dashboard."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED = PROJECT_ROOT / "data" / "processed"

ISO_TO_UTILITIES = {
    "PJM": ["ComEd", "PPL", "PECO"],
    "MISO": ["AmerenIL"],
    "NYISO": ["PSEG-LI"],
}

UTILITY_TO_ISO = {
    "ComEd": "PJM",
    "PPL": "PJM",
    "PECO": "PJM",
    "AmerenIL": "MISO",
    "PSEG-LI": "NYISO",
}

ALL_ISOS = ["PJM", "MISO", "NYISO"]
ALL_UTILITIES = ["ComEd", "PPL", "PECO", "AmerenIL", "PSEG-LI"]
ALL_PARTNERS = ["Resideo", "Google Nest", "ecobee", "Octopus Energy"]

# TEST 1: Select NYISO only
# Expected: Utility zone shows PSEG-LI only
# Expected: Selecting PSEG-LI filters all 5 tabs to NY data only
#
# TEST 2: Select PJM + MISO
# Expected: Utility zone shows ComEd, PPL, PECO, AmerenIL
# Expected: PSEG-LI does not appear anywhere
#
# TEST 3: Change from ALL to NYISO after selecting AmerenIL
# Expected: AmerenIL disappears from selected automatically
# Expected: No error thrown, no crash, silent clean removal

st.set_page_config(
    page_title="Voltus Residential VPP Dashboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data
def load_all_data() -> dict[str, pd.DataFrame]:
    files = {
        "enrollment": "enrollment_clean.parquet",
        "customers": "db_customers_clean.parquet",
        "enrollments": "db_enrollments_clean.parquet",
        "partners": "db_partners_clean.parquet",
        "programs": "db_programs_clean.parquet",
        "dr_events": "db_dr_events_clean.parquet",
        "devices": "devices_clean.parquet",
        "intervals": "interval_clean.parquet",
        "cbl": "cbl_performance.parquet",
        "eia": "eia_demand_clean.parquet",
        "master": "vpp_master.parquet",
    }
    data: dict[str, pd.DataFrame] = {}
    for key, filename in files.items():
        path = PROCESSED / filename
        if path.exists():
            data[key] = pd.read_parquet(path)
    return data


def parse_dates(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in cols:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")
    return out


def allowed_utilities_for_isos(selected_isos: list[str]) -> list[str]:
    if not selected_isos:
        return ALL_UTILITIES.copy()
    allowed: list[str] = []
    for iso in selected_isos:
        allowed.extend(ISO_TO_UTILITIES[iso])
    return allowed


def init_filter_session_state() -> None:
    if "filter_iso" not in st.session_state:
        st.session_state.filter_iso = ALL_ISOS.copy()
    if "filter_utility" not in st.session_state:
        st.session_state.filter_utility = ALL_UTILITIES.copy()
    if "filter_partner" not in st.session_state:
        st.session_state.filter_partner = ALL_PARTNERS.copy()


def render_sidebar_filters(enrollment: pd.DataFrame) -> tuple[list[str], list[str], list[str], tuple | None, str]:
    st.sidebar.header("Filters")
    init_filter_session_state()

    selected_isos = st.sidebar.multiselect(
        "ISO market",
        options=ALL_ISOS,
        key="filter_iso",
    )

    allowed_utilities = allowed_utilities_for_isos(selected_isos)
    st.session_state.filter_utility = [
        utility for utility in st.session_state.filter_utility if utility in allowed_utilities
    ]

    selected_utilities = st.sidebar.multiselect(
        "Utility zone",
        options=allowed_utilities,
        key="filter_utility",
    )
    st.sidebar.caption("Showing utility zones for selected ISO markets only.")

    selected_partners = st.sidebar.multiselect(
        "Partner",
        options=ALL_PARTNERS,
        key="filter_partner",
    )

    min_date = enrollment["enrollment_date"].min()
    max_date = enrollment["enrollment_date"].max()
    if pd.notna(min_date) and pd.notna(max_date):
        date_range = st.sidebar.date_input(
            "Enrollment date range",
            value=(min_date.date(), max_date.date()),
            min_value=min_date.date(),
            max_value=max_date.date(),
        )
    else:
        date_range = None

    iso_label = ", ".join(selected_isos) if selected_isos else "All ISOs"
    utility_label = ", ".join(selected_utilities) if selected_utilities else "All utilities"
    partner_label = ", ".join(selected_partners) if selected_partners else "All partners"
    if date_range and len(date_range) == 2:
        date_label = f"{date_range[0]} to {date_range[1]}"
    else:
        date_label = "All dates"

    filter_summary = (
        f"Showing data for: {iso_label} | {utility_label} | {partner_label} | {date_label}"
    )
    return selected_isos, selected_utilities, selected_partners, date_range, filter_summary


def apply_data_filters(
    enrollment: pd.DataFrame,
    master: pd.DataFrame,
    cbl: pd.DataFrame,
    intervals: pd.DataFrame,
    dr_events: pd.DataFrame,
    eia: pd.DataFrame,
    devices: pd.DataFrame,
    selected_isos: list[str],
    selected_utilities: list[str],
    selected_partners: list[str],
    date_range: tuple | None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    enr = enrollment.copy()
    mas = master.copy()

    if selected_isos:
        enr = enr[enr["iso_market"].isin(selected_isos)]
        mas = mas[mas["iso_market"].isin(selected_isos)]
    if selected_utilities:
        enr = enr[enr["utility_zone"].isin(selected_utilities)]
        mas = mas[mas["utility_zone"].isin(selected_utilities)]
    if selected_partners:
        enr = enr[enr["partner_name"].isin(selected_partners)]
        mas = mas[mas["partner_name"].isin(selected_partners)]

    if date_range and len(date_range) == 2:
        start, end = date_range
        enr = enr[
            (enr["enrollment_date"].dt.date >= start) & (enr["enrollment_date"].dt.date <= end)
        ]
        mas = mas[
            (mas["enrolled_date"].isna())
            | (
                (mas["enrolled_date"].dt.date >= start)
                & (mas["enrolled_date"].dt.date <= end)
            )
        ]

    valid_accounts = set(enr["utility_account_id"].dropna().astype(str))
    valid_devices = set(enr["device_serial"].dropna().astype(str))

    cbl_filtered = cbl[cbl["utility_account_id"].astype(str).isin(valid_accounts)].copy()
    intervals_filtered = intervals[
        intervals["utility_account_id"].astype(str).isin(valid_accounts)
    ].copy()

    if selected_isos:
        dr_filtered = dr_events[dr_events["iso_market"].isin(selected_isos)].copy()
        eia_filtered = eia[eia["iso_market"].isin(selected_isos)].copy()
    else:
        dr_filtered = dr_events.copy()
        eia_filtered = eia.copy()

    event_ids = set(cbl_filtered["event_id"].dropna())
    if event_ids:
        dr_filtered = dr_filtered[dr_filtered["event_id"].isin(event_ids)]
        cbl_filtered = cbl_filtered[cbl_filtered["event_id"].isin(dr_filtered["event_id"])]

    devices_filtered = devices[devices["device_id"].astype(str).isin(valid_devices)].copy()

    return enr, mas, cbl_filtered, intervals_filtered, dr_filtered, eia_filtered, devices_filtered


def apply_sidebar_filters(
    enrollment: pd.DataFrame,
    master: pd.DataFrame,
    cbl: pd.DataFrame,
    intervals: pd.DataFrame,
    dr_events: pd.DataFrame,
    eia: pd.DataFrame,
    devices: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    str,
]:
    selected_isos, selected_utilities, selected_partners, date_range, filter_summary = (
        render_sidebar_filters(enrollment)
    )
    filtered = apply_data_filters(
        enrollment,
        master,
        cbl,
        intervals,
        dr_events,
        eia,
        devices,
        selected_isos,
        selected_utilities,
        selected_partners,
        date_range,
    )
    return (*filtered, filter_summary)


def compute_funnel(enrollment: pd.DataFrame, cbl: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    participated_accounts = set(cbl.loc[cbl["responded_flag"], "utility_account_id"].astype(str))

    stages = {
        "lead_captured": len(enrollment),
        "utility_data_authorized": int(
            (
                enrollment["utility_account_id"].notna()
                & (enrollment["utility_account_id"].astype(str).str.strip() != "")
            ).sum()
        )
        if len(enrollment)
        else 0,
        "market_registered": int(enrollment["enrollment_status"].notna().sum()),
        "active_enrolled": int((enrollment["enrollment_status"] == "active").sum()),
        "event_participated": int(
            enrollment["utility_account_id"].astype(str).isin(participated_accounts).sum()
        ),
        "retained_12mo": int(
            (
                (enrollment["enrollment_status"] == "active")
                & (enrollment["enrollment_date"] <= as_of - pd.DateOffset(months=12))
            ).sum()
        ),
    }

    rows = []
    prev = None
    for stage, count in stages.items():
        conv = None if prev in (None, 0) else round(100 * count / prev, 1)
        rows.append({"stage": stage, "customers": count, "conversion_pct": conv})
        prev = count
    return pd.DataFrame(rows)


def device_summary(
    devices: pd.DataFrame,
    enrollment: pd.DataFrame,
    partners: pd.DataFrame,
    as_of: pd.Timestamp,
) -> pd.DataFrame:
    device_meta = (
        devices.sort_values("runtime_date")
        .groupby("device_id", as_index=False)
        .agg(
            last_seen=("last_seen_timestamp", "max"),
            runtime_30day_avg=("runtime_minutes", "mean"),
            connectivity_status=("connectivity_status", "last"),
        )
    )
    cutoff = as_of - pd.Timedelta(days=7)
    device_meta["online_last_7d"] = device_meta["last_seen"] >= cutoff

    enr = enrollment.drop_duplicates("device_serial").merge(
        partners[["partner_id", "partner_name", "revenue_share_pct"]],
        left_on="partner_name",
        right_on="partner_name",
        how="left",
    )
    merged = enr.merge(device_meta, left_on="device_serial", right_on="device_id", how="left")
    merged["device_age_days"] = (as_of - merged["enrollment_date"]).dt.days
    return merged


def reference_date(enrollment: pd.DataFrame) -> pd.Timestamp:
    """Use latest enrollment date so historical demo data still renders."""
    max_date = enrollment["enrollment_date"].max()
    return max_date if pd.notna(max_date) else pd.Timestamp.now()


def weekly_enrollment(enrollment: pd.DataFrame, as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    df = enrollment.dropna(subset=["enrollment_date"]).copy()
    if df.empty:
        return pd.DataFrame(columns=["week", "partner_name", "devices_enrolled"])

    df["week"] = df["enrollment_date"].dt.to_period("W").dt.start_time
    anchor = as_of or reference_date(enrollment)
    cutoff = anchor - pd.DateOffset(months=6)
    df = df[df["week"] >= cutoff]
    if df.empty:
        return pd.DataFrame(columns=["week", "partner_name", "devices_enrolled"])

    return (
        df.groupby(["week", "partner_name"], as_index=False)
        .size()
        .rename(columns={"size": "devices_enrolled"})
    )


def interval_quality(intervals: pd.DataFrame, enrollment: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    acct_zone = enrollment[["utility_account_id", "utility_zone", "iso_market"]].drop_duplicates(
        "utility_account_id"
    )
    iv = intervals.merge(acct_zone, on="utility_account_id", how="left")

    event_flags = (
        iv.groupby("event_id", as_index=False)
        .agg(
            total_rows=("usage_kwh", "count"),
            actual=("data_quality_flag", lambda s: (s == "A").sum()),
            estimated=("data_quality_flag", lambda s: (s == "E").sum()),
        )
    )
    missing = (
        iv.drop_duplicates(["event_id", "utility_account_id", "meter_id"])
        .groupby("event_id", as_index=False)
        .agg(
            expected=("intervals_expected", "sum"),
            actual_intervals=("intervals_actual", "sum"),
        )
    )
    event_flags = event_flags.merge(missing, on="event_id", how="left")
    event_flags["missing"] = event_flags["expected"] - event_flags["actual_intervals"]
    total = event_flags["total_rows"].replace(0, pd.NA)
    event_flags["pct_actual"] = 100 * event_flags["actual"] / total
    event_flags["pct_estimated"] = 100 * event_flags["estimated"] / total
    event_flags["pct_missing"] = 100 * event_flags["missing"] / event_flags["expected"].replace(0, pd.NA)
    event_flags["needs_followup"] = event_flags["pct_missing"] > 5

    zone_quality = (
        iv.groupby(["utility_zone", "iso_market"], as_index=False)
        .agg(
            total=("usage_kwh", "count"),
            actual_reads=("data_quality_flag", lambda s: int((s == "A").sum())),
            estimated_reads=("data_quality_flag", lambda s: int((s == "E").sum())),
        )
    )
    zone_quality["pct_estimated"] = (
        100 * zone_quality["estimated_reads"] / zone_quality["total"].replace(0, pd.NA)
    )
    zone_quality["quality_score"] = 100 - zone_quality["pct_estimated"]
    return event_flags, zone_quality.sort_values("quality_score")


def performance_color(pct: float) -> str:
    if pd.isna(pct):
        return "#888888"
    if pct >= 85:
        return "#2ecc71"
    if pct >= 70:
        return "#f1c40f"
    return "#e74c3c"


def tab_enrollment_funnel(
    enrollment: pd.DataFrame, cbl: pd.DataFrame, as_of: pd.Timestamp
) -> None:
    st.subheader("How many residential customers are enrolled and active?")

    funnel = compute_funnel(enrollment, cbl, as_of)
    month_start = as_of.replace(day=1)
    week_start = as_of - pd.Timedelta(days=as_of.weekday())

    total_enrolled = len(enrollment)
    active_today = int((enrollment["enrollment_status"] == "active").sum())
    churned_month = 0
    if "opt_out_date" in enrollment.columns:
        opt_out = pd.to_datetime(enrollment["opt_out_date"], errors="coerce")
        churned_month = int((opt_out.notna() & (opt_out >= month_start)).sum())
    new_week = int((enrollment["enrollment_date"] >= week_start).sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Enrolled", f"{total_enrolled:,}")
    c2.metric("Active Today", f"{active_today:,}")
    c3.metric("Churned This Month", f"{churned_month:,}")
    c4.metric("New This Week", f"{new_week:,}")

    fig = go.Figure(
        go.Funnel(
            y=funnel["stage"],
            x=funnel["customers"],
            textinfo="value+percent initial",
        )
    )
    fig.update_layout(margin=dict(l=20, r=20, t=30, b=20), height=420)
    st.plotly_chart(fig, use_container_width=True)

    conv = funnel.loc[funnel["conversion_pct"].notna(), ["stage", "conversion_pct"]]
    if not conv.empty:
        lead_to_auth = funnel.loc[funnel["stage"] == "utility_data_authorized", "conversion_pct"]
        auth_pct = lead_to_auth.iloc[0] if len(lead_to_auth) else 0
        drop_stage = conv.loc[conv["conversion_pct"].idxmin(), "stage"] if len(conv) else "utility data authorization"
        st.info(
            f"**Insight:** About **{auth_pct:.0f}%** of captured leads successfully authorized utility data. "
            f"The largest relative drop-off occurs at the **{drop_stage.replace('_', ' ')}** step."
        )

    breakdown = (
        enrollment.groupby(["partner_name", "iso_market"], as_index=False)
        .agg(
            devices=("device_serial", "count"),
            active=("enrollment_status", lambda s: (s == "active").sum()),
        )
        .sort_values(["partner_name", "iso_market"])
    )
    st.markdown("**Breakdown by partner and ISO market**")
    st.dataframe(breakdown, use_container_width=True, hide_index=True)


def tab_partner_devices(
    enrollment: pd.DataFrame,
    devices: pd.DataFrame,
    partners: pd.DataFrame,
    as_of: pd.Timestamp,
) -> None:
    st.subheader("Which partners have the most devices enrolled and which are growing fastest?")

    weekly = weekly_enrollment(enrollment, as_of=as_of)
    summary = device_summary(devices, enrollment, partners, as_of=as_of)

    fig_bar = px.bar(
        enrollment.groupby(["partner_name", "utility_zone"], as_index=False)
        .size()
        .rename(columns={"size": "devices"}),
        x="utility_zone",
        y="devices",
        color="partner_name",
        barmode="group",
        title="Enrolled devices by partner and utility zone",
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    fig_line = px.line(
        weekly,
        x="week",
        y="devices_enrolled",
        color="partner_name",
        markers=True,
        title="Weekly enrollment growth by partner (last 6 months)",
    )
    st.plotly_chart(fig_line, use_container_width=True)

    partner_table = (
        summary.groupby("partner_name", as_index=False)
        .agg(
            total_devices=("device_serial", "count"),
            avg_device_age_days=("device_age_days", "mean"),
            pct_online_7d=("online_last_7d", "mean"),
            revenue_share_pct=("revenue_share_pct", "first"),
        )
    )
    partner_table["avg_device_age_days"] = partner_table["avg_device_age_days"].round(0)
    partner_table["pct_online_7d"] = (100 * partner_table["pct_online_7d"]).round(1)

    wow = weekly.copy()
    wow["prev"] = wow.groupby("partner_name")["devices_enrolled"].shift(1)
    wow["wow_change"] = wow["devices_enrolled"] - wow["prev"]
    declining = wow.groupby("partner_name")["wow_change"].last()
    declining_partners = declining[declining < 0].index.tolist()
    partner_table["trend"] = partner_table["partner_name"].apply(
        lambda p: "⚠ Declining WoW" if p in declining_partners else "Stable / Growing"
    )

    st.markdown("**Partner device summary**")
    st.dataframe(partner_table, use_container_width=True, hide_index=True)
    if declining_partners:
        st.warning(f"Declining week-over-week enrollment: **{', '.join(declining_partners)}**")


def tab_event_performance(dr_events: pd.DataFrame, cbl: pd.DataFrame, eia: pd.DataFrame) -> None:
    st.subheader("When Voltus dispatched a demand response event, how much load was actually reduced?")

    event_stats = (
        cbl.groupby("event_id", as_index=False)
        .agg(
            participation_rate_pct=("participation_rate_pct", "first"),
            avg_performance_pct=("avg_performance_pct", "first"),
            total_mw_delivered=("total_mw_delivered", "first"),
        )
    )
    events = dr_events.merge(event_stats, on="event_id", how="left")
    events["performance_pct"] = (100 * events["mw_delivered"] / events["mw_called"]).round(1)
    events["event_date"] = pd.to_datetime(events["event_date"])

    eia["period"] = pd.to_datetime(eia["period"])
    summer_peak = eia.groupby("iso_market")["demand_mwh"].quantile(0.90).rename("peak_threshold")
    eia_peak = eia.merge(summer_peak, on="iso_market")
    eia_peak["is_peak"] = eia_peak["demand_mwh"] >= eia_peak["peak_threshold"]
    dispatch_eia = eia_peak.merge(
        events[["event_id", "event_date", "iso_market"]],
        left_on=["period", "iso_market"],
        right_on=["event_date", "iso_market"],
        how="right",
    )

    display = events[
        [
            "event_id",
            "event_date",
            "mw_called",
            "mw_delivered",
            "performance_pct",
            "participation_rate_pct",
        ]
    ].copy()
    display["performance_status"] = display["performance_pct"].apply(
        lambda p: "Green (>=85%)"
        if pd.notna(p) and p >= 85
        else "Yellow (70-85%)"
        if pd.notna(p) and p >= 70
        else "Red (<70%)"
    )
    display["event_date"] = display["event_date"].dt.date
    st.dataframe(display, use_container_width=True, hide_index=True)

    melted = events.melt(
        id_vars=["event_id", "event_date"],
        value_vars=["mw_called", "mw_delivered"],
        var_name="metric",
        value_name="mw",
    )
    fig = px.bar(
        melted,
        x="event_date",
        y="mw",
        color="metric",
        barmode="group",
        title="MW called vs MW delivered by event",
        color_discrete_map={"mw_called": "#3498db", "mw_delivered": "#2ecc71"},
    )
    st.plotly_chart(fig, use_container_width=True)

    perf_fig = go.Figure(
        go.Bar(
            x=events["event_date"],
            y=events["performance_pct"],
            marker_color=[performance_color(p) for p in events["performance_pct"]],
            name="Performance %",
        )
    )
    perf_fig.update_layout(
        title="Event performance % (green >=85, yellow 70-85, red <70)",
        yaxis_title="Performance %",
        height=360,
    )
    st.plotly_chart(perf_fig, use_container_width=True)

    peak_note = dispatch_eia.groupby("event_id")["is_peak"].max().reset_index()
    events_peak = events.merge(peak_note, on="event_id", how="left")
    peak_count = int(events_peak["is_peak"].fillna(False).sum())
    st.markdown(
        f"**Grid context:** {peak_count} of {len(events)} events occurred on days at or above the "
        f"summer 90th-percentile demand threshold for their ISO market."
    )


def tab_data_quality(intervals: pd.DataFrame, enrollment: pd.DataFrame) -> None:
    st.subheader("How reliable is the meter data we use to prove load reductions?")

    event_flags, zone_quality = interval_quality(intervals, enrollment)

    st.dataframe(
        event_flags[
            [
                "event_id",
                "pct_actual",
                "pct_estimated",
                "pct_missing",
                "needs_followup",
            ]
        ].round(1),
        use_container_width=True,
        hide_index=True,
    )

    flagged = event_flags[event_flags["needs_followup"]]
    for _, row in flagged.iterrows():
        st.error(
            f"Event **{int(row['event_id'])}** missing read rate **{row['pct_missing']:.1f}%** — "
            "manual follow-up required."
        )

    fig = px.bar(
        event_flags,
        x="event_id",
        y=["pct_actual", "pct_estimated", "pct_missing"],
        title="Interval read quality by event (%)",
        barmode="stack",
        labels={"value": "Percent", "variable": "Read type"},
        color_discrete_map={
            "pct_actual": "#2ecc71",
            "pct_estimated": "#f1c40f",
            "pct_missing": "#e74c3c",
        },
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Utility zones with weakest data quality**")
    st.dataframe(zone_quality.head(8), use_container_width=True, hide_index=True)

    st.info(
        "**Plain English:** Data quality directly affects our ability to get paid. "
        "Missing reads lead to disputed settlements and delayed partner payouts."
    )


def tab_settlement(cbl: pd.DataFrame, programs: pd.DataFrame, enrollment: pd.DataFrame) -> None:
    st.subheader("What did customers actually reduce and what do we owe them?")

    default_rate = float(programs["capacity_rate_per_kw"].mean())

    cbl = cbl.copy()
    cbl["reduction_kw"] = cbl["total_reduction_kwh"] / 2.0
    cbl["negative_reduction"] = cbl["total_reduction_kwh"] < 0
    cbl["incentive_usd"] = cbl["reduction_kw"].clip(lower=0) * default_rate

    enr_lookup = enrollment[["utility_account_id", "partner_name", "utility_zone"]].drop_duplicates(
        "utility_account_id"
    )
    cbl_seg = cbl.merge(enr_lookup, on="utility_account_id", how="left")
    cbl_seg["segment"] = cbl_seg["partner_name"].fillna("Unknown")

    summary = (
        cbl_seg.groupby("segment", as_index=False)
        .agg(
            events_participated=("event_id", "count"),
            avg_kw_reduced=("avg_kw_reduced", "mean"),
            total_incentive_usd=("incentive_usd", "sum"),
            negative_cases=("negative_reduction", "sum"),
        )
        .sort_values("total_incentive_usd", ascending=False)
    )
    summary["avg_kw_reduced"] = summary["avg_kw_reduced"].round(3)
    summary["total_incentive_usd"] = summary["total_incentive_usd"].round(2)

    total_settlement = summary["total_incentive_usd"].sum()
    c1, c2 = st.columns(2)
    c1.metric("Total settlement value (all events)", f"${total_settlement:,.2f}")
    c2.metric("Customers with negative reduction", f"{int(cbl['negative_reduction'].sum()):,}")

    st.dataframe(summary, use_container_width=True, hide_index=True)

    scatter_df = cbl.copy()
    scatter_df["cbl_kw"] = scatter_df["total_cbl_kwh"] / 2.0
    scatter_df["actual_kw"] = scatter_df["total_actual_kwh"] / 2.0
    fig = px.scatter(
        scatter_df,
        x="cbl_kw",
        y="actual_kw",
        color="responded_flag",
        hover_data=["utility_account_id", "event_id", "avg_kw_reduced"],
        title="CBL kW vs actual kW (below diagonal = over-performed / reduced load)",
        labels={"responded_flag": "Responded"},
    )
    max_val = max(scatter_df["cbl_kw"].max(), scatter_df["actual_kw"].max())
    fig.add_shape(
        type="line",
        x0=0,
        y0=0,
        x1=max_val,
        y1=max_val,
        line=dict(dash="dash", color="gray"),
    )
    st.plotly_chart(fig, use_container_width=True)

    bad = cbl_seg[cbl_seg["negative_reduction"]].head(20)
    if not bad.empty:
        st.warning("Customers who used **more** power during the event window (investigate):")
        st.dataframe(
            bad[
                [
                    "utility_account_id",
                    "event_id",
                    "total_cbl_kwh",
                    "total_actual_kwh",
                    "total_reduction_kwh",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )


def main() -> None:
    data = load_all_data()

    enrollment = parse_dates(data["enrollment"], ["enrollment_date", "opt_out_date"])
    master = parse_dates(data["master"], ["enrolled_date"])
    devices = parse_dates(data["devices"], ["last_seen_timestamp", "runtime_date"])
    cbl = parse_dates(data["cbl"], ["event_date"])
    dr_events = parse_dates(data["dr_events"], ["event_date"])
    eia = parse_dates(data["eia"], ["period"])

    enrollment, master, cbl, intervals, dr_events, eia, devices, filter_summary = (
        apply_sidebar_filters(
            enrollment,
            master,
            cbl,
            data["intervals"],
            dr_events,
            eia,
            devices,
        )
    )
    as_of = reference_date(enrollment)

    st.title("Voltus Residential VPP — Partnerships Team Dashboard")
    st.markdown(
        "Operational view of enrollment funnel, partner growth, event performance, "
        "meter data quality, and settlement reconciliation."
    )
    st.caption(filter_summary)
    st.caption(f"Data as of **{as_of.date()}** (batch snapshot — refresh by re-running `run_pipeline.py`).")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "Enrollment Funnel",
            "Partner & Device Summary",
            "Event Performance",
            "Interval Data Quality",
            "Settlement Reconciliation",
        ]
    )

    with tab1:
        tab_enrollment_funnel(enrollment, cbl, as_of)
    with tab2:
        tab_partner_devices(enrollment, devices, data["partners"], as_of)
    with tab3:
        tab_event_performance(dr_events, cbl, eia)
    with tab4:
        tab_data_quality(intervals, enrollment)
    with tab5:
        tab_settlement(cbl, data["programs"], enrollment)


if __name__ == "__main__":
    main()
