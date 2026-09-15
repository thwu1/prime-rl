
"""Verify fault-tolerance analysis results against independently computed
reference values (DNA).  The ``expected`` fixture runs the same tqec/stim
pipeline to produce deterministic ground-truth numbers that the agent's
``/app/analysis.json`` must match exactly."""

import json
import os

import pytest


# ──────────────────── fixtures ────────────────────


@pytest.fixture(scope="module")
def results():
    """Load the agent-produced results file."""
    path = "/app/analysis.json"
    assert os.path.isfile(path), f"Results file not found at {path}"
    with open(path) as fh:
        data = json.load(fh)
    assert isinstance(data, dict), "Results must be a JSON object"
    return data


@pytest.fixture(scope="module")
def expected():
    """Independently compute all reference values using tqec + stim.

    This fixture is the DNA anchor: every value produced here is deterministic
    for a given tqec version + noise parameters, so any correct solution must
    match exactly.
    """
    from tqec import compile_block_graph
    from tqec.gallery import cnot, memory, three_cnots
    from tqec.utils.enums import Basis
    from tqec.utils.noise_model import NoiseModel, NoiseRule

    uniform_noise = NoiseModel.uniform_depolarizing(0.001)

    custom_noise = NoiseModel(
        idle_depolarization=0.0002,
        any_clifford_1q_rule=NoiseRule(after={"DEPOLARIZE1": 0.001}),
        any_clifford_2q_rule=NoiseRule(after={"DEPOLARIZE2": 0.005}),
        measure_rules={
            "X": NoiseRule(after={}, flip_result=0.003),
            "Y": NoiseRule(after={}, flip_result=0.003),
            "Z": NoiseRule(after={}, flip_result=0.003),
            "XX": NoiseRule(after={}, flip_result=0.003),
            "YY": NoiseRule(after={}, flip_result=0.003),
            "ZZ": NoiseRule(after={}, flip_result=0.003),
        },
        gate_rules={
            "RX": NoiseRule(after={"Z_ERROR": 0.002}),
            "RY": NoiseRule(after={"X_ERROR": 0.002}),
            "R": NoiseRule(after={"X_ERROR": 0.002}),
        },
    )

    factories = {
        "memory": lambda: memory(observable_basis=Basis.Z),
        "cnot": lambda: cnot(observable_basis=Basis.Z),
        "three_cnots": lambda: three_cnots(observable_basis=Basis.Z),
    }

    def _circuit_metrics(circ):
        dem = circ.detector_error_model(decompose_errors=True)
        n_err = sum(1 for inst in dem.flattened() if inst.type == "error")
        errs = circ.shortest_graphlike_error(ignore_ungraphlike_errors=True)
        return {
            "num_qubits": circ.num_qubits,
            "num_detectors": circ.num_detectors,
            "num_observables": circ.num_observables,
            "num_error_mechanisms": n_err,
            "effective_code_distance": len(errs),
        }

    def _dem_analysis(circ):
        dem = circ.detector_error_model(decompose_errors=True)
        total = logical = pure = total_det = 0
        for inst in dem.flattened():
            if inst.type == "error":
                total += 1
                tgts = inst.targets_copy()
                has_log = any(t.is_logical_observable_id() for t in tgts)
                n_det = sum(1 for t in tgts if t.is_relative_detector_id())
                total_det += n_det
                if has_log:
                    logical += 1
                else:
                    pure += 1
        return {
            "logical_error_mechanisms": logical,
            "pure_detector_errors": pure,
            "avg_detectors_per_mechanism": (
                round(total_det / total, 6) if total else 0.0
            ),
        }

    def _compile_circuit(bg, k, noise):
        compiled = compile_block_graph(bg, observables="auto")
        return compiled.generate_stim_circuit(k=k, noise_model=noise)

    ref = {"scaling": {}, "noise_comparison": {}, "custom_memory": {}}

    # Section 1: Scaling
    for name, factory in factories.items():
        ref["scaling"][name] = {}
        for k_val in [1, 2, 3]:
            bg = factory()
            circ = _compile_circuit(bg, k_val, uniform_noise)
            ref["scaling"][name][f"d{2 * k_val + 1}"] = _circuit_metrics(circ)

    # Section 2: Noise comparison (memory at d=5 / k=2)
    for noise_name, noise_model in [
        ("uniform", uniform_noise),
        ("custom", custom_noise),
    ]:
        bg = memory(observable_basis=Basis.Z)
        circ = _compile_circuit(bg, 2, noise_model)
        metrics = _circuit_metrics(circ)
        dem_stats = _dem_analysis(circ)
        ref["noise_comparison"][noise_name] = {**metrics, **dem_stats}

    # Section 3: Custom memory (should equal gallery memory)
    ref["custom_memory"] = {
        d: dict(ref["scaling"]["memory"][d]) for d in ["d3", "d5", "d7"]
    }

    return ref


