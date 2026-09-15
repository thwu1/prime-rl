
import pytest
import os

THRESHOLD = 0.25
MODELS = ["eight_schools", "gp_regr", "sir"]
REFERENCE_DIR = "/tests/reference"
RESULTS_DIR = "/app/results"


def load_params(filepath):
    """Load reference parameters: name mean std."""
    params = {}
    with open(filepath) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 3:
                params[parts[0]] = (float(parts[1]), float(parts[2]))
    return params


def load_fit(filepath):
    """Load estimated means: name mean."""
    estimates = {}
    with open(filepath) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                estimates[parts[0]] = float(parts[1])
    return estimates


@pytest.mark.parametrize("model", MODELS)
def test_fit_file_exists(model):
    """Check that the .fit output file was created."""
    fit_path = os.path.join(RESULTS_DIR, f"{model}.fit")
    assert os.path.exists(fit_path), f"Missing output file: {fit_path}"


@pytest.mark.parametrize("model", MODELS)
def test_all_parameters_present(model):
    """Check that all reference parameters appear in the .fit file."""
    params = load_params(os.path.join(REFERENCE_DIR, f"{model}.params"))
    fit_path = os.path.join(RESULTS_DIR, f"{model}.fit")
    if not os.path.exists(fit_path):
        pytest.skip(f"{fit_path} does not exist")
    estimates = load_fit(fit_path)
    missing = [name for name in params if name not in estimates]
    assert len(missing) == 0, (
        f"Missing {len(missing)} parameters in {model}.fit: {missing[:10]}"
    )


@pytest.mark.parametrize("model", MODELS)
def test_z_scores_within_threshold(model):
    """Check that all parameter estimates pass the z-score criterion."""
    params = load_params(os.path.join(REFERENCE_DIR, f"{model}.params"))
    fit_path = os.path.join(RESULTS_DIR, f"{model}.fit")
    if not os.path.exists(fit_path):
        pytest.skip(f"{fit_path} does not exist")
    estimates = load_fit(fit_path)

    failures = []
    for name, (ref_mean, ref_std) in params.items():
        if name not in estimates:
            failures.append(f"{name}: MISSING")
            continue
        z = abs((ref_mean - estimates[name]) / ref_std)
        if z >= THRESHOLD:
            failures.append(
                f"{name}: z={z:.4f} "
                f"(est={estimates[name]:.6e}, ref={ref_mean:.6e} +/- {ref_std:.6e})"
            )
    assert len(failures) == 0, (
        f"{len(failures)} parameter(s) failed z-score criterion in {model}:\n"
        + "\n".join(failures)
    )


def test_total_parameter_count():
    """Verify that the total number of estimated parameters matches expectation."""
    expected_counts = {"eight_schools": 18, "gp_regr": 3, "sir": 84}
    for model, expected in expected_counts.items():
        params = load_params(os.path.join(REFERENCE_DIR, f"{model}.params"))
        assert len(params) == expected, (
            f"{model}: expected {expected} reference params, got {len(params)}"
        )
