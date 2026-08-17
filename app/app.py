"""
Streamlit dashboard: forecast + growth allocation + goal planner + chat.

Run with:
    streamlit run app/app.py
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from advisor.client import ask, ask_with_history
from advisor.prompts import (
    chat_context_prompt,
    explain_allocation_prompt,
    explain_forecast_prompt,
)
from forecaster.forecast import forecast
from optimizer.goal_planner import run_goal_planner
from optimizer.optimize import apply_to_surplus, run_optimizer

st.set_page_config(page_title="Budget advisor", layout="wide")
st.title("Budget advisor")

with st.spinner("Loading forecast..."):
    fc = forecast(3)

col1, col2, col3 = st.columns(3)
col1.metric("Months of history", fc["months_of_history"])
col2.metric("Forecast confidence", fc["confidence"])
col3.metric("Avg monthly surplus", f"{fc['avg_monthly_surplus']:,.0f} DZD")

tab_forecast, tab_growth, tab_goal, tab_chat = st.tabs(
    ["Forecast", "Growth allocation", "Goal planner", "Ask the advisor"]
)

# --- Forecast tab ---
with tab_forecast:
    months_ahead = st.slider("Months to forecast", 1, 12, 3, key="fc_months")
    fc_view = forecast(months_ahead) if months_ahead != 3 else fc

    chart_df = pd.DataFrame({
        "income": fc_view["income_forecast"],
        "expenses": fc_view["expenses_forecast"],
        "surplus": fc_view["surplus_forecast"],
    }, index=[f"+{i+1}mo" for i in range(months_ahead)])
    st.line_chart(chart_df)

    if st.button("Explain this forecast"):
        with st.spinner("Asking the advisor..."):
            st.info(ask(explain_forecast_prompt(fc_view)))

# --- Growth allocation tab ---
with tab_growth:
    surplus_override = st.number_input(
        "Monthly surplus to allocate (DZD)",
        value=float(max(fc["avg_monthly_surplus"], 0)),
        step=1000.0,
    )

    if st.button("Run optimizer"):
        with st.spinner("Running NSGA-II..."):
            front = run_optimizer()
            st.session_state["pareto_front"] = apply_to_surplus(front, surplus_override)

    if "pareto_front" in st.session_state:
        front = st.session_state["pareto_front"]
        risk_idx = st.slider("Risk appetite (0 = conservative, 100 = aggressive)", 0, 100, 50)
        idx = int(risk_idx / 100 * (len(front) - 1))
        selected = front[idx]

        st.write(f"Expected return: **{selected['expected_return']:.1%}** | "
                 f"Risk: **{selected['risk']:.1%}**")

        alloc_df = pd.DataFrame([
            {"asset": k, "amount_dzd": v, "weight": selected["allocation"][k]}
            for k, v in selected["amounts_dzd"].items()
        ])
        st.bar_chart(alloc_df.set_index("asset")["amount_dzd"])
        st.dataframe(alloc_df, use_container_width=True)

        if st.button("Explain this allocation"):
            with st.spinner("Asking the advisor..."):
                st.info(ask(explain_allocation_prompt(selected, surplus_override)))

# --- Goal planner tab ---
with tab_goal:
    gcol1, gcol2 = st.columns(2)
    goal_amount = gcol1.number_input("Target amount (DZD)", value=1_000_000.0, step=50_000.0)
    goal_months = gcol2.slider("Deadline (months)", 1, 36, 12)

    if st.button("Run goal planner"):
        with st.spinner("Running NSGA-II across cuts and investment risk..."):
            try:
                st.session_state["goal_plans"] = run_goal_planner(goal_amount, goal_months)
            except ValueError as e:
                st.error(str(e))

    if "goal_plans" in st.session_state:
        plans = st.session_state["goal_plans"]
        feasible = [p for p in plans if p["goal_met"]]

        if not feasible:
            st.warning(
                f"No plan found reaches {goal_amount:,.0f} DZD in {goal_months} months "
                f"within realistic cut limits. Try a longer deadline or a lower goal."
            )
            shown = plans[:5]
        else:
            st.success(f"{len(feasible)} plan(s) reach the goal within {goal_months} months.")
            shown = feasible[:5]

        summary_df = pd.DataFrame([
            {
                "goal_met": p["goal_met"],
                "monthly_sacrifice_dzd": p["monthly_sacrifice_dzd"],
                "invest_aggressiveness": p["invest_aggressiveness"],
                "risk": p["risk"],
                "shortfall_dzd": p["shortfall_dzd"],
            }
            for p in shown
        ])
        st.dataframe(summary_df, use_container_width=True)

        plan_idx = st.selectbox(
            "Inspect a plan", range(len(shown)),
            format_func=lambda i: f"Plan {i+1} — sacrifice {shown[i]['monthly_sacrifice_dzd']:,.0f} DZD/mo"
        )
        selected_plan = shown[plan_idx]

        cuts_df = pd.DataFrame([
            {"category": cat, "cut_dzd": amt, "cut_pct": selected_plan["cuts"][cat]}
            for cat, amt in selected_plan["cut_amounts_dzd"].items() if amt > 0
        ])
        if not cuts_df.empty:
            st.bar_chart(cuts_df.set_index("category")["cut_dzd"])
            st.dataframe(cuts_df, use_container_width=True)
        else:
            st.write("No spending cuts needed for this plan — investment growth alone covers it.")

        st.caption(
            "Note: categories built from generic 'card_purchase' / 'cash_withdrawal' buckets "
            "are only as trustworthy as your manual_tag.py review. See pipeline/manual_tag.py."
        )

# --- Chat tab ---
with tab_chat:
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    question = st.chat_input("Ask about your budget, allocation, or goal plan...")
    if question:
        st.session_state["chat_history"].append({"role": "user", "content": question})
        context = chat_context_prompt(
            fc,
            st.session_state.get("pareto_front", [{}])[0] if "pareto_front" in st.session_state else None,
        )
        full_messages = [{"role": "user", "content": f"{context}\n\nQuestion: {question}"}]
        with st.spinner("Thinking..."):
            answer = ask_with_history(full_messages)
        st.session_state["chat_history"].append({"role": "assistant", "content": answer})
        st.rerun()
