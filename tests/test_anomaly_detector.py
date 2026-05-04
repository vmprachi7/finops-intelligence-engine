"""
Tests for anomaly_detector.py
Run with: pytest tests/ -v
"""
import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timedelta

from app.anomaly_detector import (
    detect_anomalies,
    get_daily_totals,
    get_mtd_spend,
    get_spend_trend,
    get_top_services,
    get_yesterday_spend,
)


# ── Fixtures ──────────────────────────────────────────────────

def stable_df() -> pd.DataFrame:
    """30 days of stable costs — no anomalies."""
    np.random.seed(0)
    end, rows = datetime.utcnow().date(), []
    for i in range(30):
        rows.append({
            "date":           pd.Timestamp(end - timedelta(days=i)),
            "service":        "Azure Kubernetes Service",
            "resource_group": "rg",
            "cost_usd":       round(np.random.normal(3.5, 0.1), 4),
        })
    return pd.DataFrame(rows)


def spike_df() -> pd.DataFrame:
    """30 days with a 4× spike 5 days ago."""
    df = stable_df()
    spike_date = pd.Timestamp(datetime.utcnow().date() - timedelta(days=5))
    df.loc[df["date"] == spike_date, "cost_usd"] = 14.0
    return df


def empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["date", "service", "resource_group", "cost_usd"])


# ── detect_anomalies ──────────────────────────────────────────

def test_no_anomalies_stable_data():
    assert detect_anomalies(stable_df()) == []


def test_detects_spike():
    results = detect_anomalies(spike_df())
    assert len(results) >= 1
    assert results[0].service == "Azure Kubernetes Service"
    assert results[0].deviation_pct > 30


def test_severity_labels_valid():
    results = detect_anomalies(spike_df())
    for a in results:
        assert a.severity in ("critical", "warning", "info")


def test_sorted_by_severity():
    results = detect_anomalies(spike_df())
    order = {"critical": 0, "warning": 1, "info": 2}
    for i in range(len(results) - 1):
        assert order[results[i].severity] <= order[results[i + 1].severity]


def test_empty_df_returns_empty():
    assert detect_anomalies(empty_df()) == []


def test_insufficient_data_skipped():
    """Services with < 7 days should be skipped."""
    rows = [
        {"date": pd.Timestamp(datetime.utcnow().date() - timedelta(days=i)),
         "service": "NewService", "resource_group": "rg", "cost_usd": 100.0}
        for i in range(5)
    ]
    assert detect_anomalies(pd.DataFrame(rows)) == []


# ── Aggregation helpers ───────────────────────────────────────

def test_get_daily_totals_returns_correct_cols():
    result = get_daily_totals(stable_df())
    assert "date" in result.columns
    assert "total_cost_usd" in result.columns


def test_get_mtd_spend_non_negative():
    assert get_mtd_spend(stable_df()) >= 0


def test_get_yesterday_spend_non_negative():
    assert get_yesterday_spend(stable_df()) >= 0


def test_get_top_services_count():
    df = stable_df()
    # Add a second service
    extra = df.copy()
    extra["service"] = "Virtual Machines"
    combined = pd.concat([df, extra])
    assert len(get_top_services(combined, n=2)) == 2


def test_get_top_services_sorted():
    df = stable_df()
    extra = df.copy()
    extra["service"] = "Virtual Machines"
    extra["cost_usd"] = extra["cost_usd"] * 2   # VMs cost more
    combined = pd.concat([df, extra])
    result = get_top_services(combined, n=2)
    assert result.iloc[0]["service"] == "Virtual Machines"


def test_get_spend_trend_valid_values():
    assert get_spend_trend(stable_df()) in ("up", "down", "stable")


def test_get_spend_trend_empty():
    assert get_spend_trend(empty_df()) == "stable"
