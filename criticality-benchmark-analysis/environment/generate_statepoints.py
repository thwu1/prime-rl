#!/usr/bin/env python3
"""Generate synthetic Monte Carlo simulation statepoint files in HDF5 format."""

import os
import h5py
import numpy as np

os.makedirs('/app/statepoints', exist_ok=True)

configs = [
    {
        'id': 'hmf001',
        'desc': 'HEU-MET-FAST-001 case-1 eigenvalue calculation',
        'seed': 42,
        'n_batches': 200,
        'n_inactive': 20,
        'particles': 10000,
        'keff_center': 1.00015,
        'keff_batch_sigma': 0.0025,
        'entropy_eq': 5.18,
    },
    {
        'id': 'hmf003',
        'desc': 'HEU-MET-FAST-003 case-1 eigenvalue calculation',
        'seed': 137,
        'n_batches': 200,
        'n_inactive': 20,
        'particles': 10000,
        'keff_center': 1.00108,
        'keff_batch_sigma': 0.0030,
        'entropy_eq': 4.76,
    },
    {
        'id': 'hst001',
        'desc': 'HEU-SOL-THERM-001 case-1 eigenvalue calculation',
        'seed': 256,
        'n_batches': 200,
        'n_inactive': 20,
        'particles': 10000,
        'keff_center': 0.99942,
        'keff_batch_sigma': 0.0028,
        'entropy_eq': 6.05,
    },
]

for cfg in configs:
    np.random.seed(cfg['seed'])
    n = cfg['n_batches']
    ni = cfg['n_inactive']

    # K-effective: normal around center, with transient bias on inactive batches
    keff = np.random.normal(cfg['keff_center'], cfg['keff_batch_sigma'], n)
    bias = 0.008 * np.exp(-np.arange(ni) / 5.0)
    keff[:ni] += bias

    # Shannon entropy: stable with very brief initial transient
    entropy = cfg['entropy_eq'] + np.random.normal(0, 0.005, n)
    for j in range(min(3, n)):
        entropy[j] -= 0.1 * (3 - j) / 3.0

    # Additional diagnostics (red herrings for exploration)
    gen_time = np.random.uniform(3.0, 12.0, n)
    src_frac = 1.0 - 0.15 * np.exp(-np.arange(n, dtype=float) / 8.0) \
               + np.random.normal(0, 0.005, n)
    flux_mean = np.random.uniform(1e13, 5e13)
    flux_std = flux_mean * 0.003

    fpath = '/app/statepoints/{}_statepoint.h5'.format(cfg['id'])
    with h5py.File(fpath, 'w') as f:
        f.attrs['description'] = cfg['desc']
        f.attrs['code_version'] = 'OpenMC 0.14.0'
        f.attrs['date_generated'] = '2024-03-15T14:30:00'

        g = f.create_group('settings')
        g.create_dataset('n_batches', data=np.int32(n))
        g.create_dataset('n_inactive', data=np.int32(ni))
        g.create_dataset('particles_per_batch', data=np.int32(cfg['particles']))
        g.create_dataset('random_seed', data=np.int64(cfg['seed']))

        g = f.create_group('results')
        g.create_dataset('k_effective', data=keff)
        g.create_dataset('mean_generation_time_ms', data=gen_time)

        g = f.create_group('diagnostics')
        g.create_dataset('entropy', data=entropy)
        g.create_dataset('source_fraction_in_fissile', data=src_frac)

        g = f.create_group('tally_data')
        g.create_dataset('total_flux_mean', data=np.float64(flux_mean))
        g.create_dataset('total_flux_std_dev', data=np.float64(flux_std))

    print('Created {}'.format(fpath))
