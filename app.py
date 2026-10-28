"""OneRun Bank IT Operations — Streamlit dashboard.

Run:  streamlit run app.py
Data: data/OneRun_Bank_IT_Ops_Synthetic.xlsx (made by simulator/it_ops_simulator.py), or upload a workbook
      with the same sheets (the original sample format also works).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re

import numpy as np
import pandas as pd
import streamlit as st

from itops import charts as C
from itops import data as D
from itops import metrics as M

APP_TITLE = "OneRun Bank · IT Operations"
HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLED = os.path.join(HERE, "data", "OneRun_Bank_IT_Ops_Synthetic.xlsx")

st.set_page_config(page_title="OneRun Bank IT Operations", page_icon="🏦", layout="wide")
st.markdown("""
<style>
.block-container{padding-top:2rem;padding-bottom:3rem;max-width:1440px}
.ob-sub{color:#475569;margin-top:-0.5rem;font-size:0.95rem}
.ob-head{background:#0F172A;color:#FFFFFF;border-radius:10px;padding:16px 20px;font-size:1.05rem;line-height:1.55}
.ob-head b, .ob-head strong{color:#FFFFFF}
.ob-warn{background:#FFF7ED;border:1px solid #FED7AA;border-radius:10px;padding:12px 16px;color:#7C2D12;margin:4px 0}
.ob-chip{display:inline-block;padding:2px 9px;border-radius:999px;font-size:0.8rem;font-weight:600;margin-right:4px}
.ob-card{border:1px solid #E2E8F0;border-radius:10px;padding:14px 16px;height:100%}
div[data-testid="stMetricValue"]{font-size:1.65rem}
</style>
""", unsafe_allow_html=True)

SEV_CHIP = {"P1": ("#FFE4E6", "#9F1239"), "P2": ("#FFEDD5", "#9A3412"), "P3": ("#E2E8F0", "#334155"),
            "P4": ("#F1F5F9", "#475569")}


# =============================================================================== data
@st.cache_data(show_spinner="Loading IT operations data…")
def load(blob: bytes | None, key: str) -> D.Data:
    raw = D.read_workbook(blob if blob is not None else BUNDLED)
    return D.normalise(raw)


@st.cache_data(show_spinner=False)
def generate_bundled() -> bool:
    """First run on a fresh deploy without the data file: build it with the simulator."""
    from simulator.it_ops_simulator import Config, simulate, write_excel
    os.makedirs(os.path.dirname(BUNDLED), exist_ok=True)
    write_excel(simulate(Config(end_date=dt.date.today())), BUNDLED)
    return True


with st.sidebar:
    st.markdown(f"### 🏦 {APP_TITLE}")
    src = st.radio("Data", ["Bundled synthetic data", "Upload a workbook"], key="src",
                   help="Upload an .xlsx with the same sheets as the sample (Applications, Incidents, "
                        "ServiceRequests, ChangeRequests, Vulnerabilities, …).")
    blob, key = None, "bundled"
    if src == "Upload a workbook":
        up = st.file_uploader("Workbook (.xlsx)", type=["xlsx"], key="upload")
        if up is not None:
            blob = up.getvalue()
            key = hashlib.md5(blob).hexdigest()

if blob is None and not os.path.exists(BUNDLED):
    with st.spinner("Generating a year of synthetic data (first run only)…"):
        generate_bundled()
try:
    DATA = load(blob, key)
except Exception as e:  # noqa: BLE001
    st.error(f"Could not read that workbook: {e}")
    st.stop()

LOBS = ["All LOBs"] + sorted(DATA.apps["LOB"].dropna().unique())
TIERS = ["All tiers"] + sorted(DATA.apps["Tier"].dropna().unique())
TYPES = ["All types"] + sorted(DATA.apps["App_Type"].dropna().unique())

with st.sidebar:
    st.divider()
    lob = st.selectbox("Line of business", LOBS, key="lob")
    tier = st.selectbox("App tier", TIERS, key="tier")
    app_type = st.selectbox("App type", TYPES, key="app_type")
    view = st.radio("View", ["Monthly", "Quarterly", "Yearly"], horizontal=True, key="view")
    periods = D.period_options(view, DATA.first_day, DATA.last_day)
    labels = [p.label for p in periods]
    plabel = st.selectbox("Period", labels, key=f"period_{view}")
    P = periods[labels.index(plabel)]
    PREV = D.previous_period(view, P, DATA.first_day)
    last_change = max(DATA.cr["Date"].max(), DATA.last_day)
    today = st.date_input("Today (for the Today screen)", value=DATA.last_day.date(),
                          min_value=DATA.first_day.date(), max_value=last_change.date(), key="today")
    st.divider()
    st.caption(f"Data covers {DATA.first_day:%d %b %Y} – {DATA.last_day:%d %b %Y} · {len(DATA.apps):,} applications. "
               "Synthetic data for demonstration only.")

if "targets" not in st.session_state:
    st.session_state["targets"] = dict(M.DEFAULT_TARGETS)
T = st.session_state["targets"]

APPS = D.filter_apps(DATA.apps, lob, tier, app_type)
DS = D.scope(DATA, APPS)
INC = M.incidents(DS, P)
INC_PREV = M.incidents(DS, PREV) if PREV is not None else None
TODAY = pd.Timestamp(today)


@st.cache_data(show_spinner="Scoring applications…")
def cached_recs(data_key: str, lob_: str, tier_: str, type_: str, asof: pd.Timestamp) -> pd.DataFrame:
    ds = D.scope(DATA, D.filter_apps(DATA.apps, lob_, tier_, type_))
    return M.recommendations(ds, asof)


REC_ASOF = min(P.end, DATA.last_day)
REC = cached_recs(key, lob, tier, app_type, REC_ASOF)


# =============================================================================== helpers
_N = [0]


def chart(fig):
    _N[0] += 1
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key=f"c{_N[0]}")


def chips(counts: dict) -> str:
    out = ""
    for sev in ["P1", "P2", "P3", "P4"]:
        bg, fg = SEV_CHIP[sev]
        out += f"<span class='ob-chip' style='background:{bg};color:{fg}'>{sev} · {counts.get(sev, 0)}</span>"
    return out


def rate_delta(cur: int, prev: int | None, p: D.Period, pp: D.Period | None) -> str | None:
    if prev is None or pp is None or prev == 0:
        return None
    ch = (cur / p.days) / (prev / pp.days) * 100 - 100
    return f"{ch:+.1f}% per day vs {pp.label}"


def scope_text() -> str:
    parts = [lob if lob != "All LOBs" else "all lines of business"]
    if tier != "All tiers":
        parts.append(tier)
    if app_type != "All types":
        parts.append(app_type)
    return f"{P.label} · {', '.join(parts)} · {len(APPS):,} applications"


def empty_guard() -> bool:
    if APPS.empty:
        st.info("No applications match these filters.")
        return True
    return False


# =============================================================================== header
st.title("IT Operations")
st.markdown(f"<div class='ob-sub'>OneRun Bank · {scope_text()}</div>", unsafe_allow_html=True)
for n in DATA.notes:
    st.caption("ℹ️ " + n)

tabs = st.tabs([":material/dashboard: Executive", ":material/today: Today", ":material/table_chart: Tickets by LOB & app",
                ":material/hub: Root cause & correlation", ":material/speed: KPIs", ":material/flag: Top priorities"])

# =============================================================================== 1 executive
with tabs[0]:
    if not empty_guard():
        hl = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", M.headline(DS, P, PREV, T))
        st.markdown(f"<div class='ob-head'>{hl}</div>", unsafe_allow_html=True)
        st.write("")
        kt = M.kpi_table(DS, P, T).set_index("KPI")
        p1 = int((INC.Severity == "P1").sum())
        p1_prev = int((INC_PREV.Severity == "P1").sum()) if INC_PREV is not None else None
        av = kt.loc["Tier-1 application availability", "Value"]
        mttr = kt.loc["Mean time to restore (MTTR), P1", "Value"]
        cfr = kt.loc["Change failure rate", "Value"]
        vul_now = M.vulns_asof(DS.vul, P.end)
        open_crit = int(((vul_now.Status == "Open") & (vul_now.Severity == "Critical")).sum())
        past_due = int(((vul_now.Status == "Open") & (vul_now.Overdue == "Yes")).sum())
        c = st.columns(6)
        c[0].metric("Incidents", M.indian(len(INC)),
                    rate_delta(len(INC), len(INC_PREV) if INC_PREV is not None else None, P, PREV),
                    delta_color="inverse", help="Change in incidents per day, so a partial month compares fairly.")
        c[1].metric("P1 incidents", str(p1), None if p1_prev is None else f"{p1 - p1_prev:+d} vs {PREV.label}",
                    delta_color="inverse")
        c[2].metric("Tier-1 availability", "–" if pd.isna(av) else f"{av:.2f}%",
                    None if pd.isna(av) else f"{av - T['availability']:+.2f} pts vs {T['availability']}% target")
        c[3].metric("MTTR, P1", "–" if pd.isna(mttr) else f"{mttr:.1f} h",
                    None if pd.isna(mttr) else f"{mttr - T['mttr_p1']:+.1f} h vs {T['mttr_p1']:g} h target",
                    delta_color="inverse")
        c[4].metric("Change failure rate", "–" if pd.isna(cfr) else f"{cfr:.1f}%",
                    None if pd.isna(cfr) else f"{cfr - T['cfr']:+.1f} pts vs {T['cfr']:g}% target", delta_color="inverse")
        c[5].metric("Open critical vulnerabilities", str(open_crit), f"{past_due} vulns past due", delta_color="off")

        chart(C.monthly_trend(DS.inc, P.start, P.end, title="Incidents per month (bars) and P1 incidents (line) · "
                                                            "selected period highlighted"))
        a, b, cc = st.columns(3)
        with a:
            if lob == "All LOBs":
                s = INC.groupby("LOB").size().sort_values(ascending=False).head(8)
                ex = INC[INC.Severity.isin(["P1", "P2"])].groupby("LOB").size()
                chart(C.hbar(s, "Incidents by line of business (P1+P2)", extra=ex, extra_label="P1/P2"))
            else:
                s = INC.groupby("App_Name").size().sort_values(ascending=False).head(8)
                chart(C.hbar(s, f"Incidents by application · {lob}"))
        with b:
            chart(C.hbar(M.rca_counts(INC).head(6), "Top root causes"))
        with cc:
            tv = M.today_view(DS, TODAY)
            crit = tv["critical"]
            st.markdown(f"**Today · {TODAY:%a %d %b %Y}**")
            x1, x2 = st.columns(2)
            x1.metric("Incidents", len(tv["incidents"]), f"{int((crit.Severity == 'P1').sum())} P1, "
                                                        f"{int((crit.Severity == 'P2').sum())} P2", delta_color="off")
            x2.metric("Changes today", len(tv["changes"]),
                      f"{int((tv['changes']['Production release'] == 'Yes').sum())} production releases",
                      delta_color="off")
            watch = tv["changes"][tv["changes"]["Watch"].str.contains("CAB|High risk|Unstable", regex=True)]
            for _, r in watch.head(2).iterrows():
                st.markdown(f"<div class='ob-warn'><b>{r.Planned_Start:%H:%M} · {r.CR_ID}</b> {r.App_Name} "
                            f"({r.LOB}): {r.Watch}</div>", unsafe_allow_html=True)
            st.markdown("**Act this week**")
            for _, r in REC.head(3).iterrows():
                st.markdown(f"`{r.Risk_Score:>3}` **{r.App_Name}** · {r.LOB}, {r.Tier}  \n"
                            f"<span style='color:#475569;font-size:0.9rem'>{r.Top_Cause} → {r.Recommendation}</span>",
                            unsafe_allow_html=True)

# =============================================================================== 2 today
with tabs[1]:
    if not empty_guard():
        tv = M.today_view(DS, TODAY)
        ch, inc_day, crit = tv["changes"], tv["incidents"], tv["critical"]
        st.subheader(f"Today · {TODAY:%A %d %B %Y}")
        if TODAY > DATA.last_day:
            st.caption("This date is after the last incident in the data: only scheduled changes are shown.")
        c = st.columns(4)
        with c[0]:
            st.metric("Incidents today", len(inc_day))
            st.markdown(chips(inc_day.Severity.value_counts().to_dict()), unsafe_allow_html=True)
        open_crit = crit[crit["is_open"]]
        c[1].metric("Open incidents (latest status)", len(tv["open_now"]),
                    f"{len(open_crit)} of today's P1/P2 still open", delta_color="off")
        c[2].metric("Changes scheduled", len(ch), f"{int((ch.Release_Type == 'Emergency').sum())} emergency · "
                                                  f"{int((ch.Risk == 'High').sum())} high risk", delta_color="off")
        c[3].metric("Production releases", int((ch["Production release"] == "Yes").sum()),
                    ", ".join(ch[ch["Production release"] == "Yes"]["Planned_Start"].dt.strftime("%H:%M")) or None,
                    delta_color="off")
        watch = ch[ch["Watch"].str.contains("CAB|High risk|Unstable", regex=True)]
        if not watch.empty:
            st.markdown("#### Review before go-live")
            for _, r in watch.iterrows():
                why = []
                if "CAB" in r.Watch:
                    why.append("emergency change with no CAB approval")
                if "High risk" in r.Watch:
                    why.append("rated high risk")
                if "Unstable" in r.Watch:
                    why.append(f"{r['Incidents this month']} incidents on this app this month")
                st.markdown(f"<div class='ob-warn'><b>{r.Planned_Start:%H:%M} · {r.CR_ID}</b> · {r.App_Name} "
                            f"({r.LOB}, {r.Tier}, {r.Release_Type}): {'; '.join(why)}.</div>", unsafe_allow_html=True)
        st.markdown("#### Going to production today")
        if ch.empty:
            st.caption("No changes scheduled for this day.")
        else:
            show = ch.assign(Start=ch.Planned_Start.dt.strftime("%H:%M"), End=ch.Planned_End.dt.strftime("%H:%M"))[
                ["Start", "End", "CR_ID", "App_Name", "LOB", "Tier", "Release_Type", "Change_Category", "Risk",
                 "CAB_Approved", "Production release", "Status", "Incidents this month", "Watch"]]
            st.dataframe(show.rename(columns={"CR_ID": "Change", "App_Name": "Application", "Release_Type": "Type",
                                              "Change_Category": "Layer", "CAB_Approved": "CAB"}),
                         hide_index=True, width="stretch")
        st.markdown("#### Critical incidents today (P1 and P2)")
        if crit.empty:
            st.caption("No P1 or P2 incidents on this day.")
        else:
            now = DATA.last_day + pd.Timedelta(hours=9)          # data snapshot time
            cs = crit.assign(Opened=crit.Open_Time.dt.strftime("%H:%M"))
            cs["Age_h"] = np.where(cs["is_open"], ((now - cs["Open_Time"]).dt.total_seconds() / 3600).round(1),
                                   (cs["Duration_Min"] / 60).round(1))
            st.dataframe(cs[["Opened", "Incident_ID", "Severity", "App_Name", "LOB", "Tier", "RCA_Category",
                             "Affected_Layer", "Status", "Age_h", "Correlation_ID", "Related_CR_ID"]]
                         .rename(columns={"Incident_ID": "Incident", "App_Name": "Application", "RCA_Category": "Root cause",
                                          "Affected_Layer": "Layer", "Age_h": "Hours (open or to fix)",
                                          "Correlation_ID": "Event", "Related_CR_ID": "Caused by change"}),
                         hide_index=True, width="stretch")
        with st.expander(f"Next 7 days · {len(tv['upcoming'])} changes scheduled"):
            up = tv["upcoming"].sort_values("Planned_Start")
            st.dataframe(up.assign(Start=up.Planned_Start.dt.strftime("%a %d %b %H:%M"))[
                ["Start", "CR_ID", "App_Name", "LOB", "Tier", "Release_Type", "Change_Category", "Risk", "Status"]],
                hide_index=True, width="stretch")

# =============================================================================== 3 tickets
with tabs[2]:
    if not empty_guard():
        st.subheader("Tickets by line of business and application")
        mx = M.ticket_matrix(DS, P)
        c = st.columns(4)
        c[0].metric("Incidents", M.indian(mx["Incidents"].sum()), f"{mx['P1+P2'].sum()} P1/P2", delta_color="off")
        srp = M.srs(DS, P)
        c[1].metric("Service requests", M.indian(len(srp)),
                    f"{(srp.SLA_Met == 'Yes').mean() * 100:.1f}% within SLA" if len(srp) else None, delta_color="off")
        crp = M.changes(DS, P)
        c[2].metric("Change requests", M.indian(len(crp)),
                    f"{int(crp.Status.isin(D.COMPLETED).sum())} completed", delta_color="off")
        c[3].metric("New vulnerabilities", M.indian(mx["New vulns"].sum()), f"{mx['Open vulns'].sum()} open",
                    delta_color="off")
        avg = mx["Incidents"].sum() / max(mx["Apps"].sum(), 1)
        hot = mx[(mx["Incidents per app"] >= avg * 1.6) & (mx["Incidents"] >= 10)]
        if len(mx) > 1 and not hot.empty:
            names = " and ".join(f"**{ix}** ({r['Incidents per app']:.1f})" for ix, r in hot.head(3).iterrows())
            st.markdown(f"{names} raise far more incidents per application than the average of {avg:.1f}, "
                        "so their volume is not just a matter of having more apps.")
        types = st.multiselect("Ticket types in the chart", ["Incidents", "Service requests", "Changes", "New vulns"],
                               default=["Incidents", "Service requests", "Changes", "New vulns"], key="tk_types")
        left, right = st.columns([3, 2])
        with left:
            if types:
                chart(C.stacked_lob(mx, types, title="Tickets by line of business"))
        with right:
            chart(C.severity_bars(INC, "LOB", title="Incidents by severity and LOB"))
        st.markdown("#### All lines of business")
        tot = mx.sum(numeric_only=True)
        tot["Incidents per app"] = round(tot["Incidents"] / max(tot["Apps"], 1), 2)
        st.dataframe(pd.concat([mx, pd.DataFrame([tot], index=["All"])]).reset_index().rename(columns={"index": "Line of business"}),
                     hide_index=True, width="stretch",
                     column_config={"Incidents": st.column_config.ProgressColumn(
                         "Incidents", format="%d", min_value=0, max_value=int(max(mx["Incidents"].max(), 1)))})
        st.markdown("#### Applications")
        apps_t = M.app_table(DS, P)
        a1, a2 = st.columns([1, 3])
        n_show = a1.selectbox("Show", [10, 25, 50, 100], index=1, key="tk_n")
        st.dataframe(apps_t.head(n_show).reset_index().rename(columns={"App_ID": "App ID", "App_Name": "Application",
                                                                        "App_Type": "Type"}),
                     hide_index=True, width="stretch")
        st.download_button("Download application ticket counts (.csv)", apps_t.to_csv().encode(),
                           file_name=f"onerun_app_tickets_{P.start:%Y%m}.csv", mime="text/csv")
        st.markdown("#### Application drill-down")
        opts = list(apps_t.index[apps_t["Incidents"] > 0]) or list(apps_t.index)
        if opts:
            pick = st.selectbox("Application", opts, format_func=lambda x: f"{apps_t.loc[x, 'App_Name']} ({x})",
                                key="tk_app")
            info = DATA.apps.set_index("App_ID").loc[pick]
            st.markdown(f"**{info.App_Name}** · {info.LOB} · {info.Tier} · {info.App_Type} · {info.Hosting} · "
                        f"{info.Database} ({info.DB_Cluster}) · support: {info.Support_Group}")
            ai = INC[INC.App_ID == pick].sort_values("Open_Time", ascending=False)
            ac = crp[crp.App_ID == pick].sort_values("Planned_Start", ascending=False)
            av_ = M.vulns_asof(DS.vul, P.end)
            av_ = av_[(av_.App_ID == pick) & (av_.Status == "Open")]
            t1, t2, t3 = st.tabs([f"Incidents ({len(ai)})", f"Changes ({len(ac)})", f"Open vulnerabilities ({len(av_)})"])
            with t1:
                st.dataframe(ai[["Incident_ID", "Open_Time", "Severity", "RCA_Category", "Affected_Layer",
                                 "Duration_Min", "Status", "Correlation_ID", "Related_CR_ID"]], hide_index=True,
                             width="stretch")
            with t2:
                st.dataframe(ac[["CR_ID", "Planned_Start", "Release_Type", "Change_Category", "Risk", "Status",
                                 "CAB_Approved"]], hide_index=True, width="stretch")
            with t3:
                st.dataframe(av_[["Vuln_ID", "Severity", "CVSS", "Discovered_Date", "Due_Date", "Overdue", "Age_Days"]],
                             hide_index=True, width="stretch")

# =============================================================================== 4 RCA & correlation
with tabs[3]:
    if not empty_guard():
        st.subheader("Root cause and correlation")
        if INC.empty:
            st.info("No incidents in this period.")
        else:
            ls = M.layer_summary(INC)
            top_layer = ls["In shared events %"].idxmax()
            low_layer = ls["In shared events %"].idxmin()
            st.markdown(
                f"<div class='ob-head'>{top_layer} incidents spread the furthest: "
                f"{ls.loc[top_layer, 'In shared events %']:.0f}% arrive as part of an event that hits several "
                f"applications at once, against {ls.loc[low_layer, 'In shared events %']:.0f}% for "
                f"{low_layer.lower()} incidents.</div>", unsafe_allow_html=True)
            st.write("")
            a, b = st.columns(2)
            with a:
                chart(C.hbar(M.rca_counts(INC), "RCA categories", highlight=1))
            with b:
                chart(C.layer_bars(ls, title="Incidents by layer, and share arriving in multi-application events"))
            a, b = st.columns(2)
            with a:
                chart(C.heatmap(M.rca_by_layer(INC), title="Where each root cause lands (RCA × layer)"))
            with b:
                chart(C.heatmap(M.layer_by_lob(INC), title="Layer by line of business"))

            st.markdown("#### Do DB, application, infrastructure and packaging incidents happen together?")
            st.caption("Left: how many application-days had incidents on both layers. Right: correlation of hourly "
                       "incident counts (1 = always spike together, 0 = unrelated).")
            a, b = st.columns(2)
            with a:
                pairs = M.same_app_day_pairs(INC)
                if not pairs.empty:
                    chart(C.heatmap(pairs, title="Same application, same day: layer pairs"))
            with b:
                corr = M.hourly_layer_correlation(INC)
                if not corr.empty:
                    chart(C.heatmap(corr, title="Hourly correlation between layers", fmt=".2f", zmin=-0.2, zmax=1))

            st.markdown("#### Multi-application events")
            ev = M.shared_events(INC)
            if ev.empty:
                st.caption("No correlated events in this period.")
            else:
                st.dataframe(ev.head(15).assign(Start=ev.head(15).Start.dt.strftime("%d %b %H:%M")),
                             hide_index=True, width="stretch")
                pick = st.selectbox("Open an event", ev["Event"].head(30), key="rca_event")
                mem = INC[INC.Correlation_ID == pick].sort_values("Open_Time")
                st.dataframe(mem[["Incident_ID", "Open_Time", "App_Name", "LOB", "Tier", "Severity", "RCA_Category",
                                  "Affected_Layer", "DB_Cluster", "Infra_Cluster", "Duration_Min", "Related_CR_ID"]],
                             hide_index=True, width="stretch")
            a, b, cc = st.columns([2, 2, 1])
            with a:
                st.markdown("**Database clusters with the widest blast radius**")
                st.dataframe(M.blast_radius(INC, "Database", "DB_Cluster"), width="stretch")
            with b:
                st.markdown("**Infrastructure clusters with the widest blast radius**")
                st.dataframe(M.blast_radius(INC, "Infrastructure", "Infra_Cluster"), width="stretch")
            with cc:
                ci = M.change_induced(DS, P)
                st.metric("Incidents caused by changes", ci["incidents"], f"{ci['p1p2']} P1/P2", delta_color="off")
                st.metric("Releases rolled back", f"{ci['rolled_back']} of {ci['releases']}")

# =============================================================================== 5 KPIs
with tabs[4]:
    if not empty_guard():
        st.subheader("Industry-standard KPIs")
        st.caption("ITIL service-management and DORA delivery measures against the bank's targets.")
        with st.expander("Edit targets"):
            tc = st.columns(4)
            labels_t = {
                "mtta_p1": "MTTA P1 (min, max)", "mttr_p1": "MTTR P1 (h, max)", "mttr_p2": "MTTR P2 (h, max)",
                "sla_p1p2": "P1/P2 within SLA (%, min)", "sla_all": "All within SLA (%, min)",
                "reopen": "Reopen rate (%, max)", "monitoring": "Detected by monitoring (%, min)",
                "availability": "Tier-1 availability (%, min)", "change_success": "Change success (%, min)",
                "cfr": "Change failure rate (%, max)", "emergency": "Emergency changes (%, max)",
                "emergency_no_cab": "Emergency without CAB (%, max)", "sr_sla": "SR within SLA (%, min)",
                "mttrem_crit": "Remediate critical (days, max)", "mttrem_high": "Remediate high (days, max)",
                "vuln_in_sla": "Vulns closed on time (%, min)", "vuln_past_due": "Open past due (max)",
            }
            for k_, (kk, lbl) in enumerate(labels_t.items()):
                T[kk] = tc[k_ % 4].number_input(lbl, value=float(T[kk]), step=0.05 if kk == "availability" else 1.0,
                                                format="%.2f" if kk == "availability" else "%.1f", key=f"t_{kk}")
            if st.button("Reset to defaults", key="t_reset"):
                st.session_state["targets"] = dict(M.DEFAULT_TARGETS)
                for kk in labels_t:
                    st.session_state.pop(f"t_{kk}", None)
                st.rerun()
        kt = M.kpi_table(DS, P, T)
        counts = kt["Status"].value_counts()
        st.markdown(f"**{counts.get('Met', 0)} met · {counts.get('Missed', 0)} missed · {counts.get('Tracked', 0)} "
                    f"tracked** for {P.label}")
        missed = kt[kt.Status == "Missed"]
        if not missed.empty:
            def gap(r):
                return abs(r.Value - r.Target) / max(abs(r.Target), 1e-9)
            worst = missed.assign(g=missed.apply(gap, axis=1)).sort_values("g", ascending=False).head(3)
            st.markdown("Largest gaps: " + "; ".join(
                f"{r.KPI} {M.fmt_value(r.Value, r.Unit)} (target {M.fmt_target(r.Target, r.Unit, r.Better)})"
                for _, r in worst.iterrows()) + ".")
        show = kt.assign(**{"This period": [M.fmt_value(v, u) for v, u in zip(kt.Value, kt.Unit)],
                            "Target": [M.fmt_target(v, u, b) for v, u, b in zip(kt.Target, kt.Unit, kt.Better)]})
        st.dataframe(show[["Group", "KPI", "This period", "Target", "Status", "How measured"]], hide_index=True,
                     width="stretch", height=38 * (len(show) + 1))
        st.markdown("#### KPI trend")
        pick = st.selectbox("KPI", list(kt.KPI), index=list(kt.KPI).index("Change failure rate"), key="kpi_pick")
        months = D.period_options("Monthly", DATA.first_day, DATA.last_day)[::-1]
        vals = []
        for mp in months:
            r = M.kpi_table(DS, mp, T).set_index("KPI").loc[pick]
            vals.append(r.Value)
        row = kt.set_index("KPI").loc[pick]
        chart(C.kpi_trend([m.start.strftime("%b %y") for m in months], vals, row.Target, row.Unit,
                          title=f"{pick} by month"))

# =============================================================================== 6 priorities
with tabs[5]:
    if not empty_guard():
        asof = REC_ASOF
        st.subheader("Top priorities to address")
        st.caption(f"Applications ranked by a risk score from the 90 days to {asof:%d %b %Y}.")
        rec = REC
        if rec.empty:
            st.info("No applications with risk in this selection.")
        else:
            vc = rec["Action_Priority"].value_counts()
            c = st.columns(4)
            c[0].metric("Act this week · score 80+", int(vc.get("P1 - this week", 0)))
            c[1].metric("This month · 50–79", int(vc.get("P2 - this month", 0)))
            c[2].metric("This quarter · below 50", int(vc.get("P3 - this quarter", 0)))
            top50 = rec.head(50)["Recommendation"].value_counts()
            c[3].metric("Most common fix (top 50)", top50.index[0], f"{top50.iloc[0]} apps", delta_color="off")
            f1, f2 = st.columns(2)
            pr = f1.multiselect("Priority", ["P1 - this week", "P2 - this month", "P3 - this quarter"],
                                default=["P1 - this week", "P2 - this month"], key="pr_pri")
            rc = f2.multiselect("Recommendation", sorted(rec["Recommendation"].unique()), key="pr_rec")
            view_rec = rec[rec["Action_Priority"].isin(pr)] if pr else rec
            if rc:
                view_rec = view_rec[view_rec["Recommendation"].isin(rc)]
            st.dataframe(view_rec[["Rank", "Risk_Score", "App_Name", "LOB", "Tier", "Top_Cause", "Recommendation",
                                   "Action_Priority", "Evidence", "Next_Step", "Owner"]]
                         .rename(columns={"Risk_Score": "Score", "App_Name": "Application", "Top_Cause": "Costliest cause",
                                          "Action_Priority": "Priority", "Next_Step": "Next step"}),
                         hide_index=True, width="stretch",
                         column_config={"Score": st.column_config.ProgressColumn("Score", format="%d", min_value=0,
                                                                                 max_value=100)})
            st.download_button("Download priority list (.csv)", rec.to_csv(index=False).encode(),
                               file_name=f"onerun_priorities_{asof:%Y%m%d}.csv", mime="text/csv")
            a, b = st.columns(2)
            with a:
                chart(C.rec_mix(top50, title="Recommended fix, top 50 applications"))
            with b:
                chart(C.score_hist(rec["Risk_Score"], title="Risk score distribution"))
            with st.expander("How the score works"):
                st.markdown(
                    "Each application scores 0–100 from the last 90 days: incidents weighted by severity "
                    "(P1 counts 10, P2 4, P3 1, P4 0.25), repeated root causes, failed or rolled-back changes, open and "
                    "overdue vulnerabilities, and repeated data-fix or batch-rerun requests, then weighted by tier "
                    "(Tier-1 × 1.5). The factor that contributes most picks the recommendation; for incidents, the "
                    "costliest root cause picks it. It is a transparent rule, not a black-box model, so owners can see "
                    "exactly why their application is listed.")
