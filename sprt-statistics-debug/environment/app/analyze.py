#!/usr/bin/env python3
"""
SPRT Analysis CLI Tool

Computes Elo estimates and confidence intervals from chess engine
game results using the Sequential Probability Ratio Test framework.
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stats import LLRcalc
from stats.sprt import sprt


def main():
    parser = argparse.ArgumentParser(
        description="SPRT Statistical Analysis for Chess Engine Testing"
    )
    parser.add_argument(
        "--alpha", help="probability of a false positive", type=float, default=0.05
    )
    parser.add_argument(
        "--beta", help="probability of a false negative", type=float, default=0.05
    )
    parser.add_argument(
        "--elo0", help="H0 (expressed in LogisticElo)", type=float, default=0.0
    )
    parser.add_argument(
        "--elo1", help="H1 (expressed in LogisticElo)", type=float, default=5.0
    )
    parser.add_argument("--level", help="confidence level", type=float, default=0.95)
    parser.add_argument(
        "--elo-model",
        help="logistic or normalized",
        choices=["logistic", "normalized"],
        default="logistic",
    )
    parser.add_argument(
        "--results",
        help="trinomial or pentanomial frequencies, low to high",
        nargs="*",
        type=int,
        required=True,
    )
    args = parser.parse_args()

    results = args.results
    if len(results) != 3 and len(results) != 5:
        parser.error("argument --results: expected 3 or 5 arguments")

    alpha = args.alpha
    beta = args.beta
    elo0 = args.elo0
    elo1 = args.elo1
    elo_model = args.elo_model
    p = 1 - args.level

    s = sprt(alpha=alpha, beta=beta, elo0=elo0, elo1=elo1, elo_model=elo_model)
    s.set_state(results)
    a = s.analytics(p)

    print("Design parameters")
    print("=================")
    print("False positives             :  {:4.2%}".format(alpha))
    print("False negatives             :  {:4.2%}".format(beta))
    print("[Elo0,Elo1]                 :  [{:.2f},{:.2f}]".format(elo0, elo1))
    print("Confidence level            :  {:4.2%}".format(1 - p))
    print("Elo model                   :  {}".format(elo_model))
    print("Estimates")
    print("=========")
    print("Elo                         :  {:.4f}".format(a["elo"]))
    print(
        "Confidence interval         :  [{:.4f},{:.4f}] ({:4.2%})".format(
            a["ci"][0], a["ci"][1], 1 - p
        )
    )
    print("LOS                         :  {:.4f}".format(a["LOS"]))
    print("Context")
    print("=======")
    print(
        "LLR [a,b]                   :  {:.4f} {} [{:.4f},{:.4f}]".format(
            a["LLR"], "(clamped)" if a["clamped"] else "", a["a"], a["b"]
        )
    )


if __name__ == "__main__":
    main()
