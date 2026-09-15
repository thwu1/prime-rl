
import pytest
import json
import numpy as np
import h5py
import yaml
import os


def load_data():
    """Load particle positions from HDF5 and config from YAML."""
    with h5py.File('/app/data/particles.h5', 'r') as f:
        particles = f['positions'][:]
    with open('/app/config.yaml') as f:
        raw = yaml.safe_load(f)
    return particles, raw


def get_params(raw):
    """Extract relevant simulation parameters from nested config."""
    box = raw['simulation']['domain']['extents']
    rc = raw['simulation']['interactions']['cutoff']
    procs = raw['scaling_study']['target_counts']
    alpha = raw['platform']['network']['msg_startup_latency_sec']
    beta = raw['platform']['network']['per_datum_transfer_cost_sec']
    t_compute = raw['platform']['compute']['per_particle_flop_cost_sec']
    return box, rc, procs, alpha, beta, t_compute


def load_results():
    with open('/app/results.json') as f:
        return json.load(f)


def valid_decomposition_count(P, box, rc):
    """Count how many (Px,Py,Pz) factorizations satisfy subdomain >= 2*rc."""
    count = 0
    for px in range(1, P + 1):
        if P % px != 0:
            continue
        rem = P // px
        for py in range(1, rem + 1):
            if rem % py != 0:
                continue
            pz = rem // py
            if box[0] / px >= 2 * rc and box[1] / py >= 2 * rc and box[2] / pz >= 2 * rc:
                count += 1
    return count


def compute_rank_assignment(particles, grid, box):
    """Assign particles to ranks for a given grid decomposition."""
    px, py, pz = grid
    lx, ly, lz = box
    dx, dy, dz = lx / px, ly / py, lz / pz
    rx = np.minimum((particles[:, 0] / dx).astype(int), px - 1)
    ry = np.minimum((particles[:, 1] / dy).astype(int), py - 1)
    rz = np.minimum((particles[:, 2] / dz).astype(int), pz - 1)
    return rx, ry, rz, dx, dy, dz


def compute_load_imbalance(particles, grid, box):
    """Independently compute load imbalance for a grid decomposition."""
    px, py, pz = grid
    rx, ry, rz, dx, dy, dz = compute_rank_assignment(particles, grid, box)
    rank_id = rx * (py * pz) + ry * pz + rz
    counts = np.bincount(rank_id, minlength=px * py * pz)
    return float(counts.max()) / (len(particles) / (px * py * pz)), int(counts.max())


def compute_comm_volume_and_time(particles, grid, box, rc, alpha, beta):
    """Independently compute communication volume and max comm time."""
    px, py, pz = grid
    lx, ly, lz = box
    rx, ry, rz, dx, dy, dz = compute_rank_assignment(particles, grid, box)
    rank_id = rx * (py * pz) + ry * pz + rz
    n_ranks = px * py * pz

    frac_x = (particles[:, 0] - rx * dx) / dx
    frac_y = (particles[:, 1] - ry * dy) / dy
    frac_z = (particles[:, 2] - rz * dz) / dz

    send = {}
    if px > 1:
        send['lo_x'] = np.bincount(rank_id[frac_x < rc / dx], minlength=n_ranks)
        send['hi_x'] = np.bincount(rank_id[frac_x > 1 - rc / dx], minlength=n_ranks)
    if py > 1:
        send['lo_y'] = np.bincount(rank_id[frac_y < rc / dy], minlength=n_ranks)
        send['hi_y'] = np.bincount(rank_id[frac_y > 1 - rc / dy], minlength=n_ranks)
    if pz > 1:
        send['lo_z'] = np.bincount(rank_id[frac_z < rc / dz], minlength=n_ranks)
        send['hi_z'] = np.bincount(rank_id[frac_z > 1 - rc / dz], minlength=n_ranks)

    comm_time = np.zeros(n_ranks)
    halo_total = np.zeros(n_ranks, dtype=np.int64)

    for ix in range(px):
        for iy in range(py):
            for iz in range(pz):
                r = ix * (py * pz) + iy * pz + iz
                if px > 1:
                    nbr = ((ix + 1) % px) * (py * pz) + iy * pz + iz
                    h = int(send['lo_x'][nbr])
                    halo_total[r] += h
                    comm_time[r] += alpha + beta * h
                    nbr = ((ix - 1) % px) * (py * pz) + iy * pz + iz
                    h = int(send['hi_x'][nbr])
                    halo_total[r] += h
                    comm_time[r] += alpha + beta * h
                if py > 1:
                    nbr = ix * (py * pz) + ((iy + 1) % py) * pz + iz
                    h = int(send['lo_y'][nbr])
                    halo_total[r] += h
                    comm_time[r] += alpha + beta * h
                    nbr = ix * (py * pz) + ((iy - 1) % py) * pz + iz
                    h = int(send['hi_y'][nbr])
                    halo_total[r] += h
                    comm_time[r] += alpha + beta * h
                if pz > 1:
                    nbr = ix * (py * pz) + iy * pz + (iz + 1) % pz
                    h = int(send['lo_z'][nbr])
                    halo_total[r] += h
                    comm_time[r] += alpha + beta * h
                    nbr = ix * (py * pz) + iy * pz + (iz - 1) % pz
                    h = int(send['hi_z'][nbr])
                    halo_total[r] += h
                    comm_time[r] += alpha + beta * h

    return int(halo_total.sum()), float(comm_time.max())


