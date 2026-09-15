"""Reference solution: calibrated weighted ensemble for micro-gesture classification.

Discovers per-model calibration issues, recovers scaling parameters, and
optimizes ensemble fusion weights to maximize classification accuracy.
"""
import numpy as np
from scipy.optimize import minimize
from scipy.special import log_softmax, softmax
import json
import os


def main():
    data_dir = "/app/data"
    for fname in ["val_logits.npy", "test_logits.npy", "val_labels.npy"]:
        fpath = os.path.join(data_dir, fname)
        if not os.path.exists(fpath):
            raise FileNotFoundError(
                f"Data file not found: {fpath}. "
                f"Contents of {data_dir}: {os.listdir(data_dir) if os.path.isdir(data_dir) else 'DIR NOT FOUND'}"
            )

    val_logits = np.load(os.path.join(data_dir, "val_logits.npy"))
    test_logits = np.load(os.path.join(data_dir, "test_logits.npy"))
    val_labels = np.load(os.path.join(data_dir, "val_labels.npy"))

    N_MODELS, N_VAL, N_CLASSES = val_logits.shape
    _, N_TEST, _ = test_logits.shape

    print(f"Loaded: {N_MODELS} models, {N_VAL} val, {N_TEST} test, "
          f"{N_CLASSES} classes")

    # -- Step 1: Temperature scaling calibration per model --
    def nll_with_temp(log_temp, logits, labels):
        T = np.exp(log_temp[0])
        scaled = logits / T
        lsm = log_softmax(scaled, axis=1)
        return -np.mean(lsm[np.arange(len(labels)), labels])

    optimal_temps = []
    for m in range(N_MODELS):
        res = minimize(
            nll_with_temp, x0=[0.0],
            args=(val_logits[m], val_labels),
            method="Nelder-Mead",
            options={"xatol": 1e-5, "fatol": 1e-8, "maxiter": 5000}
        )
        T = float(np.exp(res.x[0]))
        optimal_temps.append(T)

        cal_preds = np.argmax(val_logits[m] / T, axis=1)
        cal_acc = np.mean(cal_preds == val_labels)
        print(f"  Model {m}: T={T:.4f}, cal val acc={cal_acc:.4f}")

    # -- Step 2: Calibrated probabilities --
    cal_val_probs = np.stack([
        softmax(val_logits[m] / optimal_temps[m], axis=1)
        for m in range(N_MODELS)
    ])
    cal_test_probs = np.stack([
        softmax(test_logits[m] / optimal_temps[m], axis=1)
        for m in range(N_MODELS)
    ])

    avg_val = np.mean(cal_val_probs, axis=0)
    avg_val_acc = np.mean(np.argmax(avg_val, axis=1) == val_labels)
    print(f"\nCalibrated uniform avg val acc: {avg_val_acc:.4f}")

    # -- Step 3: Optimize ensemble weights --
    def weighted_nll(log_w, cal_probs, labels):
        w = np.exp(log_w)
        w = w / w.sum()
        avg = np.tensordot(w, cal_probs, axes=([0], [0]))
        avg = np.clip(avg, 1e-12, 1.0)
        return -np.mean(np.log(avg[np.arange(len(labels)), labels]))

    init_accs = np.array([
        np.mean(np.argmax(cal_val_probs[m], axis=1) == val_labels)
        for m in range(N_MODELS)
    ])
    init_w = init_accs / init_accs.sum()
    init_log_w = np.log(init_w + 1e-10)

    res = minimize(
        weighted_nll, x0=init_log_w,
        args=(cal_val_probs, val_labels),
        method="Nelder-Mead",
        options={"maxiter": 20000, "xatol": 1e-6, "fatol": 1e-10}
    )
    opt_w = np.exp(res.x)
    opt_w = opt_w / opt_w.sum()
    print(f"Optimal weights: {opt_w}")

    # -- Step 4: Final predictions --
    w_val = np.tensordot(opt_w, cal_val_probs, axes=([0], [0]))
    val_acc = np.mean(np.argmax(w_val, axis=1) == val_labels)
    print(f"Weighted ensemble val acc: {val_acc:.4f}")

    w_test = np.tensordot(opt_w, cal_test_probs, axes=([0], [0]))
    test_preds = np.argmax(w_test, axis=1)

    # -- Step 5: Save outputs --
    os.makedirs("/app/output", exist_ok=True)

    with open("/app/output/test_predictions.csv", "w") as f:
        for p in test_preds:
            f.write(f"{int(p)}\n")

    config = {
        "scaling_factors": [float(t) for t in optimal_temps],
        "weights": [float(w) for w in opt_w],
        "method": "calibrated_weighted_ensemble"
    }
    with open("/app/output/ensemble_config.json", "w") as f:
        json.dump(config, f, indent=2)

    print(f"\nDone. {len(test_preds)} predictions -> /app/output/")


if __name__ == "__main__":
    main()
