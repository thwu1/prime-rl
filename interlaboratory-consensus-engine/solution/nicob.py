
"""NIST Consensus Builder (NICOB) Statistical Engine.

Implements interlaboratory consensus analysis:
- Modified DerSimonian-Laird with HKSJ correction
- Biggerstaff-Tweedie gamma approximation for tau-squared sampling
- Linear Opinion Pool mixture model
- Unilateral and Bilateral Degrees of Equivalence
"""

import numpy as np
from scipy import stats


def parse_ncb(filepath):
    """Parse a NICOB .ncb configuration file."""
    config = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, val = line.split("=", 1)
            config[key.strip()] = val.strip()

    labels = [s.strip() for s in config["lablabels"].split(",")]
    x = np.array([float(s) for s in config["mean"].split(",") if s.strip()])
    u = np.array([float(s) for s in config["se"].split(",") if s.strip()])

    df_str = config.get("df", "").strip()
    if df_str:
        parts = [s.strip() for s in df_str.split(",") if s.strip()]
        if len(parts) == len(x):
            nu = np.array([float(s) for s in parts])
        else:
            nu = np.full(len(x), np.inf)
    else:
        nu = np.full(len(x), np.inf)

    coverage = float(config.get("coverage", "0.95"))
    return {"labels": labels, "x": x, "u": u, "nu": nu, "coverage": coverage}


def dersimonian_laird(x, u, coverage=0.95):
    """Modified DerSimonian-Laird with HKSJ correction."""
    n = len(x)
    w0 = 1.0 / u**2
    x0 = np.sum(w0 * x) / np.sum(w0)

    S1 = np.sum(w0)
    S2 = np.sum(w0**2)

    tau2 = max(0.0, (np.sum(w0 * (x - x0) ** 2) - (n - 1)) / (S1 - S2 / S1))

    w = 1.0 / (u**2 + tau2)
    mu = np.sum(w * x) / np.sum(w)

    qstar = max(1.0, np.sum(w * (x - mu) ** 2) / (n - 1))
    se = np.sqrt(qstar / np.sum(w))
    df = n - 1

    t_crit = stats.t.ppf((1 + coverage) / 2, df)
    hw = np.sqrt(qstar) * se * t_crit

    return {
        "mu": float(mu),
        "se": float(se),
        "ci_lb": float(mu - hw),
        "ci_ub": float(mu + hw),
        "tau2": float(tau2),
        "tau": float(np.sqrt(tau2)),
        "qstar": float(qstar),
        "weights": w.tolist(),
        "df": int(df),
    }


def _dl_mu(x, u):
    """Plain DL consensus value (no HKSJ). For internal bootstrap use."""
    n = len(x)
    w0 = 1.0 / u**2
    x0 = np.sum(w0 * x) / np.sum(w0)
    S1 = np.sum(w0)
    S2 = np.sum(w0**2)
    tau2 = max(0.0, (np.sum(w0 * (x - x0) ** 2) - (n - 1)) / (S1 - S2 / S1))
    w = 1.0 / (u**2 + tau2)
    return float(np.sum(w * x) / np.sum(w))


def sample_tau2(y, sigma, rng=None):
    """Sample tau-squared via Biggerstaff-Tweedie (1997) gamma approximation."""
    if rng is None:
        rng = np.random.default_rng()

    K = len(y)
    w = 1.0 / sigma**2

    S1 = np.sum(w)
    S2 = np.sum(w**2)
    S3 = np.sum(w**3)

    c = S1 - S2 / S1
    if c == 0:
        return 0.0

    muhat = np.sum(w * y) / S1
    Q = np.sum(w * (y - muhat) ** 2)

    tau2_hat_M = (Q - (K - 1)) / c

    # Moments of Q at tau2_hat_M
    E_Q = (K - 1) + c * tau2_hat_M  # equals Q
    Var_Q = (
        2 * (K - 1)
        + 4 * c * tau2_hat_M
        + 2 * (S2 - 2 * S3 / S1 + S2**2 / S1**2) * tau2_hat_M**2
    )

    if Var_Q <= 0:
        Var_Q = 1e-10
    if E_Q <= 0:
        return 0.0

    r = E_Q**2 / Var_Q  # shape
    lam = E_Q / Var_Q  # rate

    Q_sample = rng.gamma(shape=r, scale=1.0 / lam)

    return max(0.0, (Q_sample - (K - 1)) / c)