class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.exists('/app/results.json'), "results.json not found"

    def test_results_valid_json(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        assert isinstance(data, dict)


class TestResultsStructure:
    def test_has_decompositions_key(self):
        results = load_results()
        assert 'decompositions' in results

    def test_has_all_processor_counts(self):
        results = load_results()
        _, raw = load_data()
        _, _, procs, _, _, _ = get_params(raw)
        for P in procs:
            assert str(P) in results['decompositions'], f"Missing P={P}"

    def test_required_fields_per_decomposition(self):
        results = load_results()
        required = ['optimal', 'T_total', 'T_comp', 'T_comm',
                     'load_imbalance', 'max_particles_per_rank',
                     'comm_volume', 'all_candidates']
        for key, dec in results['decompositions'].items():
            for field in required:
                assert field in dec, f"P={key} missing field '{field}'"

    def test_optimal_is_triplet_of_ints(self):
        results = load_results()
        for key, dec in results['decompositions'].items():
            opt = dec['optimal']
            assert isinstance(opt, list) and len(opt) == 3
            assert all(isinstance(v, int) for v in opt)

    def test_optimal_product_equals_P(self):
        results = load_results()
        for key, dec in results['decompositions'].items():
            P = int(key)
            assert dec['optimal'][0] * dec['optimal'][1] * dec['optimal'][2] == P

    def test_candidates_have_required_fields(self):
        results = load_results()
        required = ['grid', 'T_total', 'T_comp', 'T_comm',
                     'load_imbalance', 'max_particles_per_rank', 'comm_volume']
        for key, dec in results['decompositions'].items():
            for cand in dec['all_candidates']:
                for field in required:
                    assert field in cand, f"P={key} candidate missing '{field}'"


class TestDecompositionConstraints:
    def test_subdomain_size_constraint(self):
        _, raw = load_data()
        box, rc, _, _, _, _ = get_params(raw)
        results = load_results()
        for key, dec in results['decompositions'].items():
            for cand in dec['all_candidates']:
                px, py, pz = cand['grid']
                assert box[0] / px >= 2 * rc - 1e-10
                assert box[1] / py >= 2 * rc - 1e-10
                assert box[2] / pz >= 2 * rc - 1e-10

    def test_all_candidate_products_equal_P(self):
        results = load_results()
        for key, dec in results['decompositions'].items():
            P = int(key)
            for cand in dec['all_candidates']:
                g = cand['grid']
                assert g[0] * g[1] * g[2] == P

    def test_all_valid_decompositions_enumerated(self):
        _, raw = load_data()
        box, rc, _, _, _, _ = get_params(raw)
        results = load_results()
        for key, dec in results['decompositions'].items():
            P = int(key)
            expected = valid_decomposition_count(P, box, rc)
            actual = len(dec['all_candidates'])
            assert actual == expected, (
                f"P={P}: expected {expected} valid decompositions, got {actual}"
            )


class TestLoadImbalanceAccuracy:
    def test_load_imbalance_geq_1(self):
        results = load_results()
        for key, dec in results['decompositions'].items():
            assert dec['load_imbalance'] >= 1.0

    def test_load_imbalance_for_optimal(self):
        """Verify load imbalance by independent spatial binning."""
        particles, raw = load_data()
        box, _, _, _, _, _ = get_params(raw)
        results = load_results()
        for key, dec in results['decompositions'].items():
            grid = dec['optimal']
            li, max_p = compute_load_imbalance(particles, grid, box)
            assert abs(dec['load_imbalance'] - li) < 1e-6 * li, (
                f"P={key}: expected LI={li}, got {dec['load_imbalance']}"
            )
            assert dec['max_particles_per_rank'] == max_p

    def test_load_imbalance_for_all_candidates(self):
        """Spot-check load imbalance for a subset of candidates."""
        particles, raw = load_data()
        box, _, _, _, _, _ = get_params(raw)
        results = load_results()
        for key, dec in results['decompositions'].items():
            cands = dec['all_candidates']
            indices = [0, len(cands) // 2, len(cands) - 1]
            for i in indices:
                cand = cands[i]
                li, max_p = compute_load_imbalance(particles, cand['grid'], box)
                assert abs(cand['load_imbalance'] - li) < 1e-6 * li, (
                    f"P={key}, grid={cand['grid']}: expected LI={li}, "
                    f"got {cand['load_imbalance']}"
                )
                assert cand['max_particles_per_rank'] == max_p


class TestCommunicationVolumeAccuracy:
    def test_comm_volume_positive(self):
        results = load_results()
        for key, dec in results['decompositions'].items():
            assert dec['comm_volume'] > 0

    def test_comm_volume_for_optimal(self):
        """Verify communication volume by independent halo computation."""
        particles, raw = load_data()
        box, rc, _, alpha, beta, _ = get_params(raw)
        results = load_results()
        for key, dec in results['decompositions'].items():
            grid = dec['optimal']
            cv, max_ct = compute_comm_volume_and_time(
                particles, grid, box, rc, alpha, beta)
            assert abs(dec['comm_volume'] - cv) < 2, (
                f"P={key}: expected CV={cv}, got {dec['comm_volume']}"
            )

    def test_comm_time_for_optimal(self):
        """Verify T_comm independently."""
        particles, raw = load_data()
        box, rc, _, alpha, beta, _ = get_params(raw)
        results = load_results()
        for key, dec in results['decompositions'].items():
            grid = dec['optimal']
            _, max_ct = compute_comm_volume_and_time(
                particles, grid, box, rc, alpha, beta)
            assert abs(dec['T_comm'] - max_ct) / max(max_ct, 1e-20) < 1e-6, (
                f"P={key}: expected T_comm={max_ct}, got {dec['T_comm']}"
            )

    def test_comm_volume_for_candidates(self):
        """Spot-check communication volume for a subset of candidates."""
        particles, raw = load_data()
        box, rc, _, alpha, beta, _ = get_params(raw)
        results = load_results()
        for key, dec in results['decompositions'].items():
            cands = dec['all_candidates']
            indices = [0, len(cands) // 2, len(cands) - 1]
            for i in indices:
                cand = cands[i]
                cv, _ = compute_comm_volume_and_time(
                    particles, cand['grid'], box, rc, alpha, beta)
                assert abs(cand['comm_volume'] - cv) < 2, (
                    f"P={key}, grid={cand['grid']}: expected CV={cv}, "
                    f"got {cand['comm_volume']}"
                )


class TestTimingConsistency:
    def test_T_total_equals_sum(self):
        results = load_results()
        for key, dec in results['decompositions'].items():
            expected = dec['T_comp'] + dec['T_comm']
            assert abs(dec['T_total'] - expected) / dec['T_total'] < 1e-9

    def test_T_total_consistency_candidates(self):
        results = load_results()
        for key, dec in results['decompositions'].items():
            for cand in dec['all_candidates']:
                expected = cand['T_comp'] + cand['T_comm']
                assert abs(cand['T_total'] - expected) / max(cand['T_total'], 1e-20) < 1e-9

    def test_T_comp_matches_independent(self):
        """Verify T_comp = max_particles_per_rank * t_compute."""
        _, raw = load_data()
        _, _, _, _, _, t_compute = get_params(raw)
        results = load_results()
        for key, dec in results['decompositions'].items():
            expected = dec['max_particles_per_rank'] * t_compute
            assert abs(dec['T_comp'] - expected) / expected < 1e-9


class TestOptimality:
    def test_optimal_has_minimum_T_total(self):
        """The optimal decomposition must have the smallest T_total."""
        results = load_results()
        for key, dec in results['decompositions'].items():
            opt_time = dec['T_total']
            for cand in dec['all_candidates']:
                assert opt_time <= cand['T_total'] + 1e-15, (
                    f"P={key}: optimal T={opt_time} > "
                    f"candidate {cand['grid']} T={cand['T_total']}"
                )

    def test_candidates_sorted_by_T_total(self):
        results = load_results()
        for key, dec in results['decompositions'].items():
            times = [c['T_total'] for c in dec['all_candidates']]
            assert times == sorted(times), (
                f"P={key}: candidates not sorted by T_total"
            )

    def test_optimal_matches_first_candidate(self):
        results = load_results()
        for key, dec in results['decompositions'].items():
            assert dec['optimal'] == dec['all_candidates'][0]['grid']
            assert abs(dec['T_total'] - dec['all_candidates'][0]['T_total']) < 1e-15
