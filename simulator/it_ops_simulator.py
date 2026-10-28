"""OneRun Bank IT Operations: synthetic data simulator.

Creates one year of IT operations data for a bank with ~1,000 applications, in the same
sheets and columns as the sample OneRun_Bank_IT_Operations_Dataset.xlsx, plus extra
columns the dashboard needs (times, correlation groups, change links, SLA fields).

    python it_ops_simulator.py                       # 12 months ending today
    python it_ops_simulator.py --end-date 2025-12-31 # calendar year 2025
    python it_ops_simulator.py --apps 1500 --incidents 20000 --seed 7 --out my_bank.xlsx

Everything is synthetic: app, vendor and service names are invented, and the vulnerability
IDs use a SIM- prefix so they cannot be mistaken for real CVE records.
"""
from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

# =============================================================================== reference data
LOBS = {  # LOB: (weight of apps, support group, short name)
    "Deposits": (7, "Core Banking", "DEP"),
    "Loans": (7, "Core Banking", "LON"),
    "Lease": (3, "Core Banking", "LSE"),
    "Mortgage": (5, "Core Banking", "MTG"),
    "Cards": (6, "Cards & Payments", "CRD"),
    "Payments": (7, "Cards & Payments", "PAY"),
    "UPI": (4, "Cards & Payments", "UPI"),
    "Treasury": (5, "Treasury & Markets", "TRS"),
    "Wealth": (5, "Wealth & Insurance", "WLT"),
    "Corporate Banking": (6, "Corporate Banking", "CBK"),
    "Branch": (6, "Branch & Channels", "BRN"),
    "Digital Banking": (6, "Digital", "DIG"),
    "Mobile Banking": (5, "Digital", "MOB"),
    "Internet Banking": (4, "Digital", "NET"),
    "AML": (3, "Risk & Compliance", "AML"),
    "Fraud": (3, "Risk & Compliance", "FRD"),
    "Compliance": (4, "Risk & Compliance", "CMP"),
    "CRM": (4, "Enterprise", "CRM"),
    "Data Lake": (4, "Data & Analytics", "DLK"),
    "HR & Finance": (4, "Enterprise", "HRF"),
}

COMPONENTS = {
    "Deposits": ["Core Deposits Ledger", "Term Deposit Engine", "Interest Accrual", "Account Opening",
                 "Statement Service", "Dormancy Manager", "Sweep Engine", "Cheque Processing", "Standing Instructions"],
    "Loans": ["Loan Origination", "Loan Servicing", "Credit Scoring", "Collections", "EMI Scheduler",
              "Gold Loan", "Personal Loan Portal", "Loan Document Vault", "Disbursement Engine"],
    "Lease": ["Lease Origination", "Asset Register", "Lease Billing", "Residual Value Engine", "Fleet Lease Portal"],
    "Mortgage": ["Home Loan Origination", "Property Valuation", "Mortgage Servicing", "Escrow Manager",
                 "Title Verification", "Pre-approval Portal"],
    "Cards": ["Card Management", "Card Authorisation", "Rewards Engine", "Card Issuance", "Chargeback Manager",
              "Card Statement", "Merchant Acquiring"],
    "Payments": ["NEFT Gateway", "RTGS Gateway", "IMPS Switch", "SWIFT Interface", "Payment Hub",
                 "Bulk Payments", "Bill Payments", "NACH Mandates"],
    "UPI": ["UPI Switch", "UPI Collect", "UPI Mandates", "UPI Dispute Manager", "VPA Registry"],
    "Treasury": ["Treasury Front Office", "ALM Engine", "FX Dealing", "Money Market", "Liquidity Monitor",
                 "Treasury Settlements", "Market Data Feed"],
    "Wealth": ["Portfolio Manager", "Mutual Fund Platform", "Insurance Sales", "Advisory Portal",
               "Demat Gateway", "Wealth Reporting"],
    "Corporate Banking": ["Trade Finance", "Cash Management", "Supply Chain Finance", "Corporate Portal",
                          "Letter of Credit", "Virtual Accounts"],
    "Branch": ["Teller System", "Branch Queue Manager", "Cash Vault", "Branch Reporting", "Passbook Printer Service",
               "Branch Onboarding"],
    "Digital Banking": ["API Gateway", "Digital Onboarding", "eKYC Service", "Notification Hub", "Chatbot",
                        "Digital Lending Journey", "Open Banking APIs"],
    "Mobile Banking": ["Retail Mobile App", "Mobile Auth Service", "Mobile Payments", "Push Messaging",
                       "Mobile Card Controls"],
    "Internet Banking": ["Retail Net Banking", "Corporate Net Banking", "Login & SSO", "Beneficiary Manager"],
    "AML": ["Transaction Monitoring", "Sanctions Screening", "Case Manager", "CTR/STR Reporting", "KYC Risk Rating"],
    "Fraud": ["Real-time Fraud Engine", "Device Fingerprinting", "Fraud Case Manager", "Mule Account Detection"],
    "Compliance": ["Regulatory Reporting", "XBRL Filing", "Audit Trail", "Policy Manager", "Basel Capital Calculator"],
    "CRM": ["Customer 360", "Lead Manager", "Contact Centre", "Complaint Manager", "Campaign Engine"],
    "Data Lake": ["Enterprise Data Lake", "ETL Orchestrator", "MIS Reports", "Data Quality Engine",
                  "Customer Analytics", "Streaming Platform"],
    "HR & Finance": ["General Ledger", "Payroll", "HRMS", "Procurement", "Expense Manager", "Fixed Assets"],
}
QUALIFIERS = ["", "API", "Batch", "Portal", "Adapter", "Reports", "Engine", "Service", "Gateway", "UI"]

VENDORS = ["Nimbus FinTech", "Kaveri Systems", "Blue Lotus Software", "Arcadia Core Labs", "Tejas Digital",
           "Saffron Cloud", "Indigo Ledger Co", "Monsoon Analytics", "Peak Payments Ltd", "Orion RegTech"]
