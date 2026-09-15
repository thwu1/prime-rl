"""
Tests for Denoised HERC Portfolio Allocation.
"""
import numpy as np
import pandas as pd
import pytest
import json
import subprocess
import sys
import os

sys.path.insert(0, '/app')



def generate_block_returns(T=200, N=15, seed=42):
    """Generate returns with a known 3-block covariance structure.

    Block 1 (assets 0-4): intra-correlation ~0.8
    Block 2 (assets 5-9): intra-correlation ~0.6
    Block 3 (assets 10-14): intra-correlation ~0.7
    Cross-block correlation: 0
    """
    rng = np.random.RandomState(seed)

    cov_true = np.eye(N) * 0.0004  # variance = 0.02^2

    for i in range(5):
        for j in range(5):
            if i != j:
                cov_true[i, j] = 0.00032  # corr = 0.8

    for i in range(5, 10):
        for j in range(5, 10):
            if i != j:
                cov_true[i, j] = 0.00024  # corr = 0.6

    for i in range(10, 15):
        for j in range(10, 15):
            if i != j:
                cov_true[i, j] = 0.00028  # corr = 0.7

    returns = rng.multivariate_normal(np.zeros(N), cov_true, T)
    columns = [f'ASSET_{i:02d}' for i in range(N)]
    dates = pd.date_range('2020-01-01', periods=T, freq='B')
    return pd.DataFrame(returns, index=dates, columns=columns)


# ---- Denoising tests ----

class TestDenoiseCov:
    def test_psd(self):
        from denoised_herc import denoise_covariance
        df = generate_block_returns(T=100)
        cov = df.cov().values
        tn = len(df) / df.shape[1]
        denoised = denoise_covariance(cov, tn)
        eigvals = np.linalg.eigvalsh(denoised)
        assert np.all(eigvals >= -1e-10), f"Not PSD: min eigenvalue = {eigvals.min()}"

    def test_symmetric(self):
        from denoised_herc import denoise_covariance
        df = generate_block_returns(T=100)
        cov = df.cov().values
        tn = len(df) / df.shape[1]
        denoised = denoise_covariance(cov, tn)
        np.testing.assert_allclose(denoised, denoised.T, atol=1e-10)

    def test_correlation_diagonal_ones(self):
        from denoised_herc import denoise_covariance
        df = generate_block_returns(T=100)
        cov = df.cov().values
        tn = len(df) / df.shape[1]
        denoised = denoise_covariance(cov, tn)
        std = np.sqrt(np.diag(denoised))
        corr = denoised / np.outer(std, std)
        np.testing.assert_allclose(np.diag(corr), 1.0, atol=1e-6)

    def test_preserves_shape(self):
        from denoised_herc import denoise_covariance
        df = generate_block_returns(T=100)
        cov = df.cov().values
        tn = len(df) / df.shape[1]
        denoised = denoise_covariance(cov, tn)
        assert denoised.shape == cov.shape

    def test_positive_variances(self):
        from denoised_herc import denoise_covariance
        df = generate_block_returns(T=100)
        cov = df.cov().values
        tn = len(df) / df.shape[1]
        denoised = denoise_covariance(cov, tn)
        assert np.all(np.diag(denoised) > 0), "All variances must be positive"


# ---- CVaR tests ----

class TestCVaR:
    def test_known_value_10(self):
        from denoised_herc import compute_cvar
        returns = np.array([-5.0, -4.0, -3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0])
        cvar = compute_cvar(returns, alpha=0.2)
        assert abs(cvar - 4.5) < 1e-10, f"Expected 4.5, got {cvar}"

    def test_known_value_5(self):
        from denoised_herc import compute_cvar
        returns = np.array([-10.0, -1.0, 0.0, 1.0, 2.0])
        cvar = compute_cvar(returns, alpha=0.2)
        assert abs(cvar - 10.0) < 1e-10, f"Expected 10.0, got {cvar}"

    def test_positive_for_normal(self):
        from denoised_herc import compute_cvar
        rng = np.random.RandomState(42)
        returns = rng.normal(0, 0.02, 1000)
        cvar = compute_cvar(returns, alpha=0.05)
        assert cvar > 0, "CVaR should be positive for zero-mean normal"

    def test_larger_alpha_smaller_cvar(self):
        from denoised_herc import compute_cvar
        rng = np.random.RandomState(42)
        returns = rng.normal(0, 0.02, 1000)
        cvar_01 = compute_cvar(returns, alpha=0.01)
        cvar_10 = compute_cvar(returns, alpha=0.10)
        assert cvar_01 > cvar_10, "Smaller alpha should give larger CVaR (deeper tail)"

    def test_cvar_ceil_semantics(self):
        """CVaR cutoff must use ceil(n*alpha), not floor."""
        from denoised_herc import compute_cvar
        # n=7, alpha=0.2 => n*alpha=1.4 => ceil=2, floor=1
        returns = np.array([-7.0, -3.0, -1.0, 0.0, 1.0, 2.0, 5.0])
        cvar = compute_cvar(returns, alpha=0.2)
        # ceil(1.4) = 2: worst 2 are [-7, -3], mean = -5, CVaR = 5.0
        assert abs(cvar - 5.0) < 1e-10, f"Expected 5.0, got {cvar}"

    def test_cvar_single_observation_tail(self):
        """CVaR with alpha producing exactly 1 tail observation."""
        from denoised_herc import compute_cvar
        returns = np.array([-8.0, -2.0, 0.0, 3.0, 6.0])
        # n=5, alpha=0.1 => ceil(0.5)=1 => worst 1: [-8], CVaR = 8.0
        cvar = compute_cvar(returns, alpha=0.1)
        assert abs(cvar - 8.0) < 1e-10, f"Expected 8.0, got {cvar}"


