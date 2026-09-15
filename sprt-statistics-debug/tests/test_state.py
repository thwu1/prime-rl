"""
Tests for the SPRT analysis service.

Verifies correctness of the statistical engine, fastchess output parser,
and REST API server — both individually and as an integrated pipeline.

"""

import math
import os
import sys
import tempfile
import json

# Configure test database BEFORE importing server module
_test_db_path = tempfile.mktemp(suffix="_sprt_test.db")
os.environ["SPRT_DB_PATH"] = _test_db_path

sys.path.insert(0, "/app")

from stats import LLRcalc
from stats.brownian import Brownian
from stats.sprt import sprt
from stats import stat_util
from parser import parse_fastchess_output
from server import app, init_db


# ===========================================================
# Test Suite 1: Score Mapping (results_to_pdf)
# ===========================================================

class TestResultsToPdf:
    def test_trinomial_score_values(self):
        """Trinomial scores must be [0, 0.5, 1.0], not [0, 1/3, 2/3]."""
        N, pdf = LLRcalc.results_to_pdf([100, 200, 100])
        scores = [s for s, p in pdf]
        assert len(scores) == 3
        assert abs(scores[0] - 0.0) < 1e-12
        assert abs(scores[1] - 0.5) < 1e-12
        assert abs(scores[2] - 1.0) < 1e-12

    def test_pentanomial_score_values(self):
        """Pentanomial scores must be [0, 0.25, 0.5, 0.75, 1.0]."""
        N, pdf = LLRcalc.results_to_pdf([10, 20, 40, 20, 10])
        scores = [s for s, p in pdf]
        expected = [0.0, 0.25, 0.5, 0.75, 1.0]
        for got, want in zip(scores, expected):
            assert abs(got - want) < 1e-12, f"score {got} != {want}"

    def test_probabilities_sum_to_one(self):
        """PDF probabilities must sum to 1."""
        N, pdf = LLRcalc.results_to_pdf([30, 50, 20])
        total = sum(p for _, p in pdf)
        assert abs(total - 1.0) < 1e-10

    def test_trinomial_mean_symmetric(self):
        """Symmetric trinomial [n, m, n] must have mean exactly 0.5."""
        N, pdf = LLRcalc.results_to_pdf([100, 200, 100])
        mu, var = LLRcalc.stats(pdf)
        assert abs(mu - 0.5) < 1e-10


# ===========================================================
# Test Suite 2: Logistic Function
# ===========================================================

class TestLogistic:
    def test_L_zero(self):
        """L_(0) must be exactly 0.5."""
        assert LLRcalc.L_(0) == 0.5

    def test_L_400(self):
        """L_(400) must be 10/11."""
        assert abs(LLRcalc.L_(400) - 10.0 / 11.0) < 1e-12

    def test_L_symmetry(self):
        """L_(x) + L_(-x) must equal 1."""
        for x in [1, 5, 50, 100, 400]:
            s = LLRcalc.L_(x) + LLRcalc.L_(-x)
            assert abs(s - 1.0) < 1e-12, f"symmetry violated at x={x}"


# ===========================================================
# Test Suite 3: LLR Drift-Variance (alt2 approximation)
# ===========================================================

