"""Evaluate the CNS1D solver against HDF5 reference data.

Loads reference solutions from /app/data/reference.h5, runs the solver
for each parameter regime, and reports the normalized RMSE (nRMSE).
"""
import sys
import time

sys.path.insert(0, "/app")


def compute_nrmse(u_computed, u_reference):
    """Compute nRMSE over stacked [batch, time, space, 3] arrays."""
    import numpy as np

    rmse_values = np.sqrt(
        np.mean((u_computed - u_reference) ** 2, axis=(1, 2, 3))
    )
    u_true_norm = np.sqrt(np.mean(u_reference ** 2, axis=(1, 2, 3)))
    nrmse = np.mean(rmse_values / u_true_norm)
    return nrmse


def compute_nrmse_var(u_computed, u_reference):
    """Compute nRMSE for a single variable [batch, time, space]."""
    import numpy as np

    rmse_values = np.sqrt(np.mean((u_computed - u_reference) ** 2, axis=(1, 2)))
    u_true_norm = np.sqrt(np.mean(u_reference ** 2, axis=(1, 2)))
    return np.mean(rmse_values / u_true_norm)


def evaluate_regime(h5file, regime_name):
    """Evaluate solver against one regime's reference data."""
    import numpy as np
    from solver import solver

    grp = h5file[regime_name]
    eta = float(grp.attrs["eta"])
    zeta = float(grp.attrs["zeta"])

    Vx0 = grp["initial_conditions/velocity"][:]
    density0 = grp["initial_conditions/density"][:]
    pressure0 = grp["initial_conditions/pressure"][:]
    t_coord = grp["t_coordinate"][:]

    Vx_ref = grp["reference_solution/velocity"][:]
    density_ref = grp["reference_solution/density"][:]
    pressure_ref = grp["reference_solution/pressure"][:]

    print(
        f"\n--- Regime: {regime_name} (eta={eta}, zeta={zeta}) ---"
    )
    print(
        f"Data shapes: batch={Vx0.shape[0]}, N={Vx0.shape[1]}, "
        f"T={len(t_coord) - 1}"
    )

    start = time.time()
    Vx_pred, density_pred, pressure_pred = solver(
        Vx0, density0, pressure0, t_coord, eta, zeta
    )
    elapsed = time.time() - start
    print(f"Solver completed in {elapsed:.2f}s")

    # Check for NaN values
    nan_count = sum(
        np.isnan(x).sum()
        for x in [Vx_pred, density_pred, pressure_pred]
    )
    if nan_count > 0:
        print(f"WARNING: {nan_count} NaN values detected!")

    # Compute overall nRMSE
    stacked_pred = np.stack(
        [Vx_pred, density_pred, pressure_pred], axis=-1
    )
    stacked_ref = np.stack([Vx_ref, density_ref, pressure_ref], axis=-1)
    nrmse = compute_nrmse(stacked_pred, stacked_ref)

    # Per-variable diagnostics
    for name, pred, ref in [
        ("velocity", Vx_pred, Vx_ref),
        ("density", density_pred, density_ref),
        ("pressure", pressure_pred, pressure_ref),
    ]:
        var_nrmse = compute_nrmse_var(pred, ref)
        print(f"  {name}: nRMSE = {var_nrmse:.6f}")

    print(f"Overall nRMSE: {nrmse:.6f}")
    status = "PASS" if nrmse < 0.05 else "FAIL"
    print(f"Status: {status}")
    return nrmse


if __name__ == "__main__":
    import h5py
    import numpy as np

    print("Loading reference data from /app/data/reference.h5")
    with h5py.File("/app/data/reference.h5", "r") as f:
        # Print file structure for inspection
        print("\nHDF5 file structure:")
        print(f"Root attributes: gamma={f.attrs['gamma']}, "
              f"domain={list(f.attrs['domain'])}, "
              f"grid_type={f.attrs['grid_type']}")

        def show_item(name, obj):
            import h5py as _h5

            indent = "  " * (name.count("/") + 1)
            if isinstance(obj, _h5.Group):
                attrs = {k: v for k, v in obj.attrs.items()}
                if attrs:
                    print(f"{indent}[Group] {name}  attrs={attrs}")
                else:
                    print(f"{indent}[Group] {name}")
            else:
                print(
                    f"{indent}[Dataset] {name}  "
                    f"shape={obj.shape} dtype={obj.dtype}"
                )

        f.visititems(show_item)

        results = {}
        for regime_name in sorted(f.keys()):
            nrmse = evaluate_regime(f, regime_name)
            results[regime_name] = nrmse

    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    all_pass = True
    for name, nrmse in results.items():
        status = "PASS" if nrmse < 0.05 else "FAIL"
        if nrmse >= 0.05:
            all_pass = False
        print(f"  {name}: nRMSE = {nrmse:.6f} [{status}]")

    if all_pass:
        print("\nAll regimes PASS (nRMSE < 0.05)")
    else:
        print("\nSome regimes FAIL (nRMSE >= 0.05)")