# ---- HERC weight tests ----

class TestHERCWeights:
    def test_sum_to_one_cvar(self):
        from denoised_herc import herc_allocate
        df = generate_block_returns(T=300, seed=42)
        result = herc_allocate(df, risk_measure='cvar')
        total = sum(result['weights'].values())
        assert abs(total - 1.0) < 1e-8, f"Weights sum to {total}"

    def test_sum_to_one_variance(self):
        from denoised_herc import herc_allocate
        df = generate_block_returns(T=300, seed=42)
        result = herc_allocate(df, risk_measure='variance')
        total = sum(result['weights'].values())
        assert abs(total - 1.0) < 1e-8

    def test_sum_to_one_std(self):
        from denoised_herc import herc_allocate
        df = generate_block_returns(T=300, seed=42)
        result = herc_allocate(df, risk_measure='std')
        total = sum(result['weights'].values())
        assert abs(total - 1.0) < 1e-8

    def test_nonnegative(self):
        from denoised_herc import herc_allocate
        df = generate_block_returns(T=300, seed=42)
        result = herc_allocate(df, risk_measure='cvar')
        for name, w in result['weights'].items():
            assert w >= -1e-10, f"Negative weight for {name}: {w}"

    def test_all_assets_present(self):
        from denoised_herc import herc_allocate
        df = generate_block_returns(T=300, seed=42)
        result = herc_allocate(df, risk_measure='cvar')
        assert set(result['weights'].keys()) == set(df.columns)

    def test_n_clusters_reasonable(self):
        from denoised_herc import herc_allocate
        df = generate_block_returns(T=300, seed=42)
        result = herc_allocate(df, risk_measure='cvar')
        assert 2 <= result['n_clusters'] <= 10, f"n_clusters={result['n_clusters']}"

    def test_nonzero_weights(self):
        from denoised_herc import herc_allocate
        df = generate_block_returns(T=300, seed=42)
        result = herc_allocate(df, risk_measure='cvar')
        for name, w in result['weights'].items():
            assert w > 1e-12, f"Zero weight for {name}"


# ---- Linkage method tests ----

class TestLinkageMethods:
    @pytest.mark.parametrize("method", ["ward", "single", "complete", "average"])
    def test_valid_weights(self, method):
        from denoised_herc import herc_allocate
        df = generate_block_returns(T=300, seed=42)
        result = herc_allocate(df, linkage_method=method)
        total = sum(result['weights'].values())
        assert abs(total - 1.0) < 1e-8, f"Weights sum to {total} for {method}"
        for w in result['weights'].values():
            assert w >= -1e-10, f"Negative weight with {method}"


# ---- Denoised HERC pipeline tests ----

