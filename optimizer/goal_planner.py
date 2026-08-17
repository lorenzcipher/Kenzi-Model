"""
Goal-based savings planner — NSGA-II with 3 objectives.

Unlike optimizer/optimize.py (which allocates an existing surplus across
asset classes), this answers a different question: "I want to reach X DZD
in N months — what combination of spending cuts and investment risk gets
me there, and what's the cheapest way to do it?"

Each candidate plan picks:
  1. How much to cut from each DISCRETIONARY category (essentials are
     never touched — see ESSENTIAL_CATEGORIES below)
  2. How aggressively to invest the resulting monthly savings (0 = pure
     cash, 1 = maximum growth assets, same return/risk assumptions as
     optimizer/optimize.py's cash_dzd and sgbv_stocks entries)

Three objectives, all minimized:
  - shortfall: how far short of the goal this plan lands (0 = goal met)
  - sacrifice: total DZD/month cut from discretionary spending
  - risk:      the investment volatility implied by the chosen aggressiveness

Usage:
    python optimizer/goal_planner.py --goal 1000000 --months 12
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.problem import Problem
from pymoo.optimize import minimize
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.operators.sampling.rnd import FloatRandomSampling

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.schema import get_connection

# Categories that are never touched, regardless of how aggressive the plan is.
ESSENTIAL_CATEGORIES = {"rent", "utilities", "telecom", "health", "income", "transfer_in"}

MAX_CUT_FRACTION = 0.6  # never propose cutting more than 60% of a category — unrealistic

# Same illustrative return/volatility extremes as optimizer/optimize.py.
CASH_RATE, AGGR_RATE = 0.03, 0.15
CASH_VOL, AGGR_VOL = 0.01, 0.30


def load_discretionary_baselines() -> tuple[list[str], np.ndarray, float]:
    """
    Returns (category_names, avg_monthly_spend_per_category, avg_monthly_surplus)
    computed from whatever transaction history exists so far.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT category, tx_date, amount FROM transactions WHERE amount < 0"
    )
    rows = cur.fetchall()
    cur.execute(
        "SELECT tx_date, SUM(amount) FROM transactions GROUP BY substr(tx_date,1,7)"
    )
    monthly_net = cur.fetchall()
    conn.close()

    if not rows:
        raise ValueError("No transactions found. Run pipeline/ingest.py first.")

    months = {r[1][:7] for r in rows}
    n_months = max(len(months), 1)

    totals: dict[str, float] = {}
    for category, _, amount in rows:
        if category in ESSENTIAL_CATEGORIES:
            continue
        totals[category] = totals.get(category, 0.0) + abs(amount)

    categories = list(totals.keys())
    baselines = np.array([totals[c] / n_months for c in categories])

    avg_surplus = float(np.mean([net for _, net in monthly_net])) if monthly_net else 0.0

    return categories, baselines, avg_surplus


class GoalPlanningProblem(Problem):
    def __init__(self, categories, baselines, base_surplus, goal, months):
        self.categories = categories
        self.baselines = baselines
        self.base_surplus = base_surplus
        self.goal = goal
        self.months = months
        n_cat = len(categories)
        super().__init__(
            n_var=n_cat + 1,  # one cut-fraction per category + one invest_aggressiveness
            n_obj=3,
            n_constr=0,
            xl=np.zeros(n_cat + 1),
            xu=np.ones(n_cat + 1),
        )

    def _evaluate(self, X, out, *args, **kwargs):
        n_cat = len(self.categories)
        cuts = X[:, :n_cat] * MAX_CUT_FRACTION       # 0 to 60% per category
        invest_aggr = X[:, n_cat]                     # 0 (cash) to 1 (aggressive)

        extra_savings = cuts @ self.baselines          # DZD/month freed up by cutting
        monthly_savings = self.base_surplus + extra_savings

        annual_return = CASH_RATE + invest_aggr * (AGGR_RATE - CASH_RATE)
        monthly_rate = (1 + annual_return) ** (1 / 12) - 1

        # Future value of a monthly savings stream (ordinary annuity), starting from 0.
        fv = np.where(
            monthly_rate > 1e-9,
            monthly_savings * (((1 + monthly_rate) ** self.months - 1) / monthly_rate),
            monthly_savings * self.months,
        )

        shortfall = np.maximum(self.goal - fv, 0)
        sacrifice = extra_savings
        risk = CASH_VOL + invest_aggr * (AGGR_VOL - CASH_VOL)

        out["F"] = np.column_stack([shortfall, sacrifice, risk])


def run_goal_planner(goal: float, months: int, pop_size: int = 150, n_gen: int = 150) -> list[dict]:
    categories, baselines, base_surplus = load_discretionary_baselines()
    problem = GoalPlanningProblem(categories, baselines, base_surplus, goal, months)

    algorithm = NSGA2(
        pop_size=pop_size,
        sampling=FloatRandomSampling(),
        crossover=SBX(prob=0.9, eta=15),
        mutation=PM(eta=20),
    )
    res = minimize(problem, algorithm, ("n_gen", n_gen), seed=1, verbose=False)

    n_cat = len(categories)
    plans = []
    for i in range(len(res.X)):
        cuts = res.X[i, :n_cat] * MAX_CUT_FRACTION
        invest_aggr = float(res.X[i, n_cat])
        shortfall, sacrifice, risk = res.F[i]

        plans.append({
            "cuts": {categories[j]: round(float(cuts[j]), 3) for j in range(n_cat)},
            "cut_amounts_dzd": {
                categories[j]: round(float(cuts[j] * baselines[j])) for j in range(n_cat)
            },
            "invest_aggressiveness": round(invest_aggr, 3),
            "shortfall_dzd": round(float(shortfall)),
            "monthly_sacrifice_dzd": round(float(sacrifice)),
            "risk": round(float(risk), 4),
            "goal_met": bool(shortfall <= 1),
        })

    # Feasible plans (goal actually met) sorted by least sacrifice first
    plans.sort(key=lambda p: (not p["goal_met"], p["monthly_sacrifice_dzd"], p["risk"]))
    return plans


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", type=float, default=1_000_000, help="Target amount in DZD")
    ap.add_argument("--months", type=int, default=12, help="Deadline in months")
    ap.add_argument("--n-points", type=int, default=5, help="How many plans to display")
    args = ap.parse_args()

    plans = run_goal_planner(args.goal, args.months)
    feasible = [p for p in plans if p["goal_met"]]

    print(f"Goal: {args.goal:,.0f} DZD in {args.months} months\n")
    if not feasible:
        best = plans[0]
        print(f"No plan in this search reaches the goal. Closest gets within "
              f"{best['shortfall_dzd']:,.0f} DZD of it.")
        print("Consider a longer deadline, a lower goal, or check MAX_CUT_FRACTION.\n")

    shown = feasible[:args.n_points] if feasible else plans[:args.n_points]
    for p in shown:
        status = "GOAL MET" if p["goal_met"] else f"short by {p['shortfall_dzd']:,.0f} DZD"
        print(f"[{status}] sacrifice={p['monthly_sacrifice_dzd']:,.0f} DZD/mo  "
              f"invest_aggressiveness={p['invest_aggressiveness']:.0%}  risk={p['risk']:.1%}")
        for cat, amt in p["cut_amounts_dzd"].items():
            if amt > 0:
                print(f"    cut {cat:16s} {amt:>8,.0f} DZD/mo ({p['cuts'][cat]:.0%})")
        print()
