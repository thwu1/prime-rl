#!/usr/bin/env python3
"""
Solver for the particle physics statistical analysis task.

"""
import json
import numpy as np
import uproot
from scipy.optimize import minimize, brentq
from scipy.stats import norm


def load_data():
    """Load histogram data from ROOT file and model config."""
    with open("/app/model_config.json") as f:
        config = json.load(f)

    rootfile = uproot.open("/app/observations.root")

    channels = []
    nuisance_names = []
    seen_nuis = set()

    for ch_config in config["channels"]:
        obs_hist = rootfile[ch_config["observed_data_key"]]
        observed = np.array(obs_hist.values(), dtype=np.float64)

        samples = []
        for sample_config in ch_config["samples"]:
            nom_hist = rootfile[sample_config["nominal_key"]]
            nominal = np.array(nom_hist.values(), dtype=np.float64)

            modifiers = []
            for mod_config in sample_config["modifiers"]:
                mod = {"name": mod_config["name"], "type": mod_config["type"]}
                if mod_config["type"] == "normsys":
                    mod["kappa_hi"] = mod_config["kappa_hi"]
                    mod["kappa_lo"] = mod_config["kappa_lo"]
                    if mod_config["name"] not in seen_nuis:
                        nuisance_names.append(mod_config["name"])
                        seen_nuis.add(mod_config["name"])
                elif mod_config["type"] == "histosys":
                    hi_hist = rootfile[mod_config["hi_key"]]
                    lo_hist = rootfile[mod_config["lo_key"]]
                    mod["hi_yields"] = np.array(hi_hist.values(), dtype=np.float64)
                    mod["lo_yields"] = np.array(lo_hist.values(), dtype=np.float64)
                    if mod_config["name"] not in seen_nuis:
                        nuisance_names.append(mod_config["name"])
                        seen_nuis.add(mod_config["name"])
                modifiers.append(mod)

            samples.append({"nominal": nominal, "modifiers": modifiers})

        channels.append({"observed": observed, "samples": samples})

    rootfile.close()

    return channels, config["parameter_of_interest"], nuisance_names


class HistFactoryModel:
    """Binned Poisson likelihood with Gaussian-constrained nuisance parameters."""

    def __init__(self, channels, poi_name, nuisance_names):
        self.channels = channels
        self.poi_name = poi_name
        self.nuisance_names = nuisance_names

    def expected_yields(self, params):
        """Compute expected yields for all channels."""
        all_expected = []
        for chdata in self.channels:
            ch_expected = np.zeros_like(chdata["observed"])
            for sample in chdata["samples"]:
                yields = sample["nominal"].copy()

                # Apply shape modifiers (histosys) first
                for mod in sample["modifiers"]:
                    if mod["type"] == "histosys":
                        alpha = params[mod["name"]]
                        hi = mod["hi_yields"]
                        lo = mod["lo_yields"]
                        nom = sample["nominal"]
                        if alpha >= 0:
                            yields = nom + alpha * (hi - nom)
                        else:
                            yields = nom + alpha * (nom - lo)

                # Apply scale modifiers (normfactor, normsys)
                for mod in sample["modifiers"]:
                    if mod["type"] == "normfactor":
                        yields = yields * params[mod["name"]]
                    elif mod["type"] == "normsys":
                        alpha = params[mod["name"]]
                        khi = mod["kappa_hi"]
                        klo = mod["kappa_lo"]
                        if alpha >= 0:
                            scale = khi ** alpha
                        else:
                            scale = klo ** (-alpha)
                        yields = yields * scale

                ch_expected += yields
            all_expected.append(np.maximum(ch_expected, 1e-10))
        return all_expected

    def nll(self, params):
        """Negative log-likelihood (ignoring constant terms)."""
        all_expected = self.expected_yields(params)
        nll_val = 0.0
        for chdata, exp in zip(self.channels, all_expected):
            obs = chdata["observed"]
            nll_val += np.sum(exp - obs * np.log(exp))
        for name in self.nuisance_names:
            nll_val += 0.5 * params[name] ** 2
        return nll_val

    def params_from_array(self, arr, fixed_mu=None):
        """Convert parameter array to dictionary."""
        params = {}
        if fixed_mu is not None:
            params[self.poi_name] = fixed_mu
            for i, name in enumerate(self.nuisance_names):
                params[name] = arr[i]
        else:
            params[self.poi_name] = arr[0]
            for i, name in enumerate(self.nuisance_names):
                params[name] = arr[1 + i]
        return params

    def fit_global(self):
        """Unconditional MLE (mu free, mu >= 0)."""
        n_nuis = len(self.nuisance_names)
        best_result = None
        best_nll = float("inf")
        for mu_init in [0.0, 0.5, 1.0, 2.0, 5.0]:
            for a_init in [0.0, 0.3, -0.3]:
                x0 = [mu_init] + [a_init] + [0.0] * (n_nuis - 1)
                bounds = [(0, None)] + [(None, None)] * n_nuis
                try:
                    r = minimize(
                        lambda x: self.nll(self.params_from_array(x)),
                        x0, method="L-BFGS-B", bounds=bounds,
                    )
                    if r.fun < best_nll:
                        best_nll = r.fun
                        best_result = r
                except Exception:
                    pass
        params = self.params_from_array(best_result.x)
        return params, best_result.fun

    def fit_conditional(self, mu_val, start=None):
        """Conditional MLE with fixed mu."""
        n_nuis = len(self.nuisance_names)
        if start is None:
            start = [0.0] * n_nuis
        best_result = None
        best_nll = float("inf")
        starts = [start, [0.0] * n_nuis]
        if start != [0.0] * n_nuis:
            starts.append([0.1] * n_nuis)
        for s0 in starts:
            try:
                r = minimize(
                    lambda x: self.nll(self.params_from_array(x, fixed_mu=mu_val)),
                    s0, method="L-BFGS-B",
                )
                if r.fun < best_nll:
                    best_nll = r.fun
                    best_result = r
            except Exception:
                pass
        params = self.params_from_array(best_result.x, fixed_mu=mu_val)
        return params, best_result.fun

    def profile_nll(self, mu_val, nuis_start=None):
        """Profiled NLL at a given mu value."""
        _, nll_val = self.fit_conditional(mu_val, start=nuis_start)
        return nll_val


