"""
Central configuration — reads from .env file.
All app settings live here. Nothing hardcoded anywhere else.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── AI (Groq — completely free) ───────────────────────────────
# Sign up free at: https://console.groq.com
# No credit card required
GROQ_API_KEY  = os.getenv("GROQ_API_KEY", "")
AI_MODEL      = "llama-3.1-8b-instant"   # free, fast, capable
AI_MAX_TOKENS = 1024

# ── Azure ─────────────────────────────────────────────────────
AZURE_SUBSCRIPTION_ID = os.getenv("AZURE_SUBSCRIPTION_ID", "")
AZURE_TENANT_ID       = os.getenv("AZURE_TENANT_ID", "")
AZURE_CLIENT_ID       = os.getenv("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET   = os.getenv("AZURE_CLIENT_SECRET", "")

# ── App behaviour ─────────────────────────────────────────────
USE_MOCK_DATA         = os.getenv("USE_MOCK_DATA", "true").lower() == "true"
LOOKBACK_DAYS         = int(os.getenv("LOOKBACK_DAYS", "30"))
ANOMALY_THRESHOLD_PCT = float(os.getenv("ANOMALY_THRESHOLD_PCT", "30"))
DAILY_BUDGET_USD      = float(os.getenv("DAILY_BUDGET_USD", "10"))
MONTHLY_BUDGET_USD    = float(os.getenv("MONTHLY_BUDGET_USD", "100"))


def validate() -> list[str]:
    """Returns list of missing required config values."""
    missing = []
    if not GROQ_API_KEY:
        missing.append("GROQ_API_KEY")
    if not USE_MOCK_DATA:
        if not AZURE_SUBSCRIPTION_ID:
            missing.append("AZURE_SUBSCRIPTION_ID")
        if not AZURE_TENANT_ID:
            missing.append("AZURE_TENANT_ID")
        if not AZURE_CLIENT_ID:
            missing.append("AZURE_CLIENT_ID")
        if not AZURE_CLIENT_SECRET:
            missing.append("AZURE_CLIENT_SECRET")
    return missing