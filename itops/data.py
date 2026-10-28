"""Loading, normalising and filtering the IT operations workbook.

Works with the simulator's output and with the original sample format
(OneRun_Bank_IT_Operations_Dataset.xlsx): columns the sample lacks are derived or defaulted.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
import pandas as pd

SHEETS = ["Applications", "BusinessServices", "Incidents", "ServiceRequests", "ChangeRequests",
          "Vulnerabilities", "ProductionReleases", "AIRecommendations", "ExecutiveKPI"]
REQUIRED = ["Applications", "Incidents", "ServiceRequests", "ChangeRequests", "Vulnerabilities"]
APP_COLS = ["App_Name", "LOB", "Tier", "Criticality", "App_Type", "Hosting", "Database", "Support_Group",
            "DB_Cluster", "Infra_Cluster", "Vendor"]
SEV_SLA_MIN = {"P1": 240, "P2": 480, "P3": 1440, "P4": 4320}
VULN_SLA_DAYS = {"Critical": 15, "High": 30, "Medium": 90, "Low": 180}
COMPLETED = ["Implemented", "Failed", "Rolled Back"]
FAILED = ["Failed", "Rolled Back"]
OPEN_INC = ["In Progress", "Assigned", "On Hold - Vendor", "Open", "New"]


@dataclass
class Data:
    apps: pd.DataFrame
    services: pd.DataFrame
    inc: pd.DataFrame
    sr: pd.DataFrame
    cr: pd.DataFrame
    vul: pd.DataFrame
    rel: pd.DataFrame
    kpi: pd.DataFrame
    first_day: pd.Timestamp
    last_day: pd.Timestamp       # last day with incidents = "today" for live views
    notes: list


def _dt(s):
    return pd.to_datetime(s, errors="coerce")


def _nonblank(s: pd.Series) -> pd.Series:
    """Blank strings and NaN both count as missing."""
    return s.where(s.astype(str).str.strip().ne("") & s.notna())


def read_workbook(src) -> dict[str, pd.DataFrame]:
    if isinstance(src, (bytes, bytearray)):
        src = io.BytesIO(src)
    x = pd.ExcelFile(src)
    missing = [s for s in REQUIRED if s not in x.sheet_names]
    if missing:
        raise ValueError(f"Workbook is missing sheet(s): {', '.join(missing)}")
    return {s: pd.read_excel(x, s) for s in SHEETS if s in x.sheet_names}


def normalise(raw: dict[str, pd.DataFrame]) -> Data:
    notes = []
    apps = raw["Applications"].copy()
    if "App_Type" in apps:
        apps["App_Type"] = apps["App_Type"].replace({"Vendor": "3rd Party"})
    for c, default in [("DB_Cluster", None), ("Infra_Cluster", None), ("Vendor", "Unknown"),
                       ("Hosting", "Unknown"), ("Database", "Unknown"), ("Support_Group", "Unknown"),
                       ("Criticality", "Unknown"), ("App_Name", None)]:
        if c not in apps:
            apps[c] = default
    if apps["DB_Cluster"].isna().all():
        apps["DB_Cluster"] = apps["Database"].astype(str) + " (shared)"
        notes.append("No DB cluster column: incidents are grouped by database product instead.")
    if apps["Infra_Cluster"].isna().all():
        apps["Infra_Cluster"] = apps["Hosting"].astype(str) + " (shared)"
    apps["App_Name"] = apps["App_Name"].fillna(apps["App_ID"])
    if "Availability_SLA" not in apps:
        apps["Availability_SLA"] = apps["Tier"].map({"Tier-1": 99.95, "Tier-2": 99.9, "Tier-3": 99.5})
    services = raw.get("BusinessServices", pd.DataFrame(columns=["Service_ID", "Service_Name", "LOB", "Criticality"]))
    a = apps.set_index("App_ID")[APP_COLS]

    def attach(df):
        df = df.drop(columns=[c for c in APP_COLS if c in df.columns])
        return df.join(a, on="App_ID")

    # ---------------------------------------------------------------- incidents
    inc = raw["Incidents"].copy()
    inc["Date"] = _dt(inc["Date"])
    if "Open_Time" in inc:
        inc["Open_Time"] = _dt(inc["Open_Time"])
    else:
        inc["Open_Time"] = inc["Date"] + pd.Timedelta(hours=9)
        notes.append("Incidents have no open time: 09:00 assumed.")
    inc["Open_Time"] = inc["Open_Time"].fillna(inc["Date"])
    if "Acknowledge_Min" not in inc:
        inc["Acknowledge_Min"] = np.nan
        notes.append("Incidents have no acknowledge time: MTTA is not available.")
    if "Status" not in inc:
        inc["Status"] = "Closed"
    if "Resolved_Time" in inc:
        inc["Resolved_Time"] = _dt(_nonblank(inc["Resolved_Time"]))
    else:
        inc["Resolved_Time"] = inc["Open_Time"] + pd.to_timedelta(inc["Duration_Min"], "m")
    if "SLA_Breached" not in inc:
        inc["SLA_Breached"] = np.where(inc["Duration_Min"] > inc["Severity"].map(SEV_SLA_MIN), "Yes", "No")
    for c, d in [("Correlation_ID", np.nan), ("Related_CR_ID", np.nan), ("Detected_By", "Unknown"),
                 ("Customers_Impacted", 0), ("Reopened", "No")]:
        if c not in inc:
            inc[c] = d
    inc["Correlation_ID"] = _nonblank(inc["Correlation_ID"])
    inc["Related_CR_ID"] = _nonblank(inc["Related_CR_ID"])
    inc["is_open"] = inc["Status"].isin(OPEN_INC)
    inc = attach(inc)

    # ---------------------------------------------------------------- service requests
    sr = raw["ServiceRequests"].copy()
    sr["Date"] = _dt(sr["Date"])
    if "SLA_Hours" not in sr:
        sr["SLA_Hours"] = 48.0
    if "SLA_Met" not in sr:
        sr["SLA_Met"] = np.where(sr["Resolution_Hours"] <= sr["SLA_Hours"], "Yes", "No")
    if "Status" not in sr:
        sr["Status"] = "Fulfilled"
    sr = attach(sr)

    # ---------------------------------------------------------------- changes
    cr = raw["ChangeRequests"].copy()
    cr["Date"] = _dt(cr["Date"])
    for c, d in [("Change_Category", "Application"), ("CAB_Approved", "Yes")]:
        if c not in cr:
            cr[c] = d
    cr["Planned_Start"] = _dt(cr["Planned_Start"]) if "Planned_Start" in cr else cr["Date"] + pd.Timedelta(hours=22)
    cr["Planned_End"] = _dt(cr["Planned_End"]) if "Planned_End" in cr else cr["Planned_Start"] + pd.Timedelta(hours=2)
    cr = attach(cr)

    # ---------------------------------------------------------------- vulnerabilities
    vul = raw["Vulnerabilities"].copy()
    if "Discovered_Date" in vul:
        vul["Discovered_Date"] = _dt(vul["Discovered_Date"])
    else:
        vul["Discovered_Date"] = inc["Date"].min()
        notes.append("Vulnerabilities have no dates: ageing and remediation KPIs are not available.")
    if "Due_Date" in vul:
        vul["Due_Date"] = _dt(vul["Due_Date"])
    else:
        vul["Due_Date"] = vul["Discovered_Date"] + pd.to_timedelta(vul["Severity"].map(VULN_SLA_DAYS), "D")
    vul["Closed_Date"] = _dt(_nonblank(vul["Closed_Date"])) if "Closed_Date" in vul else pd.NaT
    vul = attach(vul)

    # ---------------------------------------------------------------- releases
    rel = raw.get("ProductionReleases", pd.DataFrame(columns=["Release_ID", "Release_Date", "App_ID", "Risk_Level"])).copy()
    rel["Release_Date"] = _dt(rel["Release_Date"])
    for c, d in [("CR_ID", np.nan), ("Status", "Scheduled"), ("Release_Window", ""), ("Release_Type", "")]:
        if c not in rel:
            rel[c] = d
    rel = attach(rel)

    kpi = raw.get("ExecutiveKPI", pd.DataFrame())
    if "Date" in kpi:
        kpi = kpi.copy()
        kpi["Date"] = _dt(kpi["Date"])

    first_day = inc["Date"].min().normalize()
    last_day = inc["Date"].max().normalize()
    return Data(apps, services, inc, sr, cr, vul, rel, kpi, first_day, last_day, notes)


# =============================================================================== periods
def fy_of(d: pd.Timestamp) -> int:
    return d.year + (1 if d.month >= 4 else 0)


def fy_quarter_start(d: pd.Timestamp) -> pd.Timestamp:
    """First day of the Indian financial-year quarter (Apr, Jul, Oct, Jan) containing d."""
    start = pd.Timestamp(year=d.year, month=d.month, day=1)
    while (start.month - 4) % 3 != 0:
        start = start - pd.DateOffset(months=1)
    return start


@dataclass
class Period:
    label: str
    start: pd.Timestamp
    end: pd.Timestamp          # inclusive (a day)

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def period_options(view: str, first: pd.Timestamp, last: pd.Timestamp) -> list[Period]:
    out = []
    if view == "Monthly":
        m = pd.Timestamp(year=last.year, month=last.month, day=1)
        while m >= pd.Timestamp(year=first.year, month=first.month, day=1):
            end = min(m + pd.offsets.MonthEnd(0), last)
            label = m.strftime("%b %Y") + (" (to date)" if end < m + pd.offsets.MonthEnd(0) else "")
            out.append(Period(label, max(m, first), end))
            m = m - pd.DateOffset(months=1)
    elif view == "Quarterly":
        q = fy_quarter_start(last)
        while q + pd.DateOffset(months=3) > first:
            q_end = q + pd.DateOffset(months=3) - pd.Timedelta(days=1)
            end = min(q_end, last)
            n = ((q.month - 4) % 12) // 3 + 1
            lbl = f"FY{fy_of(q) % 100:02d} Q{n} ({q:%b}–{q_end:%b %Y})"
            if end < q_end:
                lbl += " to date"
            if q < first:
                lbl += f" from {first:%d %b}"
            out.append(Period(lbl, max(q, first), end))
            q = q - pd.DateOffset(months=3)
    else:
        out.append(Period(f"Last 12 months ({first:%b %Y} – {last:%b %Y})", first, last))
        fy = fy_of(last)
        while True:
            s = pd.Timestamp(year=fy - 1, month=4, day=1)
            e = pd.Timestamp(year=fy, month=3, day=31)
            if e < first:
                break
            lbl = f"FY{fy - 1}-{fy % 100:02d}"
            if s < first or e > last:
                lbl += " (partial)"
            out.append(Period(lbl, max(s, first), min(e, last)))
            fy -= 1
    return out


def previous_period(view: str, p: Period, first: pd.Timestamp) -> Period | None:
    if view == "Monthly":
        s = p.start.replace(day=1) - pd.DateOffset(months=1)
        e = s + pd.offsets.MonthEnd(0)
    elif view == "Quarterly":
        s = fy_quarter_start(p.start) - pd.DateOffset(months=3)
        e = s + pd.DateOffset(months=3) - pd.Timedelta(days=1)
    else:
        return None
    if e < first:
        return None
    if view == "Quarterly":
        n = ((s.month - 4) % 12) // 3 + 1
        return Period(f"FY{fy_of(s) % 100:02d} Q{n}", max(s, first), e)
    return Period(f"{s:%b %Y}", max(s, first), e)


def in_period(s: pd.Series, p: Period) -> pd.Series:
    return (s >= p.start) & (s < p.end + pd.Timedelta(days=1))


# =============================================================================== filters
def filter_apps(apps: pd.DataFrame, lob: str, tier: str, app_type: str) -> pd.DataFrame:
    a = apps
    if lob != "All LOBs":
        a = a[a["LOB"] == lob]
    if tier != "All tiers":
        a = a[a["Tier"] == tier]
    if app_type != "All types":
        a = a[a["App_Type"] == app_type]
    return a


def scope(d: Data, apps: pd.DataFrame) -> Data:
    ids = set(apps["App_ID"])
    f = lambda df: df[df["App_ID"].isin(ids)]  # noqa: E731
    return Data(apps, d.services, f(d.inc), f(d.sr), f(d.cr), f(d.vul), f(d.rel), d.kpi,
                d.first_day, d.last_day, d.notes)
