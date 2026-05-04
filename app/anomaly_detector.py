"""
Anomaly detection on Azure cost data.

Method: rolling 7-day average + deviation threshold.
Chosen over ML models deliberately — transparent, explainable,
no training data needed, easy to reason about in an interview.
"""
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from app import config


@dataclass
class Anomaly:
    date:           datetime
    service:        str
    resource_group: str
    actual_cost:    float
    expected_cost:  float
    deviation_pct:  float
    severity:       str   # "critical" | "warning" | "info"
    description:    str


# ── Main detection function ───────────────────────────────────

def detect_anomalies(df: pd.DataFrame) -> list[Anomaly]:
    """
    For each service, compute rolling 7-day average.
    Flag days where actual cost deviates > ANOMALY_THRESHOLD_PCT.
    Returns list sorted by severity then deviation size.
    """
    if df.empty:
        return []

    anomalies: list[Anomaly] = []

    for service in df["service"].unique():
        svc_df = (
            df[df["service"] == service]
            .groupby("date")["cost_usd"]
            .sum()
            .reset_index()
            .sort_values("date")
        )

        # Need at least 7 days to compute a meaningful rolling average
        if len(svc_df) < 7:
            continue

        # Shift by 1 so we don't include today's cost in its own baseline
        svc_df["rolling_mean"] = (
            svc_df["cost_usd"]
            .shift(1)
            .rolling(window=7, min_periods=3)
            .mean()
        )

        for _, row in svc_df.iterrows():
            if pd.isna(row["rolling_mean"]) or row["rolling_mean"] == 0:
                continue

            deviation_pct = (
                (row["cost_usd"] - row["rolling_mean"])
                / row["rolling_mean"] * 100
            )

            if abs(deviation_pct) < config.ANOMALY_THRESHOLD_PCT:
                continue

            # Find most common resource group for this service on this date
            rg_match = df[
                (df["service"] == service) & (df["date"] == row["date"])
            ]["resource_group"]
            resource_group = rg_match.mode()[0] if not rg_match.empty else "unknown"

            anomalies.append(Anomaly(
                date=row["date"],
                service=service,
                resource_group=resource_group,
                actual_cost=round(float(row["cost_usd"]), 4),
                expected_cost=round(float(row["rolling_mean"]), 4),
                deviation_pct=round(deviation_pct, 1),
                severity=_severity(deviation_pct),
                description=_describe(service, deviation_pct,
                                      row["cost_usd"], row["rolling_mean"]),
            ))

    _order = {"critical": 0, "warning": 1, "info": 2}
    anomalies.sort(key=lambda a: (_order[a.severity], -abs(a.deviation_pct)))
    return anomalies


# ── Aggregation helpers ───────────────────────────────────────

def get_daily_totals(df: pd.DataFrame) -> pd.DataFrame:
    """Daily total spend across all services."""
    return (
        df.groupby("date")["cost_usd"]
        .sum()
        .reset_index()
        .rename(columns={"cost_usd": "total_cost_usd"})
        .sort_values("date")
    )


def get_mtd_spend(df: pd.DataFrame) -> float:
    """Month-to-date total spend."""
    now = datetime.utcnow()
    mtd = df[(df["date"].dt.month == now.month) & (df["date"].dt.year == now.year)]
    return round(float(mtd["cost_usd"].sum()), 2)


def get_yesterday_spend(df: pd.DataFrame) -> float:
    """Yesterday's total spend."""
    if df.empty:
        return 0.0
    latest = df["date"].max()
    return round(float(df[df["date"] == latest]["cost_usd"].sum()), 2)


def get_top_services(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """Top N services by total spend."""
    return (
        df.groupby("service")["cost_usd"]
        .sum()
        .reset_index()
        .sort_values("cost_usd", ascending=False)
        .head(n)
    )


def get_spend_trend(df: pd.DataFrame) -> str:
    """Compare last 7 days vs prior 7 days. Returns 'up', 'down', or 'stable'."""
    if df.empty:
        return "stable"
    daily = get_daily_totals(df)
    if len(daily) < 14:
        return "stable"
    recent = daily.tail(7)["total_cost_usd"].sum()
    prior  = daily.iloc[-14:-7]["total_cost_usd"].sum()
    if prior == 0:
        return "stable"
    pct = (recent - prior) / prior * 100
    if pct > 10:
        return "up"
    elif pct < -10:
        return "down"
    return "stable"


# ── Internal helpers ──────────────────────────────────────────

def _severity(deviation_pct: float) -> str:
    abs_dev = abs(deviation_pct)
    if abs_dev >= 100:
        return "critical"
    elif abs_dev >= 50:
        return "warning"
    return "info"


def _describe(service: str, deviation_pct: float,
              actual: float, expected: float) -> str:
    direction = "spike" if deviation_pct > 0 else "drop"
    return (
        f"{service} cost {direction} of {abs(deviation_pct):.0f}% "
        f"(${actual:.2f} vs expected ${expected:.2f})"
    )