class TestDenoisedHERC:
    def test_full_pipeline_denoised(self):
        from denoised_herc import herc_allocate
        df = generate_block_returns(T=200, seed=42)
        result = herc_allocate(df, risk_measure='cvar', denoise=True)
        assert result['denoised'] is True
        total = sum(result['weights'].values())
        assert abs(total - 1.0) < 1e-8
        assert result['n_clusters'] >= 2

    def test_denoised_flag_false(self):
        from denoised_herc import herc_allocate
        df = generate_block_returns(T=200, seed=42)
        result = herc_allocate(df, risk_measure='cvar', denoise=False)
        assert result['denoised'] is False

    def test_denoised_covariance_differs(self):
        """Denoising must actually modify the covariance matrix."""
        from denoised_herc import denoise_covariance
        df = generate_block_returns(T=75, seed=42)
        cov = df.cov().values
        tn = len(df) / df.shape[1]
        denoised = denoise_covariance(cov, tn)
        # Off-diagonal elements should change due to eigenvalue shrinkage
        off_diag_mask = ~np.eye(cov.shape[0], dtype=bool)
        assert not np.allclose(cov[off_diag_mask], denoised[off_diag_mask], atol=1e-8), \
            "Denoised covariance off-diagonal should differ from raw"


# ---- Cluster quality tests ----

class TestClusterQuality:
    def test_within_block_similarity(self):
        """Assets in the same true block should receive similar weights."""
        from denoised_herc import herc_allocate
        df = generate_block_returns(T=500, seed=42)
        result = herc_allocate(df, risk_measure='variance', linkage_method='ward')
        w = result['weights']

        b1 = [w[f'ASSET_{i:02d}'] for i in range(5)]
        b2 = [w[f'ASSET_{i:02d}'] for i in range(5, 10)]
        b3 = [w[f'ASSET_{i:02d}'] for i in range(10, 15)]

        within_std = np.mean([np.std(b1), np.std(b2), np.std(b3)])
        total_std = np.std(list(w.values()))

        assert within_std < total_std, \
            f"Within-block std ({within_std:.6f}) should be < total std ({total_std:.6f})"

    def test_risk_measures_differ(self):
        """Different risk measures should generally produce different allocations."""
        from denoised_herc import herc_allocate
        df = generate_block_returns(T=300, seed=123)
        result_var = herc_allocate(df, risk_measure='variance')
        result_cvar = herc_allocate(df, risk_measure='cvar')
        w_var = np.array([result_var['weights'][k] for k in sorted(result_var['weights'])])
        w_cvar = np.array([result_cvar['weights'][k] for k in sorted(result_cvar['weights'])])
        # Both valid
        assert abs(sum(result_var['weights'].values()) - 1.0) < 1e-8
        assert abs(sum(result_cvar['weights'].values()) - 1.0) < 1e-8
        # At least slightly different
        assert np.max(np.abs(w_var - w_cvar)) > 1e-6, \
            "Variance and CVaR should produce different weight vectors"

    def test_lower_risk_block_gets_more_weight(self):
        """A block with lower risk should receive more total weight
        than a block with higher risk (inverse risk allocation)."""
        from denoised_herc import herc_allocate
        rng = np.random.RandomState(66)
        T = 500
        N = 6
        # Block 1 (assets 0-2): low volatility, high within-corr
        # Block 2 (assets 3-5): high volatility, high within-corr
        cov = np.zeros((N, N))
        for i in range(3):
            cov[i, i] = 0.0001  # vol = 0.01
            for j in range(3):
                if i != j:
                    cov[i, j] = 0.00009  # corr = 0.9
        for i in range(3, 6):
            cov[i, i] = 0.01  # vol = 0.1
            for j in range(3, 6):
                if i != j:
                    cov[i, j] = 0.009  # corr = 0.9

        returns = rng.multivariate_normal(np.zeros(N), cov, T)
        df = pd.DataFrame(
            returns,
            index=pd.date_range('2020-01-01', periods=T, freq='B'),
            columns=['LO_A', 'LO_B', 'LO_C', 'HI_D', 'HI_E', 'HI_F']
        )

        result = herc_allocate(df, risk_measure='variance', linkage_method='ward')
        w = result['weights']

        lo_total = w['LO_A'] + w['LO_B'] + w['LO_C']
        hi_total = w['HI_D'] + w['HI_E'] + w['HI_F']

        assert lo_total > hi_total, \
            f"Low-risk block ({lo_total:.4f}) should have more weight than high-risk block ({hi_total:.4f})"


# ---- Edge case tests ----

