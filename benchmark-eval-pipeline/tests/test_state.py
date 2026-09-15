
"""
Tests for the benchmark evaluation pipeline implemented at /app/evaluator.py.
Verifies metric computation, tournament selection, statistical aggregation,
CLI interface, configuration loading, and SQLite caching.
"""

import sys
import os
import ast
import json
import subprocess
import sqlite3
import tempfile

import numpy as np
import pytest

sys.path.insert(0, "/app")

from evaluator import (
    photometric_loss,
    ssim_score,
    composite_distance,
    multi_view_aggregate,
    swiss_tournament,
    trimmed_mean,
    bca_bootstrap_ci,
    evaluate_benchmark,
    load_config,
    init_cache,
)


# ---------------------------------------------------------------------------
# Photometric Loss
# ---------------------------------------------------------------------------

class TestPhotometricLoss:
    def test_identical_images(self):
        img = np.full((32, 32, 3), 128, dtype=np.uint8)
        assert photometric_loss(img, img.copy()) == pytest.approx(0.0, abs=1e-10)

    def test_black_vs_white(self):
        black = np.zeros((32, 32, 3), dtype=np.uint8)
        white = np.full((32, 32, 3), 255, dtype=np.uint8)
        # MSE of (0-1)^2 = 1.0
        assert photometric_loss(black, white) == pytest.approx(1.0, abs=1e-6)

    def test_known_value(self):
        img1 = np.zeros((32, 32, 3), dtype=np.uint8)
        img2 = np.full((32, 32, 3), 128, dtype=np.uint8)
        expected = (128.0 / 255.0) ** 2
        assert photometric_loss(img1, img2) == pytest.approx(expected, abs=1e-6)

    def test_rgba_uses_only_rgb(self):
        img1 = np.zeros((32, 32, 4), dtype=np.uint8)
        img2 = np.full((32, 32, 4), 255, dtype=np.uint8)
        pl = photometric_loss(img1, img2)
        # Only RGB channels matter; both go from 0 to 255 => MSE = 1.0
        assert pl == pytest.approx(1.0, abs=1e-6)

    def test_size_mismatch(self):
        img1 = np.full((32, 32, 3), 100, dtype=np.uint8)
        img2 = np.full((64, 64, 3), 100, dtype=np.uint8)
        # After resizing uniform img2 to 32x32, both are identical
        assert photometric_loss(img1, img2) == pytest.approx(0.0, abs=1e-4)


# ---------------------------------------------------------------------------
# SSIM
# ---------------------------------------------------------------------------