class TestLLRDriftVariance:
    def test_variance_uses_variance_not_stdev(self):
        """sigma^2_LLR must be (s1-s0)^2 / var, NOT (s1-s0)^2 / sqrt(var)."""
        pdf = [(0.0, 0.2), (0.5, 0.5), (1.0, 0.3)]
        s0, s1 = 0.45, 0.55
        mu_llr, var_llr = LLRcalc.LLR_drift_variance_alt2(pdf, s0, s1, None)
        mu_pdf, var_pdf = LLRcalc.stats(pdf)
        expected_var = (s1 - s0) ** 2 / var_pdf
        assert abs(var_llr - expected_var) < 1e-10, (
            f"var_llr={var_llr}, expected={expected_var}"
        )

    def test_drift_uses_variance_not_stdev(self):
        """mu_LLR must be (s-(s0+s1)/2)*(s1-s0)/var, NOT .../sqrt(var)."""
        pdf = [(0.0, 0.2), (0.5, 0.5), (1.0, 0.3)]
        s0, s1 = 0.45, 0.55
        mu_llr, var_llr = LLRcalc.LLR_drift_variance_alt2(pdf, s0, s1, None)
        mu_pdf, var_pdf = LLRcalc.stats(pdf)
        expected_mu = (mu_pdf - (s0 + s1) / 2) * (s1 - s0) / var_pdf
        assert abs(mu_llr - expected_mu) < 1e-10, (
            f"mu_llr={mu_llr}, expected={expected_mu}"
        )

    def test_drift_zero_at_midpoint(self):
        """When mu equals (s0+s1)/2, drift should be 0."""
        pdf = [(0.0, 0.25), (0.5, 0.50), (1.0, 0.25)]
        s0, s1 = 0.4, 0.6
        mu_llr, _ = LLRcalc.LLR_drift_variance_alt2(pdf, s0, s1, None)
        assert abs(mu_llr) < 1e-12

    def test_llr_alt2_sign(self):
        """LLR should be positive when score exceeds midpoint of (s0,s1)."""
        pdf = [(0.0, 0.1), (0.5, 0.5), (1.0, 0.4)]
        mu, _ = LLRcalc.stats(pdf)
        assert mu > 0.55
        llr = LLRcalc.LLR_alt2(pdf, 0.4, 0.6)
        assert llr > 0


# ===========================================================
# Test Suite 4: MLE Expected
# ===========================================================

class TestMLEExpected:
    def test_mle_at_sample_mean_is_identity(self):
        """MLE at the sample mean must return the original distribution."""
        pdf = [(0.0, 0.25), (0.5, 0.50), (1.0, 0.25)]
        mu, _ = LLRcalc.stats(pdf)
        pdf_mle = LLRcalc.MLE_expected(pdf, mu)
        for (a1, p1), (a2, p2) in zip(pdf, pdf_mle):
            assert abs(a1 - a2) < 1e-12
            assert abs(p1 - p2) < 1e-6, f"p_orig={p1}, p_mle={p2}"

    def test_mle_constraint_satisfied(self):
        """MLE result must have the requested mean."""
        pdf = [(0.0, 0.3), (0.5, 0.4), (1.0, 0.3)]
        target = 0.55
        pdf_mle = LLRcalc.MLE_expected(pdf, target)
        mu_mle = sum(a * p for a, p in pdf_mle)
        assert abs(mu_mle - target) < 1e-6


# ===========================================================
# Test Suite 5: Brownian Motion
# ===========================================================

class TestBrownian:
    def test_alt1_alt2_consistency(self):
        """Series expansion (alt1) and Siegmund approximation (alt2) must
        approximately agree for the same parameters."""
        b_obj = Brownian(a=-2.0, b=1.0, mu=0.02, sigma=0.15)
        T = 200
        y = 0.0
        cdf1 = b_obj.outcome_cdf_alt1(T, y)
        cdf2 = b_obj.outcome_cdf_alt2(T, y)
        assert abs(cdf1 - cdf2) < 0.05, (
            f"alt1={cdf1:.6f}, alt2={cdf2:.6f}, diff={abs(cdf1-cdf2):.6f}"
        )

    def test_cdf_in_valid_range(self):
        """CDF values must be in [0, 1]."""
        b_obj = Brownian(a=-2.0, b=1.0, mu=0.02, sigma=0.15)
        cdf = b_obj.outcome_cdf(T=200, y=0.0)
        assert -0.01 <= cdf <= 1.01

    def test_positive_drift_shifts_cdf(self):
        """Positive drift should produce different CDF than zero drift."""
        b0 = Brownian(a=-2.0, b=1.0, mu=0.0001, sigma=0.15)
        b1 = Brownian(a=-2.0, b=1.0, mu=0.05, sigma=0.15)
        cdf0 = b0.outcome_cdf(T=200, y=0.0)
        cdf1 = b1.outcome_cdf(T=200, y=0.0)
        assert abs(cdf1 - cdf0) > 0.01