class TestEdgeCases:
    def test_two_assets(self):
        """Must handle a minimal 2-asset portfolio."""
        from denoised_herc import herc_allocate
        rng = np.random.RandomState(99)
        T = 200
        returns = pd.DataFrame(
            rng.normal(0, 0.02, (T, 2)),
            index=pd.date_range('2020-01-01', periods=T, freq='B'),
            columns=['A', 'B']
        )
        result = herc_allocate(returns, risk_measure='variance')
        assert abs(sum(result['weights'].values()) - 1.0) < 1e-8
        assert all(w >= -1e-10 for w in result['weights'].values())
        assert len(result['weights']) == 2
        assert result['n_clusters'] >= 1

    def test_large_portfolio(self):
        """Must handle 25 assets."""
        from denoised_herc import herc_allocate
        rng = np.random.RandomState(77)
        T, N = 400, 25
        returns = pd.DataFrame(
            rng.normal(0, 0.02, (T, N)),
            index=pd.date_range('2020-01-01', periods=T, freq='B'),
            columns=[f'X{i:02d}' for i in range(N)]
        )
        result = herc_allocate(returns, risk_measure='cvar')
        assert abs(sum(result['weights'].values()) - 1.0) < 1e-8
        assert len(result['weights']) == N
        for w in result['weights'].values():
            assert w > 0

    def test_denoised_two_assets(self):
        """Denoising must work with a minimal portfolio."""
        from denoised_herc import herc_allocate
        rng = np.random.RandomState(88)
        T = 200
        returns = pd.DataFrame(
            rng.normal(0, 0.02, (T, 2)),
            index=pd.date_range('2020-01-01', periods=T, freq='B'),
            columns=['A', 'B']
        )
        result = herc_allocate(returns, risk_measure='cvar', denoise=True)
        assert abs(sum(result['weights'].values()) - 1.0) < 1e-8
        assert result['denoised'] is True

    def test_large_portfolio_denoised(self):
        """Denoising must work with a larger portfolio."""
        from denoised_herc import herc_allocate
        rng = np.random.RandomState(55)
        T, N = 250, 20
        returns = pd.DataFrame(
            rng.normal(0, 0.02, (T, N)),
            index=pd.date_range('2020-01-01', periods=T, freq='B'),
            columns=[f'D{i:02d}' for i in range(N)]
        )
        result = herc_allocate(returns, risk_measure='std', denoise=True)
        assert abs(sum(result['weights'].values()) - 1.0) < 1e-8
        assert all(w > 0 for w in result['weights'].values())
        assert len(result['weights']) == N
        assert result['denoised'] is True


# ---- Denoising quality tests ----

class TestDenoisingQuality:
    def test_noise_eigenvalue_compression(self):
        """After denoising, noise eigenvalues should have lower dispersion."""
        from denoised_herc import denoise_covariance
        rng = np.random.RandomState(42)
        N, T = 12, 80  # low T/N ratio means significant noise
        data = rng.normal(0, 0.02, (T, N))
        cov = np.cov(data, rowvar=False)

        std_raw = np.sqrt(np.diag(cov))
        corr_raw = cov / np.outer(std_raw, std_raw)
        eigs_before = np.sort(np.linalg.eigvalsh(corr_raw))

        denoised = denoise_covariance(cov, T / N)
        std_den = np.sqrt(np.diag(denoised))
        corr_den = denoised / np.outer(std_den, std_den)
        eigs_after = np.sort(np.linalg.eigvalsh(corr_den))

        # Bottom half eigenvalues (noise) should be more uniform
        half = N // 2
        noise_std_before = np.std(eigs_before[:half])
        noise_std_after = np.std(eigs_after[:half])
        assert noise_std_after <= noise_std_before + 1e-10, \
            f"Noise eigenvalue dispersion should not increase: {noise_std_before:.6f} -> {noise_std_after:.6f}"


# ---- Cluster detection tests ----

class TestClusterDetection:
    def test_well_separated_blocks(self):
        """For strongly separated 3-block data, n_clusters should reflect
        the true grouping (approximately 3)."""
        from denoised_herc import herc_allocate
        N = 15
        T = 500
        rng = np.random.RandomState(42)

        # Very strong block structure: within-corr = 0.95, cross-corr = 0
        cov = np.eye(N) * 0.0004
        for block_start in [0, 5, 10]:
            for i in range(block_start, block_start + 5):
                for j in range(block_start, block_start + 5):
                    if i != j:
                        cov[i, j] = 0.00038  # corr = 0.95

        returns = rng.multivariate_normal(np.zeros(N), cov, T)
        df = pd.DataFrame(
            returns,
            index=pd.date_range('2020-01-01', periods=T, freq='B'),
            columns=[f'BLK_{i:02d}' for i in range(N)]
        )

        result = herc_allocate(df, risk_measure='variance', linkage_method='ward')
        assert 3 <= result['n_clusters'] <= 5, \
            f"Expected ~3 clusters for 3-block data, got {result['n_clusters']}"

    def test_four_block_detection(self):
        """For strongly separated 4-block data, detected count should be near 4."""
        from denoised_herc import herc_allocate
        N = 20  # 4 blocks of 5
        T = 600
        rng = np.random.RandomState(42)

        cov = np.eye(N) * 0.0004
        for block_start in [0, 5, 10, 15]:
            for i in range(block_start, block_start + 5):
                for j in range(block_start, block_start + 5):
                    if i != j:
                        cov[i, j] = 0.00036  # corr = 0.9

        returns = rng.multivariate_normal(np.zeros(N), cov, T)
        df = pd.DataFrame(
            returns,
            index=pd.date_range('2020-01-01', periods=T, freq='B'),
            columns=[f'Q_{i:02d}' for i in range(N)]
        )

        result = herc_allocate(df, risk_measure='variance', linkage_method='ward')
        assert 3 <= result['n_clusters'] <= 6, \
            f"Expected ~4 clusters for 4-block data, got {result['n_clusters']}"