# ──────────────────── constants ────────────────────

COMPUTATIONS = ["memory", "cnot", "three_cnots"]
D_KEYS = ["d3", "d5", "d7"]
METRIC_FIELDS = [
    "num_qubits",
    "num_detectors",
    "num_observables",
    "num_error_mechanisms",
    "effective_code_distance",
]
NOISE_MODELS = ["uniform", "custom"]
DEM_FIELDS = [
    "logical_error_mechanisms",
    "pure_detector_errors",
    "avg_detectors_per_mechanism",
]


# ──────────────────── structure tests ────────────────────


class TestStructure:
    """Validate that the JSON has the required shape."""

    def test_has_scaling(self, results):
        assert "scaling" in results

    def test_has_noise_comparison(self, results):
        assert "noise_comparison" in results

    def test_has_custom_memory(self, results):
        assert "custom_memory" in results

    def test_scaling_computations(self, results):
        for comp in COMPUTATIONS:
            assert comp in results["scaling"], f"Missing scaling/{comp}"

    def test_scaling_distances(self, results):
        for comp in COMPUTATIONS:
            for d in D_KEYS:
                assert d in results["scaling"][comp], (
                    f"Missing scaling/{comp}/{d}"
                )

    def test_scaling_fields(self, results):
        for comp in COMPUTATIONS:
            for d in D_KEYS:
                for field in METRIC_FIELDS:
                    assert field in results["scaling"][comp][d], (
                        f"Missing {field} in scaling/{comp}/{d}"
                    )

    def test_noise_comparison_models(self, results):
        for model in NOISE_MODELS:
            assert model in results["noise_comparison"], (
                f"Missing noise_comparison/{model}"
            )

    def test_noise_comparison_fields(self, results):
        for model in NOISE_MODELS:
            for field in METRIC_FIELDS + DEM_FIELDS:
                assert field in results["noise_comparison"][model], (
                    f"Missing {field} in noise_comparison/{model}"
                )

    def test_custom_memory_distances(self, results):
        for d in D_KEYS:
            assert d in results["custom_memory"], f"Missing custom_memory/{d}"

    def test_custom_memory_fields(self, results):
        for d in D_KEYS:
            for field in METRIC_FIELDS:
                assert field in results["custom_memory"][d], (
                    f"Missing {field} in custom_memory/{d}"
                )


# ──────────────────── DNA: scaling exact-match ────────────────────


class TestScalingExact:
    """Verify every scaling metric matches independently computed values."""

    @pytest.mark.parametrize("comp", COMPUTATIONS)
    @pytest.mark.parametrize("d", D_KEYS)
    @pytest.mark.parametrize("field", METRIC_FIELDS)
    def test_metric(self, results, expected, comp, d, field):
        got = results["scaling"][comp][d][field]
        want = expected["scaling"][comp][d][field]
        assert got == want, f"scaling/{comp}/{d}/{field}: got {got}, want {want}"


# ──────────────────── DNA: noise comparison exact-match ────────────────────


class TestNoiseComparisonExact:
    """Verify noise comparison metrics match independently computed values."""

    @pytest.mark.parametrize("model", NOISE_MODELS)
    @pytest.mark.parametrize("field", METRIC_FIELDS)
    def test_circuit_metric(self, results, expected, model, field):
        got = results["noise_comparison"][model][field]
        want = expected["noise_comparison"][model][field]
        assert got == want, (
            f"noise_comparison/{model}/{field}: got {got}, want {want}"
        )

    @pytest.mark.parametrize("model", NOISE_MODELS)
    def test_logical_error_mechanisms(self, results, expected, model):
        got = results["noise_comparison"][model]["logical_error_mechanisms"]
        want = expected["noise_comparison"][model]["logical_error_mechanisms"]
        assert got == want, (
            f"noise_comparison/{model}/logical_error_mechanisms: "
            f"got {got}, want {want}"
        )

    @pytest.mark.parametrize("model", NOISE_MODELS)
    def test_pure_detector_errors(self, results, expected, model):
        got = results["noise_comparison"][model]["pure_detector_errors"]
        want = expected["noise_comparison"][model]["pure_detector_errors"]
        assert got == want, (
            f"noise_comparison/{model}/pure_detector_errors: "
            f"got {got}, want {want}"
        )

    @pytest.mark.parametrize("model", NOISE_MODELS)
    def test_avg_detectors_per_mechanism(self, results, expected, model):
        got = results["noise_comparison"][model]["avg_detectors_per_mechanism"]
        want = expected["noise_comparison"][model][
            "avg_detectors_per_mechanism"
        ]
        assert abs(got - want) < 1e-4, (
            f"noise_comparison/{model}/avg_detectors_per_mechanism: "
            f"got {got}, want {want}"
        )


