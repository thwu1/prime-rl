#!/usr/bin/env python3
"""Entry point for the EOF analysis pipeline.

"""
import xarray as xr
import numpy as np
import json
import os

from pipeline.preprocess import preprocess
from pipeline.decompose import eof_decompose
from pipeline.rotate import promax_rotation, varimax_criterion
from pipeline.postprocess import (
    compute_rotated_scores, apply_sign_convention, reorder_by_variance,
)


def main():
    with open('/app/task_config.json') as f:
        config = json.load(f)
    n_modes = config['n_modes']
    n_rotate = config['n_rotate']
    power = config['rotation_power']

    # Load climate data from NetCDF
    ds = xr.open_dataset('/app/climate_data.nc')
    data = ds['sst_anomaly'].values
    lats = ds['latitude'].values
    land_mask = ds['land_mask'].values.astype(bool)
    ds.close()

    # Preprocess
    X, valid_mask = preprocess(data, lats, land_mask)

    # EOF decomposition
    components, scores, singular_values, exp_var, exp_var_ratio, total_var = \
        eof_decompose(X, n_modes)

    # Build loadings for rotation (top n_rotate modes)
    loadings = components[:n_rotate].T * np.sqrt(exp_var[:n_rotate])[None, :]
    vc_before = varimax_criterion(loadings)

    # Promax rotation (includes Varimax as intermediate step)
    rot_loadings, R_combined, phi, varimax_loadings = \
        promax_rotation(loadings, power=power)
    vc_after = varimax_criterion(varimax_loadings)

    # Rotated explained variance from loadings
    rot_exp_var = np.sum(rot_loadings ** 2, axis=0)

    # Reorder modes by descending variance
    rot_loadings, rot_exp_var, R_combined, phi, order = \
        reorder_by_variance(rot_loadings, rot_exp_var, R_combined, phi)

    # Normalize to get rotated components
    rot_components = (rot_loadings / np.sqrt(rot_exp_var)[None, :]).T
    rot_components, sign_mult = apply_sign_convention(rot_components, n_rotate)

    # Compute rotated scores
    n_time = X.shape[0]
    rot_scores = compute_rotated_scores(
        scores, singular_values, R_combined, rot_exp_var, n_rotate, n_time,
    )
    rot_scores = rot_scores * sign_mult[None, :]

    rot_exp_var_ratio = rot_exp_var / total_var

    # Save results
    out_dir = '/app/results'
    os.makedirs(out_dir, exist_ok=True)
    np.save(f'{out_dir}/total_variance.npy', total_var)
    np.save(f'{out_dir}/unrotated_expvar_ratio.npy', exp_var_ratio)
    np.save(f'{out_dir}/unrotated_components.npy', components)
    np.save(f'{out_dir}/unrotated_scores.npy', scores)
    np.save(f'{out_dir}/rotated_components.npy', rot_components)
    np.save(f'{out_dir}/rotated_scores.npy', rot_scores)
    np.save(f'{out_dir}/rotated_expvar_ratio.npy', rot_exp_var_ratio)
    np.save(f'{out_dir}/rotation_matrix.npy', R_combined)
    np.save(f'{out_dir}/phi_matrix.npy', phi)
    np.save(f'{out_dir}/varimax_criterion_before.npy', vc_before)
    np.save(f'{out_dir}/varimax_criterion_after.npy', vc_after)


if __name__ == '__main__':
    main()
