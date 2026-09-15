
import json
import pytest
import numpy as np


@pytest.fixture(scope="session")
def config():
    with open("/app/task_config.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def results():
    try:
        with open("/app/results.json") as f:
            return json.load(f)
    except FileNotFoundError:
        pytest.fail("/app/results.json not found")
    except json.JSONDecodeError as e:
        pytest.fail(f"/app/results.json is not valid JSON: {e}")


# --- Config verification ---

class TestConfigUsed:
    def test_config_used_present(self, results):
        assert "config_used" in results, "Missing 'config_used' field"

    def test_config_matches(self, results, config):
        used = results["config_used"]
        assert used["seed_values"] == config["seed_values"]
        assert abs(used["bedroc_alpha"] - config["bedroc_alpha"]) < 1e-6
        assert used["ef_percentage"] == config["ef_percentage"]
        assert used["pains_variants"] == config["pains_variants"]
        assert abs(used["test_size"] - config["test_size"]) < 1e-6


# --- Schema checks ---

class TestSchema:
    def test_top_level_keys(self, results):
        for key in ["config_used", "preprocessing", "per_split_results", "summary"]:
            assert key in results, f"Missing top-level key: {key}"

    def test_preprocessing_keys(self, results):
        p = results["preprocessing"]
        for key in [
            "n_molecules_raw",
            "n_molecules_valid",
            "n_molecules_after_pains",
            "n_actives_after_pains",
            "n_inactives_after_pains",
        ]:
            assert key in p, f"Missing preprocessing key: {key}"

    def test_split_count_matches_seeds(self, results, config):
        assert len(results["per_split_results"]) == len(config["seed_values"])

    def test_split_seeds_match_config(self, results, config):
        seeds = sorted(s["seed"] for s in results["per_split_results"])
        assert seeds == sorted(config["seed_values"])

    def test_split_structure(self, results):
        method_names = [
            "ecfp_binary",
            "ecfp_count",
            "atom_pair",
            "maccs",
            "combsum_fusion",
            "rank_fusion",
        ]
        for split in results["per_split_results"]:
            for key in ["seed", "n_train", "n_test", "n_train_actives", "methods"]:
                assert key in split, f"Missing split key: {key}"
            for method in method_names:
                assert method in split["methods"], f"Missing method: {method}"
                for metric in ["bedroc", "ef"]:
                    assert metric in split["methods"][method], (
                        f"Missing metric {metric} in {method}"
                    )

    def test_summary_structure(self, results):
        summary = results["summary"]
        method_names = [
            "ecfp_binary",
            "ecfp_count",
            "atom_pair",
            "maccs",
            "combsum_fusion",
            "rank_fusion",
        ]
        for method in method_names:
            assert method in summary, f"Missing summary method: {method}"
            for key in ["bedroc_mean", "bedroc_std", "ef_mean", "ef_std"]:
                assert key in summary[method], f"Missing {key} in summary[{method}]"
        assert "best_method_bedroc" in summary
        assert "best_method_ef" in summary


# --- Preprocessing checks ---

class TestPreprocessing:
    def test_raw_count_is_bace(self, results):
        """BACE dataset has 1513 molecules."""
        assert results["preprocessing"]["n_molecules_raw"] == 1513

    def test_valid_within_range(self, results):
        p = results["preprocessing"]
        assert p["n_molecules_valid"] <= p["n_molecules_raw"]
        assert p["n_molecules_valid"] > 1400

    def test_pains_reduces(self, results):
        p = results["preprocessing"]
        assert p["n_molecules_after_pains"] <= p["n_molecules_valid"]
        assert p["n_molecules_after_pains"] > 1000

    def test_active_inactive_sum(self, results):
        p = results["preprocessing"]
        assert (
            p["n_actives_after_pains"] + p["n_inactives_after_pains"]
            == p["n_molecules_after_pains"]
        )

    def test_actives_present(self, results):
        p = results["preprocessing"]
        assert p["n_actives_after_pains"] > 0
        assert p["n_inactives_after_pains"] > 0


# --- Numerical range checks ---

class TestNumericalRanges:
    def test_bedroc_range(self, results):
        for split in results["per_split_results"]:
            for method, vals in split["methods"].items():
                assert 0.0 <= vals["bedroc"] <= 1.0, (
                    f"BEDROC out of [0,1] for {method} seed={split['seed']}: "
                    f"{vals['bedroc']}"
                )

    def test_ef_nonnegative(self, results):
        for split in results["per_split_results"]:
            for method, vals in split["methods"].items():
                assert vals["ef"] >= 0, (
                    f"EF negative for {method} seed={split['seed']}: {vals['ef']}"
                )

    def test_split_sizes(self, results, config):
        p = results["preprocessing"]
        total = p["n_molecules_after_pains"]
        for split in results["per_split_results"]:
            assert split["n_train"] + split["n_test"] == total
            expected_test = int(round(total * config["test_size"]))
            assert abs(split["n_test"] - expected_test) < total * 0.08
            assert split["n_train_actives"] > 0
            assert split["n_train_actives"] < split["n_train"]


# --- Summary consistency ---

class TestSummaryConsistency:
    def test_mean_bedroc(self, results):
        methods = [
            "ecfp_binary", "ecfp_count", "atom_pair",
            "maccs", "combsum_fusion", "rank_fusion",
        ]
        for method in methods:
            vals = [
                s["methods"][method]["bedroc"] for s in results["per_split_results"]
            ]
            expected = np.mean(vals)
            actual = results["summary"][method]["bedroc_mean"]
            assert abs(actual - expected) < 1e-6, (
                f"BEDROC mean mismatch for {method}: {actual} vs {expected}"
            )

    def test_std_bedroc(self, results):
        methods = [
            "ecfp_binary", "ecfp_count", "atom_pair",
            "maccs", "combsum_fusion", "rank_fusion",
        ]
        for method in methods:
            vals = [
                s["methods"][method]["bedroc"] for s in results["per_split_results"]
            ]
            expected = float(np.std(vals))
            actual = results["summary"][method]["bedroc_std"]
            assert abs(actual - expected) < 1e-6, (
                f"BEDROC std mismatch for {method}: {actual} vs {expected}"
            )

    def test_mean_ef(self, results):
        methods = [
            "ecfp_binary", "ecfp_count", "atom_pair",
            "maccs", "combsum_fusion", "rank_fusion",
        ]
        for method in methods:
            vals = [
                s["methods"][method]["ef"] for s in results["per_split_results"]
            ]
            expected = np.mean(vals)
            actual = results["summary"][method]["ef_mean"]
            assert abs(actual - expected) < 1e-6, (
                f"EF mean mismatch for {method}: {actual} vs {expected}"
            )

    def test_std_ef(self, results):
        methods = [
            "ecfp_binary", "ecfp_count", "atom_pair",
            "maccs", "combsum_fusion", "rank_fusion",
        ]
        for method in methods:
            vals = [
                s["methods"][method]["ef"] for s in results["per_split_results"]
            ]
            expected = float(np.std(vals))
            actual = results["summary"][method]["ef_std"]
            assert abs(actual - expected) < 1e-6, (
                f"EF std mismatch for {method}: {actual} vs {expected}"
            )

    def test_best_method_bedroc(self, results):
        methods = [
            "ecfp_binary", "ecfp_count", "atom_pair",
            "maccs", "combsum_fusion", "rank_fusion",
        ]
        best = max(methods, key=lambda m: results["summary"][m]["bedroc_mean"])
        assert results["summary"]["best_method_bedroc"] == best

    def test_best_method_ef(self, results):
        methods = [
            "ecfp_binary", "ecfp_count", "atom_pair",
            "maccs", "combsum_fusion", "rank_fusion",
        ]
        best = max(methods, key=lambda m: results["summary"][m]["ef_mean"])
        assert results["summary"]["best_method_ef"] == best


# --- Reference computation: ECFP binary, first config seed ---

class TestReferenceComputation:
    """Independently verify preprocessing and ECFP binary for the first seed."""

    @pytest.fixture(scope="class")
    def reference_data(self, config):
        """Run independent preprocessing and one VS computation using config."""
        from skfp.preprocessing import MolFromSmilesTransformer
        from skfp.filters import PAINSFilter
        from skfp.model_selection import randomized_scaffold_train_test_split
        from skfp.fingerprints import ECFPFingerprint
        from skfp.distances import bulk_tanimoto_binary_similarity
        from skfp.metrics import bedroc_score, enrichment_factor

        with open("/app/data/bace.json") as f:
            data = json.load(f)
        smiles_list = data["smiles"]
        y = np.array(data["labels"])

        n_raw = len(smiles_list)

        mol_transformer = MolFromSmilesTransformer(valid_only=True)
        mols, y = mol_transformer.transform_x_y(smiles_list, y)
        n_valid = len(mols)

        for variant in config["pains_variants"]:
            pains = PAINSFilter(variant=variant)
            mols, y = pains.transform_x_y(mols, y)

        n_after = len(mols)
        n_actives = int(y.sum())

        first_seed = config["seed_values"][0]
        mols_train, mols_test, y_train, y_test = (
            randomized_scaffold_train_test_split(
                mols, y,
                test_size=config["test_size"],
                random_state=first_seed,
            )
        )

        active_mask = y_train == 1
        mols_active_train = np.array(mols_train)[active_mask]

        fp = ECFPFingerprint()
        X_train = fp.transform(mols_active_train)
        X_test = fp.transform(mols_test)

        sims = bulk_tanimoto_binary_similarity(X_train, X_test)
        y_pred_scores = np.max(sims, axis=0)

        ref_bedroc = float(bedroc_score(
            y_test, y_pred_scores, alpha=config["bedroc_alpha"]
        ))
        ref_ef = float(enrichment_factor(
            y_test, y_pred_scores, fraction=config["ef_percentage"] / 100
        ))

        return {
            "n_raw": n_raw,
            "n_valid": n_valid,
            "n_after_pains": n_after,
            "n_actives": n_actives,
            "first_seed": first_seed,
            "n_train": len(mols_train),
            "n_test": len(mols_test),
            "n_train_actives": int(active_mask.sum()),
            "ref_bedroc": ref_bedroc,
            "ref_ef": ref_ef,
        }

    def test_preprocessing_n_valid(self, results, reference_data):
        assert results["preprocessing"]["n_molecules_valid"] == reference_data["n_valid"]

    def test_preprocessing_after_pains(self, results, reference_data):
        assert (
            results["preprocessing"]["n_molecules_after_pains"]
            == reference_data["n_after_pains"]
        )

    def test_preprocessing_actives(self, results, reference_data):
        assert (
            results["preprocessing"]["n_actives_after_pains"]
            == reference_data["n_actives"]
        )

    def test_first_split_train_size(self, results, reference_data):
        seed = reference_data["first_seed"]
        split = next(s for s in results["per_split_results"] if s["seed"] == seed)
        assert split["n_train"] == reference_data["n_train"]

    def test_first_split_test_size(self, results, reference_data):
        seed = reference_data["first_seed"]
        split = next(s for s in results["per_split_results"] if s["seed"] == seed)
        assert split["n_test"] == reference_data["n_test"]

    def test_first_split_train_actives(self, results, reference_data):
        seed = reference_data["first_seed"]
        split = next(s for s in results["per_split_results"] if s["seed"] == seed)
        assert split["n_train_actives"] == reference_data["n_train_actives"]

    def test_first_split_ecfp_binary_bedroc(self, results, reference_data):
        seed = reference_data["first_seed"]
        split = next(s for s in results["per_split_results"] if s["seed"] == seed)
        agent_val = split["methods"]["ecfp_binary"]["bedroc"]
        ref_val = reference_data["ref_bedroc"]
        assert abs(agent_val - ref_val) < 0.01, (
            f"ECFP binary BEDROC seed={seed}: agent={agent_val:.4f}, ref={ref_val:.4f}"
        )

    def test_first_split_ecfp_binary_ef(self, results, reference_data):
        seed = reference_data["first_seed"]
        split = next(s for s in results["per_split_results"] if s["seed"] == seed)
        agent_val = split["methods"]["ecfp_binary"]["ef"]
        ref_val = reference_data["ref_ef"]
        assert abs(agent_val - ref_val) < 0.5, (
            f"ECFP binary EF seed={seed}: agent={agent_val:.3f}, ref={ref_val:.3f}"
        )
