"""
Tests for the fixed hierarchical AR(1) Stan model.
Verifies MCMC diagnostics: no divergent transitions, acceptable R-hat,
ESS, E-BFMI, and AR coefficient recovery.

"""

import subprocess
import os
import json
import re
import pytest

CMDSTAN = os.environ.get("CMDSTAN", "/opt/cmdstan")
STAN_FILE = "/app/fixed_model.stan"
MODEL_BINARY = "/app/fixed_model"
DATA_FILE = "/app/data.json"
NUM_CHAINS = 4
SEED = 1234

# Sampler diagnostic parameters — not model parameters, should be excluded
# from convergence checks. stepsize__ in particular differs by design across
# chains (each chain adapts independently).
DIAGNOSTIC_PARAMS = {
    "lp__", "accept_stat__", "stepsize__", "treedepth__",
    "divergent__", "energy__", "n_leapfrog__",
}


def _parse_stansummary(stdout):
    """Parse stansummary text output into dict of param -> {mean, ess, rhat}."""
    results = {}
    for line in stdout.split("\n"):
        parts = line.split()
        if len(parts) < 9:
            continue
        name = parts[0]
        try:
            mean = float(parts[1])
            ess = float(parts[-3])
            rhat = float(parts[-1])
            results[name] = {"mean": mean, "ess": ess, "rhat": rhat}
        except (ValueError, IndexError):
            continue
    return results