def symmetrical_bootstrap_ci(x, estimate, coverage):
    """Half-width of symmetric coverage interval via bisection."""
    x = np.asarray(x, dtype=float)
    m = len(x)
    Umax = float(np.max(np.abs(x - estimate)))
    Udelta = float(np.max(x) - np.min(x)) / m

    x1 = Umax
    x0_val = 0.0
    iteration = 0

    while iteration < 10_000_000 and (x1 - x0_val) > Udelta:
        iteration += 1
        x3 = (x1 + x0_val) / 2
        frac = np.sum((estimate - x3 <= x) & (x <= estimate + x3)) / m
        if frac < coverage:
            x0_val = x3
        else:
            x1 = x3

    return (x1 + x0_val) / 2


def linear_pool(x, ux, nu, weights, m, rng=None):
    """Draw m samples from the Linear Opinion Pool mixture."""
    if rng is None:
        rng = np.random.default_rng()

    n = len(x)
    w_norm = np.asarray(weights, dtype=float)
    w_norm = w_norm / w_norm.sum()

    index = rng.choice(n, size=m, p=w_norm)
    mu_s = x[index]
    sigma_s = ux[index]

    y = np.zeros(m)

    if nu is not None and len(nu) > 0 and not np.all(np.isnan(nu)):
        nu_s = nu[index]

        inf_mask = np.isinf(nu_s)
        gt2_mask = (~inf_mask) & (nu_s > 2)
        le2_mask = (~inf_mask) & (nu_s <= 2)

        a = 0.4668994
        b = -0.3998882

        if np.any(gt2_mask):
            factor = sigma_s[gt2_mask] / np.sqrt(
                nu_s[gt2_mask] / (nu_s[gt2_mask] - 2)
            )
            y[gt2_mask] = mu_s[gt2_mask] + rng.standard_t(nu_s[gt2_mask]) * factor

        if np.any(le2_mask):
            nu_le2 = nu_s[le2_mask]
            phi = 1.5 * (
                (1 - (3 / 4) * (a - 4 * b * (nu_le2 ** (-3 / 4) - 1) / 3))
                ** (-4 / 3)
            )
            factor = sigma_s[le2_mask] / phi
            y[le2_mask] = mu_s[le2_mask] + rng.standard_t(nu_le2) * factor

        if np.any(inf_mask):
            y[inf_mask] = rng.normal(mu_s[inf_mask], sigma_s[inf_mask])
    else:
        y = rng.normal(mu_s, sigma_s)

    return y


def _phi_factor(nu_val):
    """Compute phi factor for scaling t-distribution."""
    a = 0.4668994
    b = -0.3998882
    if nu_val <= 2:
        return 1.5 * (
            (1 - (3 / 4) * (a - 4 * b * (nu_val ** (-3 / 4) - 1) / 3)) ** (-4 / 3)
        )
    else:
        return np.sqrt(nu_val / (nu_val - 2))


