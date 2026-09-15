"""Tests for the coupled MCMC library and benchmark artifacts.

"""
import numpy as np
import os
import pytest
import scipy.stats as st
import sqlite3


@pytest.fixture(autouse=True)
def random_seed():
    """Reset numpy random state for reproducibility."""
    np.random.seed(0)


# ================================================================
# Part 1: Library correctness tests
# ================================================================


class TestMaximalCoupling:
    def test_same_distribution_couples(self):
        """Identical distributions must always couple with cost 1."""
        from couplings import maximal_coupling

        rv = st.norm()
        samples, cost = maximal_coupling(rv, rv, size=500)
        assert samples.shape == (500, 2)
        assert (samples[:, 0] == samples[:, 1]).all(), (
            "Same distributions must produce identical draws"
        )
        assert (cost == 1).all(), "Cost must be 1 for identical distributions"

    def test_disjoint_never_couples(self):
        """Disjoint supports must never couple, with cost exactly 2."""
        from couplings import maximal_coupling

        rv1 = st.uniform(0, 1)   # support [0, 1]
        rv2 = st.uniform(2, 1)   # support [2, 3]
        samples, cost = maximal_coupling(rv1, rv2, size=500)
        assert (samples[:, 0] != samples[:, 1]).all(), (
            "Disjoint distributions must not couple"
        )
        assert (cost == 2).all(), "Cost must be 2 for disjoint distributions"

    def test_overlapping_variable_cost(self):
        """Overlapping distributions should have varying costs."""
        from couplings import maximal_coupling

        rv1 = st.uniform(0, 1)
        rv2 = st.uniform(0, 0.99)
        _, cost = maximal_coupling(rv1, rv2, size=1000)
        assert cost.min() == 1, "Some samples should couple immediately"
        assert cost.max() > 2, "Some samples should require multiple resamples"

    def test_output_shapes(self):
        """Check that output shapes match the specification."""
        from couplings import maximal_coupling

        rv1 = st.norm(0, 1)
        rv2 = st.norm(2, 3)
        n = 300
        samples, cost = maximal_coupling(rv1, rv2, size=n)
        assert samples.shape == (n, 2)
        assert cost.shape == (n,)
        assert (cost >= 1).all()


class TestReflectionCoupling:
    def test_same_mean_couples(self):
        """Same mean must produce identical coupled samples."""
        from couplings import ReflectionMaximalCoupling

        rmc = ReflectionMaximalCoupling(st.norm(), 1)
        x, y = rmc(4, 4, 10)
        assert (x == y).all(), "Same mean must give x == y"

    def test_ordering_1d(self):
        """Well-separated means must preserve component ordering."""
        from couplings import ReflectionMaximalCoupling

        rmc = ReflectionMaximalCoupling(st.norm(), 1)
        x, y = rmc(-4, 4, 10)
        assert x.shape[0] == 10
        assert (x < y).all(), "mu1 < mu2 should give x < y"
        x, y = rmc(4, -4, 10)
        assert (x > y).all(), "mu1 > mu2 should give x > y"

    def test_3d_ordering(self):
        """Works correctly with multivariate distributions."""
        from couplings import ReflectionMaximalCoupling

        rmc = ReflectionMaximalCoupling(
            st.multivariate_normal(np.zeros(3), np.eye(3)),
            np.eye(3),
        )
        x, y = rmc(-4 * np.ones(3), 4 * np.ones(3), 10)
        assert (x < y).all()
        x, y = rmc(4 * np.ones(3), -4 * np.ones(3), 10)
        assert (x > y).all()

    def test_single_chain(self):
        """Works correctly with chains=1."""
        from couplings import ReflectionMaximalCoupling

        rmc = ReflectionMaximalCoupling(st.norm(), 1)
        x, y = rmc(-4, 4, 1)
        assert x.shape == (1, 1)
        assert (x < y).all()

    def test_reusable(self):
        """The coupling object can be reused for multiple calls."""
        from couplings import ReflectionMaximalCoupling

        rmc = ReflectionMaximalCoupling(st.norm(), 1)
        x1, y1 = rmc(-4, 4, 5)
        x2, y2 = rmc(4, -4, 5)
        assert (x1 < y1).all()
        assert (x2 > y2).all()


