"""Evaluator for the 1D compressible Navier-Stokes solver.

Downloads reference data from HuggingFace and computes nRMSE against the solver output.
"""
import argparse
import h5py
import numpy as np
import os
import sys
import time
import urllib.request


HF_BASE = "https://huggingface.co/datasets/LDA1020/codepde-data/resolve/main/cns1d"
FULL_DATA_URL = f"{HF_BASE}/1D_CFD_Rand_Eta0.1_Zeta0.1_periodic_Train.hdf5"
DEV_DATA_URL = f"{HF_BASE}/1D_CFD_Rand_Eta0.1_Zeta0.1_periodic_Train_development.hdf5"


def download_if_needed(url, path):
    """Download a file if it does not already exist."""
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        print(f"Downloading {url} ...")
        urllib.request.urlretrieve(url, path)
        print(f"Saved to {path}")


def compute_nrmse(u_computed, u_reference):
    """Computes nRMSE. Arrays have shape [batch, T+1, N, 3]."""
    rmse_values = np.sqrt(np.mean((u_computed - u_reference) ** 2, axis=(1, 2, 3)))
    u_true_norm = np.sqrt(np.mean(u_reference ** 2, axis=(1, 2, 3)))
    nrmse = np.mean(rmse_values / u_true_norm)
    return nrmse


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate 1D CNS solver")
    parser.add_argument("--eta", type=float, default=0.1)
    parser.add_argument("--dev", action="store_true",
                        help="Use smaller development dataset for faster iteration")
    parser.add_argument("--dataset-path", type=str, default=None,
                        help="Path to HDF5 dataset (overrides download)")
    args = parser.parse_args()

    if args.dataset_path is None:
        if args.dev:
            url = DEV_DATA_URL
            args.dataset_path = "/app/data/cns1d_dev.hdf5"
        else:
            url = FULL_DATA_URL
            args.dataset_path = "/app/data/cns1d_test.hdf5"
        download_if_needed(url, args.dataset_path)

    with h5py.File(args.dataset_path, "r") as f:
        t_coordinate = np.array(f["t-coordinate"])
        Vx = np.array(f["Vx"])
        density = np.array(f["density"])
        pressure = np.array(f["pressure"])

    print(f"Loaded data: Vx={Vx.shape}, density={density.shape}, "
          f"pressure={pressure.shape}, t={t_coordinate.shape}")

    sys.path.insert(0, "/app")
    from solver import solver

    Vx0 = Vx[:, 0]
    density0 = density[:, 0]
    pressure0 = pressure[:, 0]
    eta = args.eta
    zeta = args.eta

    print(f"Running solver with eta={eta}, zeta={zeta} ...")
    start = time.time()
    Vx_pred, density_pred, pressure_pred = solver(
        Vx0, density0, pressure0, t_coordinate, eta, zeta
    )
    elapsed = time.time() - start

    assert Vx_pred.shape == Vx.shape, \
        f"Vx shape mismatch: {Vx_pred.shape} vs {Vx.shape}"
    assert density_pred.shape == density.shape, \
        f"density shape mismatch: {density_pred.shape} vs {density.shape}"
    assert pressure_pred.shape == pressure.shape, \
        f"pressure shape mismatch: {pressure_pred.shape} vs {pressure.shape}"

    stacked_pred = np.stack([Vx_pred, density_pred, pressure_pred], axis=-1)
    stacked_ref = np.stack([Vx, density, pressure], axis=-1)
    nrmse = compute_nrmse(stacked_pred, stacked_ref)

    print(f"nRMSE: {nrmse:.6f}")
    print(f"Time: {elapsed:.2f}s")
    print(f"PASS: {nrmse < 0.05}")