# ===========================================================
# Test Suite 6: SPRT Pentanomial sigma_pg
# ===========================================================

class TestSPRTPentanomial:
    def test_pentanomial_sigma_pg_factor_of_two(self):
        """For pentanomial data, sigma_pg must be sqrt(2*var), not sqrt(var)."""
        s = sprt(alpha=0.05, beta=0.05, elo0=0, elo1=5, elo_model="normalized")
        s.set_state([100, 200, 400, 200, 100])
        N, pdf = LLRcalc.results_to_pdf([100, 200, 400, 200, 100])
        _, var = LLRcalc.stats(pdf)
        expected_sigma = (2 * var) ** 0.5
        assert abs(s.sigma_pg - expected_sigma) < 1e-10, (
            f"sigma_pg={s.sigma_pg}, expected={expected_sigma}"
        )

    def test_trinomial_sigma_pg_no_factor(self):
        """For trinomial data, sigma_pg must be sqrt(var) (no factor of 2)."""
        s = sprt(alpha=0.05, beta=0.05, elo0=0, elo1=5, elo_model="normalized")
        s.set_state([100, 200, 100])
        N, pdf = LLRcalc.results_to_pdf([100, 200, 100])
        _, var = LLRcalc.stats(pdf)
        expected_sigma = var ** 0.5
        assert abs(s.sigma_pg - expected_sigma) < 1e-10


# ===========================================================
# Test Suite 7: BayesElo Conversions
# ===========================================================

class TestBayesElo:
    def test_bayeselo_to_proba_known_value(self):
        """bayeselo_to_proba(400, 0) must give P_win = 10/11, P_loss = 1/11."""
        P = stat_util.bayeselo_to_proba(400, 0)
        assert abs(P[2] - 10.0 / 11.0) < 1e-6, f"P_win={P[2]}, expected={10/11}"
        assert abs(P[0] - 1.0 / 11.0) < 1e-6, f"P_loss={P[0]}, expected={1/11}"

    def test_bayeselo_zero_elo_symmetry(self):
        """With elo=0, win and loss probabilities must be equal."""
        P = stat_util.bayeselo_to_proba(0, 200)
        assert abs(P[2] - P[0]) < 1e-12

    def test_bayeselo_probabilities_sum_to_one(self):
        """Win + loss + draw must equal 1."""
        P = stat_util.bayeselo_to_proba(50, 200)
        assert abs(sum(P) - 1.0) < 1e-12

    def test_bayeselo_roundtrip(self):
        """bayeselo_to_proba -> proba_to_bayeselo must round-trip."""
        elo_in, drawelo_in = 75, 250
        P = stat_util.bayeselo_to_proba(elo_in, drawelo_in)
        elo_out, drawelo_out = stat_util.proba_to_bayeselo(P)
        assert abs(elo_in - elo_out) < 1e-4, (
            f"elo roundtrip: {elo_in} -> {elo_out}"
        )
        assert abs(drawelo_in - drawelo_out) < 1e-4, (
            f"drawelo roundtrip: {drawelo_in} -> {drawelo_out}"
        )

    def test_bayeselo_to_elo_zero(self):
        """BayesElo 0 with any drawelo should give logistic Elo 0."""
        for drawelo in [100, 200, 300]:
            le = stat_util.bayeselo_to_elo(0, drawelo)
            assert abs(le) < 1e-6, f"bayeselo_to_elo(0, {drawelo}) = {le}"


# ===========================================================
# Test Suite 8: Statistical Integration
# ===========================================================

