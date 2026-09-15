
import json
import os
import numpy as np
import pytest


RESULTS_PATH = '/app/output/results.json'


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), \
        "Pipeline output not found. Ensure 'python3 /app/pipeline.py' runs successfully."
    with open(RESULTS_PATH) as f:
        return json.load(f)


@pytest.fixture
def source_data():
    with open('/app/data/source.json') as f:
        return json.load(f)


@pytest.fixture
def target_data():
    with open('/app/data/target.json') as f:
        return json.load(f)


@pytest.fixture
def graph_data():
    with open('/app/data/graphs.json') as f:
        return json.load(f)


@pytest.fixture
def measure_data():
    with open('/app/data/measures.json') as f:
        return json.load(f)


class TestResultsStructure:
    def test_output_exists(self, results):
        assert 'sinkhorn' in results
        assert 'gromov_wasserstein' in results
        assert 'barycenter' in results

    def test_sinkhorn_fields(self, results):
        s = results['sinkhorn']
        assert 'transport_plan' in s
        assert 'cost' in s
        assert 'iterations' in s

    def test_gw_fields(self, results):
        gw = results['gromov_wasserstein']
        assert 'transport_plan' in gw
        assert 'gw_distance' in gw
        assert 'iterations' in gw

    def test_barycenter_fields(self, results):
        assert 'weights' in results['barycenter']


class TestSinkhornTransport:
    def test_marginals_source(self, results, source_data):
        T = np.array(results['sinkhorn']['transport_plan'])
        a = np.array(source_data['weights'])
        np.testing.assert_allclose(T.sum(axis=1), a, atol=1e-5,
            err_msg="Sinkhorn row sums must equal source weights")

    def test_marginals_target(self, results, target_data):
        T = np.array(results['sinkhorn']['transport_plan'])
        b = np.array(target_data['weights'])
        np.testing.assert_allclose(T.sum(axis=0), b, atol=1e-5,
            err_msg="Sinkhorn column sums must equal target weights")

    def test_nonnegative(self, results):
        T = np.array(results['sinkhorn']['transport_plan'])
        assert np.all(T >= -1e-10), "Transport plan entries must be non-negative"

    def test_cost_positive(self, results):
        assert results['sinkhorn']['cost'] > 0, "Transport cost must be positive"

    def test_sufficient_iterations(self, results):
        iters = results['sinkhorn']['iterations']
        assert iters > 5, \
            f"Sinkhorn converged in {iters} iterations — suspiciously fast"

    def test_not_nearly_uniform(self, results):
        T = np.array(results['sinkhorn']['transport_plan'])
        n, m = T.shape
        uniform_val = 1.0 / (n * m)
        assert np.max(T) > 2 * uniform_val, \
            "Transport plan should not be nearly uniform for well-separated data"

    def test_cost_consistency(self, results, source_data, target_data):
        """Reported cost must match sum(T * M) with squared Euclidean M."""
        T = np.array(results['sinkhorn']['transport_plan'])
        X = np.array(source_data['points'])
        Y = np.array(target_data['points'])
        M = np.sum((X[:, None, :] - Y[None, :, :]) ** 2, axis=2)
        recomputed_cost = float(np.sum(T * M))
        np.testing.assert_allclose(
            results['sinkhorn']['cost'], recomputed_cost, rtol=0.01,
            err_msg="Reported cost must be consistent with squared Euclidean distances")

    def test_cost_below_uniform(self, results, source_data, target_data):
        """Optimal transport cost must be below the independent coupling cost."""
        T = np.array(results['sinkhorn']['transport_plan'])
        X = np.array(source_data['points'])
        Y = np.array(target_data['points'])
        M = np.sum((X[:, None, :] - Y[None, :, :]) ** 2, axis=2)
        a = np.array(source_data['weights'])
        b = np.array(target_data['weights'])
        T_uniform = np.outer(a, b)
        uniform_cost = float(np.sum(T_uniform * M))
        actual_cost = float(np.sum(T * M))
        assert actual_cost < uniform_cost, \
            f"Transport cost {actual_cost:.6f} should be less than " \
            f"independent coupling cost {uniform_cost:.6f}"