class TestCoupledMH:
    def test_scalar_basic(self):
        """Basic scalar test: shapes, initial values, meeting detection."""
        from couplings import metropolis_hastings

        rv = st.norm()
        data = metropolis_hastings(
            log_prob=rv.logpdf,
            proposal_cov=10,
            init_x=0.5,
            init_y=0.5,
            lag=3,
            iters=20,
            chains=10,
        )
        assert (data.x[0] == 0.5).all()
        assert (data.y[0] == 0.5).all()
        assert data.x.shape[0] == 20
        assert data.y.shape[0] == 17  # iters - lag
        assert data.dim == 1
        assert data.chains == 10
        assert (data.meeting_time < 20).all()
        assert 0 <= data.x_accept.mean() <= 1.0
        assert 0 <= data.y_accept.mean() <= 1.0

    def test_vector_8d(self):
        """Multivariate normal in 8 dimensions."""
        from couplings import metropolis_hastings

        dim = 8
        rv = st.multivariate_normal(np.zeros(dim), np.eye(dim))
        init_x, init_y = rv.rvs(size=2)
        data = metropolis_hastings(
            log_prob=rv.logpdf,
            proposal_cov=10 * np.eye(dim),
            init_x=init_x,
            init_y=init_y,
            lag=1,
            iters=20,
            chains=10,
        )
        assert (data.x[0] == init_x).all()
        assert (data.y[0] == init_y).all()
        assert data.x.shape[0] == 20
        assert data.y.shape[0] == 19
        assert data.dim == dim
        assert (data.meeting_time < 20).all()

    def test_short_circuit(self):
        """Short-circuit mode terminates early after all chains meet."""
        from couplings import metropolis_hastings

        rv = st.norm()
        data = metropolis_hastings(
            log_prob=rv.logpdf,
            proposal_cov=10,
            init_x=0.5,
            init_y=0.5,
            iters=200,
            short_circuit=True,
        )
        assert data.x.shape[0] == data.meeting_time.max()
        assert data.y.shape[0] == data.meeting_time.max() - 1
        assert (data.meeting_time > 0).all()
        assert (data.meeting_time < 200).all()

    def test_accept_arrays_shape(self):
        """Accept arrays have correct boolean dtype and shapes."""
        from couplings import metropolis_hastings

        rv = st.norm()
        data = metropolis_hastings(
            log_prob=rv.logpdf,
            proposal_cov=10,
            init_x=0.0,
            init_y=0.0,
            lag=2,
            iters=15,
            chains=5,
        )
        assert data.x_accept.shape == (15, 5)
        assert data.y_accept.shape == (13, 5)


class TestUnbiasedEstimator:
    def test_vector_shapes_and_bounds(self):
        """Shapes and bounded values for multivariate case."""
        from couplings import metropolis_hastings, unbiased_estimator

        dim = 10
        chains = 12
        rv = st.multivariate_normal(np.zeros(dim), np.eye(dim))
        init_x, init_y = rv.rvs(size=2)
        data = metropolis_hastings(
            log_prob=rv.logpdf,
            proposal_cov=10 * np.eye(dim),
            init_x=init_x,
            init_y=init_y,
            iters=20,
            chains=chains,
        )
        mcmc_est, bias_corr = unbiased_estimator(data, lambda x: x, burn_in=10)
        assert mcmc_est.shape == (chains, dim)
        assert bias_corr.shape == (chains, dim)
        estimate = mcmc_est + bias_corr
        assert (-3 < estimate).all()
        assert (estimate < 3).all()

    def test_scalar_shapes_and_bounds(self):
        """Shapes and bounded values for scalar case."""
        from couplings import metropolis_hastings, unbiased_estimator

        chains = 10
        rv = st.norm()
        data = metropolis_hastings(
            log_prob=rv.logpdf,
            proposal_cov=10,
            init_x=0.5,
            init_y=0.5,
            lag=3,
            iters=20,
            chains=chains,
        )
        mcmc_est, bias_corr = unbiased_estimator(data, lambda x: x, burn_in=0)
        assert mcmc_est.shape == (chains, 1)
        assert bias_corr.shape == (chains, 1)
        estimate = mcmc_est + bias_corr
        assert (-4 < estimate).all()
        assert (estimate < 4).all()


