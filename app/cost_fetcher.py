"""
Azure Cost Management API client.

Two modes:
  USE_MOCK_DATA=true  → generates realistic fake data locally (no Azure needed)
  USE_MOCK_DATA=false → calls real Azure Cost Management API
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from app import config

MOCK_FILE = Path(__file__).parent.parent / "mock_data" / "sample_costs.json"


# ── Public interface ──────────────────────────────────────────

def fetch_daily_costs() -> pd.DataFrame:
    """
    Returns DataFrame with columns:
      date (datetime), service (str), resource_group (str), cost_usd (float)
    """
    if config.USE_MOCK_DATA:
        return _load_or_generate_mock()
    return _fetch_from_azure()


def fetch_cost_by_service(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate total spend per Azure service."""
    return (
        df.groupby("service")["cost_usd"]
        .sum()
        .reset_index()
        .sort_values("cost_usd", ascending=False)
    )


def fetch_cost_by_resource_group(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate total spend per resource group."""
    return (
        df.groupby("resource_group")["cost_usd"]
        .sum()
        .reset_index()
        .sort_values("cost_usd", ascending=False)
    )


# ── Azure Cost API ────────────────────────────────────────────

def _fetch_from_azure() -> pd.DataFrame:
    try:
        from azure.identity import ClientSecretCredential
        from azure.mgmt.costmanagement import CostManagementClient
        from azure.mgmt.costmanagement.models import (
            QueryDefinition, QueryTimePeriod,
            QueryDataset, QueryAggregation, QueryGrouping,
        )
    except ImportError:
        raise ImportError(
            "Azure SDK not installed. "
            "Run: pip install azure-identity azure-mgmt-costmanagement"
        )

    credential = ClientSecretCredential(
        tenant_id=config.AZURE_TENANT_ID,
        client_id=config.AZURE_CLIENT_ID,
        client_secret=config.AZURE_CLIENT_SECRET,
    )
    client = CostManagementClient(credential)
    scope  = f"/subscriptions/{config.AZURE_SUBSCRIPTION_ID}"

    end_date   = datetime.utcnow().date()
    start_date = end_date - timedelta(days=config.LOOKBACK_DAYS)

    query = QueryDefinition(
        type="ActualCost",
        timeframe="Custom",
        time_period=QueryTimePeriod(
            from_property=datetime.combine(start_date, datetime.min.time()),
            to=datetime.combine(end_date, datetime.min.time()),
        ),
        dataset=QueryDataset(
            granularity="Daily",
            aggregation={
                "totalCost": QueryAggregation(name="PreTaxCost", function="Sum")
            },
            grouping=[
                QueryGrouping(type="Dimension", name="ServiceName"),
                QueryGrouping(type="Dimension", name="ResourceGroupName"),
            ],
        ),
    )

    result = client.query.usage(scope=scope, parameters=query)

    rows = []
    for row in result.rows:
        rows.append({
            "cost_usd":       round(float(row[0]), 4),
            "date":           pd.to_datetime(str(row[1])),
            "service":        str(row[2]),
            "resource_group": str(row[3]),
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["date", "service", "resource_group", "cost_usd"]
    )


# ── Mock data ─────────────────────────────────────────────────

def _load_or_generate_mock() -> pd.DataFrame:
    """Load saved mock data or generate fresh if not found."""
    if MOCK_FILE.exists():
        df = pd.read_json(MOCK_FILE)
        df["date"] = pd.to_datetime(df["date"])
        return df
    return _generate_and_save_mock()


def _generate_and_save_mock() -> pd.DataFrame:
    """
    Generate 30 days of realistic Azure cost data.
    Includes a deliberate spike on day 20 ago for demo purposes.
    """
    np.random.seed(42)

    end_date   = datetime.utcnow().date()
    start_date = end_date - timedelta(days=config.LOOKBACK_DAYS)

    # (service_name, base_cost_usd, std_dev)
    services = [
        ("Azure Kubernetes Service",  3.50, 0.40),
        ("Virtual Machines",          2.20, 0.60),
        ("Azure Container Registry",  0.15, 0.02),
        ("Log Analytics",             0.80, 0.15),
        ("Azure Monitor",             0.40, 0.08),
        ("Storage Accounts",          0.25, 0.05),
        ("Virtual Network",           0.10, 0.02),
    ]

    resource_groups = [
        "devops-platform-rg",
        "terraform-state-rg",
        "shared-services-rg",
    ]

    rows    = []
    current = start_date

    while current <= end_date:
        days_ago = (end_date - current).days

        for service, base, std in services:
            # Inject a 3× AKS cost spike 20 days ago — visible anomaly for demo
            spike = 3.0 if (service == "Azure Kubernetes Service" and days_ago == 20) else 1.0
            # Inject a VM spike 10 days ago
            spike = 2.5 if (service == "Virtual Machines" and days_ago == 10) else spike

            cost = max(0.0, np.random.normal(base * spike, std))

            rows.append({
                "date":           current.isoformat(),
                "service":        service,
                "resource_group": np.random.choice(resource_groups),
                "cost_usd":       round(cost, 4),
            })

        current += timedelta(days=1)

    df = pd.DataFrame(rows)

    # Save for consistent runs
    MOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_json(MOCK_FILE, orient="records", indent=2)

    df["date"] = pd.to_datetime(df["date"])
    return df