SAAS_VENDORS = ["CloudDesk CRM", "SkyHR Suite", "LedgerCloud", "ComplyCloud", "TalkWave Contact", "DataNest SaaS"]

APP_TYPES = ["InHouse", "3rd Party", "SaaS"]
DATABASES = ["Oracle", "Postgres", "SQL Server", "DB2", "MongoDB"]
RCA = {  # RCA category: (weight, layer distribution)
    "Application Defect": (18, {"Application": 0.85, "Packaging": 0.15}),
    "Release Defect": (9, {"Packaging": 0.6, "Application": 0.4}),
    "Configuration Error": (9, {"Application": 0.4, "Infrastructure": 0.3, "Packaging": 0.3}),
    "Database Failure": (8, {"Database": 1.0}),
    "Capacity / Performance": (9, {"Infrastructure": 0.45, "Database": 0.35, "Application": 0.2}),
    "Infrastructure Outage": (7, {"Infrastructure": 0.9, "Network": 0.1}),
    "Connectivity Issue": (9, {"Network": 0.8, "Infrastructure": 0.2}),
    "Vendor Defect": (7, {"Application": 0.7, "Packaging": 0.3}),
    "Human Error": (6, {"Application": 0.3, "Database": 0.3, "Infrastructure": 0.2, "Packaging": 0.2}),
    "Source Data Issue": (8, {"Data": 0.8, "Database": 0.2}),
    "Batch Job Failure": (6, {"Data": 0.5, "Application": 0.3, "Database": 0.2}),
    "Certificate Expiry": (2, {"Infrastructure": 0.6, "Network": 0.4}),
    "Security Event": (2, {"Network": 0.5, "Application": 0.5}),
}
SEVERITIES = ["P1", "P2", "P3", "P4"]
SEV_SLA_MIN = {"P1": 240, "P2": 480, "P3": 1440, "P4": 4320}  # resolution SLA
SR_CATS = {  # category: (weight, median hours, SLA hours)
    "Access": (24, 8, 24), "Password Reset": (18, 1.5, 4), "Data Fix": (16, 30, 72),
    "API Access": (8, 20, 48), "Report Request": (10, 24, 72), "Environment Request": (6, 60, 120),
    "Batch Rerun": (8, 3, 8), "Certificate Renewal": (4, 16, 48), "Firewall Rule": (6, 30, 72),
}
CR_TYPES = {"Standard": 34, "Minor": 30, "Major": 14, "Emergency": 10, "Regulatory": 6, "Security Patch": 6}
CHANGE_CATS = {"Application": 46, "Database": 14, "Infrastructure": 18, "Packaging": 14, "Network": 8}
VULN_SLA_DAYS = {"Critical": 15, "High": 30, "Medium": 90, "Low": 180}
VULN_SOURCES = ["Infra Scanner", "App Scanner (DAST)", "Code Scan (SAST)", "Pen Test", "Vendor Advisory",
                "Container Scan"]
VULN_LAYERS = ["OS", "Database", "Middleware", "Open-source Library", "Container Image", "Web Server", "Network Device"]


@dataclass
class Config:
    end_date: dt.date
    apps: int = 1000
    incidents: int = 15000
    srs: int = 8000
    crs: int = 4000
    vulns: int = 3000
    releases: int = 1500
    seed: int = 42
    bank: str = "OneRun Bank"
    forward_days: int = 14        # scheduled changes/releases after end_date (for "today" views)


# =============================================================================== helpers
def wchoice(rng, d: dict, size=None):
    keys = list(d)
    w = np.array([v[0] if isinstance(v, tuple) else v for v in d.values()], float)
    return rng.choice(keys, size=size, p=w / w.sum())


def fy_label(d: pd.Series) -> pd.Series:
    """Indian financial year label: Apr 2025-Mar 2026 -> FY2026."""
    return "FY" + (d.dt.year + (d.dt.month >= 4).astype(int)).astype(str)