def _count_divergences(csv_file):
    """Count divergent transitions in a CmdStan output CSV."""
    count = 0
    header = None
    div_idx = None
    with open(csv_file, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            cols = line.split(",")
            if header is None:
                header = cols
                for i, c in enumerate(header):
                    if c.strip() == "divergent__":
                        div_idx = i
                        break
                continue
            if div_idx is not None and div_idx < len(cols):
                count += int(float(cols[div_idx].strip()))
    return count


def _clean_stale_artifacts():
    """Remove stale compilation artifacts to ensure clean build."""
    for ext in [".hpp", ".o", ".d", ""]:
        path = MODEL_BINARY + ext
        if os.path.exists(path) and (ext != "" or os.path.isfile(path)):
            try:
                os.remove(path)
            except OSError:
                pass


@pytest.fixture(scope="session")
def output_files():
    """Compile the fixed model and run MCMC sampling on 4 chains."""
    assert os.path.exists(STAN_FILE), (
        "Fixed model not found at {}. Save your corrected model there.".format(STAN_FILE)
    )

    # Clean any stale compilation artifacts from prior runs
    _clean_stale_artifacts()

    # Compile with O=0 to avoid slow -O3 compilation
    result = subprocess.run(
        ["make", "O=0", MODEL_BINARY],
        cwd=CMDSTAN,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        "Model compilation failed:\n{}".format(
            (result.stdout + "\n" + result.stderr)[-1500:]
        )
    )
    assert os.path.isfile(MODEL_BINARY), "Compiled model binary not found"

    # Run chains sequentially
    files = []
    for chain_id in range(1, NUM_CHAINS + 1):
        outfile = "/app/test_chain_{}.csv".format(chain_id)
        files.append(outfile)
        result = subprocess.run(
            [
                MODEL_BINARY,
                "sample",
                "num_warmup=500",
                "num_samples=500",
                "random",
                "seed={}".format(SEED),
                "id={}".format(chain_id),
                "data",
                "file={}".format(DATA_FILE),
                "output",
                "file={}".format(outfile),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            "Chain {} sampling failed:\n{}".format(
                chain_id, (result.stderr)[-500:]
            )
        )

    return files


def test_model_exists():
    """The fixed Stan model must exist at /app/fixed_model.stan."""
    assert os.path.exists(STAN_FILE)
    with open(STAN_FILE, "r") as f:
        content = f.read()
    assert len(content) > 100, "Model file appears empty or trivial"
    assert "model" in content, "File does not look like a Stan model"


def test_model_has_ar_structure():
    """The model must retain AR(1) time-series structure with lagged observations."""
    with open(STAN_FILE, "r") as f:
        content = f.read()
    assert "t-1" in content or "t - 1" in content, (
        "Model must reference lagged values (t-1) for AR(1) structure"
    )


def test_no_divergent_transitions(output_files):
    """All chains must have zero divergent transitions."""
    total = sum(_count_divergences(f) for f in output_files)
    assert total == 0, (
        "Found {} divergent transitions across {} chains".format(total, NUM_CHAINS)
    )


def test_ebfmi(output_files):
    """E-BFMI must be above 0.2 for all chains."""
    result = subprocess.run(
        ["{}/bin/diagnose".format(CMDSTAN)] + output_files,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = result.stdout + "\n" + result.stderr

    # Check for low E-BFMI warnings
    low_vals = re.findall(r"Chain\s+\d+:\s+E-BFMI\s*=\s*([\d.]+)", output)
    for val in low_vals:
        assert float(val) >= 0.2, "E-BFMI = {} is below threshold 0.2".format(val)

    assert "E-BFMI below" not in output, (
        "Low E-BFMI warning detected:\n{}".format(output)
    )


def test_rhat(output_files):
    """Split R-hat must be below 1.05 for all model parameters.

    Sampler diagnostic parameters (stepsize__, treedepth__, etc.) are excluded
    because they are per-chain adaptation quantities, not model parameters —
    e.g. stepsize__ is independently adapted per chain and is expected to differ.
    """
    result = subprocess.run(
        ["{}/bin/stansummary".format(CMDSTAN)] + output_files,
        capture_output=True,
        text=True,
        timeout=60,
    )
    params = _parse_stansummary(result.stdout)
    assert len(params) > 0, (
        "Could not parse stansummary output:\n{}".format(result.stdout[:500])
    )

    problem_params = []
    for name, vals in params.items():
        if name in DIAGNOSTIC_PARAMS:
            continue
        if vals["rhat"] > 1.05:
            problem_params.append("{}: R_hat={:.4f}".format(name, vals["rhat"]))

    assert len(problem_params) == 0, (
        "Parameters with R-hat > 1.05:\n{}".format("\n".join(problem_params))
    )


def test_effective_sample_size(output_files):
    """Effective sample size must be above 100 for all non-diagnostic parameters."""
    result = subprocess.run(
        ["{}/bin/stansummary".format(CMDSTAN)] + output_files,
        capture_output=True,
        text=True,
        timeout=60,
    )
    params = _parse_stansummary(result.stdout)

    problem_params = []
    for name, vals in params.items():
        if name in DIAGNOSTIC_PARAMS:
            continue
        if vals["ess"] < 100:
            problem_params.append("{}: N_Eff={:.1f}".format(name, vals["ess"]))

    assert len(problem_params) == 0, (
        "Parameters with ESS < 100:\n{}".format("\n".join(problem_params))
    )


def test_ar_coefficient_recovery(output_files):
    """The AR coefficient must be recovered near its true value of 0.92."""
    result = subprocess.run(
        ["{}/bin/stansummary".format(CMDSTAN)] + output_files,
        capture_output=True,
        text=True,
        timeout=60,
    )
    params = _parse_stansummary(result.stdout)

    # Look for named AR coefficient
    for name in ["rho", "phi", "ar_coef", "ar"]:
        if name in params:
            mean = params[name]["mean"]
            assert 0.75 < mean < 0.99, (
                "AR coefficient '{}' = {:.3f}, expected near 0.92".format(name, mean)
            )
            return

    # Fallback: look for any scalar parameter in the right range
    candidates = [
        (n, p["mean"])
        for n, p in params.items()
        if 0.80 < p["mean"] < 0.99
        and "[" not in n
        and n not in DIAGNOSTIC_PARAMS
    ]
    assert len(candidates) > 0, (
        "No parameter found with posterior mean near the true AR coefficient (0.92)"
    )