class TestConvergence:
    def _get_data(self):
        """Produce coupled MH samples for convergence tests."""
        from couplings import metropolis_hastings

        rv = st.norm()
        return metropolis_hastings(
            log_prob=rv.logpdf,
            proposal_cov=10,
            init_x=0.0,
            init_y=0.0,
            lag=1,
            iters=50,
            chains=10,
        )

    def test_tv_shape_nonneg(self):
        """TV distance has correct shape and is non-negative."""
        from couplings import total_variation

        data = self._get_data()
        tv = total_variation(data)
        assert tv.shape == (data.x.shape[0],)
        assert (tv >= 0).all()

    def test_tv_zero_after_meeting(self):
        """TV must be zero from max(meeting_time) - lag onward."""
        from couplings import total_variation

        data = self._get_data()
        assert (data.meeting_time > 0).all(), "All chains should meet"
        tv = total_variation(data)
        max_mt = int(data.meeting_time.max())
        assert tv[max_mt - data.lag :].sum() == 0.0

    def test_wasserstein_shape_nonneg(self):
        """Wasserstein distance has correct shape and is non-negative."""
        from couplings import wasserstein

        data = self._get_data()
        wass = wasserstein(data)
        assert wass.shape[0] == data.x.shape[0]
        assert (wass >= 0).all()

    def test_wasserstein_zero_after_meeting(self):
        """Wasserstein must be zero after all chains meet."""
        from couplings import wasserstein

        data = self._get_data()
        assert (data.meeting_time > 0).all(), "All chains should meet"
        wass = wasserstein(data)
        max_mt = int(data.meeting_time.max())
        assert wass[max_mt - data.lag :].sum() == 0.0

    def test_tv_multidim(self):
        """TV works for multidimensional distributions."""
        from couplings import metropolis_hastings, total_variation

        dim = 2
        cov = 0.1 * np.eye(dim) + 0.9 * np.ones((dim, dim))
        rv = st.multivariate_normal(np.zeros(dim), cov)
        data = metropolis_hastings(
            log_prob=rv.logpdf,
            proposal_cov=0.1 * np.eye(dim),
            init_x=4 * np.ones(dim),
            init_y=-4 * np.ones(dim),
            lag=1,
            iters=500,
            chains=8,
        )
        tv = total_variation(data)
        assert tv.shape == (500,)
        assert (tv >= 0).all()
        mid = len(tv) // 2
        assert tv[mid:].mean() <= tv[:mid].mean()


# ================================================================
# Part 2: Benchmark database tests
# ================================================================


class TestBenchmarkDB:
    def test_db_exists(self):
        """results.db must exist at /app/results.db."""
        assert os.path.exists("/app/results.db"), "results.db not found at /app/"

    def test_schema(self):
        """Database must have the expected table and columns."""
        db = sqlite3.connect("/app/results.db")
        cursor = db.execute("PRAGMA table_info(results)")
        columns = {row[1] for row in cursor.fetchall()}
        expected = {
            "target", "config", "chain_id",
            "meeting_time", "x_accept_rate", "y_accept_rate",
        }
        assert expected <= columns, f"Missing columns: {expected - columns}"
        db.close()

    def test_data_completeness(self):
        """All target/config combinations must be present."""
        db = sqlite3.connect("/app/results.db")
        cursor = db.execute("SELECT DISTINCT target, config FROM results")
        combos = cursor.fetchall()
        targets = {row[0] for row in combos}
        configs = {row[1] for row in combos}
        assert len(targets) >= 3, f"Expected >= 3 targets, got {targets}"
        assert len(configs) >= 4, f"Expected >= 4 configs, got {configs}"
        db.close()

    def test_chain_counts(self):
        """Each target/config should have multiple chains."""
        db = sqlite3.connect("/app/results.db")
        cursor = db.execute("""
            SELECT target, config, COUNT(*) AS n
            FROM results
            GROUP BY target, config
            HAVING n < 10
        """)
        sparse = cursor.fetchall()
        assert len(sparse) == 0, (
            f"Some target/config combos have too few chains: {sparse}"
        )
        db.close()

    def test_valid_meeting_times(self):
        """Meeting times must be positive integers."""
        db = sqlite3.connect("/app/results.db")
        row = db.execute(
            "SELECT MIN(meeting_time), MAX(meeting_time) FROM results"
        ).fetchone()
        assert row[0] > 0, "Meeting times must be positive"
        assert row[1] <= 300, "Meeting times unreasonably large (> 300)"
        db.close()

    def test_valid_accept_rates(self):
        """Acceptance rates must be in [0, 1]."""
        db = sqlite3.connect("/app/results.db")
        row = db.execute(
            "SELECT MIN(x_accept_rate), MAX(x_accept_rate) FROM results"
        ).fetchone()
        assert row[0] >= 0, "Accept rate must be non-negative"
        assert row[1] <= 1.0, "Accept rate must be at most 1"
        db.close()