class TestStatIntegration:
    def test_symmetric_results_elo_near_zero(self):
        """Symmetric W/L results should produce Elo estimate near 0."""
        s = sprt(alpha=0.05, beta=0.05, elo0=0, elo1=5, elo_model="logistic")
        s.set_state([500, 1000, 500])
        a = s.analytics()
        assert abs(a["elo"]) < 10, f"Elo={a['elo']}, expected near 0"
        assert a["ci"][0] < 0 < a["ci"][1], (
            f"CI=[{a['ci'][0]}, {a['ci'][1]}] should contain 0"
        )

    def test_llr_boundaries_correct(self):
        """SPRT boundaries must match log(beta/(1-alpha)) and log((1-beta)/alpha)."""
        s = sprt(alpha=0.05, beta=0.05, elo0=0, elo1=5, elo_model="logistic")
        s.set_state([100, 200, 100])
        a = s.analytics()
        expected_a = math.log(0.05 / 0.95)
        expected_b = math.log(0.95 / 0.05)
        assert abs(a["a"] - expected_a) < 1e-10
        assert abs(a["b"] - expected_b) < 1e-10

    def test_analytics_returns_finite_values(self):
        """All analytics outputs must be finite numbers."""
        s = sprt(alpha=0.05, beta=0.05, elo0=0, elo1=5, elo_model="logistic")
        s.set_state([200, 500, 300])
        a = s.analytics()
        for key in ["elo", "LLR", "LOS"]:
            assert math.isfinite(a[key]), f"{key}={a[key]} is not finite"
        for v in a["ci"]:
            assert math.isfinite(v), f"CI value {v} is not finite"

    def test_llr_logistic_sign_for_winning(self):
        """Heavily winning results should produce positive LLR."""
        llr = LLRcalc.LLR_logistic(0, 5, [10, 200, 800])
        assert llr > 0, f"LLR={llr}, expected positive"

    def test_llr_logistic_sign_for_losing(self):
        """Heavily losing results should produce negative LLR."""
        llr = LLRcalc.LLR_logistic(0, 5, [800, 200, 10])
        assert llr < 0, f"LLR={llr}, expected negative"


# ===========================================================
# Test Suite 9: Fastchess Output Parser
# ===========================================================

class TestParserNormal:
    def test_wld_extraction(self):
        """Parser must extract correct W/D/L from normal output."""
        with open("/app/data/output_normal.txt") as f:
            text = f.read()
        result = parse_fastchess_output(text)
        assert result['games'] == 200
        assert result['wins'] == 65
        assert result['losses'] == 55
        assert result['draws'] == 80

    def test_pentanomial_extraction(self):
        """Parser must extract correct pentanomial frequencies."""
        with open("/app/data/output_normal.txt") as f:
            text = f.read()
        result = parse_fastchess_output(text)
        assert result['pentanomial'] == [5, 22, 48, 18, 7]

    def test_no_crashes_in_clean_output(self):
        """Clean output should have zero crashes and time losses."""
        with open("/app/data/output_normal.txt") as f:
            text = f.read()
        result = parse_fastchess_output(text)
        assert result['crashes'] == 0
        assert result['time_losses'] == 0

    def test_game_count_consistency(self):
        """2 * sum(pentanomial) must equal games count."""
        with open("/app/data/output_normal.txt") as f:
            text = f.read()
        result = parse_fastchess_output(text)
        assert 2 * sum(result['pentanomial']) == result['games']


class TestParserCrashes:
    def test_crash_detection(self):
        """Parser must detect disconnect/stall as crashes."""
        with open("/app/data/output_crashes.txt") as f:
            text = f.read()
        result = parse_fastchess_output(text)
        assert result['crashes'] == 2

    def test_time_loss_detection(self):
        """Parser must detect 'on time' and 'timeout' as time losses."""
        with open("/app/data/output_crashes.txt") as f:
            text = f.read()
        result = parse_fastchess_output(text)
        assert result['time_losses'] == 2

    def test_wld_with_incidents(self):
        """W/D/L extraction must work correctly despite crash/timeout lines."""
        with open("/app/data/output_crashes.txt") as f:
            text = f.read()
        result = parse_fastchess_output(text)
        assert result['wins'] == 40
        assert result['losses'] == 28
        assert result['draws'] == 32

    def test_pentanomial_with_incidents(self):
        """Pentanomial must be extracted correctly despite crash/timeout lines."""
        with open("/app/data/output_crashes.txt") as f:
            text = f.read()
        result = parse_fastchess_output(text)
        assert result['pentanomial'] == [3, 10, 20, 12, 5]


