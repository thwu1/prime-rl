#!/usr/bin/env python3
"""
Fix the 5 bugs in /app/gm_ops.py.

"""

SRC = "/app/gm_ops.py"

with open(SRC) as f:
    code = f.read()

# ===================================================================
# Bug 1 (gm_nll_loss): uses .mean(dim=-1) instead of .sum(dim=-1)
# for the Gaussian log-likelihood reduction over dimensions.
# The per-component log-likelihood must SUM over dimensions, not average.
# ===================================================================
code = code.replace(
    "(-0.5 * diff_weighted.square() - logstds).mean(dim=-1)",
    "(-0.5 * diff_weighted.square() - logstds).sum(dim=-1)",
    1,
)

# ===================================================================
# Bug 2 (gm_to_iso_gaussian): uses spread.sum(dim=-1, ...) instead of
# spread.mean(dim=-1, ...) for the isotropic variance.
# The isotropic variance averages the per-dimension spread to yield
# a single scalar, it does not sum them.
# ===================================================================
code = code.replace(
    "g_var = spread.sum(dim=-1, keepdim=True) + gm_vars.squeeze(1)",
    "g_var = spread.mean(dim=-1, keepdim=True) + gm_vars.squeeze(1)",
    1,
)

# ===================================================================
# Bug 3 (gm_mul_iso_gaussian): the power ratio is inverted.
# It should be gaussian_power / gm_power, not gm_power / gaussian_power.
# ===================================================================
code = code.replace(
    "power_ratio = gm_power / gaussian_power",
    "power_ratio = gaussian_power / gm_power",
    1,
)

# ===================================================================
# Bug 4 (gm_logprob): the logsumexp marginalisation over components
# does not include the log mixing weights. The correct computation
# must add the (squeezed, unsqueezed) logweights to the per-component
# Gaussian log-probabilities before the logsumexp.
# ===================================================================
code = code.replace(
    "    # Marginalize over components\n"
    "    logprob = torch.logsumexp(gaussian_logprobs, dim=-1)",
    "    # Marginalize over components\n"
    "    lw = logweights.squeeze(-1).unsqueeze(1)\n"
    "    logprob = torch.logsumexp(lw + gaussian_logprobs, dim=-1)",
    1,
)

# ===================================================================
# Bug 5 (gm_kl_div): uses .sum(dim=-1) instead of .mean(dim=-1) for
# the Monte Carlo average. The KL estimate must average over samples,
# not sum, to be independent of n_samples.
# ===================================================================
code = code.replace(
    "return (logp - logq).sum(dim=-1)",
    "return (logp - logq).mean(dim=-1)",
    1,
)

with open(SRC, "w") as f:
    f.write(code)

print("Fixed all 5 bugs in gm_ops.py")