def compute_mu_error(model, mu_hat, nll_best, nuis_hat_list):
    """Estimate uncertainty on mu from profile likelihood curvature."""
    eps = 0.01
    nll_plus = model.profile_nll(mu_hat + eps, nuis_start=nuis_hat_list)
    nll_minus = model.profile_nll(max(0, mu_hat - eps), nuis_start=nuis_hat_list)
    nll_center = nll_best

    if mu_hat - eps < 0:
        eps2 = 0.02
        nll_plus2 = model.profile_nll(mu_hat + eps2, nuis_start=nuis_hat_list)
        d2 = (nll_plus2 - 2 * nll_plus + nll_center) / (eps ** 2)
    else:
        d2 = (nll_plus - 2 * nll_center + nll_minus) / (eps ** 2)

    if d2 > 0:
        return 1.0 / np.sqrt(d2)

    profile_pts = []
    for mu_test in np.linspace(max(0, mu_hat - 1.5), mu_hat + 1.5, 25):
        pnll = model.profile_nll(mu_test, nuis_start=nuis_hat_list)
        profile_pts.append((mu_test, pnll - nll_best))
    profile_pts = np.array(profile_pts)
    mask = profile_pts[:, 1] < 2.0
    if np.sum(mask) > 3:
        coeffs = np.polyfit(profile_pts[mask, 0], profile_pts[mask, 1], 2)
        if coeffs[0] > 0:
            return 1.0 / np.sqrt(2 * coeffs[0])
    return 0.5


def compute_cls(q_mu, mu_test, sigma):
    """Compute CLs using asymptotic formulae."""
    if q_mu <= 0:
        return 1.0
    sqrt_q = np.sqrt(q_mu)
    p_sb = 1.0 - norm.cdf(sqrt_q)
    p_b = 1.0 - norm.cdf(sqrt_q - mu_test / sigma)
    if p_b <= 0:
        return 0.0
    return p_sb / p_b


def main():
    channels, poi_name, nuisance_names = load_data()
    model = HistFactoryModel(channels, poi_name, nuisance_names)

    # Global fit
    params_hat, nll_best = model.fit_global()
    mu_hat = params_hat[model.poi_name]
    nuis_hat_list = [params_hat[n] for n in model.nuisance_names]

    # Mu uncertainty
    mu_error = compute_mu_error(model, mu_hat, nll_best, nuis_hat_list)

    # Discovery test statistic
    _, nll_mu0 = model.fit_conditional(0.0, start=nuis_hat_list)
    q0 = 2.0 * (nll_mu0 - nll_best) if mu_hat > 0 else 0.0
    q0 = max(q0, 0.0)
    significance = np.sqrt(q0)
    p_value = 1.0 - norm.cdf(significance)

    # CLs at mu=1
    nll_mu1 = model.profile_nll(1.0, nuis_start=nuis_hat_list)
    q_mu1 = max(2.0 * (nll_mu1 - nll_best), 0.0) if mu_hat <= 1.0 else 0.0
    cls_mu1 = compute_cls(q_mu1, 1.0, mu_error)

    # 95% CLs upper limit
    sigma = mu_error

    def cls_at_mu(mu_val):
        nll_mu = model.profile_nll(mu_val, nuis_start=nuis_hat_list)
        qmu = max(2.0 * (nll_mu - nll_best), 0.0) if mu_hat <= mu_val else 0.0
        return compute_cls(qmu, mu_val, sigma)

    try:
        mu_lo = mu_hat + 0.01
        mu_hi = mu_hat + 2.0
        while cls_at_mu(mu_hi) > 0.05 and mu_hi < 20:
            mu_hi += 1.0
        upper_limit_95 = brentq(
            lambda mu: cls_at_mu(mu) - 0.05, mu_lo, mu_hi, xtol=1e-4
        )
    except Exception:
        upper_limit_95 = -1.0

    results = {
        "mu_hat": float(round(mu_hat, 6)),
        "mu_hat_error": float(round(mu_error, 6)),
        "significance": float(round(significance, 6)),
        "p_value": float(round(p_value, 8)),
        "cls_mu1": float(round(cls_mu1, 6)),
        "upper_limit_95": float(round(upper_limit_95, 6)),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json:")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
