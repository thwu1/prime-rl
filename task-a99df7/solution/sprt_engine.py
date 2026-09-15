#!/usr/bin/env python3
"""
SPRT analysis engine for chess engine testing.
Implements the generalized Sequential Probability Ratio Test using
constrained MLE on multinomial distributions, Brownian motion modeling
for confidence intervals, and multiple Elo model support.
"""

from __future__ import division

import copy
import json
import math

import scipy.optimize
import scipy.stats

# ============================================================
# Constants
# ============================================================

NELO_DIVIDED_BY_NT = 800 / math.log(10)


# ============================================================
# Core statistical functions
# ============================================================

def secular(pdf):
    """Solve the secular equation sum_i pi*ai/(1+x*ai)=0."""
    epsilon = 1e-9
    values = [ai for ai, pi in pdf]
    v = min(values)
    w = max(values)
    if v * w >= 0:
        raise ValueError("secular equation requires support straddling zero")
    lower_bound = -1 / w
    upper_bound = -1 / v

    def f(x):
        return sum([pi * ai / (1 + x * ai) for ai, pi in pdf])

    x, res = scipy.optimize.brentq(
        f, lower_bound + epsilon, upper_bound - epsilon,
        full_output=True, disp=False
    )
    if not res.converged:
        raise ValueError("secular root finding did not converge")
    return x


def stats(pdf):
    """Compute expectation and variance of a discrete distribution."""
    n = sum([prob for value, prob in pdf])
    s = sum([prob * value for value, prob in pdf])
    var = sum([prob * (value - s) ** 2 for value, prob in pdf])
    return s, var


def MLE_expected(pdfhat, s):
    """
    MLE for a discrete distribution with expectation value s,
    given empirical distribution pdfhat.
    """
    pdf1 = [(ai - s, pi) for ai, pi in pdfhat]
    x = secular(pdf1)
    pdf_MLE = [(ai, pi / (1 + x * (ai - s))) for ai, pi in pdfhat]
    return pdf_MLE


def MLE_t_value(pdfhat, ref, s):
    """
    MLE for a discrete distribution with t-value (mu-ref)/sigma = s,
    given empirical distribution pdfhat.
    """
    N = len(pdfhat)
    # Start with uniform
    pdf_MLE = [(ai, 1 / N) for ai, pi in pdfhat]
    for _ in range(10):
        pdf_ = pdf_MLE
        mu, var = stats(pdf_MLE)
        sigma = var ** 0.5
        pdf1 = [
            (ai - ref - s * sigma * (1 + ((mu - ai) / sigma) ** 2) / 2, pi)
            for ai, pi in pdfhat
        ]
        x = secular(pdf1)
        pdf_MLE = [
            (pdfhat[i][0], pdfhat[i][1] / (1 + x * pdf1[i][0]))
            for i in range(N)
        ]
        if max([abs(pdf_[i][1] - pdf_MLE[i][1]) for i in range(N)]) < 1e-9:
            break
    return pdf_MLE


def regularize(results):
    """Replace zero frequencies with small epsilon for numerical stability."""
    epsilon = 1e-3
    results = copy.copy(results)
    for i in range(len(results)):
        if results[i] == 0:
            results[i] = epsilon
    return results


def results_to_pdf(results):
    """Convert result frequencies to a probability distribution."""
    results = regularize(results)
    N = sum(results)
    count = len(results)
    return N, [(i / (count - 1), results[i] / N) for i in range(count)]


# ============================================================
# LLR computation
# ============================================================

def LLRjumps(pdf, s0, s1, ref=None, statistic="expectation"):
    if statistic == "expectation":
        pdf0, pdf1 = [MLE_expected(pdf, s) for s in (s0, s1)]
    elif statistic == "t_value":
        pdf0, pdf1 = [MLE_t_value(pdf, ref, s) for s in (s0, s1)]
    else:
        raise ValueError(f"Unknown statistic: {statistic}")
    return [
        (math.log(pdf1[i][1]) - math.log(pdf0[i][1]), pdf[i][1])
        for i in range(len(pdf))
    ]


