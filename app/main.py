"""
FinOps Intelligence Engine — Streamlit Dashboard
Run with: streamlit run app/main.py
"""
import pandas as pd
import plotly.express as px
import streamlit as st

from app import config
from app.ai_advisor import get_recommendations
from app.anomaly_detector import (
    detect_anomalies,
    get_daily_totals,
    get_mtd_spend,
    get_spend_trend,
    get_top_services,
    get_yesterday_spend,
)
from app.cost_fetcher import fetch_daily_costs

# ── Page config ───────────────────────────────────────────────
st.set_page_config(
    page_title="FinOps Intelligence Engine",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────
st.markdown("""
<style>
.anomaly-critical {
    background:#fff5f5;border-left:4px solid #e53e3e;
    padding:12px;border-radius:0 8px 8px 0;margin:6px 0;
}
.anomaly-warning {
    background:#fffbeb;border-left:4px solid #d69e2e;
    padding:12px;border-radius:0 8px 8px 0;margin:6px 0;
}
.anomaly-info {
    background:#ebf8ff;border-left:4px solid #3182ce;
    padding:12px;border-radius:0 8px 8px 0;margin:6px 0;
}
</style>
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────
def render_sidebar() -> tuple[float, float]:
    with st.sidebar:
        st.title("⚙️ Settings")

        if config.USE_MOCK_DATA:
            st.info(
                "🔧 **Mock data mode**\n\n"
                "Set `USE_MOCK_DATA=false` in `.env` to use real Azure costs."
            )

        missing = config.validate()
        if missing:
            st.warning(f"Missing config:\n`{'`, `'.join(missing)}`")

        st.divider()
        st.markdown("**Budget thresholds (USD)**")
        daily   = st.number_input("Daily budget ($)",   value=config.DAILY_BUDGET_USD,   step=1.0)
        monthly = st.number_input("Monthly budget ($)", value=config.MONTHLY_BUDGET_USD, step=10.0)

        st.divider()
        st.markdown("**About**")
        st.markdown("""
Built by **Prachi** · Senior DevOps & Platform Engineer

Stack: Python · Streamlit · Azure Cost API · Groq AI (Llama 3.1)

[GitHub](https://github.com/vmprachi7/finops-intelligence-engine)
        """)

    return daily, monthly


# ── Data loading (cached for 1 hour) ─────────────────────────
@st.cache_data(ttl=3600)
def load_data() -> pd.DataFrame:
    return fetch_daily_costs()


# ── Main dashboard ────────────────────────────────────────────
def main():
    daily_budget, monthly_budget = render_sidebar()

    # Header
    col_title, col_refresh = st.columns([5, 1])
    with col_title:
        st.title("💰 FinOps Intelligence Engine")
        mode = "Mock data" if config.USE_MOCK_DATA else "Live Azure data"
        st.caption(
            f"Azure cost anomaly detection + AI recommendations · "
            f"Last {config.LOOKBACK_DAYS} days · {mode}"
        )
    with col_refresh:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Refresh"):
            st.cache_data.clear()
            st.rerun()

    st.divider()

    # Load data
    with st.spinner("Fetching cost data..."):
        df = load_data()

    if df.empty:
        st.error(
            "No cost data available. "
            "Check your Azure credentials or set `USE_MOCK_DATA=true` in `.env`."
        )
        return

    # Compute all metrics
    mtd         = get_mtd_spend(df)
    yesterday   = get_yesterday_spend(df)
    anomalies   = detect_anomalies(df)
    trend       = get_spend_trend(df)
    top_svc_df  = get_top_services(df)
    budget_pct  = (mtd / monthly_budget * 100) if monthly_budget > 0 else 0
    daily_avg   = df.groupby("date")["cost_usd"].sum().mean()
    projected   = daily_avg * 30
    trend_emoji = {"up": "📈", "down": "📉", "stable": "➡️"}[trend]
    critical_n  = sum(1 for a in anomalies if a.severity == "critical")
    warning_n   = sum(1 for a in anomalies if a.severity == "warning")

    # ── KPI row ───────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric(
            "Month-to-date",
            f"${mtd:.2f}",
            delta=f"{budget_pct:.0f}% of ${monthly_budget:.0f} budget",
            delta_color="inverse" if budget_pct > 80 else "normal",
        )
    with c2:
        st.metric("Yesterday", f"${yesterday:.2f}")
    with c3:
        st.metric("7-day trend", f"{trend_emoji} {trend.capitalize()}")
    with c4:
        st.metric(
            "Anomalies",
            len(anomalies),
            delta=f"{critical_n} critical · {warning_n} warnings",
            delta_color="inverse" if critical_n > 0 else "normal",
        )
    with c5:
        st.metric("Projected monthly", f"${projected:.2f}")

    st.divider()

    # ── Main two-column layout ────────────────────────────────
    left, right = st.columns([3, 2])

    with left:
        # Daily spend stacked area chart
        st.subheader("📊 Daily spend by service")
        daily_svc = (
            df.groupby(["date", "service"])["cost_usd"]
            .sum()
            .reset_index()
        )
        fig = px.area(
            daily_svc,
            x="date", y="cost_usd", color="service",
            labels={"cost_usd": "Cost (USD)", "date": "Date"},
            color_discrete_sequence=px.colors.qualitative.Set2,
        )

        # Mark critical anomaly dates with scatter markers
        # (add_vline is incompatible with pandas 2.x + older Plotly versions)
        if anomalies:
            critical_dates = [a.date for a in anomalies if a.severity == "critical"]
            if critical_dates:
                daily_totals = df.groupby("date")["cost_usd"].sum().reset_index()
                markers = daily_totals[daily_totals["date"].isin(critical_dates)]
                if not markers.empty:
                    fig.add_scatter(
                        x=markers["date"],
                        y=markers["cost_usd"],
                        mode="markers+text",
                        marker=dict(color="red", size=10, symbol="x"),
                        text=["⚠"] * len(markers),
                        textposition="top center",
                        name="Critical anomaly",
                        showlegend=True,
                    )

        fig.update_layout(
            height=320,
            margin=dict(l=0, r=0, t=20, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            plot_bgcolor="white",
        )
        st.plotly_chart(fig, use_container_width=True)

        # Budget progress bar
        st.subheader("🎯 Budget tracking")
        bar_color = (
            "#e53e3e" if budget_pct > 90
            else "#d69e2e" if budget_pct > 70
            else "#38a169"
        )
        st.markdown(f"""
        <div style="margin:8px 0">
          <div style="display:flex;justify-content:space-between;
                      font-size:13px;color:#666">
            <span>Budget: ${monthly_budget:.0f}/month</span>
            <span>${mtd:.2f} used ({budget_pct:.0f}%)</span>
          </div>
          <div style="background:#eee;border-radius:6px;height:12px;margin-top:4px">
            <div style="background:{bar_color};
                        width:{min(budget_pct,100):.0f}%;
                        height:12px;border-radius:6px"></div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        # Service breakdown pie chart
        st.subheader("🍩 Spend by service")
        fig2 = px.pie(
            top_svc_df,
            values="cost_usd", names="service", hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig2.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0))
        fig2.update_traces(textposition="inside", textinfo="percent")
        st.plotly_chart(fig2, use_container_width=True)

    with right:
        # Anomaly cards
        st.subheader(f"🚨 Anomalies ({len(anomalies)})")

        if not anomalies:
            st.success("✅ No anomalies detected in the current period.")
        else:
            for a in anomalies[:8]:
                css   = f"anomaly-{a.severity}"
                icon  = {"critical": "🔴", "warning": "🟡", "info": "🔵"}[a.severity]
                arrow = "▲" if a.deviation_pct > 0 else "▼"
                st.markdown(f"""
                <div class="{css}">
                  <strong>{icon} {a.service}</strong><br>
                  <span style="font-size:12px;color:#555">
                    {a.date.strftime('%b %d')} &nbsp;·&nbsp;
                    {arrow} {abs(a.deviation_pct):.0f}% &nbsp;·&nbsp;
                    ${a.actual_cost:.2f} actual vs ${a.expected_cost:.2f} expected
                  </span>
                </div>
                """, unsafe_allow_html=True)

        st.divider()

        # Top services table
        st.subheader("💸 Top services")
        tbl = top_svc_df.copy()
        tbl.columns = ["Service", "Total (USD)"]
        tbl["Total (USD)"] = tbl["Total (USD)"].map("${:.2f}".format)
        st.dataframe(tbl, use_container_width=True, hide_index=True)

    st.divider()

    # ── AI recommendations ────────────────────────────────────
    st.subheader("🤖 AI Cost Recommendations")
    st.caption("Powered by Groq (Llama 3.1) · Analyses anomalies + spend patterns → specific actions")

    if st.button("✨ Generate AI recommendations", type="primary"):
        with st.spinner("Groq AI is analysing your cost data..."):
            recs = get_recommendations(
                anomalies=anomalies,
                mtd_spend=mtd,
                yesterday_spend=yesterday,
                top_services=top_svc_df.to_dict("records"),
                trend=trend,
            )
        st.markdown(recs)
        st.download_button(
            "📥 Download recommendations",
            data=recs,
            file_name=f"finops-recommendations-{pd.Timestamp.now().strftime('%Y%m%d')}.md",
            mime="text/markdown",
        )
    else:
        st.info(
            "Click the button above to get AI-powered cost recommendations "
            "based on your current anomalies and spend pattern."
        )

    st.divider()

    # ── Raw data expander ─────────────────────────────────────
    with st.expander("📋 Raw cost data"):
        st.dataframe(
            df.sort_values("date", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
        st.download_button(
            "📥 Download CSV",
            data=df.to_csv(index=False),
            file_name=f"azure-costs-{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )


if __name__ == "__main__":
    main()