class TestGromovWasserstein:
    def test_marginals_p(self, results, graph_data):
        T = np.array(results['gromov_wasserstein']['transport_plan'])
        p = np.array(graph_data['p'])
        np.testing.assert_allclose(T.sum(axis=1), p, atol=1e-5,
            err_msg="GW row sums must equal p")

    def test_marginals_q(self, results, graph_data):
        T = np.array(results['gromov_wasserstein']['transport_plan'])
        q = np.array(graph_data['q'])
        np.testing.assert_allclose(T.sum(axis=0), q, atol=1e-5,
            err_msg="GW column sums must equal q")

    def test_nonnegative(self, results):
        T = np.array(results['gromov_wasserstein']['transport_plan'])
        assert np.all(T >= -1e-10), "GW transport plan must be non-negative"

    def test_gw_distance_positive(self, results):
        assert results['gromov_wasserstein']['gw_distance'] > 0, \
            "GW distance must be positive for non-isometric spaces"

    def test_gw_cost_consistency(self, results, graph_data):
        """Reported GW distance must match independently computed cost."""
        T = np.array(results['gromov_wasserstein']['transport_plan'])
        C1 = np.array(graph_data['C1'])
        C2 = np.array(graph_data['C2'])
        n, m = T.shape
        cost = 0.0
        for i in range(n):
            for j in range(m):
                for k in range(n):
                    for ll in range(m):
                        cost += (C1[i, k] - C2[j, ll]) ** 2 * T[i, j] * T[k, ll]
        np.testing.assert_allclose(
            results['gromov_wasserstein']['gw_distance'], cost, rtol=0.05,
            err_msg="Reported GW distance is inconsistent with transport plan")

    def test_gw_distance_below_initial(self, results, graph_data):
        """GW distance must be less than the cost of the initial coupling."""
        C1 = np.array(graph_data['C1'])
        C2 = np.array(graph_data['C2'])
        p = np.array(graph_data['p'])
        q = np.array(graph_data['q'])
        n, m = len(p), len(q)

        T_init = np.outer(p, q)
        init_cost = 0.0
        for i in range(n):
            for j in range(m):
                for k in range(n):
                    for ll in range(m):
                        init_cost += (C1[i, k] - C2[j, ll]) ** 2 * \
                                     T_init[i, j] * T_init[k, ll]

        assert results['gromov_wasserstein']['gw_distance'] < init_cost, \
            f"GW distance {results['gromov_wasserstein']['gw_distance']:.6f} " \
            f"should be less than initial coupling cost {init_cost:.6f}"


class TestBarycenter:
    def test_valid_distribution(self, results):
        bary = np.array(results['barycenter']['weights'])
        assert np.all(bary >= -1e-10), "Barycenter entries must be non-negative"
        np.testing.assert_allclose(bary.sum(), 1.0, atol=1e-5,
            err_msg="Barycenter must sum to 1")

    def test_correct_size(self, results, measure_data):
        bary = np.array(results['barycenter']['weights'])
        expected_size = len(measure_data['distributions'][0])
        assert len(bary) == expected_size, \
            f"Barycenter size {len(bary)} != expected {expected_size}"

    def test_not_uniform(self, results):
        bary = np.array(results['barycenter']['weights'])
        n = len(bary)
        uniform_val = 1.0 / n
        assert np.max(np.abs(bary - uniform_val)) > 0.01, \
            "Barycenter of non-uniform distributions should not be approximately uniform"

    def test_barycenter_concentrates_mass(self, results, measure_data):
        """Barycenter max entry should reflect the input distributions' structure."""
        bary = np.array(results['barycenter']['weights'])
        dists = [np.array(d) for d in measure_data['distributions']]
        input_maxes = [d.max() for d in dists]
        assert bary.max() < max(input_maxes) * 1.5, \
            "Barycenter max entry implausibly large"
        assert bary.max() > min(input_maxes) * 0.3, \
            "Barycenter max entry implausibly small"
