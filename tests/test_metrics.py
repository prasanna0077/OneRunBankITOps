"""Run with:  python tests/test_metrics.py   (or pytest)"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from itops import data as D, metrics as M  # noqa: E402

DATA = D.normalise(D.read_workbook(os.path.join(ROOT, "data", "OneRun_Bank_IT_Ops_Synthetic.xlsx")))


def _all():
    return D.scope(DATA, D.filter_apps(DATA.apps, "All LOBs", "All tiers", "All types"))


def test_periods_cover_the_data():
    for view in ["Monthly", "Quarterly", "Yearly"]:
        ps = D.period_options(view, DATA.first_day, DATA.last_day)
        assert ps and all(p.start <= p.end for p in ps)
    months = D.period_options("Monthly", DATA.first_day, DATA.last_day)
    assert sum(len(M.incidents(_all(), p)) for p in months) == len(DATA.inc)


def test_kpis_reconcile_with_daily_kpi_sheet():
    ds = _all()
    p = D.period_options("Yearly", DATA.first_day, DATA.last_day)[0]
    assert len(M.incidents(ds, p)) == int(DATA.kpi["Incidents"].sum())
    assert int((M.incidents(ds, p).Severity == "P1").sum()) == int(DATA.kpi["P1"].sum())


def test_lob_matrix_adds_up():
    ds = _all()
    p = D.period_options("Monthly", DATA.first_day, DATA.last_day)[0]
    mx = M.ticket_matrix(ds, p)
    assert mx["Incidents"].sum() == len(M.incidents(ds, p))
    assert mx["Apps"].sum() == len(DATA.apps)


def test_filters_partition_the_bank():
    p = D.period_options("Monthly", DATA.first_day, DATA.last_day)[0]
    total = 0
    for lob in DATA.apps["LOB"].unique():
        total += len(M.incidents(D.scope(DATA, D.filter_apps(DATA.apps, lob, "All tiers", "All types")), p))
    assert total == len(M.incidents(_all(), p))


def test_kpi_status_logic():
    p = D.period_options("Monthly", DATA.first_day, DATA.last_day)[0]
    kt = M.kpi_table(_all(), p, M.DEFAULT_TARGETS)
    assert set(kt["Status"]) <= {"Met", "Missed", "Tracked", "No data"}
    r = kt.set_index("KPI").loc["Change failure rate"]
    assert (r.Status == "Met") == (r.Value <= r.Target)


def test_today_and_recommendations():
    tv = M.today_view(_all(), DATA.last_day)
    assert len(tv["changes"]) > 0 and "Watch" in tv["changes"]
    rec = M.recommendations(_all(), DATA.last_day)
    assert rec["Risk_Score"].between(1, 100).all()
    assert list(rec["Rank"]) == list(range(1, len(rec) + 1))


def test_correlation_tables():
    p = D.period_options("Monthly", DATA.first_day, DATA.last_day)[0]
    i = M.incidents(_all(), p)
    ls = M.layer_summary(i)
    assert ls["Incidents"].sum() == len(i)
    ev = M.shared_events(i)
    assert (ev["Apps hit"] >= 1).all()
    corr = M.hourly_layer_correlation(i)
    assert ((corr.values.diagonal() - 1).__abs__() < 1e-9).all()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