# ──────────────────── DNA: custom memory exact-match ────────────────────


class TestCustomMemoryExact:
    """Custom-built block graph must yield metrics identical to gallery."""

    @pytest.mark.parametrize("d", D_KEYS)
    @pytest.mark.parametrize("field", METRIC_FIELDS)
    def test_metric(self, results, expected, d, field):
        got = results["custom_memory"][d][field]
        want = expected["custom_memory"][d][field]
        assert got == want, (
            f"custom_memory/{d}/{field}: got {got}, want {want}"
        )


# ──────────────────── consistency / sanity checks ────────────────────


class TestConsistency:
    """Cross-section consistency and physical sanity checks."""

    @pytest.mark.parametrize("model", NOISE_MODELS)
    def test_logical_plus_pure_equals_total(self, results, model):
        nc = results["noise_comparison"][model]
        total = nc["num_error_mechanisms"]
        logical = nc["logical_error_mechanisms"]
        pure = nc["pure_detector_errors"]
        assert total == logical + pure, (
            f"{model}: total ({total}) != logical ({logical}) + pure ({pure})"
        )

    def test_noise_models_same_circuit_dimensions(self, results):
        """Same compilation yields identical circuit dimensions."""
        u = results["noise_comparison"]["uniform"]
        c = results["noise_comparison"]["custom"]
        assert u["num_qubits"] == c["num_qubits"]
        assert u["num_detectors"] == c["num_detectors"]
        assert u["num_observables"] == c["num_observables"]

    def test_custom_memory_matches_gallery_scaling(self, results):
        """Custom memory must exactly match gallery memory from scaling."""
        for d in D_KEYS:
            for field in METRIC_FIELDS:
                custom = results["custom_memory"][d][field]
                gallery = results["scaling"]["memory"][d][field]
                assert custom == gallery, (
                    f"{d}/{field}: custom={custom} != gallery={gallery}"
                )


class TestPhysicalScaling:
    """Physical sanity: resources must grow with code distance."""

    def test_qubits_increase(self, results):
        for comp in COMPUTATIONS:
            for i in range(len(D_KEYS) - 1):
                prev = results["scaling"][comp][D_KEYS[i]]["num_qubits"]
                curr = results["scaling"][comp][D_KEYS[i + 1]]["num_qubits"]
                assert curr > prev, (
                    f"{comp}: qubits {D_KEYS[i]}={prev} >= {D_KEYS[i+1]}={curr}"
                )

    def test_detectors_increase(self, results):
        for comp in COMPUTATIONS:
            for i in range(len(D_KEYS) - 1):
                prev = results["scaling"][comp][D_KEYS[i]]["num_detectors"]
                curr = results["scaling"][comp][D_KEYS[i + 1]]["num_detectors"]
                assert curr > prev, (
                    f"{comp}: detectors {D_KEYS[i]}={prev} >= "
                    f"{D_KEYS[i+1]}={curr}"
                )

    def test_cnot_more_qubits_than_memory(self, results):
        for d in D_KEYS:
            mem = results["scaling"]["memory"][d]["num_qubits"]
            cn = results["scaling"]["cnot"][d]["num_qubits"]
            assert cn > mem, (
                f"{d}: cnot ({cn}) should have more qubits than memory ({mem})"
            )

    def test_effective_code_distance_nondecreasing(self, results):
        for comp in COMPUTATIONS:
            for i in range(len(D_KEYS) - 1):
                prev = results["scaling"][comp][D_KEYS[i]][
                    "effective_code_distance"
                ]
                curr = results["scaling"][comp][D_KEYS[i + 1]][
                    "effective_code_distance"
                ]
                assert curr >= prev, (
                    f"{comp}: ecd {D_KEYS[i]}={prev} > {D_KEYS[i+1]}={curr}"
                )

    def test_three_cnots_more_qubits_than_cnot(self, results):
        for d in D_KEYS:
            cn = results["scaling"]["cnot"][d]["num_qubits"]
            tcn = results["scaling"]["three_cnots"][d]["num_qubits"]
            assert tcn > cn, (
                f"{d}: three_cnots ({tcn}) should exceed cnot ({cn})"
            )
