
import json
import zlib
import base64
import numpy as np
import pytest
import os

PREDICTIONS_PATH = "/app/output/test_predictions.csv"
CONFIG_PATH = "/app/output/ensemble_config.json"
TEST_LOGITS_PATH = "/app/data/test_logits.npy"

N_TEST = 250
N_CLASSES = 32
N_MODELS = 6
ACCURACY_THRESHOLD = 0.68

# Obfuscated verification digest — do not modify
_VRF_DIGEST = "eNoB+gAF/7AvQgfhV5F5siVOBP5Uh2CzKE0f9FaZZLotQwzgT5BouStbEO9Il2OqJ0Md5VmVerwuUQ//QoljtzZcDeZPgWmqP1AN+0iLbrg7TBbtXYFsqSpTDvpWm3m4O14C4V+eeKMqVhbxVp1xrz1HGupYlH6sM1EC+02Ycb07RArpSI5xsyJMAupDjm+3NVQd6kOeYrc2Qxf9W4VmqSNIG/RagnqmI1QC9kOLdb4wTQL0V515rDZHBfFNknekI0cb7FaVdLolWhfsVod6vC1KHv9Zh3K6NEwF502BaKM2RwTkW5p3tjlaBfVFhWW5OUoI/k+dYaUiShngTJJ+viRv3m0g"
_VRF_XK = bytes([0xA7, 0x3B, 0x5C, 0x19, 0xE2, 0x4D, 0x8F, 0x61])


def _decode_vrf():
    raw = zlib.decompress(base64.b64decode(_VRF_DIGEST))
    return np.array(
        [b ^ _VRF_XK[i % len(_VRF_XK)] for i, b in enumerate(raw)],
        dtype=np.int64
    )


def _softmax(x, axis=-1):
    e = np.exp(x - np.max(x, axis=axis, keepdims=True))
    return e / e.sum(axis=axis, keepdims=True)


def load_predictions():
    assert os.path.exists(PREDICTIONS_PATH), \
        f"Predictions file not found: {PREDICTIONS_PATH}"
    preds = []
    with open(PREDICTIONS_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                preds.append(int(line))
    return np.array(preds)


def load_config():
    assert os.path.exists(CONFIG_PATH), \
        f"Config file not found: {CONFIG_PATH}"
    with open(CONFIG_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Output format tests
# ---------------------------------------------------------------------------
class TestOutputFormat:
    def test_predictions_file_exists(self):
        assert os.path.exists(PREDICTIONS_PATH), \
            f"Predictions file not found at {PREDICTIONS_PATH}"

    def test_predictions_count(self):
        preds = load_predictions()
        assert len(preds) == N_TEST, \
            f"Expected {N_TEST} predictions, got {len(preds)}"

    def test_predictions_range(self):
        preds = load_predictions()
        assert np.all(preds >= 0) and np.all(preds < N_CLASSES), \
            f"Predictions must be integers in [0, {N_CLASSES - 1}]"

    def test_config_file_exists(self):
        assert os.path.exists(CONFIG_PATH), \
            f"Config file not found at {CONFIG_PATH}"

    def test_config_has_scaling_factors(self):
        config = load_config()
        assert "scaling_factors" in config, "Config missing 'scaling_factors'"
        sf = config["scaling_factors"]
        assert isinstance(sf, list) and len(sf) == N_MODELS, \
            f"'scaling_factors' must be a list of {N_MODELS} values"
        assert all(isinstance(t, (int, float)) and t > 0 for t in sf), \
            "All scaling_factors must be positive numbers"

    def test_config_has_weights(self):
        config = load_config()
        assert "weights" in config, "Config missing 'weights'"
        weights = config["weights"]
        assert isinstance(weights, list) and len(weights) == N_MODELS, \
            f"'weights' must be a list of {N_MODELS} values"
        assert all(isinstance(w, (int, float)) and w >= 0 for w in weights), \
            "All weights must be non-negative numbers"
        assert abs(sum(weights) - 1.0) < 0.05, \
            f"Weights must sum to ~1.0, got {sum(weights):.4f}"

    def test_config_has_method(self):
        config = load_config()
        assert "method" in config, "Config missing 'method'"
        assert isinstance(config["method"], str) and len(config["method"]) > 0


# ---------------------------------------------------------------------------
# Accuracy tests
# ---------------------------------------------------------------------------
class TestAccuracy:
    def test_accuracy_above_threshold(self):
        """Ensemble accuracy must meet the minimum threshold."""
        preds = load_predictions()
        gt = _decode_vrf()
        accuracy = np.mean(preds == gt)
        assert accuracy >= ACCURACY_THRESHOLD, \
            f"Test accuracy {accuracy:.4f} is below threshold {ACCURACY_THRESHOLD}"

    def test_beats_naive_probability_averaging(self):
        """Ensemble must outperform naive probability averaging of raw logits."""
        preds = load_predictions()
        gt = _decode_vrf()
        agent_acc = np.mean(preds == gt)

        test_logits = np.load(TEST_LOGITS_PATH)
        naive_probs = np.mean(
            [_softmax(test_logits[m], axis=1) for m in range(N_MODELS)],
            axis=0
        )
        naive_preds = np.argmax(naive_probs, axis=1)
        naive_acc = np.mean(naive_preds == gt)

        assert agent_acc > naive_acc, \
            (f"Agent accuracy ({agent_acc:.4f}) must exceed naive "
             f"probability averaging ({naive_acc:.4f})")


# ---------------------------------------------------------------------------
# Scaling factor and weight quality tests
# ---------------------------------------------------------------------------
class TestEnsembleQuality:
    def test_scaling_factors_in_reasonable_range(self):
        """Scaling factors should be in a plausible range."""
        config = load_config()
        for sf in config["scaling_factors"]:
            assert 0.01 < sf < 100.0, \
                f"Scaling factor {sf} is outside (0.01, 100.0)"

    def test_scaling_factors_vary_across_models(self):
        """Scaling factors must vary meaningfully across models."""
        config = load_config()
        sfs = config["scaling_factors"]
        ratio = max(sfs) / max(min(sfs), 1e-6)
        assert ratio > 1.5, \
            (f"Scaling factor ratio {ratio:.2f} too small — "
             f"max/min ratio must exceed 1.5")

    def test_weights_not_uniform(self):
        """Optimized weights should differ from uniform 1/N."""
        config = load_config()
        weights = config["weights"]
        uniform = 1.0 / N_MODELS
        max_dev = max(abs(w - uniform) for w in weights)
        assert max_dev > 0.02, \
            "Weights appear uniform — at least one must differ from 1/6 by > 0.02"