# ================================================================
# Part 3: Analysis SQL tests
# ================================================================


class TestAnalysisSQL:
    @staticmethod
    def _parse_queries():
        """Parse analysis.sql into individual queries keyed by number."""
        with open("/app/analysis.sql") as f:
            content = f.read()
        queries = {}
        parts = content.split("-- QUERY ")
        for part in parts[1:]:
            lines = part.strip().split("\n")
            num = int(lines[0].strip().rstrip(":"))
            sql = "\n".join(lines[1:]).strip()
            while sql.endswith(";"):
                sql = sql[:-1].strip()
            queries[num] = sql
        return queries

    def test_file_exists(self):
        """analysis.sql must exist."""
        assert os.path.exists("/app/analysis.sql"), "analysis.sql not found"

    def test_three_queries(self):
        """File must contain exactly queries 1, 2, and 3."""
        queries = self._parse_queries()
        assert set(queries.keys()) == {1, 2, 3}, (
            f"Expected queries 1,2,3; got {set(queries.keys())}"
        )

    def test_query1_runs_and_correct(self):
        """Query 1 must return the actual best config per target."""
        queries = self._parse_queries()
        db = sqlite3.connect("/app/results.db")

        q1_rows = db.execute(queries[1]).fetchall()
        assert len(q1_rows) >= 3, (
            f"Query 1 should return >= 3 rows, got {len(q1_rows)}"
        )
        q1_best_mt = {row[0]: float(row[2]) for row in q1_rows}

        # Independently compute best mean meeting time per target
        truth = db.execute("""
            SELECT target, MIN(avg_mt) FROM (
                SELECT target, AVG(meeting_time) AS avg_mt
                FROM results GROUP BY target, config
            ) GROUP BY target
        """).fetchall()
        true_best = {row[0]: float(row[1]) for row in truth}

        for target, expected_mt in true_best.items():
            assert target in q1_best_mt, f"Query 1 missing target '{target}'"
            assert abs(q1_best_mt[target] - expected_mt) < 0.5, (
                f"For '{target}', Query 1 reports {q1_best_mt[target]:.2f} "
                f"but actual best is {expected_mt:.2f}"
            )
        db.close()

    def test_query2_ranking(self):
        """Query 2 must rank configs by median meeting time."""
        queries = self._parse_queries()
        db = sqlite3.connect("/app/results.db")
        rows = db.execute(queries[2]).fetchall()
        assert len(rows) >= 4, (
            f"Query 2 should return >= 4 rows, got {len(rows)}"
        )
        # Median meeting times should be non-decreasing
        medians = [float(row[1]) for row in rows]
        for i in range(len(medians) - 1):
            assert medians[i] <= medians[i + 1], (
                f"Ranking not sorted: {medians[i]} > {medians[i+1]}"
            )
        db.close()

    def test_query3_spread(self):
        """Query 3 must return acceptance-rate spread per target."""
        queries = self._parse_queries()
        db = sqlite3.connect("/app/results.db")
        rows = db.execute(queries[3]).fetchall()
        assert len(rows) >= 3, (
            f"Query 3 should return >= 3 rows, got {len(rows)}"
        )
        for row in rows:
            spread = float(row[1])
            assert 0 <= spread <= 1.0, (
                f"Accept spread {spread} for '{row[0]}' out of [0, 1]"
            )
        db.close()