class TestParserMultiblock:
    def test_uses_last_block_games(self):
        """Parser must return data from the LAST results block."""
        with open("/app/data/output_multiblock.txt") as f:
            text = f.read()
        result = parse_fastchess_output(text)
        assert result['games'] == 120

    def test_uses_last_block_wld(self):
        """W/D/L must come from the final results block."""
        with open("/app/data/output_multiblock.txt") as f:
            text = f.read()
        result = parse_fastchess_output(text)
        assert result['wins'] == 42
        assert result['losses'] == 32
        assert result['draws'] == 46

    def test_uses_last_block_pentanomial(self):
        """Pentanomial must come from the final results block."""
        with open("/app/data/output_multiblock.txt") as f:
            text = f.read()
        result = parse_fastchess_output(text)
        assert result['pentanomial'] == [3, 11, 28, 13, 5]


# ===========================================================
# Test Suite 10: API Server — calc_elo
# ===========================================================

class TestCalcElo:
    def setup_method(self):
        if os.path.exists(_test_db_path):
            os.remove(_test_db_path)
        init_db()
        self.client = app.test_client()

    def test_trinomial_symmetric_elo_near_zero(self):
        """Symmetric W/L via calc_elo must give Elo near 0."""
        resp = self.client.get(
            '/api/calc_elo?W=500&D=1000&L=500&elo0=0&elo1=5&elo_model=logistic'
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert abs(data['elo']) < 10, f"Elo={data['elo']}"
        assert data['ci'][0] < 0 < data['ci'][1]

    def test_trinomial_positive_elo(self):
        """Winning results via calc_elo must give positive Elo."""
        resp = self.client.get('/api/calc_elo?W=600&D=800&L=400&elo0=0&elo1=5')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['elo'] > 0

    def test_pentanomial_response(self):
        """Pentanomial calc_elo must return all required fields."""
        resp = self.client.get(
            '/api/calc_elo?LL=10&LD=50&DDWL=200&WD=50&WW=10&elo0=0&elo1=5'
        )
        assert resp.status_code == 200
        data = resp.get_json()
        for key in ['elo', 'ci', 'LLR', 'LOS', 'a', 'b']:
            assert key in data, f"Missing key: {key}"

    def test_sprt_bounds_correct(self):
        """SPRT bounds in calc_elo response must be mathematically correct."""
        resp = self.client.get('/api/calc_elo?W=500&D=1000&L=500')
        data = resp.get_json()
        expected_a = math.log(0.05 / 0.95)
        expected_b = math.log(0.95 / 0.05)
        assert abs(data['a'] - expected_a) < 1e-6
        assert abs(data['b'] - expected_b) < 1e-6


# ===========================================================
# Test Suite 11: API Server — submit/retrieve
# ===========================================================

class TestSubmitRetrieve:
    def setup_method(self):
        if os.path.exists(_test_db_path):
            os.remove(_test_db_path)
        init_db()
        self.client = app.test_client()

    def test_submit_and_get_elo(self):
        """Submitted results must be retrievable via get_elo."""
        payload = {
            'run_id': 'test-run-1',
            'stats': {'wins': 100, 'losses': 80, 'draws': 200},
            'elo0': 0, 'elo1': 5, 'elo_model': 'logistic'
        }
        resp = self.client.post('/api/submit_results',
                                data=json.dumps(payload),
                                content_type='application/json')
        assert resp.status_code == 200
        submitted = resp.get_json()
        assert 'elo' in submitted

        resp2 = self.client.get('/api/get_elo/test-run-1')
        assert resp2.status_code == 200
        retrieved = resp2.get_json()
        assert abs(retrieved['elo'] - submitted['elo']) < 1e-6
        assert abs(retrieved['LLR'] - submitted['LLR']) < 1e-6

    def test_submit_with_pentanomial(self):
        """Submitting pentanomial data must produce valid analytics."""
        payload = {
            'run_id': 'penta-run',
            'stats': {
                'wins': 65, 'losses': 55, 'draws': 80,
                'pentanomial': [5, 22, 48, 18, 7]
            },
            'elo0': 0, 'elo1': 5, 'elo_model': 'logistic'
        }
        resp = self.client.post('/api/submit_results',
                                data=json.dumps(payload),
                                content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert math.isfinite(data['elo'])
        assert math.isfinite(data['LLR'])

    def test_get_elo_unknown_run(self):
        """get_elo for unknown run_id must return 404."""
        resp = self.client.get('/api/get_elo/nonexistent-run')
        assert resp.status_code == 404

    def test_submit_raw_output(self):
        """Raw fastchess output must be parsed, stored, and analyzed."""
        with open("/app/data/output_normal.txt") as f:
            raw = f.read()
        payload = {
            'run_id': 'raw-run-1',
            'raw_output': raw,
            'elo0': 0, 'elo1': 5, 'elo_model': 'logistic'
        }
        resp = self.client.post('/api/submit_raw',
                                data=json.dumps(payload),
                                content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'elo' in data
        assert math.isfinite(data['elo'])

        # Verify retrieval works
        resp2 = self.client.get('/api/get_elo/raw-run-1')
        assert resp2.status_code == 200
        retrieved = resp2.get_json()
        assert abs(retrieved['elo'] - data['elo']) < 1e-6


# ===========================================================
# Test Suite 12: End-to-End Integration
# ===========================================================

class TestEndToEnd:
    def setup_method(self):
        if os.path.exists(_test_db_path):
            os.remove(_test_db_path)
        init_db()
        self.client = app.test_client()

    def test_raw_to_analytics_pipeline(self):
        """Complete pipeline: raw output -> parse -> store -> retrieve -> verify."""
        with open("/app/data/output_crashes.txt") as f:
            raw = f.read()

        # Submit raw output
        resp = self.client.post('/api/submit_raw',
                                data=json.dumps({
                                    'run_id': 'e2e-crash',
                                    'raw_output': raw,
                                    'elo0': 0, 'elo1': 5
                                }),
                                content_type='application/json')
        assert resp.status_code == 200
        submitted = resp.get_json()

        # Retrieve and compare
        resp2 = self.client.get('/api/get_elo/e2e-crash')
        assert resp2.status_code == 200
        retrieved = resp2.get_json()
        assert abs(submitted['elo'] - retrieved['elo']) < 1e-6

    def test_calc_vs_submit_consistency(self):
        """calc_elo and submit_results must produce identical analytics
        for the same input data."""
        # calc_elo
        resp1 = self.client.get(
            '/api/calc_elo?W=200&D=500&L=300&elo0=0&elo1=5&elo_model=logistic'
        )
        calc_data = resp1.get_json()

        # submit_results with same data
        resp2 = self.client.post('/api/submit_results',
                                 data=json.dumps({
                                     'run_id': 'consistency-test',
                                     'stats': {'wins': 200, 'losses': 300, 'draws': 500},
                                     'elo0': 0, 'elo1': 5, 'elo_model': 'logistic'
                                 }),
                                 content_type='application/json')
        submit_data = resp2.get_json()

        assert abs(calc_data['elo'] - submit_data['elo']) < 1e-6
        assert abs(calc_data['LLR'] - submit_data['LLR']) < 1e-6
        assert abs(calc_data['LOS'] - submit_data['LOS']) < 1e-6

    def test_winning_elo_positive_via_api(self):
        """Winning results submitted via API must yield positive Elo."""
        payload = {
            'run_id': 'winning-test',
            'stats': {'wins': 400, 'losses': 200, 'draws': 400},
            'elo0': 0, 'elo1': 5
        }
        resp = self.client.post('/api/submit_results',
                                data=json.dumps(payload),
                                content_type='application/json')
        data = resp.get_json()
        assert data['elo'] > 0, f"Elo={data['elo']}, expected positive"


# ===========================================================
# Test Suite 13: LLR Normalized Model
# ===========================================================

class TestLLRNormalized:
    def test_normalized_trinomial_positive_for_winning(self):
        """LLR_normalized must be positive when new engine is winning."""
        llr = LLRcalc.LLR_normalized(0, 5, [200, 500, 300])
        assert llr > 0, f"LLR={llr}, expected positive"

    def test_normalized_trinomial_negative_for_losing(self):
        """LLR_normalized must be negative when new engine is losing."""
        llr = LLRcalc.LLR_normalized(0, 5, [300, 500, 200])
        assert llr < 0, f"LLR={llr}, expected negative"

    def test_normalized_pentanomial_positive_for_winning(self):
        """LLR_normalized with pentanomial must be positive for winning data."""
        llr = LLRcalc.LLR_normalized(0, 5, [10, 50, 200, 100, 40])
        assert llr > 0, f"LLR={llr}, expected positive"

    def test_normalized_alt_vs_exact_pentanomial_consistency(self):
        """LLR_normalized and LLR_normalized_alt must approximately agree
        for pentanomial data. Both compute the normalized-model LLR for game
        pairs using different methods (exact MLE vs quadratic approximation),
        so they should converge for typical chess engine test data."""
        results = [10, 50, 200, 100, 40]
        llr_exact = LLRcalc.LLR_normalized(0, 5, results)
        llr_alt = LLRcalc.LLR_normalized_alt(0, 5, results)
        rel_diff = abs(llr_exact - llr_alt) / max(abs(llr_exact), 0.1)
        assert rel_diff < 0.25, (
            f"exact={llr_exact:.4f}, alt={llr_alt:.4f}, rel_diff={rel_diff:.4f}"
        )


# ===========================================================
# Test Suite 14: SPRT_elo Multi-Model Integration
# ===========================================================

class TestSPRTEloIntegration:
    def test_sprt_elo_logistic_symmetric(self):
        """SPRT_elo with logistic model: symmetric data must give Elo near 0."""
        R = {"wins": 500, "losses": 500, "draws": 1000}
        a = stat_util.SPRT_elo(R, elo0=0, elo1=5, elo_model="logistic")
        assert abs(a["elo"]) < 10
        assert math.isfinite(a["LLR"])

    def test_sprt_elo_normalized_symmetric(self):
        """SPRT_elo with normalized model: symmetric data must give Elo near 0."""
        R = {"wins": 500, "losses": 500, "draws": 1000}
        a = stat_util.SPRT_elo(R, elo0=0, elo1=5, elo_model="normalized")
        assert abs(a["elo"]) < 15
        assert math.isfinite(a["LLR"])

    def test_sprt_elo_normalized_pentanomial(self):
        """SPRT_elo with normalized model and pentanomial data must produce
        valid, finite analytics."""
        R = {"wins": 65, "losses": 55, "draws": 80,
             "pentanomial": [5, 22, 48, 18, 7]}
        a = stat_util.SPRT_elo(R, elo0=0, elo1=5, elo_model="normalized")
        assert math.isfinite(a["elo"])
        assert math.isfinite(a["LLR"])

    def test_sprt_elo_bayeselo_symmetric(self):
        """SPRT_elo with BayesElo model: symmetric data must give Elo near 0."""
        R = {"wins": 500, "losses": 500, "draws": 1000}
        a = stat_util.SPRT_elo(R, elo0=0, elo1=5, elo_model="BayesElo")
        assert abs(a["elo"]) < 10
        assert math.isfinite(a["LLR"])

    def test_sprt_elo_normalized_llr_differs_from_logistic(self):
        """The LLR computation must be model-specific: SPRT_elo with the
        normalized model must use LLR_normalized (not LLR_logistic). When
        the same asymmetric data is analyzed with both models, the final
        LLR values must differ because logistic and normalized Elo models
        define score differently."""
        R = {"wins": 350, "losses": 200, "draws": 450}
        a_norm = stat_util.SPRT_elo(R, elo0=0, elo1=5, elo_model="normalized")
        a_log = stat_util.SPRT_elo(R, elo0=0, elo1=5, elo_model="logistic")
        assert abs(a_norm["LLR"] - a_log["LLR"]) > 0.01, (
            f"norm LLR={a_norm['LLR']:.6f} vs log LLR={a_log['LLR']:.6f} — "
            f"model-specific LLR must differ"
        )
