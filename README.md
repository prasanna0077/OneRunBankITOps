# OneRun Bank IT Operations

A Streamlit dashboard for a bank IT team, built on a year of simulated Incident, Service Request,
Change and Vulnerability tickets across ~1,000 applications.

## Run the app

```bash
pip install -r requirements.txt
streamlit run app.py
```

Deploy on Streamlit Community Cloud by pushing this folder to GitHub and pointing it at `app.py`.
If `data/OneRun_Bank_IT_Ops_Synthetic.xlsx` is missing, the app generates a fresh year ending today on first run.

**Sidebar picker (applies to every screen):** data source (bundled or upload your own workbook), line of
business (All or one LOB), app tier, app type, **View: Monthly / Quarterly / Yearly** with the period list
(quarters follow the Indian financial year, Apr–Mar), and the date used by the Today screen.

| Screen | Answers |
| --- | --- |
| Executive | Headline, 6 KPI tiles vs previous period and targets, 12-month trend, incidents by LOB, top root causes, today's watch-list, top 3 actions |
| Today | Changes and production releases for the day with watch flags (emergency without CAB, high risk, unstable app, Tier-1), P1/P2 incidents with status and age, next 7 days |
| Tickets by LOB & app | Incidents, P1+P2, incidents per app, SRs, changes, new and open vulnerabilities per LOB; severity mix; application ranking and drill-down; CSV download |
| Root cause & correlation | All RCA categories; incidents by layer and share in multi-app events; RCA × layer and layer × LOB heatmaps; whether DB, App, Infra and Packaging incidents occur together (same app/day pairs and hourly correlation); largest correlated events with drill-down; DB and infra clusters with the widest blast radius; change-induced incidents |
| KPIs | 19 ITIL / DORA KPIs with Met / Missed status against editable targets, and a 12-month trend for any KPI |
| Top priorities | Applications ranked by risk score (last 90 days) with evidence, recommended fix, next step and owner; filters; CSV download |

The app also reads the original sample `OneRun_Bank_IT_Operations_Dataset.xlsx`; measures that need columns
the sample lacks (acknowledge time, correlation groups, vulnerability dates) show a note or "–".

## Project layout

```
app.py                     Streamlit screens and sidebar
itops/data.py              load and normalise the workbook, periods, filters
itops/metrics.py           KPIs, availability, correlation, today, recommendations
itops/charts.py            Plotly figures
simulator/it_ops_simulator.py   synthetic data generator
data/OneRun_Bank_IT_Ops_Synthetic.xlsx
tests/test_metrics.py      python tests/test_metrics.py
```

# Data simulator

Generates one year of synthetic IT operations data for a bank with about 1,000 applications,
in the same sheets and leading columns as `OneRun_Bank_IT_Operations_Dataset.xlsx`.

```bash
python simulator/it_ops_simulator.py                          # 12 months ending today
python simulator/it_ops_simulator.py --end-date 2025-12-31    # calendar year 2025
python simulator/it_ops_simulator.py --apps 1500 --incidents 20000 --seed 7 --out my_bank.xlsx
python simulator/it_ops_simulator.py --csv-dir csv/           # also one CSV per sheet
```

Same `--seed` and `--end-date` always give the same data. `data/OneRun_Bank_IT_Ops_Synthetic.xlsx` was made
with `--end-date 2026-10-28` (Nov 2025 – 28 Oct 2026, plus 14 days of scheduled changes).

## Sheets

| Sheet | Rows | What it holds |
| --- | --- | --- |
| Applications | 1,000 | 20 LOBs (Deposits, Loans, Lease, Mortgage, Cards, Payments, UPI, Treasury, Wealth, Corporate Banking, Branch, Digital/Mobile/Internet Banking, AML, Fraud, Compliance, CRM, Data Lake, HR & Finance); Tier-1/2/3; InHouse / 3rd Party / SaaS; OnPrem / Cloud / Hybrid; database, DB cluster, infra cluster, vendor, SLA, owner |
| BusinessServices | 110 | Business services per LOB; each app maps to one (`Service_ID`) |
| Incidents | ~15,000 | Severity P1–P4, RCA category (13), affected layer (Application, Database, Infrastructure, Packaging, Network, Data), open/acknowledge/resolve times, SLA breach, correlation group, linked change, customers impacted |
| ServiceRequests | ~8,000 | 9 categories, resolution hours, SLA, status, channel |
| ChangeRequests | ~4,000 + 14 days ahead | Type, risk, status (Implemented, Failed, Rolled Back, Cancelled, Approved, Pending CAB), change layer, planned window, CAB approval |
| Vulnerabilities | ~3,000 | Severity with consistent CVSS, discovered/due/closed dates, overdue flag, source, layer, `SIM-CVE` reference |
| ProductionReleases | ~1,500 | Releases linked to their change, window, status (Deployed, Rolled Back, Scheduled) |
| AIRecommendations | 500 | Ranked apps: risk score, costliest cause, recommendation, priority, evidence, next step |
| ExecutiveKPI | 1 row per day | Incidents, P1, P2, MTTR, MTTA, Tier-1 availability, changes, change failure rate, SRs, customers impacted |

Every dated sheet also has `Year`, `Month`, `Quarter`, `Month_Name`, `FY` (Indian financial year, Apr–Mar) and
`FY_Quarter`, for the monthly / quarterly / yearly picker.

## How the data behaves (so the dashboard has something real to find)

- **Hot spots:** a lognormal "propensity" per app (higher for Tier-1, in-house and older apps) means about 5% of apps
  produce over 20% of incidents.
- **Correlation:** shared-component events (a DB cluster, an infra cluster or the network) raise incidents on many apps
  within minutes, sharing a `Correlation_ID`. Failed or rolled-back changes raise incidents on their app within 36 hours,
  with `Related_CR_ID` set.
- **Calendar:** weekdays, month-end, quarter-end and the festive season are busier; changes avoid month-end.
- **Consistency:** `ExecutiveKPI` is computed from the ticket sheets, so totals reconcile; CVSS always matches severity.
- **Recommendations:** a transparent rule over the last 90 days (severity-weighted incidents, repeated causes, failed
  changes, open and overdue vulnerabilities, repeated data fixes, tier weight). The largest factor chooses the action.

## Differences from the sample

- `App_Type` uses `3rd Party` instead of `Vendor`; LOBs include Loans, Lease, Branch and Digital Banking.
- The sample's random CVSS values (e.g. "Low" at 2.0 but "Critical" at 5.1) are replaced by values that match severity.
- Extra columns are appended to the right of each sheet; the sample's columns keep their names and order.

All names (applications, vendors, services) are invented. This is synthetic data for demos and training only.
