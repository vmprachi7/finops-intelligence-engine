"""
AI-powered cost recommendations using Groq API (free tier).
Groq is OpenAI-compatible — same interface, completely free.
Model: llama-3.1-8b-instant (fast, capable, free)

Get a free API key at: https://console.groq.com
"""
from openai import OpenAI

from app import config
from app.anomaly_detector import Anomaly


def get_recommendations(
    anomalies:       list[Anomaly],
    mtd_spend:       float,
    yesterday_spend: float,
    top_services:    list[dict],
    trend:           str,
) -> str:
    """
    Main entry point. Returns markdown string with recommendations.
    Uses Groq API (free) with OpenAI-compatible client.
    """
    if not config.GROQ_API_KEY:
        return (
            "⚠️ **No Groq API key found.**\n\n"
            "1. Sign up free at https://console.groq.com\n"
            "2. Create an API key\n"
            "3. Add `GROQ_API_KEY=gsk_your-key` to your `.env` file\n\n"
            + _rule_based(anomalies)
        )

    if not anomalies and mtd_spend < 1.0:
        return (
            "✅ **No anomalies detected.** "
            "Your Azure spend looks normal for the current period. "
            "Keep an eye on costs as workloads scale."
        )

    try:
        # Groq uses the same OpenAI client — just point it at Groq's base URL
        client = OpenAI(
            api_key=config.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )
        prompt = _build_prompt(
            anomalies, mtd_spend, yesterday_spend, top_services, trend
        )
        response = client.chat.completions.create(
            model=config.AI_MODEL,
            max_tokens=config.AI_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    except Exception as e:
        return (
            f"⚠️ **AI unavailable** ({type(e).__name__}: {str(e)[:120]}). "
            "Showing rule-based recommendations instead.\n\n"
            + _rule_based(anomalies)
        )


# ── Prompt builder ────────────────────────────────────────────

def _build_prompt(
    anomalies:       list[Anomaly],
    mtd_spend:       float,
    yesterday_spend: float,
    top_services:    list[dict],
    trend:           str,
) -> str:

    anomaly_lines = "\n".join([
        f"- [{a.severity.upper()}] {a.service} on "
        f"{a.date.strftime('%b %d')}: "
        f"${a.actual_cost:.2f} actual vs ${a.expected_cost:.2f} expected "
        f"({a.deviation_pct:+.0f}%)"
        for a in anomalies[:5]
    ]) or "None detected."

    services_lines = "\n".join([
        f"- {s['service']}: ${s['cost_usd']:.2f}"
        for s in top_services[:5]
    ])

    return f"""You are a FinOps engineer analysing Azure cloud costs for a DevOps platform team.

COST SUMMARY
- Month-to-date spend: ${mtd_spend:.2f}
- Yesterday's spend:   ${yesterday_spend:.2f}
- 7-day spend trend:   {trend}

TOP SERVICES BY SPEND
{services_lines}

DETECTED ANOMALIES
{anomaly_lines}

TASK
Provide 3-5 specific, actionable cost optimisation recommendations.

FORMAT
1. One sentence overall assessment.
2. Each recommendation as:
   **[Service Name]** — specific action, why it saves money, estimated saving if possible.
3. End with one "quick win" (< 30 minutes to implement).

Rules:
- Be specific to the services listed above — no generic advice.
- For AKS spikes: consider node pool sizing, spot instances, idle detection.
- For VM spikes: consider reserved instances, auto-shutdown schedules.
- For storage: consider lifecycle policies, tier changes.
- For Log Analytics: consider retention settings, data source filtering.
- Keep tone direct and technical. Reader is a senior DevOps engineer."""


# ── Rule-based fallback ───────────────────────────────────────

def _rule_based(anomalies: list[Anomaly]) -> str:
    """Returns rule-based recommendations when AI is unavailable."""
    if not anomalies:
        return "✅ No anomalies detected. Spend looks normal."

    lines = ["**Cost optimisation recommendations (rule-based mode):**\n"]

    for a in anomalies[:3]:
        svc = a.service.lower()

        if "kubernetes" in svc:
            lines.append(
                f"**{a.service}** — Cost {a.deviation_pct:+.0f}% vs baseline. "
                "Check for over-provisioned node pools. "
                "Consider spot/preemptible nodes for non-critical workloads (up to 80% saving). "
                "Run `kubectl top pods` to identify over-requested containers."
            )
        elif "virtual machine" in svc:
            lines.append(
                f"**{a.service}** — Cost {a.deviation_pct:+.0f}% vs baseline. "
                "Check for VMs running outside business hours. "
                "Implement auto-shutdown schedules. "
                "Consider Azure Reserved Instances for 1-year commitment (up to 40% saving)."
            )
        elif "storage" in svc:
            lines.append(
                f"**{a.service}** — Storage cost anomaly detected. "
                "Review blob lifecycle policies — move data >30 days to Cool tier, "
                ">90 days to Archive. Delete orphaned managed disks from terminated VMs."
            )
        elif "log analytics" in svc or "monitor" in svc:
            lines.append(
                f"**{a.service}** — Log ingestion spike detected. "
                "Review data sources — verbose container logs are a common culprit. "
                "Set retention to 30 days for non-compliance workspaces. "
                "Use DCR transformation rules to filter noisy log sources."
            )
        else:
            lines.append(
                f"**{a.service}** — Unexpected {a.deviation_pct:+.0f}% deviation. "
                f"Review deployments and scaling events around {a.date.strftime('%b %d')}."
            )

    lines.append(
        "\n**Quick win (< 30 min):** Run `kubectl top nodes` and `kubectl top pods -A` "
        "to identify containers consuming more CPU/memory than requested. "
        "Rightsize resource requests to reduce AKS node costs immediately."
    )

    return "\n\n".join(lines)