def LLR(pdf, s0, s1, ref=None, statistic="expectation"):
    """Compute generalized log likelihood ratio (divided by N)."""
    return stats(LLRjumps(pdf, s0, s1, ref=ref, statistic=statistic))[0]


def L_(x):
    """Logistic function for Elo conversion."""
    return 1 / (1 + 10 ** (-x / 400))


def LLR_logistic(elo0, elo1, results):
    """Compute LLR using logistic Elo model."""
    s0, s1 = [L_(elo) for elo in (elo0, elo1)]
    N, pdf = results_to_pdf(results)
    return N * LLR(pdf, s0, s1, statistic="expectation")


def LLR_normalized(nelo0, nelo1, results):
    """Compute LLR using normalized Elo model."""
    nt0, nt1 = [nelo / NELO_DIVIDED_BY_NT for nelo in (nelo0, nelo1)]
    sqrt2 = 2 ** 0.5
    if len(results) == 3:
        t0, t1 = nt0, nt1
    elif len(results) == 5:
        t0, t1 = nt0 * sqrt2, nt1 * sqrt2
    else:
        raise ValueError("results must have 3 or 5 elements")
    N, pdf = results_to_pdf(results)
    return N * LLR(pdf, t0, t1, ref=0.5, statistic="t_value")


def LLR_drift_variance_alt2(pdf, s0, s1, s=None):
    """Approximate drift and variance of LLR process."""
    s_, v_ = stats(pdf)
    s_val, v = (s_, v_) if s is None else (s, v_ + (s - s_) ** 2)
    mu = (s_val - (s0 + s1) / 2) * (s1 - s0) / v
    var = (s1 - s0) ** 2 / v
    return mu, var


# ============================================================
# Brownian motion CDF
# ============================================================

def Phi(x):
    return scipy.stats.norm.cdf(x)


def U_func(n, gamma, A, y):
    """Primitive function for eigenfunction expansion."""
    return (
        2 * A * gamma * math.sin(math.pi * n * y / A)
        - 2 * math.pi * n * math.cos(math.pi * n * y / A)
    ) / (A ** 2 * gamma ** 2 + math.pi ** 2 * n ** 2)


class Brownian:
    def __init__(self, a=-1.0, b=1.0, mu=0.0, sigma=0.005):
        self.a = a
        self.b = b
        self.mu = mu
        self.sigma = sigma
        self.sigma2 = sigma ** 2

    def outcome_cdf(self, T=None, y=None):
        sigma2 = self.sigma2
        mu = self.mu
        gamma = mu / sigma2
        A = self.b - self.a
        if sigma2 * T / A ** 2 < 1e-2 or abs(gamma * A) > 15:
            ret = self.outcome_cdf_alt2(T, y)
        else:
            ret = self.outcome_cdf_alt1(T, y)
        return max(0.0, min(1.0, ret))

    def outcome_cdf_alt1(self, T=None, y=None):
        """Exact formula using eigenfunction expansion."""
        mu = self.mu
        sigma2 = self.sigma2
        A = self.b - self.a
        x = 0 - self.a
        y = y - self.a
        gamma = mu / sigma2
        n = 1
        s = 0.0
        lambda_1 = ((math.pi / A) ** 2) * sigma2 / 2 + (mu ** 2 / sigma2) / 2
        t0 = math.exp(-lambda_1 * T - x * gamma + y * gamma)
        while True:
            lambda_n = ((n * math.pi / A) ** 2) * sigma2 / 2 + (mu ** 2 / sigma2) / 2
            t1 = math.exp(-(lambda_n - lambda_1) * T)
            t3 = U_func(n, gamma, A, y)
            t4 = math.sin(n * math.pi * x / A)
            s += t1 * t3 * t4
            if abs(t0 * t1 * t3) <= 1e-9:
                break
            n += 1
        if gamma * A > 30:
            pre = math.exp(-2 * gamma * x)
        elif abs(gamma * A) < 1e-8:
            pre = (A - x) / A
        else:
            pre = (1 - math.exp(2 * gamma * (A - x))) / (1 - math.exp(2 * gamma * A))
        return pre + t0 * s

    def outcome_cdf_alt2(self, T=None, y=None):
        """Siegmund's approximation for slow convergence."""
        denom = math.sqrt(T * self.sigma2)
        offset = self.mu * T
        gamma = self.mu / self.sigma2
        a = self.a
        b = self.b
        z = (y - offset) / denom
        za = (-y + offset + 2 * a) / denom
        zb = (y - offset - 2 * b) / denom
        t1 = Phi(z)
        if gamma * a >= 5:
            t2 = (
                -math.exp(-(za ** 2) / 2 + 2 * gamma * a)
                / math.sqrt(2 * math.pi)
                * (1 / za - 1 / za ** 3)
            )
        else:
            t2 = math.exp(2 * gamma * a) * Phi(za)
        if gamma * b >= 5:
            t3 = (
                -math.exp(-(zb ** 2) / 2 + 2 * gamma * b)
                / math.sqrt(2 * math.pi)
                * (1 / zb - 1 / zb ** 3)
            )
        else:
            t3 = math.exp(2 * gamma * b) * Phi(zb)
        return t1 + t2 - t3


