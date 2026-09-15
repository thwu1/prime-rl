"""
Generate noisy dynamical system observations in HDF5 format plus
an XML output specification. Runs during Docker build.
"""
import numpy as np
import h5py
import os


def generate():
    np.random.seed(12345)

    n = 10        # state dimension
    r_true = 4    # true rank (2 real eigenvalues + 1 complex conjugate pair)
    m = 200       # number of snapshot pairs => m+1 = 201 snapshots
    n_pred = 50   # prediction horizon

    # Construct an orthogonal basis via QR decomposition of a random matrix
    H = np.random.randn(n, n)
    Q, _ = np.linalg.qr(H)

    # Build system dynamics in modal basis:
    #   Two real eigenvalues: 0.995 and 0.98
    #   One complex conjugate pair via 2x2 rotation-scaling block: 0.92 +/- 0.15i
    #   Remaining 6 dimensions: zero (noise subspace)
    Lambda = np.zeros((n, n))
    Lambda[0, 0] = 0.995
    Lambda[1, 1] = 0.92;  Lambda[1, 2] = -0.15
    Lambda[2, 1] = 0.15;  Lambda[2, 2] = 0.92
    Lambda[3, 3] = 0.98

    A = Q @ Lambda @ Q.T

    coeffs = np.array([2.0, 1.5, -1.0, 0.8])
    x0 = Q[:, :r_true] @ coeffs

    total_steps = m + 1 + n_pred
    X_full = np.zeros((n, total_steps))
    X_full[:, 0] = x0
    for t in range(total_steps - 1):
        X_full[:, t + 1] = A @ X_full[:, t]

    noise_std = 0.01
    noise = noise_std * np.random.randn(n, m + 1)
    X_train_noisy = X_full[:, :m + 1] + noise

    # ── Write HDF5 observation file ─────────────────────────────────────
    os.makedirs('/app/data', exist_ok=True)
    with h5py.File('/app/data/system_observations.h5', 'w') as f:
        obs = f.create_group('observations')
        ds = obs.create_dataset('snapshots', data=X_train_noisy.T)  # (201, 10)
        ds.attrs['row_meaning'] = 'time_step'
        ds.attrs['col_meaning'] = 'state_variable'
        obs.create_dataset('timestamps', data=np.arange(m + 1) * 0.1)
        obs.attrs['description'] = (
            'Noisy observations of a discrete-time linear dynamical system'
        )

        meta = f.create_group('metadata')
        meta.attrs['state_dimension'] = n
        meta.attrs['num_snapshots'] = m + 1
        meta.attrs['sampling_interval_dt'] = 0.1
        meta.attrs['noise_level_std'] = noise_std

        cfg = f.create_group('analysis_config')
        cfg.attrs['prediction_horizon'] = n_pred

    # ── Write XML output specification ──────────────────────────────────
    os.makedirs('/app/config', exist_ok=True)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<OutputSpecification xmlns="urn:raven:output:1.0" version="1.0">\n'
        '  <Analysis type="SystemIdentification">\n'
        '    <ResultGroup name="rank_analysis">\n'
        '      <Field name="optimal_rank" dtype="int64"\n'
        '             description="Intrinsic dimensionality of the signal subspace"/>\n'
        '    </ResultGroup>\n'
        '    <ResultGroup name="spectral_analysis">\n'
        '      <Field name="eigenvalues" dtype="complex128"\n'
        '             format="real_imag_pairs" sort_order="magnitude_descending"\n'
        '             description="Dominant dynamic modes as discrete-time eigenvalues"/>\n'
        '      <Field name="eigenvalue_magnitudes" dtype="float64"\n'
        '             sort_order="descending"\n'
        '             description="Absolute values of the eigenvalues"/>\n'
        '    </ResultGroup>\n'
        '    <ResultGroup name="forecasting">\n'
        '      <Field name="predictions" dtype="float64"\n'
        '             shape_spec="(prediction_horizon, state_dimension)"\n'
        '             description="Row-wise predicted future state vectors"/>\n'
        '    </ResultGroup>\n'
        '    <ResultGroup name="reconstruction">\n'
        '      <Field name="reconstruction_rmse" dtype="float64"\n'
        '             description="RMSE of model reconstruction vs noisy observations"/>\n'
        '    </ResultGroup>\n'
        '  </Analysis>\n'
        '  <OutputFormats>\n'
        '    <Format type="json" path="/app/results.json">\n'
        '      <FieldMapping source="eigenvalues" json_format="list_of_pairs"/>\n'
        '      <FieldMapping source="predictions" json_format="nested_list"/>\n'
        '    </Format>\n'
        '    <Format type="hdf5" path="/app/results.h5">\n'
        '      <GroupMapping result_group="rank_analysis"\n'
        '                    hdf5_group="/analysis/rank"/>\n'
        '      <GroupMapping result_group="spectral_analysis"\n'
        '                    hdf5_group="/analysis/spectral"/>\n'
        '      <GroupMapping result_group="forecasting"\n'
        '                    hdf5_group="/analysis/forecasting"/>\n'
        '      <GroupMapping result_group="reconstruction"\n'
        '                    hdf5_group="/analysis/quality"/>\n'
        '    </Format>\n'
        '  </OutputFormats>\n'
        '</OutputSpecification>\n'
    )
    with open('/app/config/output_spec.xml', 'w') as f:
        f.write(xml)


if __name__ == '__main__':
    generate()