# ================================================================
# Part 4: Custom proposal tests
# ================================================================


class TestOptimalProposal:
    def test_file_exists(self):
        """optimal_proposal.npy must exist."""
        assert os.path.exists("/app/optimal_proposal.npy"), (
            "optimal_proposal.npy not found"
        )

    def test_shape_and_validity(self):
        """Must be an 8x8 symmetric positive-definite matrix."""
        proposal = np.load("/app/optimal_proposal.npy")
        assert proposal.shape == (8, 8), (
            f"Expected (8, 8), got {proposal.shape}"
        )
        assert np.allclose(proposal, proposal.T), "Must be symmetric"
        eigvals = np.linalg.eigvalsh(proposal)
        assert (eigvals > 0).all(), (
            f"Must be positive definite; eigenvalues: {eigvals}"
        )

    def test_not_isotropic(self):
        """Proposal must exploit the target's correlation structure."""
        proposal = np.load("/app/optimal_proposal.npy")
        off_diag = proposal - np.diag(np.diag(proposal))
        assert np.abs(off_diag).max() > 0.01, (
            "Proposal is isotropic (scaled identity). "
            "It should capture off-diagonal correlations."
        )

    def test_meeting_time_threshold(self):
        """Mean meeting time must be <= 20 across multiple seeds."""
        from couplings import metropolis_hastings

        proposal = np.load("/app/optimal_proposal.npy")
        dim = 8
        cov = 0.3 * np.eye(dim) + 0.7 * np.ones((dim, dim))
        rv = st.multivariate_normal(np.zeros(dim), cov)

        all_mt = []
        for seed in [123, 456, 789]:
            np.random.seed(seed)
            data = metropolis_hastings(
                log_prob=rv.logpdf,
                proposal_cov=proposal,
                init_x=4 * np.ones(dim),
                init_y=-4 * np.ones(dim),
                lag=1,
                iters=300,
                chains=20,
            )
            mt = data.meeting_time.copy()
            mt[mt < 0] = 300
            all_mt.extend(mt.tolist())

        mean_mt = np.mean(all_mt)
        assert mean_mt <= 50, (
            f"Mean meeting time {mean_mt:.1f} exceeds threshold 50"
        )

    def test_beats_benchmark_best(self):
        """Custom proposal must beat the best isotropic config."""
        from couplings import metropolis_hastings

        proposal = np.load("/app/optimal_proposal.npy")
        dim = 8
        cov = 0.3 * np.eye(dim) + 0.7 * np.ones((dim, dim))
        rv = st.multivariate_normal(np.zeros(dim), cov)

        # Best isotropic meeting time from benchmark
        db = sqlite3.connect("/app/results.db")
        row = db.execute("""
            SELECT MIN(avg_mt) FROM (
                SELECT AVG(meeting_time) AS avg_mt
                FROM results
                WHERE target = 'correlated_8d'
                GROUP BY config
            )
        """).fetchone()
        db.close()
        best_isotropic_mt = float(row[0])

        # Evaluate custom proposal with same chain count as benchmark
        np.random.seed(42)
        data = metropolis_hastings(
            log_prob=rv.logpdf,
            proposal_cov=proposal,
            init_x=4 * np.ones(dim),
            init_y=-4 * np.ones(dim),
            lag=1,
            iters=300,
            chains=32,
        )
        mt = data.meeting_time.copy()
        mt[mt < 0] = 300
        custom_mt = mt.mean()

        assert custom_mt < best_isotropic_mt, (
            f"Custom proposal (mean MT={custom_mt:.1f}) must beat "
            f"benchmark's best isotropic ({best_isotropic_mt:.1f})"
        )