class TestSSIM:
    def test_identical_images(self):
        rng = np.random.RandomState(99)
        img = rng.randint(30, 220, (48, 48, 3)).astype(np.uint8)
        assert ssim_score(img, img.copy()) == pytest.approx(1.0, abs=1e-6)

    def test_very_different_images(self):
        """Random images with different seeds should have low SSIM."""
        img1 = np.random.RandomState(1).randint(0, 256, (48, 48, 3)).astype(np.uint8)
        img2 = np.random.RandomState(2).randint(0, 256, (48, 48, 3)).astype(np.uint8)
        s = ssim_score(img1, img2)
        assert s < 0.1, f"SSIM of uncorrelated random images should be low, got {s}"

    def test_similar_images(self):
        """Image with small additive noise should have high SSIM."""
        rng = np.random.RandomState(42)
        base = rng.randint(50, 200, (48, 48, 3)).astype(np.uint8)
        noise = rng.randint(-5, 6, (48, 48, 3)).astype(np.int16)
        noisy = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        s = ssim_score(base, noisy)
        assert s > 0.5, f"SSIM of image + small noise should be high, got {s}"

    def test_black_vs_white(self):
        """Uniform black vs white should give SSIM near 0."""
        black = np.zeros((32, 32, 3), dtype=np.uint8)
        white = np.full((32, 32, 3), 255, dtype=np.uint8)
        s = ssim_score(black, white)
        assert s < 0.01, f"SSIM(black, white) should be near 0, got {s}"

    def test_no_forbidden_imports(self):
        """Verify evaluator.py does not import skimage, cv2, scipy.signal, or scipy.ndimage."""
        with open("/app/evaluator.py") as f:
            source = f.read()
        tree = ast.parse(source)
        forbidden_prefixes = ("skimage", "cv2", "scipy.signal", "scipy.ndimage")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for fp in forbidden_prefixes:
                        assert not alias.name.startswith(fp), (
                            f"Forbidden import detected: {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for fp in forbidden_prefixes:
                        assert not node.module.startswith(fp), (
                            f"Forbidden import-from detected: {node.module}"
                        )


# ---------------------------------------------------------------------------
# Composite Distance
# ---------------------------------------------------------------------------

class TestCompositeDistance:
    def test_identical_images(self):
        img = np.full((32, 32, 3), 128, dtype=np.uint8)
        cd = composite_distance(img, img.copy())
        assert cd == pytest.approx(0.0, abs=1e-6)

    def test_weights(self):
        """Check that alpha and beta control the weighting."""
        black = np.zeros((32, 32, 3), dtype=np.uint8)
        white = np.full((32, 32, 3), 255, dtype=np.uint8)
        cd1 = composite_distance(black, white, alpha=1.0, beta=0.0)
        cd2 = composite_distance(black, white, alpha=0.0, beta=1.0)
        # cd1 should be pure photometric loss = 1.0
        assert cd1 == pytest.approx(1.0, abs=1e-4)
        # cd2 should be pure (1 - ssim) which is near 1.0
        assert cd2 > 0.9


# ---------------------------------------------------------------------------
# Multi-View Aggregate
# ---------------------------------------------------------------------------

class TestMultiViewAggregate:
    def test_basic(self):
        scores = [{"pl": 0.1, "ssim": 0.9}, {"pl": 0.2, "ssim": 0.8}]
        agg = multi_view_aggregate(scores)
        assert agg["avg_pl"] == pytest.approx(0.15, abs=1e-9)
        assert agg["avg_ssim"] == pytest.approx(0.85, abs=1e-9)

    def test_with_none(self):
        scores = [{"pl": 0.1, "ssim": None}, {"pl": 0.2, "ssim": 0.8}]
        agg = multi_view_aggregate(scores)
        assert agg["avg_pl"] == pytest.approx(0.15, abs=1e-9)
        assert agg["avg_ssim"] == pytest.approx(0.8, abs=1e-9)

    def test_all_none(self):
        scores = [{"pl": None, "ssim": None}, {"pl": None, "ssim": None}]
        agg = multi_view_aggregate(scores)
        assert agg["avg_pl"] is None
        assert agg["avg_ssim"] is None


# ---------------------------------------------------------------------------
# Swiss Tournament
# ---------------------------------------------------------------------------

class TestSwissTournament:
    @staticmethod
    def _simple_metric(candidate, target):
        """Absolute distance for 1D scalar arrays."""
        return abs(float(candidate[0]) - float(target[0]))

    def test_four_candidates_three_rounds(self):
        """
        Candidates with distances [1, 3, 2, 4] from target.
        After 3 rounds of Swiss pairing the expected result is:
          (0, 3.0, 3.0), (2, 2.0, 4.0), (1, 1.0, 5.0), (3, 0.0, 6.0)
        """
        candidates = [
            np.array([1.0]),
            np.array([3.0]),
            np.array([2.0]),
            np.array([4.0]),
        ]
        target = np.array([0.0])
        result = swiss_tournament(candidates, target, 3, self._simple_metric)

        expected = [
            (0, 3.0, 3.0),
            (2, 2.0, 4.0),
            (1, 1.0, 5.0),
            (3, 0.0, 6.0),
        ]
        assert len(result) == 4
        for (ri, rs, rb), (ei, es, eb) in zip(result, expected):
            assert ri == ei, f"Index mismatch: got {ri}, expected {ei}"
            assert rs == pytest.approx(es), f"Score mismatch for idx {ri}"
            assert rb == pytest.approx(eb), f"Buchholz mismatch for idx {ri}"

    def test_five_candidates_one_round_bye(self):
        """
        5 candidates, 1 round. Candidate 4 (lowest-ranked unpaired) gets bye.
        Distances [1, 5, 3, 4, 2]. Pairings: 0v1, 2v3. Bye: 4.
        Winners: 0, 2, 4(bye). Losers: 1, 3.
        """
        candidates = [
            np.array([1.0]),
            np.array([5.0]),
            np.array([3.0]),
            np.array([4.0]),
            np.array([2.0]),
        ]
        target = np.array([0.0])
        result = swiss_tournament(candidates, target, 1, self._simple_metric)

        assert len(result) == 5
        # All winners (0, 2, 4) have score 1.0
        winner_indices = {r[0] for r in result if r[1] == 1.0}
        assert winner_indices == {0, 2, 4}
        # Losers (1, 3) have score 0.0
        loser_indices = {r[0] for r in result if r[1] == 0.0}
        assert loser_indices == {1, 3}
        # Candidate 4 has buchholz 0 (no opponents, got bye)
        for idx, score, buchholz in result:
            if idx == 4:
                assert buchholz == pytest.approx(0.0)

    def test_edge_cases(self):
        assert swiss_tournament([], np.array([0.0]), 3, self._simple_metric) == []
        result = swiss_tournament(
            [np.array([5.0])], np.array([0.0]), 3, self._simple_metric
        )
        assert result == [(0, 0.0, 0.0)]

    def test_deterministic(self):
        candidates = [np.array([float(i)]) for i in range(6)]
        target = np.array([0.0])
        r1 = swiss_tournament(candidates, target, 3, self._simple_metric, seed=42)
        r2 = swiss_tournament(candidates, target, 3, self._simple_metric, seed=42)
        assert r1 == r2


# ---------------------------------------------------------------------------
# Trimmed Mean
# ---------------------------------------------------------------------------

class TestTrimmedMean:
    def test_basic(self):
        values = list(range(1, 11))  # [1..10]
        # trim 0.1 => k=1, trim 1 from each end => mean of [2..9] = 5.5
        assert trimmed_mean(values, 0.1) == pytest.approx(5.5, abs=1e-9)

    def test_no_trim(self):
        values = [1.0, 2.0, 3.0]
        # k = int(3*0.1) = 0 => no trimming => mean = 2.0
        assert trimmed_mean(values, 0.1) == pytest.approx(2.0, abs=1e-9)

    def test_empty(self):
        assert trimmed_mean([]) == 0.0

    def test_all_trimmed(self):
        values = [1.0, 2.0]
        # trim 0.5 => k=1, 2*1 >= 2 => return full mean = 1.5
        assert trimmed_mean(values, 0.5) == pytest.approx(1.5, abs=1e-9)

    def test_larger_trim(self):
        values = list(range(1, 21))  # [1..20]
        # trim 0.2 => k=4, keep [5..16], mean = 10.5
        assert trimmed_mean(values, 0.2) == pytest.approx(10.5, abs=1e-9)


# ---------------------------------------------------------------------------
# BCa Bootstrap CI
# ---------------------------------------------------------------------------

class TestBCABootstrapCI:
    def test_empty(self):
        assert bca_bootstrap_ci([]) == (0.0, 0.0)

    def test_single_value(self):
        assert bca_bootstrap_ci([3.14]) == (3.14, 3.14)

    def test_ci_ordering(self):
        rng = np.random.RandomState(123)
        values = list(rng.normal(5.0, 1.0, 50))
        lo, hi = bca_bootstrap_ci(values, confidence=0.95, seed=42)
        assert lo < hi, f"CI lower ({lo}) should be less than upper ({hi})"

    def test_ci_contains_mean(self):
        rng = np.random.RandomState(123)
        values = list(rng.normal(5.0, 1.0, 50))
        sample_mean = np.mean(values)
        lo, hi = bca_bootstrap_ci(values, confidence=0.95, seed=42)
        assert lo <= sample_mean <= hi, (
            f"95% CI [{lo}, {hi}] should contain sample mean {sample_mean}"
        )

    def test_deterministic(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        r1 = bca_bootstrap_ci(values, seed=42)
        r2 = bca_bootstrap_ci(values, seed=42)
        assert r1[0] == pytest.approx(r2[0])
        assert r1[1] == pytest.approx(r2[1])

    def test_narrow_ci_for_tight_data(self):
        """Data with very low variance should have a narrow CI."""
        values = [5.0, 5.01, 4.99, 5.005, 4.995, 5.0, 5.0, 5.0]
        lo, hi = bca_bootstrap_ci(values, confidence=0.95, seed=42)
        assert hi - lo < 0.05, f"CI too wide for tight data: [{lo}, {hi}]"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class TestConfig:
    def test_load_default_config(self):
        """Default config file must be loadable and contain expected sections."""
        config = load_config("/app/config.toml")
        assert "metrics" in config
        assert config["metrics"]["alpha"] == 0.5
        assert config["metrics"]["beta"] == 0.5
        assert "aggregation" in config
        assert config["aggregation"]["trim_fraction"] == 0.1
        assert "bootstrap" in config
        assert config["bootstrap"]["confidence"] == 0.95
        assert config["bootstrap"]["n_bootstrap"] == 10000

    def test_config_affects_composite(self):
        """Different config weights must produce different composite distances."""
        from PIL import Image as PILImage

        with tempfile.TemporaryDirectory() as tmp:
            task_dir = os.path.join(tmp, "task1", "inst0")
            goal_dir = os.path.join(task_dir, "goal")
            cand_dir = os.path.join(task_dir, "candidate_0")
            os.makedirs(goal_dir)
            os.makedirs(cand_dir)

            goal_img = PILImage.new("RGB", (32, 32), (128, 128, 128))
            cand_img = PILImage.new("RGB", (32, 32), (255, 0, 0))
            goal_img.save(os.path.join(goal_dir, "v0.png"))
            cand_img.save(os.path.join(cand_dir, "v0.png"))

            config_a = {"metrics": {"alpha": 1.0, "beta": 0.0}}
            config_b = {"metrics": {"alpha": 0.0, "beta": 1.0}}

            result_a = evaluate_benchmark(tmp, config=config_a)
            result_b = evaluate_benchmark(tmp, config=config_b)

            dist_a = result_a["tasks"]["task1"]["instances"]["inst0"]["best_composite_distance"]
            dist_b = result_b["tasks"]["task1"]["instances"]["inst0"]["best_composite_distance"]

            assert dist_a != pytest.approx(dist_b, abs=1e-4), (
                f"Different weights should give different distances: {dist_a} vs {dist_b}"
            )


# ---------------------------------------------------------------------------
# SQLite Cache
# ---------------------------------------------------------------------------

class TestCache:
    def test_init_cache_creates_table(self, tmp_path):
        """init_cache should create the metric_cache table with correct schema."""
        db_path = str(tmp_path / "test.db")
        conn = init_cache(db_path)

        cursor = conn.execute("PRAGMA table_info(metric_cache)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        assert "goal_path" in columns
        assert "candidate_path" in columns
        assert "photometric_loss" in columns
        assert "ssim_score" in columns
        conn.close()

    def test_cache_populated_during_evaluation(self, tmp_path):
        """evaluate_benchmark with cache_db should populate the cache."""
        from PIL import Image as PILImage

        data_dir = tmp_path / "data"
        task_dir = data_dir / "taskC" / "inst0"
        goal_dir = task_dir / "goal"
        goal_dir.mkdir(parents=True)
        cand_dir = task_dir / "candidate_0"
        cand_dir.mkdir()

        PILImage.fromarray(
            np.full((32, 32, 3), 128, dtype=np.uint8)
        ).save(str(goal_dir / "v0.png"))
        PILImage.fromarray(
            np.full((32, 32, 3), 200, dtype=np.uint8)
        ).save(str(cand_dir / "v0.png"))

        cache_path = str(tmp_path / "cache.db")
        evaluate_benchmark(str(data_dir), cache_db=cache_path)

        conn = sqlite3.connect(cache_path)
        cursor = conn.execute("SELECT COUNT(*) FROM metric_cache")
        count = cursor.fetchone()[0]
        assert count > 0, "Cache should contain at least one entry"

        cursor = conn.execute("SELECT photometric_loss, ssim_score FROM metric_cache")
        row = cursor.fetchone()
        assert row[0] is not None, "Cached photometric_loss should not be None"
        assert row[1] is not None, "Cached ssim_score should not be None"
        assert row[0] > 0, "Cached photometric_loss should be > 0 for different images"
        conn.close()


# ---------------------------------------------------------------------------
# CLI Interface
# ---------------------------------------------------------------------------

class TestCLI:
    @staticmethod
    def _make_solid_image(h, w, color, path):
        from PIL import Image as PILImage
        arr = np.full((h, w, 3), color, dtype=np.uint8)
        PILImage.fromarray(arr, "RGB").save(path)

    def test_cli_produces_valid_json(self, tmp_path):
        """CLI invocation must produce a valid JSON evaluation report."""
        data_dir = tmp_path / "data"
        task_dir = data_dir / "taskCLI" / "inst0"
        goal_dir = task_dir / "goal"
        goal_dir.mkdir(parents=True)
        cand_dir = task_dir / "candidate_0"
        cand_dir.mkdir()

        self._make_solid_image(32, 32, [128, 128, 128], str(goal_dir / "v0.png"))
        self._make_solid_image(32, 32, [130, 130, 130], str(cand_dir / "v0.png"))

        output_path = str(tmp_path / "report.json")
        result = subprocess.run(
            ["python3", "/app/evaluator.py",
             "--data-dir", str(data_dir),
             "--output", output_path],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(output_path) as f:
            report = json.load(f)

        assert "tasks" in report
        assert "overall" in report
        assert "taskCLI" in report["tasks"]
        assert "harmonic_mean_distance" in report["overall"]

    def test_cli_with_custom_config(self, tmp_path):
        """CLI must accept --config and apply parameter overrides."""
        data_dir = tmp_path / "data"
        task_dir = data_dir / "taskConf" / "inst0"
        goal_dir = task_dir / "goal"
        goal_dir.mkdir(parents=True)
        cand_dir = task_dir / "candidate_0"
        cand_dir.mkdir()

        self._make_solid_image(32, 32, [128, 128, 128], str(goal_dir / "v0.png"))
        self._make_solid_image(32, 32, [200, 200, 200], str(cand_dir / "v0.png"))

        config_path = str(tmp_path / "custom.toml")
        with open(config_path, "w") as f:
            f.write(
                "[metrics]\nalpha = 1.0\nbeta = 0.0\n"
                "[aggregation]\ntrim_fraction = 0.1\n"
                "[bootstrap]\nconfidence = 0.95\nn_bootstrap = 1000\nseed = 42\n"
            )

        output_path = str(tmp_path / "report.json")
        result = subprocess.run(
            ["python3", "/app/evaluator.py",
             "--data-dir", str(data_dir),
             "--output", output_path,
             "--config", config_path],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        with open(output_path) as f:
            report = json.load(f)
        assert "taskConf" in report["tasks"]

        # With alpha=1, beta=0, composite should equal photometric_loss
        inst = report["tasks"]["taskConf"]["instances"]["inst0"]
        pl = inst["per_candidate"]["0"]["avg_pl"]
        comp = inst["per_candidate"]["0"]["composite"]
        assert comp == pytest.approx(pl, abs=1e-6), (
            f"With alpha=1.0 beta=0.0, composite ({comp}) should equal pl ({pl})"
        )

    def test_cli_with_cache_db(self, tmp_path):
        """CLI must accept --cache-db and create the cache database."""
        data_dir = tmp_path / "data"
        task_dir = data_dir / "taskDB" / "inst0"
        goal_dir = task_dir / "goal"
        goal_dir.mkdir(parents=True)
        cand_dir = task_dir / "candidate_0"
        cand_dir.mkdir()

        self._make_solid_image(32, 32, [128, 128, 128], str(goal_dir / "v0.png"))
        self._make_solid_image(32, 32, [130, 130, 130], str(cand_dir / "v0.png"))

        output_path = str(tmp_path / "report.json")
        cache_path = str(tmp_path / "cli_cache.db")
        result = subprocess.run(
            ["python3", "/app/evaluator.py",
             "--data-dir", str(data_dir),
             "--output", output_path,
             "--cache-db", cache_path],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        assert os.path.exists(cache_path), "Cache database should be created"

        conn = sqlite3.connect(cache_path)
        cursor = conn.execute("SELECT COUNT(*) FROM metric_cache")
        count = cursor.fetchone()[0]
        assert count > 0, "CLI cache should contain entries"
        conn.close()


# ---------------------------------------------------------------------------
# Full Pipeline: evaluate_benchmark
# ---------------------------------------------------------------------------

class TestEvaluateBenchmark:
    @staticmethod
    def _make_solid_image(h, w, color, path):
        from PIL import Image as PILImage

        arr = np.full((h, w, 3), color, dtype=np.uint8)
        PILImage.fromarray(arr, "RGB").save(path)

    def test_synthetic_benchmark(self, tmp_path):
        """
        Create a synthetic benchmark with one task, three instances, two
        candidates each. Candidate 0 is always close to goal; candidate 1 is
        far. Verify correct candidate selection and output structure.
        """
        task_dir = tmp_path / "taskA"
        goal_color = [128, 128, 128]
        close_color = [130, 130, 130]
        far_color = [255, 0, 0]

        for inst_idx in range(3):
            inst_name = f"inst{inst_idx}"
            inst_dir = task_dir / inst_name

            goal_dir = inst_dir / "goal"
            goal_dir.mkdir(parents=True)
            cand0_dir = inst_dir / "candidate_0"
            cand0_dir.mkdir()
            cand1_dir = inst_dir / "candidate_1"
            cand1_dir.mkdir()

            for view_name in ["view0.png", "view1.png"]:
                self._make_solid_image(32, 32, goal_color, str(goal_dir / view_name))
                self._make_solid_image(32, 32, close_color, str(cand0_dir / view_name))
                self._make_solid_image(32, 32, far_color, str(cand1_dir / view_name))

        result = evaluate_benchmark(str(tmp_path))

        # Structure checks
        assert "tasks" in result
        assert "overall" in result
        assert "taskA" in result["tasks"]
        task_result = result["tasks"]["taskA"]
        assert "instances" in task_result
        assert "trimmed_mean_distance" in task_result
        assert "ci_lower" in task_result
        assert "ci_upper" in task_result

        # All instances should select candidate 0
        for inst_name, inst_data in task_result["instances"].items():
            assert inst_data["best_candidate"] == 0, (
                f"{inst_name}: expected best_candidate=0, got {inst_data['best_candidate']}"
            )
            # Candidate 0 composite distance should be much smaller than candidate 1
            c0 = inst_data["per_candidate"]["0"]["composite"]
            c1 = inst_data["per_candidate"]["1"]["composite"]
            assert c0 < c1, (
                f"{inst_name}: candidate 0 distance ({c0}) should be less than "
                f"candidate 1 distance ({c1})"
            )

        # Overall checks
        assert result["overall"]["harmonic_mean_distance"] >= 0
        assert task_result["ci_lower"] <= task_result["trimmed_mean_distance"]

    def test_missing_candidate_view(self, tmp_path):
        """
        If a candidate is missing a view file, the pipeline should still
        produce a result by aggregating over available views.
        """
        task_dir = tmp_path / "taskB"
        inst_dir = task_dir / "inst0"
        goal_dir = inst_dir / "goal"
        goal_dir.mkdir(parents=True)
        cand_dir = inst_dir / "candidate_0"
        cand_dir.mkdir()

        self._make_solid_image(32, 32, [128, 128, 128], str(goal_dir / "v0.png"))
        self._make_solid_image(32, 32, [128, 128, 128], str(goal_dir / "v1.png"))
        # Only provide one view for the candidate
        self._make_solid_image(32, 32, [128, 128, 128], str(cand_dir / "v0.png"))

        result = evaluate_benchmark(str(tmp_path))
        assert "taskB" in result["tasks"]
        inst = result["tasks"]["taskB"]["instances"]["inst0"]
        assert inst["best_candidate"] == 0
        # Should still produce a valid composite (from the one available view)
        assert inst["per_candidate"]["0"]["composite"] < float("inf")