# ============================================================
# SPRT class
# ============================================================

class SPRT:
    def __init__(self, alpha=0.05, beta=0.05, elo0=0, elo1=5, elo_model="logistic"):
        assert elo_model in ("logistic", "normalized")
        self.elo_model = elo_model
        self.a = math.log(beta / (1 - alpha))
        self.b = math.log((1 - beta) / alpha)
        self.elo0 = elo0
        self.elo1 = elo1
        self.clamped = False

    def elo_to_score(self, elo):
        if self.elo_model == "normalized":
            nt = elo / NELO_DIVIDED_BY_NT
            return nt * self.sigma_pg + 0.5
        else:
            return L_(elo)

    def set_state(self, results):
        N, self.pdf = results_to_pdf(results)
        if self.elo_model == "normalized":
            mu, var = stats(self.pdf)
            if len(results) == 5:
                self.sigma_pg = (2 * var) ** 0.5
            elif len(results) == 3:
                self.sigma_pg = var ** 0.5
            else:
                raise ValueError("results must have 3 or 5 elements")
        self.s0, self.s1 = [self.elo_to_score(elo) for elo in (self.elo0, self.elo1)]

        mu_LLR, var_LLR = LLR_drift_variance_alt2(self.pdf, self.s0, self.s1, None)
        self.llr = N * mu_LLR
        self.T = N

        # Clamp LLR to SPRT bounds
        slope = self.llr / N
        if self.llr > 1.03 * self.b or self.llr < 1.03 * self.a:
            self.clamped = True
        if self.llr < self.a:
            self.T = self.a / slope
            self.llr = self.a
        elif self.llr > self.b:
            self.T = self.b / slope
            self.llr = self.b

    def outcome_prob(self, elo):
        s = L_(elo)
        mu_LLR, var_LLR = LLR_drift_variance_alt2(self.pdf, self.s0, self.s1, s)
        sigma_LLR = math.sqrt(var_LLR)
        return Brownian(a=self.a, b=self.b, mu=mu_LLR, sigma=sigma_LLR).outcome_cdf(
            T=self.T, y=self.llr
        )

    def lower_cb(self, p):
        avg_elo = (self.elo0 + self.elo1) / 2
        delta = self.elo1 - self.elo0
        N = 30
        while True:
            elo0 = max(avg_elo - N * delta, -1000)
            elo1 = min(avg_elo + N * delta, 1000)
            try:
                sol, res = scipy.optimize.brentq(
                    lambda elo: self.outcome_prob(elo) - (1 - p),
                    elo0, elo1, full_output=True, disp=False,
                )
            except ValueError:
                if elo0 > -1000 or elo1 < 1000:
                    N *= 2
                    continue
                else:
                    if self.outcome_prob(elo0) - (1 - p) > 0:
                        return elo1
                    else:
                        return elo0
            assert res.converged
            break
        return sol

    def analytics(self, p=0.05):
        ret = {}
        ret["a"] = self.a
        ret["b"] = self.b
        ret["elo"] = self.lower_cb(0.5)
        ret["ci"] = [self.lower_cb(p / 2), self.lower_cb(1 - p / 2)]
        ret["LOS"] = self.outcome_prob(0)
        ret["LLR"] = self.llr
        return ret