def add_period_cols(df: pd.DataFrame, col: str) -> pd.DataFrame:
    d = pd.to_datetime(df[col])
    df["Year"] = d.dt.year
    df["Month"] = d.dt.month
    df["Quarter"] = d.dt.quarter
    df["Month_Name"] = d.dt.strftime("%b-%Y")
    df["FY"] = fy_label(d)
    df["FY_Quarter"] = df["FY"] + "-Q" + (((d.dt.month - 4) % 12) // 3 + 1).astype(str)
    return df


def day_weights(days: pd.DatetimeIndex) -> np.ndarray:
    """Weekdays busier, month-end and quarter-end spikes, a few holiday-season peaks."""
    w = np.where(days.dayofweek < 5, 1.15, 0.7)
    month_end = (days.day >= 28) | (days.day <= 2)
    w = w * np.where(month_end, 1.35, 1.0)
    qe = month_end & days.month.isin([3, 6, 9, 12])
    w = w * np.where(qe, 1.2, 1.0)
    festive = days.month.isin([10, 11]) & (days.day >= 15)       # festive-season load
    return w * np.where(festive, 1.15, 1.0)


# =============================================================================== applications
def make_apps(cfg: Config, rng) -> tuple[pd.DataFrame, pd.DataFrame]:
    lob_w = np.array([v[0] for v in LOBS.values()], float)
    lobs = rng.choice(list(LOBS), size=cfg.apps, p=lob_w / lob_w.sum())
    rows, used = [], set()
    n_db = {"Oracle": 10, "Postgres": 8, "SQL Server": 6, "DB2": 3, "MongoDB": 4}
    for k, lob in enumerate(lobs, 1):
        comp = rng.choice(COMPONENTS[lob])
        q = rng.choice(QUALIFIERS)
        name = comp if (not q or q in comp.split()) else f"{comp} {q}"
        base, n = name, 2
        while name in used:
            name = f"{base} {n}"
            n += 1
        used.add(name)
        core = lob in ("Deposits", "Loans", "Payments", "UPI", "Cards", "Treasury", "Mobile Banking",
                       "Internet Banking", "Digital Banking")
        tier = rng.choice(["Tier-1", "Tier-2", "Tier-3"], p=[0.30, 0.40, 0.30] if core else [0.08, 0.37, 0.55])
        crit = {"Tier-1": rng.choice(["Critical", "High"], p=[0.8, 0.2]),
                "Tier-2": rng.choice(["High", "Medium"], p=[0.6, 0.4]),
                "Tier-3": rng.choice(["Medium", "Low"], p=[0.6, 0.4])}[tier]
        saas_lob = lob in ("CRM", "HR & Finance", "Compliance", "Data Lake")
        app_type = rng.choice(APP_TYPES, p=[0.30, 0.35, 0.35] if saas_lob else [0.45, 0.42, 0.13])
        hosting = "Cloud" if app_type == "SaaS" else rng.choice(["OnPrem", "Cloud", "Hybrid"], p=[0.55, 0.30, 0.15])
        db = rng.choice(DATABASES, p=[0.38, 0.24, 0.20, 0.10, 0.08])
        if app_type == "SaaS":
            vendor = rng.choice(SAAS_VENDORS)
        elif app_type == "3rd Party":
            vendor = rng.choice(VENDORS)
        else:
            vendor = "In-house"
        db_cluster = f"{db[:3].upper()}-CL{rng.integers(1, n_db[db] + 1):02d}"
        if hosting == "Cloud":
            infra = f"CLOUD-{rng.choice(['EKS', 'AKS', 'VM'])}-{rng.integers(1, 7):02d}"
        else:
            infra = f"DC{rng.integers(1, 3)}-{rng.choice(['VMW', 'AIX', 'LNX'])}-{rng.integers(1, 9):02d}"
        if app_type == "SaaS":
            db_cluster, infra = "Vendor-managed", f"SAAS-{vendor.split()[0].upper()}"
        rows.append(dict(
            App_ID=f"APP{k:04d}", Bank=cfg.bank, App_Name=name, LOB=lob, Tier=tier, Criticality=crit,
            App_Type=app_type, Hosting=hosting, Database=db, Support_Group=LOBS[lob][1],
            Vendor=vendor, DB_Cluster=db_cluster, Infra_Cluster=infra,
            Availability_SLA=float({"Tier-1": 99.95, "Tier-2": 99.9, "Tier-3": 99.5}[tier]),
            RTO_Hrs=int({"Tier-1": 2, "Tier-2": 8, "Tier-3": 24}[tier]),
            Go_Live_Year=int(rng.integers(2006, cfg.end_date.year + 1)),
            App_Owner=f"{LOBS[lob][2]} Product Owner {rng.integers(1, 9)}",
        ))
    apps = pd.DataFrame(rows)

    # business services: 6 per LOB, apps mapped to one service of their LOB
    svc_rows, svc_of = [], {}
    sid = 1
    for lob in LOBS:
        comps = COMPONENTS[lob][:6]
        for c in comps:
            svc_rows.append(dict(Service_ID=f"SVC{sid:03d}", Service_Name=f"{c} Service", LOB=lob,
                                 Criticality=rng.choice(["High", "Medium", "Low"], p=[0.45, 0.4, 0.15])))
            sid += 1
    services = pd.DataFrame(svc_rows)
    for idx, r in apps.iterrows():
        cands = services[services.LOB == r.LOB].Service_ID.values
        svc_of[idx] = rng.choice(cands)
    apps["Service_ID"] = pd.Series(svc_of)
    # propensity: a few problem apps generate a large share of tickets
    tier_mult = apps.Tier.map({"Tier-1": 1.6, "Tier-2": 1.0, "Tier-3": 0.6}).values
    type_mult = apps.App_Type.map({"InHouse": 1.15, "3rd Party": 1.0, "SaaS": 0.55}).values
    age_mult = 1 + np.clip(cfg.end_date.year - apps.Go_Live_Year.values, 0, 20) / 25
    apps["_prop"] = rng.lognormal(0, 0.8, len(apps)) * tier_mult * type_mult * age_mult
    return apps, services


# =============================================================================== changes & releases
def make_changes(cfg: Config, rng, apps: pd.DataFrame, days: pd.DatetimeIndex):
    n_fwd = int(cfg.crs * cfg.forward_days / 365)
    all_days = days.append(pd.date_range(days[-1] + pd.Timedelta(days=1), periods=cfg.forward_days))
    w = np.where(all_days.dayofweek < 5, 1.0, 1.4)          # weekend change windows
    w = w * np.where((all_days.day >= 26) | (all_days.day <= 3), 0.6, 1.0)   # month-end freeze
    n = cfg.crs + n_fwd
    dates = rng.choice(all_days, size=n, p=w / w.sum())
    app_idx = rng.choice(len(apps), size=n, p=apps._prop.values / apps._prop.sum())
    a = apps.iloc[app_idx].reset_index(drop=True)
    rtype = wchoice(rng, CR_TYPES, n)
    risk = np.where(np.isin(rtype, ["Major", "Emergency"]), rng.choice(["High", "Medium"], n, p=[0.6, 0.4]),
                    rng.choice(["High", "Medium", "Low"], n, p=[0.12, 0.38, 0.5]))
    ccat = wchoice(rng, CHANGE_CATS, n)
    start_hr = np.where(rtype == "Emergency", rng.integers(0, 24, n), rng.choice([21, 22, 23, 0, 1], n))
    start = pd.to_datetime(dates) + pd.to_timedelta(start_hr, "h") + pd.to_timedelta(rng.choice([0, 30], n), "m")
    dur_h = np.where(np.isin(rtype, ["Major", "Regulatory"]), rng.integers(3, 7, n), rng.integers(1, 4, n))
    end = start + pd.to_timedelta(dur_h, "h")
    future = pd.to_datetime(dates) > pd.Timestamp(cfg.end_date)
    today = pd.to_datetime(dates) == pd.Timestamp(cfg.end_date)
    # failure probability by type, risk, tier and app quality
    p_fail = (0.025 + np.select([rtype == "Emergency", rtype == "Major"], [0.06, 0.035], 0.0)
              + np.select([risk == "High", risk == "Medium"], [0.025, 0.01], 0.0)
              + np.where(a.App_Type.values == "InHouse", 0.01, 0.0)
              + np.clip(a._prop.values / a._prop.mean() - 1, 0, 3) * 0.01)
    u = rng.random(n)
    status = np.where(u < p_fail * 0.65, "Failed", np.where(u < p_fail, "Rolled Back", "Implemented"))
    cancel = rng.random(n) < 0.03
    status = np.where(cancel, "Cancelled", status)
    status = np.where(future | today, np.where(rng.random(n) < 0.9, "Approved", "Pending CAB"), status)
    cab = np.where(rtype == "Emergency", rng.choice(["Yes", "No"], n, p=[0.55, 0.45]), "Yes")
    cr = pd.DataFrame(dict(
        CR_ID=[f"CR{k:05d}" for k in range(1, n + 1)],
        Date=pd.to_datetime(dates).strftime("%Y-%m-%d"),
        App_ID=a.App_ID.values, Release_Type=rtype, Risk=risk, Status=status,
        Change_Category=ccat,
        Planned_Start=start.strftime("%Y-%m-%d %H:%M"), Planned_End=end.strftime("%Y-%m-%d %H:%M"),
        CAB_Approved=cab, Implementer_Group=a.Support_Group.values,
        LOB=a.LOB.values, Tier=a.Tier.values,
    ))
    cr = cr.sort_values(["Date", "Planned_Start"]).reset_index(drop=True)
    cr["CR_ID"] = [f"CR{k:05d}" for k in range(1, len(cr) + 1)]

    # production releases: the deployable subset of non-standard changes
    rel_mask = cr.Release_Type.isin(["Minor", "Major", "Regulatory", "Emergency", "Security Patch"]) & \
        cr.Change_Category.isin(["Application", "Packaging", "Database"]) & (cr.Status != "Cancelled")
    rel_src = cr[rel_mask]
    n_rel_hist = min(cfg.releases, int((rel_src.Date <= str(cfg.end_date)).sum()))
    hist = rel_src[rel_src.Date <= str(cfg.end_date)].sample(n_rel_hist, random_state=cfg.seed)
    fwd = rel_src[rel_src.Date > str(cfg.end_date)]
    tod = rel_src[rel_src.Date == str(cfg.end_date)]
    rel = pd.concat([hist, fwd, tod]).drop_duplicates("CR_ID").sort_values("Planned_Start").reset_index(drop=True)
    rel_status = np.select([rel.Status.isin(["Failed", "Rolled Back"]), rel.Status == "Implemented"],
                           ["Rolled Back", "Deployed"], "Scheduled")
    releases = pd.DataFrame(dict(
        Release_ID=[f"REL{k:05d}" for k in range(1, len(rel) + 1)],
        Release_Date=rel.Date.values, App_ID=rel.App_ID.values, Risk_Level=rel.Risk.values,
        CR_ID=rel.CR_ID.values, Release_Type=rel.Release_Type.values,
        Release_Window=[f"{s[-5:]}–{e[-5:]}" for s, e in zip(rel.Planned_Start, rel.Planned_End)],
        Components=rng.integers(1, 12, len(rel)), Status=rel_status,
        LOB=rel.LOB.values, Tier=rel.Tier.values,
    ))
    return cr, releases


# =============================================================================== incidents
def make_incidents(cfg: Config, rng, apps: pd.DataFrame, cr: pd.DataFrame, days: pd.DatetimeIndex):
    rows = []
    corr_n = 0
    prop = apps._prop.values / apps._prop.sum()
    end_ts = pd.Timestamp(cfg.end_date) + pd.Timedelta(hours=9)          # "now" = 9 am on end date

    def sev_for(tier, boost=0.0):
        base = {"Tier-1": [0.04, 0.14, 0.38, 0.44], "Tier-2": [0.015, 0.08, 0.37, 0.535],
                "Tier-3": [0.005, 0.04, 0.32, 0.635]}[tier]
        p = np.array(base) + np.array([boost * 0.5, boost, 0, -boost * 1.5])
        p = np.clip(p, 0.001, None)
        return rng.choice(SEVERITIES, p=p / p.sum())

    def add(app, ts, rca, layer, sev, corr=None, cr_id=None, detected=None):
        rows.append(dict(app=app, ts=ts, rca=rca, layer=layer, sev=sev, corr=corr, cr=cr_id,
                         det=detected or rng.choice(["Monitoring", "User Reported", "Service Desk", "Vendor"],
                                                    p=[0.52, 0.28, 0.14, 0.06])))

    # 1) shared-component events: a DB cluster, infra cluster or network outage hits many apps at once
    shared = apps[apps.DB_Cluster != "Vendor-managed"]
    n_events = max(20, cfg.incidents // 60)
    dw = day_weights(days)
    ev_days = rng.choice(days, size=n_events, p=dw / dw.sum())
    for d in ev_days:
        corr_n += 1
        kind = rng.choice(["Database", "Infrastructure", "Network"], p=[0.45, 0.35, 0.20])
        ts = pd.Timestamp(d) + pd.Timedelta(minutes=int(rng.integers(0, 1440)))
        if kind == "Database":
            cl = rng.choice(shared.DB_Cluster.unique())
            members = shared[shared.DB_Cluster == cl]
            rca = rng.choice(["Database Failure", "Capacity / Performance", "Human Error"], p=[0.65, 0.25, 0.10])
        elif kind == "Infrastructure":
            cl = rng.choice(shared.Infra_Cluster.unique())
            members = shared[shared.Infra_Cluster == cl]
            rca = rng.choice(["Infrastructure Outage", "Capacity / Performance", "Certificate Expiry"],
                             p=[0.7, 0.2, 0.1])
        else:
            members = shared.sample(int(rng.integers(4, 18)), random_state=int(rng.integers(1e9)))
            rca = rng.choice(["Connectivity Issue", "Certificate Expiry"], p=[0.85, 0.15])
        hit = members.sample(min(len(members), int(rng.integers(3, 16))), random_state=int(rng.integers(1e9)))
        cid = f"COR{corr_n:04d}"
        for _, a in hit.iterrows():
            add(a.App_ID, ts + pd.Timedelta(minutes=int(rng.integers(0, 25))), rca, kind,
                sev_for(a.Tier, 0.06), corr=cid, detected="Monitoring")

    # 2) change-induced incidents: failed or rolled-back changes, plus a few "successful" ones
    past = cr[cr.Status.isin(["Implemented", "Failed", "Rolled Back"])].copy()
    bad = past[past.Status.isin(["Failed", "Rolled Back"])]
    lucky = past[past.Status == "Implemented"].sample(frac=0.02, random_state=cfg.seed)
    app_lookup = apps.set_index("App_ID")
    for src, k_rng in ((bad, (1, 5)), (lucky, (1, 2))):
        for _, c in src.iterrows():
            a = app_lookup.loc[c.App_ID]
            base = pd.Timestamp(c.Planned_End)
            cid = None
            n_inc = int(rng.integers(*k_rng))
            if n_inc > 1:
                corr_n += 1
                cid = f"COR{corr_n:04d}"
            for _ in range(n_inc):
                ts = base + pd.Timedelta(minutes=int(rng.integers(5, 36 * 60)))
                if ts > end_ts:
                    continue
                layer = {"Database": "Database", "Infrastructure": "Infrastructure", "Network": "Network",
                         "Packaging": "Packaging"}.get(c.Change_Category, rng.choice(["Application", "Packaging"]))
                rca = rng.choice(["Release Defect", "Configuration Error", "Vendor Defect"]
                                 if a.App_Type != "InHouse" else ["Release Defect", "Configuration Error",
                                                                   "Application Defect"], p=[0.6, 0.3, 0.1])
                add(c.App_ID, ts, rca, layer, sev_for(a.Tier, 0.04), corr=cid, cr_id=c.CR_ID)

    # 3) everyday independent incidents to reach the target volume
    n_rest = max(0, cfg.incidents - len(rows))
    d_idx = rng.choice(len(days), size=n_rest, p=dw / dw.sum())
    a_idx = rng.choice(len(apps), size=n_rest, p=prop)
    rcas = list(RCA)
    rca_w = np.array([RCA[r][0] for r in rcas], float)
    rca_pick = rng.choice(rcas, size=n_rest, p=rca_w / rca_w.sum())
    hw = np.array([1, 1, 1, 1, 1, 2, 3, 4, 6, 7, 7, 7, 6, 6, 6, 6, 6, 6, 5, 4, 3, 2, 2, 1], float)
    hours = rng.choice(24, size=n_rest, p=hw / hw.sum())
    for di, ai, rc, hr in zip(d_idx, a_idx, rca_pick, hours):
        a = apps.iloc[ai]
        layers = RCA[rc][1]
        layer = rng.choice(list(layers), p=list(layers.values()))
        ts = pd.Timestamp(days[di]) + pd.Timedelta(hours=int(hr), minutes=int(rng.integers(0, 60)))
        if ts > end_ts:
            ts = end_ts - pd.Timedelta(minutes=int(rng.integers(5, 500)))
        add(a.App_ID, ts, rc, layer, sev_for(a.Tier))

    inc = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    n = len(inc)
    ack_med = {"P1": 4, "P2": 10, "P3": 35, "P4": 90}
    res_med = {"P1": 150, "P2": 320, "P3": 900, "P4": 2400}
    ack = np.array([max(1, rng.lognormal(np.log(ack_med[s]), 0.6)) for s in inc.sev]).round().astype(int)
    dur = np.array([max(10, rng.lognormal(np.log(res_med[s]), 0.75)) for s in inc.sev]).round().astype(int)
    opened = pd.to_datetime(inc.ts)
    resolved = opened + pd.to_timedelta(dur, "m")
    is_open = resolved > end_ts
    status = np.where(is_open, rng.choice(["In Progress", "Assigned", "On Hold - Vendor"], n, p=[0.6, 0.3, 0.1]),
                      np.where(rng.random(n) < 0.85, "Closed", "Resolved"))
    a = app_lookup.loc[inc.app.values]
    impact = np.where(inc.sev.isin(["P1", "P2"]),
                      (rng.lognormal(8, 1.3, n) * np.where(a.Tier.values == "Tier-1", 3, 1)).astype(int), 0)
    df = pd.DataFrame(dict(
        Incident_ID=[f"INC{k:06d}" for k in range(1, n + 1)],
        Date=opened.dt.strftime("%Y-%m-%d"),
        Month=opened.dt.month, Quarter=opened.dt.quarter,
        App_ID=inc.app.values, Severity=inc.sev.values, RCA_Category=inc.rca.values,
        Affected_Layer=inc.layer.values, Duration_Min=dur,
        Open_Time=opened.dt.strftime("%Y-%m-%d %H:%M"),
        Acknowledge_Min=ack,
        Resolved_Time=np.where(is_open, "", resolved.dt.strftime("%Y-%m-%d %H:%M")),
        Status=status,
        SLA_Breached=np.where(dur > np.array([SEV_SLA_MIN[s] for s in inc.sev]), "Yes", "No"),
        Correlation_ID=inc["corr"].fillna("").values,
        Related_CR_ID=inc["cr"].fillna("").values,
        Detected_By=inc.det.values,
        Customers_Impacted=impact,
        Reopened=np.where(rng.random(n) < 0.04, "Yes", "No"),
        LOB=a.LOB.values, Tier=a.Tier.values, App_Type=a.App_Type.values,
    ))
    df.loc[is_open, "Duration_Min"] = ((end_ts - opened[is_open]).dt.total_seconds() // 60).astype(int)
    df.loc[is_open, "SLA_Breached"] = np.where(
        df.loc[is_open, "Duration_Min"].values > np.array([SEV_SLA_MIN[s] for s in df.loc[is_open, "Severity"]]),
        "Yes", "No")
    return df


# =============================================================================== SRs & vulnerabilities
def make_srs(cfg: Config, rng, apps, days):
    n = cfg.srs
    dw = np.where(days.dayofweek < 5, 1.3, 0.35)
    d = rng.choice(days, size=n, p=dw / dw.sum())
    a = apps.iloc[rng.choice(len(apps), size=n, p=apps._prop.values ** 0.5 / (apps._prop.values ** 0.5).sum())]
    cats = wchoice(rng, SR_CATS, n)
    med = np.array([SR_CATS[c][1] for c in cats])
    sla = np.array([SR_CATS[c][2] for c in cats])
    hrs = np.round(rng.lognormal(np.log(med), 0.7), 1)
    opened = pd.to_datetime(d) + pd.to_timedelta(rng.integers(8 * 60, 19 * 60, n), "m")
    end_ts = pd.Timestamp(cfg.end_date) + pd.Timedelta(hours=9)
    open_now = opened + pd.to_timedelta(hrs, "h") > end_ts
    return pd.DataFrame(dict(
        SR_ID=[f"SR{k:05d}" for k in range(1, n + 1)],
        Date=opened.strftime("%Y-%m-%d"), App_ID=a.App_ID.values, Category=cats, Resolution_Hours=hrs,
        Priority=rng.choice(["High", "Medium", "Low"], n, p=[0.15, 0.55, 0.30]),
        Status=np.where(open_now, "Open", "Fulfilled"), SLA_Hours=sla,
        SLA_Met=np.where(hrs <= sla, "Yes", "No"), Channel=rng.choice(["Portal", "Email", "Phone", "Chat"], n,
                                                                         p=[0.55, 0.2, 0.15, 0.1]),
        LOB=a.LOB.values,
    )).sort_values("Date").reset_index(drop=True).assign(
        SR_ID=lambda x: [f"SR{k:05d}" for k in range(1, len(x) + 1)])


def make_vulns(cfg: Config, rng, apps, days):
    n = cfg.vulns
    # internet-facing / older / in-house apps carry more findings
    w = apps.LOB.isin(["Digital Banking", "Mobile Banking", "Internet Banking", "UPI", "Payments"]).map(
        {True: 1.8, False: 1.0}).values * (1 + (cfg.end_date.year - apps.Go_Live_Year.values) / 15)
    a = apps.iloc[rng.choice(len(apps), size=n, p=w / w.sum())]
    sev = rng.choice(["Critical", "High", "Medium", "Low"], n, p=[0.08, 0.27, 0.42, 0.23])
    cvss = np.round(np.select(
        [sev == "Critical", sev == "High", sev == "Medium"],
        [rng.uniform(9.0, 10.0, n), rng.uniform(7.0, 8.9, n), rng.uniform(4.0, 6.9, n)], rng.uniform(0.1, 3.9, n)), 1)
    found = pd.to_datetime(rng.choice(days, size=n))
    due = found + pd.to_timedelta([VULN_SLA_DAYS[s] for s in sev], "D")
    fix_days = np.array([rng.lognormal(np.log(VULN_SLA_DAYS[s] * f), 0.7)
                         for s, f in zip(sev, rng.choice([0.6, 0.9, 1.4], n, p=[0.5, 0.3, 0.2]))])
    fix_days = np.where(a.App_Type.values == "3rd Party", fix_days * 1.3, fix_days)
    closed = found + pd.to_timedelta(fix_days.round(), "D")
    today = pd.Timestamp(cfg.end_date)
    still_open = closed > today
    accepted = (~still_open) & (rng.random(n) < 0.03)
    status = np.where(still_open, "Open", np.where(accepted, "Risk Accepted", "Closed"))
    overdue = np.where(still_open, today > due, closed > due)
    return pd.DataFrame(dict(
        Vuln_ID=[f"VULN{k:05d}" for k in range(1, n + 1)], App_ID=a.App_ID.values, Severity=sev, CVSS=cvss,
        Status=status, Discovered_Date=found.strftime("%Y-%m-%d"), Due_Date=due.strftime("%Y-%m-%d"),
        Closed_Date=np.where(still_open, "", closed.strftime("%Y-%m-%d")),
        Overdue=np.where(overdue, "Yes", "No"),
        Days_Open=np.where(still_open, (today - found).days, (closed - found).days),
        Source=rng.choice(VULN_SOURCES, n), Asset_Layer=rng.choice(VULN_LAYERS, n),
        Reference=[f"SIM-CVE-{rng.integers(2019, cfg.end_date.year + 1)}-{rng.integers(1000, 99999):05d}"
                   for _ in range(n)],
        LOB=a.LOB.values, Tier=a.Tier.values,
    )).sort_values("Discovered_Date").reset_index(drop=True).assign(
        Vuln_ID=lambda x: [f"VULN{k:05d}" for k in range(1, len(x) + 1)])


# =============================================================================== KPIs & recommendations
def make_kpis(cfg, apps, inc, cr, sr, vul, days):
    t1 = apps[apps.Tier == "Tier-1"].App_ID
    out = []
    inc_d = inc.groupby("Date")
    for d in days:
        ds = d.strftime("%Y-%m-%d")
        x = inc_d.get_group(ds) if ds in inc_d.groups else inc.iloc[0:0]
        down = x[x.Severity.isin(["P1", "P2"]) & x.App_ID.isin(t1)]
        # outage minutes: P1 full, P2 counted at 30% (degradation)
        mins = (down.Duration_Min.where(down.Severity == "P1", down.Duration_Min * 0.3)).clip(upper=1440).sum()
        avail = 100 * (1 - mins / (len(t1) * 1440))
        res = x[x.Resolved_Time != ""]
        c = cr[cr.Date == ds]
        done = c[c.Status.isin(["Implemented", "Failed", "Rolled Back"])]
        out.append(dict(
            Date=ds, Incidents=len(x), P1=int((x.Severity == "P1").sum()),
            MTTR_Hrs=round(res.Duration_Min.mean() / 60, 2) if len(res) else 0.0,
            Availability=round(avail, 3),
            P2=int((x.Severity == "P2").sum()),
            MTTA_Min=round(x.Acknowledge_Min.mean(), 1) if len(x) else 0.0,
            Changes=len(done),
            Failed_Changes=int(done.Status.isin(["Failed", "Rolled Back"]).sum()),
            Service_Requests=int((sr.Date == ds).sum()),
            Customers_Impacted=int(x.Customers_Impacted.sum()),
        ))
    k = pd.DataFrame(out)
    k["Change_Failure_Rate"] = np.where(k.Changes > 0, (k.Failed_Changes / k.Changes * 100).round(1), 0.0)
    return k


RCA_ACTION = {
    "Database Failure": "DB Health Check",
    "Capacity / Performance": "Capacity Upgrade",
    "Infrastructure Outage": "Infra Resilience Review",
    "Connectivity Issue": "Infra Resilience Review",
    "Certificate Expiry": "Automate Certificate Renewal",
    "Release Defect": "Strengthen Release Testing",
    "Configuration Error": "Strengthen Release Testing",
    "Vendor Defect": "Vendor Escalation",
    "Application Defect": "Open Problem Record",
    "Source Data Issue": "Data Quality Fix",
    "Batch Job Failure": "Data Quality Fix",
    "Human Error": "Runbook Automation",
    "Security Event": "Security Review",
}
NEXT_STEP = {
    "Patch Required": "Patch open critical/high vulnerabilities; agree a dated plan with the owner.",
    "Release Freeze": "Pause non-urgent releases until failed changes are root-caused and test gates added.",
    "Automate Recurring Fix": "Script the repeated data fix / batch rerun and fix the upstream cause.",
    "Open Problem Record": "Raise a problem ticket for the repeating defect and track the permanent fix.",
    "DB Health Check": "DBA review of cluster health, failover, indexes and backup windows.",
    "Capacity Upgrade": "Review CPU/memory/IO headroom and add capacity before peak (month end).",
    "Infra Resilience Review": "Check single points of failure, failover tests and network redundancy.",
    "Automate Certificate Renewal": "Inventory certificates and automate renewal and expiry alerts.",
    "Strengthen Release Testing": "Add regression and config validation gates to the release pipeline.",
    "Vendor Escalation": "Escalate defects to the vendor with SLA credits; demand a fix roadmap.",
    "Data Quality Fix": "Add validation at source and reconciliation checks before batch runs.",
    "Runbook Automation": "Automate the manual step that failed; add four-eyes checks.",
    "Security Review": "Security team investigation and hardening review.",
    "Immediate Review": "Service owner to review recent incidents and propose actions.",
}


def make_recommendations(cfg, apps, inc, cr, sr, vul, top_n=500):
    """Rule-based risk score per app over the last 90 days (incidents weighted by severity,
    repeat root causes, failed changes, open/overdue vulnerabilities, repetitive SRs), scaled
    0-100 and weighted by tier. The top driver picks the recommendation."""
    end = pd.Timestamp(cfg.end_date)
    recent = inc[pd.to_datetime(inc.Date) > end - pd.Timedelta(days=90)]
    sev_w = recent.Severity.map({"P1": 10, "P2": 4, "P3": 1, "P4": 0.25})
    s_inc = sev_w.groupby(recent.App_ID).sum()
    rep = recent.groupby(["App_ID", "RCA_Category"]).size()
    s_rep = (rep[rep >= 3] - 2).groupby(level=0).sum()
    rcr = cr[(pd.to_datetime(cr.Date) > end - pd.Timedelta(days=90)) & (pd.to_datetime(cr.Date) <= end)]
    s_chg = rcr[rcr.Status.isin(["Failed", "Rolled Back"])].groupby("App_ID").size() * 5
    ov = vul[vul.Status == "Open"]
    s_vul = (ov.Severity.map({"Critical": 8, "High": 3, "Medium": 0.5, "Low": 0.1})
             * np.where(ov.Overdue == "Yes", 2, 1)).groupby(ov.App_ID).sum()
    rsr = sr[pd.to_datetime(sr.Date) > end - pd.Timedelta(days=90)]
    s_sr = rsr[rsr.Category.isin(["Data Fix", "Batch Rerun"])].groupby("App_ID").size() * 0.6
    f = pd.DataFrame({"inc": s_inc, "rep": s_rep, "chg": s_chg, "vul": s_vul, "sr": s_sr}).fillna(0)
    f = f.reindex(apps.App_ID).fillna(0)
    tw = apps.set_index("App_ID").Tier.map({"Tier-1": 1.5, "Tier-2": 1.15, "Tier-3": 0.85})
    raw = (f.inc + 2 * f.rep + f.chg + f.vul + f.sr) * tw
    score = (100 * raw / raw.quantile(0.995)).clip(upper=100).round().astype(int)
    rows = []
    for app_id in score.sort_values(ascending=False).index[:top_n]:
        r = f.loc[app_id]
        drivers = {"inc": r.inc, "rep": 2 * r.rep, "chg": r.chg, "vul": r.vul, "sr": r.sr}
        top = max(drivers, key=drivers.get)
        x = recent[recent.App_ID == app_id]
        # the cause that cost most (severity-weighted) decides what to do about incidents
        wt = x.Severity.map({"P1": 10, "P2": 4, "P3": 1, "P4": 0.25})
        cause = wt.groupby(x.RCA_Category).sum().idxmax() if len(x) else "n/a"
        if top == "vul":
            rec = "Patch Required"
        elif top == "chg":
            rec = "Release Freeze"
        elif top == "sr":
            rec = "Automate Recurring Fix"
        else:
            rec = RCA_ACTION.get(cause, "Immediate Review")
            if top == "rep" and rec == "Immediate Review":
                rec = "Open Problem Record"
        n_crit = int((ov[ov.App_ID == app_id].Severity == "Critical").sum())
        n_over = int(((ov.App_ID == app_id) & (ov.Overdue == "Yes")).sum())
        def n(k, word):
            return f"{k} {word}" + ("" if k == 1 else "s")
        ev = (f"{int((x.Severity == 'P1').sum())} P1 and {int((x.Severity == 'P2').sum())} P2 in 90 days "
              f"({n(len(x), 'incident')}); costliest cause: {cause}; {n(int(r.chg / 5), 'failed change')}; "
              f"{n(n_crit, 'open critical vulnerability')}; {n(n_over, 'vulnerability')} past due")
        ev = ev.replace("vulnerabilitys", "vulnerabilities")
        score_i = int(score[app_id])
        prio = "P1 - this week" if score_i >= 80 else ("P2 - this month" if score_i >= 50 else "P3 - this quarter")
        rows.append(dict(App_ID=app_id, Risk_Score=score_i, Recommendation=rec, Evidence=ev,
                         Top_Cause=cause, Action_Priority=prio, Next_Step=NEXT_STEP[rec]))
    out = pd.DataFrame(rows)
    out.insert(0, "Rank", range(1, len(out) + 1))
    a = apps.set_index("App_ID")
    out["App_Name"] = a.loc[out.App_ID, "App_Name"].values
    out["LOB"] = a.loc[out.App_ID, "LOB"].values
    out["Tier"] = a.loc[out.App_ID, "Tier"].values
    out["Owner"] = a.loc[out.App_ID, "Support_Group"].values
    return out


# =============================================================================== main
def simulate(cfg: Config) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(cfg.seed)
    end = pd.Timestamp(cfg.end_date)
    start = (end.replace(day=1) - pd.DateOffset(months=11))     # 12 whole months, current one to date
    days = pd.date_range(start, end, freq="D")
    apps, services = make_apps(cfg, rng)
    cr, rel = make_changes(cfg, rng, apps, days)
    inc = make_incidents(cfg, rng, apps, cr, days)
    sr = make_srs(cfg, rng, apps, days)
    vul = make_vulns(cfg, rng, apps, days)
    kpi = make_kpis(cfg, apps, inc, cr, sr, vul, days)
    rec = make_recommendations(cfg, apps, inc, cr, sr, vul)
    for df, col in ((inc, "Date"), (sr, "Date"), (cr, "Date"), (rel, "Release_Date"), (kpi, "Date")):
        add_period_cols(df, col)
    # keep the sample's column order first, extras after
    inc = inc[["Incident_ID", "Date", "Month", "Quarter", "App_ID", "Severity", "RCA_Category", "Affected_Layer",
               "Duration_Min"] + [c for c in inc.columns if c not in
                                  ("Incident_ID", "Date", "Month", "Quarter", "App_ID", "Severity", "RCA_Category",
                                   "Affected_Layer", "Duration_Min")]]
    readme = pd.DataFrame({"OneRun Bank IT Operations: synthetic dataset": [
        f"Generated {dt.date.today():%Y-%m-%d} by it_ops_simulator.py (seed {cfg.seed}).",
        f"Period: {days[0]:%d %b %Y} to {days[-1]:%d %b %Y} (12 months, the last one to date), plus {cfg.forward_days} days of scheduled "
        "changes and releases after the end date (for 'going to production today').",
        "All data is synthetic. App, vendor and service names are invented; vulnerability references use SIM-CVE.",
        "Sheets and leading columns follow the sample OneRun_Bank_IT_Operations_Dataset.xlsx; extra columns are "
        "appended to the right of each sheet.",
        "Correlation_ID groups incidents caused by one shared event (DB cluster, infra cluster, network or a "
        "single change). Related_CR_ID links an incident to the change that caused it.",
        "ExecutiveKPI is computed from the ticket sheets, so dashboard totals reconcile.",
        "AIRecommendations is a transparent rule-based score (last 90 days), not a trained model.",
        "App_Type uses InHouse / 3rd Party / SaaS ('3rd Party' replaces the sample's 'Vendor').",
    ]})
    return {
        "README": readme,
        "Applications": apps.drop(columns="_prop"),
        "BusinessServices": services,
        "Incidents": inc,
        "ServiceRequests": sr,
        "ChangeRequests": cr,
        "Vulnerabilities": vul,
        "ProductionReleases": rel,
        "AIRecommendations": rec,
        "ExecutiveKPI": kpi,
    }


def write_excel(sheets: dict, path: str):
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "A2"
            for i, col in enumerate(df.columns, 1):
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)])
                ws.column_dimensions[ws.cell(1, i).column_letter].width = min(max(9, width + 2), 60)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--end-date", default=dt.date.today().isoformat(), help="last day of the 12 months (YYYY-MM-DD)")
    p.add_argument("--apps", type=int, default=1000)
    p.add_argument("--incidents", type=int, default=15000)
    p.add_argument("--srs", type=int, default=8000)
    p.add_argument("--crs", type=int, default=4000)
    p.add_argument("--vulns", type=int, default=3000)
    p.add_argument("--releases", type=int, default=1500)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--bank", default="OneRun Bank")
    p.add_argument("--out", default="OneRun_Bank_IT_Ops_Synthetic.xlsx")
    p.add_argument("--csv-dir", default=None, help="also write one CSV per sheet into this folder")
    a = p.parse_args()
    cfg = Config(end_date=dt.date.fromisoformat(a.end_date), apps=a.apps, incidents=a.incidents, srs=a.srs,
                 crs=a.crs, vulns=a.vulns, releases=a.releases, seed=a.seed, bank=a.bank)
    sheets = simulate(cfg)
    write_excel(sheets, a.out)
    if a.csv_dir:
        import os
        os.makedirs(a.csv_dir, exist_ok=True)
        for name, df in sheets.items():
            df.to_csv(os.path.join(a.csv_dir, f"{name}.csv"), index=False)
    for name, df in sheets.items():
        print(f"{name:20s} {len(df):>7,} rows")
    print(f"Saved {a.out}")


if __name__ == "__main__":
    main()
