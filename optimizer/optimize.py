"""
Growth optimizer — NSGA-II multi-objective allocation.

Given a monthly surplus (from the forecaster) and a set of asset classes with
assumed expected return and volatility, finds a Pareto front of allocations
trading off return vs risk, subject to constraints (weights sum to 1, minimum
cash floor for liquidity).

The ASSETS dict below is a starting point with illustrative numbers — replace
with your own return/volatility assumptions for DZD cash, gold, SGBV stocks,
etc. This is the same NSGA-II pattern as the Sonatrach portfolio project,
just re-pointed at personal asset classes instead of energy projects.

Usage:
    python optimizer/optimize.py --surplus 31500
"""
import argparse

import numpy as np
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.problem import Problem
from pymoo.optimize import minimize
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.operators.sampling.rnd import FloatRandomSampling

# --- Edit these to reflect your actual assumptions ---
# expected_return and volatility are illustrative annualized figures (0.10 = 10%/yr).
# Replace with numbers grounded in real data before relying on this for decisions.
ASSETS = {
    "cash_dzd":     {"expected_return": 0.03, "volatility": 0.01},
    "gold":         {"expected_return": 0.08, "volatility": 0.15},
    "sgbv_stocks":  {"expected_return": 0.15, "volatility": 0.30},
    "fixed_income": {"expected_return": 0.06, "volatility": 0.05},
}
ASSET_NAMES = list(ASSETS.keys())
N_ASSETS = len(ASSET_NAMES)

MIN_CASH_FLOOR = 0.15  # keep at least 15% liquid, non-negotiable emergency buffer


class AllocationProblem(Problem):
    """
    Decision variables: weight for each asset (0 to 1), normalized to sum to 1.
    Objective 1: minimize -expected_return (i.e. maximize return)
    Objective 2: minimize portfolio volatility (simplified, ignores correlation —
                 for a real model add a covariance matrix between assets)
    Constraint: cash weight >= MIN_CASH_FLOOR
    """

    def __init__(self):
        super().__init__(
            n_var=N_ASSETS,
            n_obj=2,
            n_constr=1,
            xl=np.zeros(N_ASSETS),
            xu=np.ones(N_ASSETS),
        )

    def _evaluate(self, X, out, *args, **kwargs):
        # Normalize each row so weights sum to 1
        weights = X / X.sum(axis=1, keepdims=True)

        returns = np.array([ASSETS[a]["expected_return"] for a in ASSET_NAMES])
        vols = np.array([ASSETS[a]["volatility"] for a in ASSET_NAMES])

        expected_return = weights @ returns
        # Simplified risk: weighted sum of volatilities (no correlation matrix yet).
        # Swap for sqrt(w.T @ cov_matrix @ w) once you have real covariance data.
        portfolio_vol = weights @ vols

        cash_idx = ASSET_NAMES.index("cash_dzd")
        cash_weight = weights[:, cash_idx]

        out["F"] = np.column_stack([-expected_return, portfolio_vol])
        out["G"] = np.column_stack([MIN_CASH_FLOOR - cash_weight])  # <= 0 satisfied


def run_optimizer(pop_size: int = 100, n_gen: int = 100) -> list[dict]:
    problem = AllocationProblem()
    algorithm = NSGA2(
        pop_size=pop_size,
        sampling=FloatRandomSampling(),
        crossover=SBX(prob=0.9, eta=15),
        mutation=PM(eta=20),
    )
    res = minimize(problem, algorithm, ("n_gen", n_gen), seed=1, verbose=False)

    weights = res.X / res.X.sum(axis=1, keepdims=True)
    returns = -res.F[:, 0]
    risks = res.F[:, 1]

    pareto_front = []
    for i in range(len(weights)):
        allocation = {ASSET_NAMES[j]: round(float(weights[i][j]), 3) for j in range(N_ASSETS)}
        pareto_front.append({
            "allocation": allocation,
            "expected_return": round(float(returns[i]), 4),
            "risk": round(float(risks[i]), 4),
        })

    # Sort by expected return so the printed front reads conservative -> aggressive
    pareto_front.sort(key=lambda p: p["expected_return"])
    return pareto_front


def apply_to_surplus(pareto_front: list[dict], monthly_surplus: float) -> list[dict]:
    """Converts weight allocations into actual DZD amounts for a given surplus."""
    result = []
    for point in pareto_front:
        amounts = {k: round(v * monthly_surplus) for k, v in point["allocation"].items()}
        result.append({**point, "amounts_dzd": amounts})
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--surplus", type=float, default=30000,
                     help="Monthly surplus in DZD to allocate")
    ap.add_argument("--n-points", type=int, default=5,
                     help="How many Pareto points to display (sampled evenly)")
    args = ap.parse_args()

    front = run_optimizer()
    front = apply_to_surplus(front, args.surplus)

    # Sample evenly across the front for a readable conservative -> aggressive spread
    idxs = np.linspace(0, len(front) - 1, args.n_points).astype(int)
    print(f"Pareto front for {args.surplus:,.0f} DZD monthly surplus "
          f"(min {MIN_CASH_FLOOR:.0%} cash floor):\n")
    for idx in idxs:
        p = front[idx]
        print(f"Return {p['expected_return']:.1%} / Risk {p['risk']:.1%}")
        for asset, amt in p["amounts_dzd"].items():
            print(f"    {asset:14s} {amt:>10,.0f} DZD  ({p['allocation'][asset]:.0%})")
        print()