# ---- CLI tests ----

class TestCLI:
    def test_basic(self, tmp_path):
        df = generate_block_returns(T=200, seed=42)
        csv_path = str(tmp_path / 'returns.csv')
        json_path = str(tmp_path / 'output.json')
        df.to_csv(csv_path)

        result = subprocess.run(
            ['python3', '/app/denoised_herc.py',
             '--input', csv_path, '--output', json_path,
             '--risk-measure', 'cvar'],
            capture_output=True, text=True, timeout=180
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(json_path) as f:
            output = json.load(f)

        assert 'weights' in output
        assert 'n_clusters' in output
        assert 'denoised' in output
        assert isinstance(output['weights'], dict)
        assert isinstance(output['n_clusters'], int)
        assert isinstance(output['denoised'], bool)
        assert abs(sum(output['weights'].values()) - 1.0) < 1e-8

    def test_denoise_flag(self, tmp_path):
        df = generate_block_returns(T=200, seed=42)
        csv_path = str(tmp_path / 'returns.csv')
        json_path = str(tmp_path / 'output.json')
        df.to_csv(csv_path)

        result = subprocess.run(
            ['python3', '/app/denoised_herc.py',
             '--input', csv_path, '--output', json_path,
             '--denoise', '--risk-measure', 'variance'],
            capture_output=True, text=True, timeout=180
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(json_path) as f:
            output = json.load(f)

        assert output['denoised'] is True
        assert abs(sum(output['weights'].values()) - 1.0) < 1e-8

    def test_all_risk_measures_cli(self, tmp_path):
        df = generate_block_returns(T=200, seed=42)
        csv_path = str(tmp_path / 'returns.csv')
        df.to_csv(csv_path)

        for rm in ['cvar', 'variance', 'std']:
            json_path = str(tmp_path / f'output_{rm}.json')
            result = subprocess.run(
                ['python3', '/app/denoised_herc.py',
                 '--input', csv_path, '--output', json_path,
                 '--risk-measure', rm],
                capture_output=True, text=True, timeout=180
            )
            assert result.returncode == 0, f"CLI failed for {rm}: {result.stderr}"

            with open(json_path) as f:
                output = json.load(f)
            assert abs(sum(output['weights'].values()) - 1.0) < 1e-8

    def test_custom_options(self, tmp_path):
        df = generate_block_returns(T=200, seed=42)
        csv_path = str(tmp_path / 'returns.csv')
        json_path = str(tmp_path / 'output.json')
        df.to_csv(csv_path)

        result = subprocess.run(
            ['python3', '/app/denoised_herc.py',
             '--input', csv_path, '--output', json_path,
             '--risk-measure', 'cvar', '--cvar-alpha', '0.10',
             '--linkage', 'complete', '--denoise', '--kde-bwidth', '0.15'],
            capture_output=True, text=True, timeout=180
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(json_path) as f:
            output = json.load(f)
        assert output['denoised'] is True
        assert abs(sum(output['weights'].values()) - 1.0) < 1e-8

    def test_sample_data(self, tmp_path):
        """CLI should work with the provided sample dataset."""
        json_path = str(tmp_path / 'output.json')
        result = subprocess.run(
            ['python3', '/app/denoised_herc.py',
             '--input', '/app/data/sample_returns.csv',
             '--output', json_path,
             '--risk-measure', 'variance'],
            capture_output=True, text=True, timeout=180
        )
        assert result.returncode == 0, f"CLI failed on sample data: {result.stderr}"

        with open(json_path) as f:
            output = json.load(f)
        assert abs(sum(output['weights'].values()) - 1.0) < 1e-8
        assert len(output['weights']) == 5  # sample has 5 assets
