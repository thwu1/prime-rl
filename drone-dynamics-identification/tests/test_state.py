
import base64
import json
import os
import sys

import numpy as np
import pytest


# Ground truth is encoded to prevent trivial extraction
_ENC = "ClcoHApNTk9DcVFcWwZFb0MdUVcoHQtNTk9DcVZWWAZFb0MdUVcoHghNTk9AcVNSXQZFb0MdUVcKAlBVVFxcblQAQ1JYc1YTGhhDXlJYWlZGOk9UXE9IfRJDEBJDXlJfWl9Dc0JHAwwcMARuBRQURkhPR19cbx8="
_KEY = b"quadrotor_bench_v1"


def _decode_gt():
    raw = base64.b64decode(_ENC)
    cleartext = bytes(b ^ _KEY[i % len(_KEY)] for i, b in enumerate(raw))
    return json.loads(cleartext.decode())


PARAMS_PATH = "/app/identified_params.json"
CONFIG_PATH = "/app/config.json"
MODEL_PATH = "/app/model.py"
VAL_DIR = "/app/data/validation"

PARAM_KEYS = ["Ixx", "Iyy", "Izz", "kf", "km", "drag", "motor_tau"]
TOLERANCE = 0.10          # 10 % relative
MAX_POS_RMSE = 0.15       # metres


def _load_json(path):
    with open(path) as f:
        return json.load(f)


# -- parameter accuracy --

class TestParameterAccuracy:
    def test_params_file_exists(self):
        assert os.path.exists(PARAMS_PATH), f"Missing {PARAMS_PATH}"

    def test_all_params_present(self):
        params = _load_json(PARAMS_PATH)
        for k in PARAM_KEYS:
            assert k in params, f"Missing parameter: {k}"
            assert isinstance(params[k], (int, float)), f"{k} is not numeric"

    @pytest.mark.parametrize("param", PARAM_KEYS)
    def test_param_within_tolerance(self, param):
        gt = _decode_gt()
        identified = _load_json(PARAMS_PATH)
        gt_val = gt[param]
        id_val = identified[param]
        rel_err = abs(id_val - gt_val) / abs(gt_val)
        assert rel_err <= TOLERANCE, (
            f"{param}: identified={id_val:.6e}  "
            f"rel_error={rel_err:.4f} > {TOLERANCE}"
        )


# -- forward-simulation prediction --

class TestModelPrediction:
    def test_model_file_exists(self):
        assert os.path.exists(MODEL_PATH), f"Missing {MODEL_PATH}"

    def test_model_has_simulate(self):
        sys.path.insert(0, "/app")
        import importlib, model  # noqa: E401
        importlib.reload(model)
        assert callable(getattr(model, "simulate", None)), \
            "model.py must expose a callable simulate()"

    @pytest.mark.parametrize(
        "traj_name", ["val_mixed", "val_yaw_step", "val_chirp"]
    )
    def test_validation_rmse(self, traj_name):
        import jax.numpy as jnp

        sys.path.insert(0, "/app")
        import importlib, model  # noqa: E401
        importlib.reload(model)

        data = np.load(os.path.join(VAL_DIR, f"{traj_name}.npz"))
        config = _load_json(CONFIG_PATH)
        id_params = _load_json(PARAMS_PATH)

        params_dict = {k: jnp.float32(v) for k, v in id_params.items()}
        params_dict["mass"] = jnp.float32(config["mass"])
        params_dict["L"] = jnp.float32(config["L"])
        params_dict["g"] = jnp.float32(config["g"])

        initial_state = {
            "pos": jnp.array(data["initial_pos"], dtype=jnp.float32),
            "quat": jnp.array(data["initial_quat"], dtype=jnp.float32),
            "vel": jnp.array(data["initial_vel"], dtype=jnp.float32),
            "ang_vel": jnp.array(data["initial_ang_vel"], dtype=jnp.float32),
            "rotor_vel": jnp.array(data["initial_rotor_vel"], dtype=jnp.float32),
        }

        commands = jnp.array(data["commands"], dtype=jnp.float32)
        dt = config["dt"]
        n_steps = config["n_steps_validation"]

        result = model.simulate(params_dict, initial_state, commands, dt, n_steps)

        pred_pos = np.asarray(result["positions"])
        true_pos = data["positions"][:n_steps]
        rmse = float(np.sqrt(np.mean((pred_pos - true_pos) ** 2)))

        assert rmse < MAX_POS_RMSE, (
            f"{traj_name}: position RMSE = {rmse:.6f} > {MAX_POS_RMSE}"
        )