# ============================================================
# Elo model conversions
# ============================================================

def elo_from_score(x):
    epsilon = 1e-3
    x = max(x, epsilon)
    x = min(x, 1 - epsilon)
    return -400 * math.log10(1 / x - 1)


def bayeselo_to_proba(belo, drawelo):
    P = [0, 0, 0]
    P[2] = 1.0 / (1.0 + pow(10.0, (-belo + drawelo) / 400.0))
    P[0] = 1.0 / (1.0 + pow(10.0, (belo + drawelo) / 400.0))
    P[1] = 1.0 - P[2] - P[0]
    return P


def proba_to_bayeselo(P):
    elo = 200 * math.log10(P[2] / P[0] * (1 - P[0]) / (1 - P[2]))
    drawelo = 200 * math.log10((1 - P[0]) / P[0] * (1 - P[2]) / P[2])
    return elo, drawelo


def draw_elo_calc(R):
    N = sum(R)
    P = [p / N for p in R]
    _, drawelo = proba_to_bayeselo(P)
    return drawelo


def bayeselo_to_elo(belo, drawelo):
    P = bayeselo_to_proba(belo, drawelo)
    return elo_from_score(P[2] + 0.5 * P[1])


# ============================================================
# Main analysis function
# ============================================================

def analyze_run(run):
    run_id = run["id"]
    alpha = run["alpha"]
    beta = run["beta"]
    elo0 = run["elo0"]
    elo1 = run["elo1"]
    elo_model = run["elo_model"]
    R = run["results"]

    # Compute trinomial
    R3 = regularize([
        R.get("losses", 0),
        R.get("draws", 0),
        R.get("wins", 0),
    ])

    # Handle BayesElo model: convert bounds to logistic Elo
    if elo_model == "BayesElo":
        drawelo = draw_elo_calc(R3)
        elo0, elo1 = [bayeselo_to_elo(e, drawelo) for e in (elo0, elo1)]
        elo_model = "logistic"

    # Create SPRT object
    sp = SPRT(alpha=alpha, beta=beta, elo0=elo0, elo1=elo1, elo_model=elo_model)

    # Get results array (prefer pentanomial if available)
    if "pentanomial" in R:
        R_ = R["pentanomial"]
    else:
        R_ = R3

    # Set state and compute analytics
    sp.set_state(R_)
    analytics = sp.analytics(p=0.05)

    # Override LLR with exact computation
    if elo_model == "logistic":
        analytics["LLR"] = LLR_logistic(elo0, elo1, R_)
    else:
        analytics["LLR"] = LLR_normalized(elo0, elo1, R_)

    # Determine SPRT decision
    lower_bound = math.log(alpha * (1 - beta) / ((1 - alpha) * beta)) * -1
    lower_bound = math.log(beta / (1 - alpha))
    upper_bound = math.log((1 - beta) / alpha)

    if analytics["LLR"] < lower_bound:
        decision = "rejected"
    elif analytics["LLR"] > upper_bound:
        decision = "accepted"
    else:
        decision = "continue"

    return {
        "id": run_id,
        "LLR": analytics["LLR"],
        "decision": decision,
        "elo": analytics["elo"],
        "ci": analytics["ci"],
        "LOS": analytics["LOS"],
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
    }


def main():
    with open("/app/test_runs.json") as f:
        runs = json.load(f)

    results = []
    for run in runs:
        result = analyze_run(run)
        results.append(result)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