def doe_unilateral_dl(x, u, nu, labels, K, LOO, coverage, dl_result, rng=None):
    """Parametric bootstrap for unilateral degrees of equivalence."""
    if rng is None:
        rng = np.random.default_rng()

    n = len(x)
    mu = dl_result["mu"]

    D = np.zeros((K, n))

    if LOO:
        DoE_x = np.zeros(n)
        for j in range(n):
            xj = np.delete(x, j)
            uj = np.delete(u, j)
            nj = len(xj)

            # Sample tau2 K times from leave-one-out data
            tau2B = np.array([sample_tau2(xj, uj, rng) for _ in range(K)])

            # LOO modified HKSJ for point estimate and SE
            wj0 = 1.0 / uj**2
            xj0 = np.sum(wj0 * xj) / np.sum(wj0)
            Sj1 = np.sum(wj0)
            Sj2 = np.sum(wj0**2)
            tauj2 = max(
                0.0,
                (np.sum(wj0 * (xj - xj0) ** 2) - (nj - 1)) / (Sj1 - Sj2 / Sj1),
            )
            wj = 1.0 / (uj**2 + tauj2)
            muj = np.sum(wj * xj) / np.sum(wj)
            qSTAR = max(1.0, np.sum(wj * (xj - muj) ** 2) / (nj - 1))
            muj_u = np.sqrt(qSTAR / np.sum(wj))
            muj_df = nj - 1

            muj_phi = _phi_factor(muj_df)

            # Bootstrap replicates of LOO consensus via t-approximation
            mujB = float(muj) + muj_u * rng.standard_t(muj_df, size=K) / muj_phi

            DoE_x[j] = x[j] - muj

            # Lab j measurement noise
            sigmaj = np.sqrt(tau2B + u[j] ** 2)

            if np.isinf(nu[j]):
                ej = rng.normal(0, sigmaj)
            else:
                phi_j = _phi_factor(nu[j])
                ej = sigmaj * rng.standard_t(nu[j], size=K) / phi_j

            D[:, j] = x[j] + ej - mujB
    else:
        # MRA mode
        DoE_x = x - mu
        inf_mask = np.isinf(nu)

        for k in range(K):
            tau2B = sample_tau2(x, u, rng)

            xB = rng.normal(mu, np.sqrt(tau2B + u**2))

            uB = u.copy()
            finite = ~inf_mask
            if np.any(finite):
                uB[finite] = u[finite] * np.sqrt(
                    nu[finite] / rng.chisquare(nu[finite])
                )

            muB = _dl_mu(xB, uB)
            D[k, :] = xB - muB

        # Center columns at zero, then shift to DoE_x
        DC = D - D.mean(axis=0)
        D = DC + DoE_x

    # Compute intervals
    DoE_Lwr = np.quantile(D, (1 - coverage) / 2, axis=0)
    DoE_Upr = np.quantile(D, (1 + coverage) / 2, axis=0)
    DoE_U = np.array(
        [symmetrical_bootstrap_ci(D[:, j], DoE_x[j], coverage) for j in range(n)]
    )

    DoE_list = []
    for j in range(n):
        DoE_list.append(
            {
                "lab": labels[j],
                "DoE_x": float(DoE_x[j]),
                "DoE_U95": float(DoE_U[j]),
                "DoE_Lwr": float(DoE_Lwr[j]),
                "DoE_Upr": float(DoE_Upr[j]),
            }
        )

    return {"D": D, "DoE": DoE_list}


def doe_bilateral_dl(x, u, nu, labels, coverage, unilateral_result):
    """Pairwise bilateral degrees of equivalence from unilateral D matrix."""
    D_uni = unilateral_result["D"]
    DoE_uni = unilateral_result["DoE"]
    n = len(x)

    B_x = np.zeros((n, n))
    B_U = np.zeros((n, n))
    B_Lwr = np.zeros((n, n))
    B_Upr = np.zeros((n, n))

    for j1 in range(n - 1):
        for j2 in range(j1 + 1, n):
            Bj = D_uni[:, j1] - D_uni[:, j2]
            B_x[j1, j2] = DoE_uni[j1]["DoE_x"] - DoE_uni[j2]["DoE_x"]
            B_x[j2, j1] = -B_x[j1, j2]
            B_Lwr[j1, j2] = np.quantile(Bj, (1 - coverage) / 2)
            B_Upr[j1, j2] = np.quantile(Bj, (1 + coverage) / 2)
            B_Lwr[j2, j1] = -B_Upr[j1, j2]
            B_Upr[j2, j1] = -B_Lwr[j1, j2]
            B_U[j1, j2] = symmetrical_bootstrap_ci(Bj, np.mean(Bj), coverage)
            B_U[j2, j1] = B_U[j1, j2]

    return {
        "B_x": B_x.tolist(),
        "B_U": B_U.tolist(),
        "B_Lwr": B_Lwr.tolist(),
        "B_Upr": B_Upr.tolist(),
        "labels": labels,
    }
