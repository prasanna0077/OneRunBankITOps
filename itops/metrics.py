"""All calculations behind the screens. Pure pandas; no Streamlit."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd

from .data import COMPLETED, FAILED, Data, Period, in_period

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from simulator.it_ops_simulator import make_recommendations  # noqa: E402

LAYERS = ["Application", "Database", "Infrastructure", "Packaging", "Network", "Data"]
SEVERITIES = ["P1", "P2", "P3", "P4"]

DEFAULT_TARGETS = {  # bank policy targets: editable in the app
    "mtta_p1": 15.0, "mttr_p1": 4.0, "mttr_p2": 8.0, "sla_p1p2": 95.0, "sla_all": 90.0, "reopen": 5.0,
    "monitoring": 70.0, "availability": 99.95, "change_success": 95.0, "cfr": 5.0, "emergency": 10.0,
    "emergency_no_cab": 0.0, "sr_sla": 95.0, "mttrem_crit": 15.0, "mttrem_high": 30.0, "vuln_in_sla": 90.0,
    "vuln_past_due": 0.0,
}


def _mean(s):
    s = pd.to_numeric(s, errors="coerce").dropna()
    return float(s.mean()) if len(s) else np.nan


def _pct(mask) -> float:
    mask = pd.Series(mask)
    return float(mask.mean() * 100) if len(mask) else np.nan


# =============================================================================== slices
def incidents(ds: Data, p: Period) -> pd.DataFrame:
    return ds.inc[in_period(ds.inc["Date"], p)]


def changes(ds: Data, p: Period) -> pd.DataFrame:
    return ds.cr[in_period(ds.cr["Date"], p)]


def srs(ds: Data, p: Period) -> pd.DataFrame:
    return ds.sr[in_period(ds.sr["Date"], p)]


def vulns_asof(vul: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """Status and overdue flag as of a date, recomputed from the dates."""
    v = vul[vul["Discovered_Date"] <= asof].copy()
    closed = v["Closed_Date"].notna() & (v["Closed_Date"] <= asof)
    accepted = closed & v.get("Status", pd.Series("", index=v.index)).eq("Risk Accepted")
    v["Status"] = np.where(accepted, "Risk Accepted", np.where(closed, "Closed", "Open"))
    v["Overdue"] = np.where(v["Status"] == "Open", np.where(v["Due_Date"] < asof, "Yes", "No"),
                            np.where(v["Closed_Date"] > v["Due_Date"], "Yes", "No"))
    v["Age_Days"] = np.where(v["Status"] == "Open", (asof - v["Discovered_Date"]).dt.days,
                             (v["Closed_Date"] - v["Discovered_Date"]).dt.days)
    return v


# =============================================================================== availability
def availability(inc_p: pd.DataFrame, apps: pd.DataFrame, p: Period) -> float:
    """Tier-1 availability: P1 minutes count as full outage, P2 as 30% degradation."""
    t1 = apps[apps["Tier"] == "Tier-1"]["App_ID"]
    if len(t1) == 0:
        return np.nan
    x = inc_p[inc_p["App_ID"].isin(t1) & inc_p["Severity"].isin(["P1", "P2"])]
    mins = (x["Duration_Min"].clip(upper=1440) * np.where(x["Severity"] == "P1", 1.0, 0.3)).sum()
    return float(100 * (1 - mins / (len(t1) * 1440 * p.days)))


# =============================================================================== KPIs
def kpi_table(ds: Data, p: Period, t: dict) -> pd.DataFrame:
    i = incidents(ds, p)
    res = i[i["Resolved_Time"].notna() & ~i["is_open"]]
    p12 = i[i["Severity"].isin(["P1", "P2"])]
    c = changes(ds, p)
    done = c[c["Status"].isin(COMPLETED)]
    s = srs(ds, p)
    v_all = vulns_asof(ds.vul, p.end)
    v_closed = v_all[(v_all["Status"] != "Open") & in_period(v_all["Closed_Date"], p)]
    rows = [
        ("Incident management", "Mean time to acknowledge (MTTA), P1", _mean(i[i.Severity == "P1"]["Acknowledge_Min"]),
         "min", t["mtta_p1"], "low", "Open → first engineer response"),
        ("Incident management", "Mean time to restore (MTTR), P1", _mean(res[res.Severity == "P1"]["Duration_Min"]) / 60,
         "h", t["mttr_p1"], "low", "Open → service restored, resolved P1s"),
        ("Incident management", "Mean time to restore (MTTR), P2", _mean(res[res.Severity == "P2"]["Duration_Min"]) / 60,
         "h", t["mttr_p2"], "low", "Open → service restored, resolved P2s"),
        ("Incident management", "P1/P2 resolved within SLA", _pct(p12["SLA_Breached"] == "No"),
         "%", t["sla_p1p2"], "high", "SLA: P1 4 h, P2 8 h"),
        ("Incident management", "All incidents resolved within SLA", _pct(i["SLA_Breached"] == "No"),
         "%", t["sla_all"], "high", "SLA: P3 24 h, P4 72 h"),
        ("Incident management", "Reopen rate", _pct(i["Reopened"] == "Yes"), "%", t["reopen"], "low",
         "Incidents reopened after resolution"),
        ("Incident management", "Detected by monitoring", _pct(i["Detected_By"] == "Monitoring"), "%",
         t["monitoring"], "high", "Raised by alerts before users reported them"),
        ("Availability and customer impact", "Tier-1 application availability", availability(i, ds.apps, p), "%",
         t["availability"], "high", "P1 outage minutes (P2 at 30%) across Tier-1 apps in scope"),
        ("Availability and customer impact", "Customers affected by P1/P2", float(p12["Customers_Impacted"].sum()),
         "count", None, None, "Sum of customers impacted per incident"),
        ("Change and release (DORA)", "Change success rate", _pct(done["Status"] == "Implemented"), "%",
         t["change_success"], "high", "Implemented without failure or rollback"),
        ("Change and release (DORA)", "Change failure rate", _pct(done["Status"].isin(FAILED)), "%", t["cfr"], "low",
         "Failed or rolled-back changes / completed changes"),
        ("Change and release (DORA)", "Emergency changes", _pct(done["Release_Type"] == "Emergency"), "%",
         t["emergency"], "low", "Share of completed changes"),
        ("Change and release (DORA)", "Emergency changes without CAB approval",
         _pct((done["Release_Type"] == "Emergency") & (done["CAB_Approved"] == "No")), "%", t["emergency_no_cab"],
         "low", "Share of completed changes"),
        ("Change and release (DORA)", "Incidents caused by changes", float(i["Related_CR_ID"].notna().sum()), "count",
         None, None, "Incidents linked to a change record"),
        ("Service requests", "Requests fulfilled within SLA", _pct(s["SLA_Met"] == "Yes"), "%", t["sr_sla"], "high",
         "SLA by request category"),
        ("Vulnerability management", "Mean time to remediate, critical",
         _mean(v_closed[v_closed.Severity == "Critical"]["Age_Days"]), "days", t["mttrem_crit"], "low",
         "Discovered → closed, criticals closed in the period"),
        ("Vulnerability management", "Mean time to remediate, high",
         _mean(v_closed[v_closed.Severity == "High"]["Age_Days"]), "days", t["mttrem_high"], "low",
         "Discovered → closed, highs closed in the period"),
        ("Vulnerability management", "Closed within due date", _pct(v_closed["Overdue"] == "No"), "%",
         t["vuln_in_sla"], "high", "Due: critical 15, high 30, medium 90, low 180 days"),
        ("Vulnerability management", "Open vulnerabilities past due date",
         float(((v_all["Status"] == "Open") & (v_all["Overdue"] == "Yes")).sum()), "count", t["vuln_past_due"], "low",
         f"Open at {p.end:%d %b %Y}, all severities"),
    ]
    df = pd.DataFrame(rows, columns=["Group", "KPI", "Value", "Unit", "Target", "Better", "How measured"])

    def status(r):
        if r.Target is None or pd.isna(r.Target) or r.Better is None:
            return "Tracked"
        if pd.isna(r.Value):
            return "No data"
        ok = r.Value <= r.Target if r.Better == "low" else r.Value >= r.Target
        return "Met" if ok else "Missed"

    df["Status"] = df.apply(status, axis=1)
    return df


def fmt_value(v, unit) -> str:
    if v is None or pd.isna(v):
        return "–"
    if unit == "%":
        return f"{v:.2f}%" if v >= 99 else f"{v:.1f}%"
    if unit == "count":
        return indian(v)
    return f"{v:.1f} {unit}"


def fmt_target(v, unit, better) -> str:
    if v is None or pd.isna(v):
        return "–"
    sign = "≤ " if better == "low" else "≥ "
    if unit == "count":
        return sign + indian(v)
    if unit == "%":
        return sign + (f"{v:.2f}%" if v >= 99 else f"{v:g}%")
    return sign + f"{v:g} {unit}"


def indian(x) -> str:
    """12345678 -> 1,23,45,678."""
    if x is None or pd.isna(x):
        return "–"
    neg, s = x < 0, str(int(round(abs(x))))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if neg else "") + s


def lakh(x) -> str:
    if x >= 1e7:
        return f"{x / 1e7:.1f} crore"
    if x >= 1e5:
        return f"{x / 1e5:.1f} lakh"
    return indian(x)


# =============================================================================== tickets
def ticket_matrix(ds: Data, p: Period) -> pd.DataFrame:
    i = incidents(ds, p)
    v = vulns_asof(ds.vul, p.end)
    out = pd.DataFrame({
        "Apps": ds.apps.groupby("LOB").size(),
        "Incidents": i.groupby("LOB").size(),
        "P1+P2": i[i.Severity.isin(["P1", "P2"])].groupby("LOB").size(),
        "Service requests": srs(ds, p).groupby("LOB").size(),
        "Changes": changes(ds, p).groupby("LOB").size(),
        "New vulns": v[in_period(v["Discovered_Date"], p)].groupby("LOB").size(),
        "Open vulns": v[v["Status"] == "Open"].groupby("LOB").size(),
    }).fillna(0).astype(int)
    out["Incidents per app"] = (out["Incidents"] / out["Apps"].replace(0, np.nan)).round(2)
    out = out.sort_values("Incidents", ascending=False)
    out.index.name = "Line of business"
    return out[["Apps", "Incidents", "P1+P2", "Incidents per app", "Service requests", "Changes", "New vulns",
                "Open vulns"]]


def app_table(ds: Data, p: Period) -> pd.DataFrame:
    i = incidents(ds, p)
    c = changes(ds, p)
    v = vulns_asof(ds.vul, p.end)
    t = pd.DataFrame({
        "Incidents": i.groupby("App_ID").size(),
        "P1+P2": i[i.Severity.isin(["P1", "P2"])].groupby("App_ID").size(),
        "Service requests": srs(ds, p).groupby("App_ID").size(),
        "Changes": c.groupby("App_ID").size(),
        "Failed changes": c[c.Status.isin(FAILED)].groupby("App_ID").size(),
        "Open vulns": v[v.Status == "Open"].groupby("App_ID").size(),
    }).fillna(0).astype(int)
    a = ds.apps.set_index("App_ID")[["App_Name", "LOB", "Tier", "App_Type", "Hosting", "Database"]]
    t = a.join(t, how="inner").fillna(0)
    return t.sort_values(["Incidents", "P1+P2"], ascending=False)


# =============================================================================== RCA and correlation
def rca_counts(i: pd.DataFrame) -> pd.Series:
    return i["RCA_Category"].value_counts()


def layer_summary(i: pd.DataFrame) -> pd.DataFrame:
    g = i.groupby("Affected_Layer")
    out = pd.DataFrame({"Incidents": g.size(),
                        "In shared events %": g["Correlation_ID"].apply(lambda s: s.notna().mean() * 100),
                        "P1+P2": g["Severity"].apply(lambda s: s.isin(["P1", "P2"]).sum())})
    order = [x for x in LAYERS if x in out.index] + [x for x in out.index if x not in LAYERS]
    return out.reindex(order).fillna(0)


def rca_by_layer(i: pd.DataFrame, top: int = 8) -> pd.DataFrame:
    ct = pd.crosstab(i["RCA_Category"], i["Affected_Layer"])
    cols = [x for x in LAYERS if x in ct.columns] + [x for x in ct.columns if x not in LAYERS]
    return ct.loc[i["RCA_Category"].value_counts().index[:top], cols]


def layer_by_lob(i: pd.DataFrame, top: int = 10) -> pd.DataFrame:
    ct = pd.crosstab(i["LOB"], i["Affected_Layer"])
    cols = [x for x in LAYERS if x in ct.columns] + [x for x in ct.columns if x not in LAYERS]
    return ct.loc[i["LOB"].value_counts().index[:top], cols]


def hourly_layer_correlation(i: pd.DataFrame) -> pd.DataFrame:
    """Pearson correlation of hourly incident counts between layers: how often layers spike together."""
    if i.empty:
        return pd.DataFrame()
    h = i.assign(hour=i["Open_Time"].dt.floor("h"))
    m = pd.crosstab(h["hour"], h["Affected_Layer"])
    full = pd.date_range(m.index.min(), m.index.max(), freq="h")
    m = m.reindex(full, fill_value=0)
    cols = [x for x in LAYERS if x in m.columns]
    return m[cols].corr().round(2)


def same_app_day_pairs(i: pd.DataFrame) -> pd.DataFrame:
    """For each application-day with incidents on two or more layers, count each layer pair."""
    g = i.groupby([i["App_ID"], i["Date"].dt.date])["Affected_Layer"].apply(lambda s: sorted(set(s)))
    cols = [x for x in LAYERS if x in set(i["Affected_Layer"])]
    mat = pd.DataFrame(0, index=cols, columns=cols)
    for layers in g:
        if len(layers) < 2:
            continue
        for a in layers:
            for b in layers:
                if a != b and a in mat.index and b in mat.columns:
                    mat.loc[a, b] += 1
    return mat


def shared_events(i: pd.DataFrame) -> pd.DataFrame:
    x = i[i["Correlation_ID"].notna()]
    if x.empty:
        return pd.DataFrame(columns=["Event", "Start", "Apps hit", "Incidents", "Layer", "Root cause", "P1+P2",
                                     "LOBs", "Linked change"])
    g = x.groupby("Correlation_ID")
    out = pd.DataFrame({
        "Start": g["Open_Time"].min(),
        "Apps hit": g["App_ID"].nunique(),
        "Incidents": g.size(),
        "Layer": g["Affected_Layer"].agg(lambda s: s.value_counts().index[0]),
        "Root cause": g["RCA_Category"].agg(lambda s: s.value_counts().index[0]),
        "P1+P2": g["Severity"].apply(lambda s: s.isin(["P1", "P2"]).sum()),
        "LOBs": g["LOB"].agg(lambda s: ", ".join(sorted(set(s))[:4]) + (" …" if s.nunique() > 4 else "")),
        "Linked change": g["Related_CR_ID"].agg(lambda s: s.dropna().iloc[0] if s.notna().any() else ""),
        "Shared component": g.apply(lambda d: _component(d), include_groups=False),
    })
    out.index.name = "Event"
    return out.sort_values(["Apps hit", "Incidents"], ascending=False).reset_index()


def _component(d: pd.DataFrame) -> str:
    layer = d["Affected_Layer"].value_counts().index[0]
    col = {"Database": "DB_Cluster", "Infrastructure": "Infra_Cluster"}.get(layer)
    if col and d[col].notna().any():
        top = d[col].value_counts()
        if top.iloc[0] >= max(2, len(d) * 0.6):
            return str(top.index[0])
    if d["Related_CR_ID"].notna().any():
        return "Change " + str(d["Related_CR_ID"].dropna().iloc[0])
    return "Network" if layer == "Network" else "Several"


def blast_radius(i: pd.DataFrame, layer: str, col: str, top: int = 6) -> pd.DataFrame:
    x = i[(i["Affected_Layer"] == layer) & i[col].notna()]
    x = x[~x[col].astype(str).str.startswith(("Vendor", "SAAS"))]
    g = x.groupby(col)
    return pd.DataFrame({"Incidents": g.size(), "Apps": g["App_ID"].nunique(),
                         "P1+P2": g["Severity"].apply(lambda s: s.isin(["P1", "P2"]).sum())}) \
        .sort_values(["Apps", "Incidents"], ascending=False).head(top)


def change_induced(ds: Data, p: Period) -> dict:
    i = incidents(ds, p)
    linked = i[i["Related_CR_ID"].notna()]
    r = ds.rel[in_period(ds.rel["Release_Date"], p)]
    done = r[r["Status"].isin(["Deployed", "Rolled Back"])]
    return dict(incidents=len(linked), p1p2=int(linked["Severity"].isin(["P1", "P2"]).sum()),
                changes=int(linked["Related_CR_ID"].nunique()), releases=len(done),
                rolled_back=int((done["Status"] == "Rolled Back").sum()))


# =============================================================================== today
def today_view(ds: Data, day: pd.Timestamp) -> dict:
    day = pd.Timestamp(day).normalize()
    month = pd.Timestamp(year=day.year, month=day.month, day=1)
    inc_month = ds.inc[(ds.inc["Date"] >= month) & (ds.inc["Date"] <= day)]
    per_app = inc_month.groupby("App_ID").size()
    hot = per_app.quantile(0.98) if len(per_app) else np.inf
    c = ds.cr[ds.cr["Date"] == day].copy()
    rel_ids = set(ds.rel["CR_ID"].dropna())
    c["Production release"] = np.where(c["CR_ID"].isin(rel_ids), "Yes", "No")
    c["Incidents this month"] = c["App_ID"].map(per_app).fillna(0).astype(int)
    flags = []
    for _, r in c.iterrows():
        f = []
        if r["Release_Type"] == "Emergency" and r["CAB_Approved"] == "No":
            f.append("Emergency without CAB")
        if r["Risk"] == "High":
            f.append("High risk")
        if r["Incidents this month"] >= max(hot, 8):
            f.append("Unstable app")
        if r["Tier"] == "Tier-1":
            f.append("Tier-1")
        flags.append(", ".join(f))
    c["Watch"] = pd.Series(flags, index=c.index, dtype=object).astype(str)
    c = c.sort_values("Planned_Start")
    i = ds.inc[ds.inc["Date"] == day]
    crit = i[i["Severity"].isin(["P1", "P2"])].sort_values("Open_Time", ascending=False)
    upcoming = ds.cr[(ds.cr["Date"] > day) & (ds.cr["Date"] <= day + pd.Timedelta(days=7))]
    return dict(changes=c, incidents=i, critical=crit, inc_month=inc_month, upcoming=upcoming,
                open_now=ds.inc[ds.inc["is_open"] & (ds.inc["Open_Time"] < day + pd.Timedelta(days=1))])


# =============================================================================== recommendations
def recommendations(ds: Data, asof: pd.Timestamp, top_n: int = 500) -> pd.DataFrame:
    """Same transparent rule as the simulator, recomputed for the apps and date in view."""
    if ds.apps.empty or ds.inc.empty:
        return pd.DataFrame()
    v = vulns_asof(ds.vul, asof)
    i = ds.inc[ds.inc["Date"] <= asof].copy()
    i["Date"] = i["Date"].dt.strftime("%Y-%m-%d")
    c = ds.cr[ds.cr["Date"] <= asof].copy()
    c["Date"] = c["Date"].dt.strftime("%Y-%m-%d")
    s = ds.sr[ds.sr["Date"] <= asof].copy()
    s["Date"] = s["Date"].dt.strftime("%Y-%m-%d")
    cfg = SimpleNamespace(end_date=pd.Timestamp(asof).date())
    out = make_recommendations(cfg, ds.apps, i, c, s, v, top_n=min(top_n, len(ds.apps)))
    return out[out["Risk_Score"] > 0]


# =============================================================================== headline
def headline(ds: Data, p: Period, prev: Period | None, t: dict) -> str:
    i = incidents(ds, p)
    if i.empty:
        return "No incidents in this period for the current selection."
    bits = []
    p1 = int((i.Severity == "P1").sum())
    if prev is not None:
        ip = incidents(ds, prev)
        p1p = int((ip.Severity == "P1").sum())
        chg = (len(i) / p.days - len(ip) / max(prev.days, 1)) / max(len(ip) / max(prev.days, 1), 1e-9) * 100 \
            if len(ip) else np.nan
        trend = "fell" if chg < 0 else "rose"
        bits.append(f"P1 incidents {'rose' if p1 > p1p else 'fell' if p1 < p1p else 'held'} to **{p1}** "
                    f"(from {p1p} in {prev.label})" + (f" while the daily incident rate {trend} "
                                                         f"{abs(chg):.1f}%" if not np.isnan(chg) else "") + ".")
    else:
        bits.append(f"**{indian(len(i))}** incidents, **{p1}** of them P1.")
    ev = shared_events(i)
    if not ev.empty:
        top4 = ev.head(4)
        lay = top4["Layer"].value_counts()
        if lay.iloc[0] >= 3:
            n = "All" if lay.iloc[0] == len(top4) else f"{lay.iloc[0]} of the"
            bits.append(f"{n} {len(top4)} largest multi-application events started in the "
                        f"**{lay.index[0].lower()}** layer.")
    av = availability(i, ds.apps, p)
    if not np.isnan(av):
        bits.append(f"Tier-1 availability is **{av:.2f}%** against a {t['availability']:.2f}% target.")
    return " ".join(bits)
