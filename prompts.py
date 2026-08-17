"""
Prompt templates for the advisor layer. Keeps the prompt engineering separate
from the API plumbing in client.py.
"""

SYSTEM_CONTEXT = """You are a personal budget advisor for someone in Algeria managing \
their finances in DZD. You have access to their real forecasted cash flow and a \
proposed investment allocation. Be direct, concrete, and use their actual numbers. \
Do not give generic financial advice — reference the specific figures provided. \
Flag when confidence in the forecast is low due to limited data history."""


def explain_forecast_prompt(forecast_result: dict) -> str:
    lines = [SYSTEM_CONTEXT, "", "Here is the current cash flow forecast:"]
    lines.append(f"- History available: {forecast_result['months_of_history']} month(s), "
                  f"confidence: {forecast_result['confidence']}")
    for i in range(forecast_result["months_ahead"]):
        lines.append(
            f"- Month +{i+1}: income {forecast_result['income_forecast'][i]:,.0f} DZD, "
            f"expenses {forecast_result['expenses_forecast'][i]:,.0f} DZD, "
            f"surplus {forecast_result['surplus_forecast'][i]:,.0f} DZD"
        )
    lines.append("")
    lines.append("In 3-4 sentences, explain what this forecast means practically, "
                  "and flag anything that looks risky or worth watching.")
    return "\n".join(lines)


def explain_allocation_prompt(allocation_point: dict, monthly_surplus: float) -> str:
    lines = [SYSTEM_CONTEXT, "", f"Monthly surplus available: {monthly_surplus:,.0f} DZD",
             f"Proposed allocation (expected return {allocation_point['expected_return']:.1%}, "
             f"risk {allocation_point['risk']:.1%}):"]
    for asset, amt in allocation_point["amounts_dzd"].items():
        lines.append(f"- {asset}: {amt:,.0f} DZD "
                      f"({allocation_point['allocation'][asset]:.0%})")
    lines.append("")
    lines.append("In 3-4 sentences, explain why this allocation makes sense given the "
                  "trade-off between return and risk, and what the person is giving up "
                  "by choosing this point on the Pareto front instead of a more "
                  "conservative or more aggressive one.")
    return "\n".join(lines)


def chat_context_prompt(forecast_result: dict, allocation_point: dict | None) -> str:
    """Builds a context block to prepend to a free-form chat question."""
    parts = [SYSTEM_CONTEXT, "", "Current data:"]
    parts.append(f"Average monthly surplus forecast: "
                  f"{forecast_result['avg_monthly_surplus']:,.0f} DZD "
                  f"(confidence: {forecast_result['confidence']})")
    if allocation_point:
        parts.append(f"Currently selected allocation: {allocation_point['allocation']}")
    return "\n".join(parts)
