
import json
import math
import os
import sqlite3
import pytest


# ---------------------------------------------------------------------------
# Load inputs from environment
# ---------------------------------------------------------------------------

def load_inputs():
    with open('/app/workloads.json') as f:
        wl_config = json.load(f)
    target_gpu = wl_config['target_gpu']
    workloads = wl_config['workloads']

    with open('/app/search_space.json') as f:
        space = json.load(f)

    # Query SQLite database for hardware specifications
    conn = sqlite3.connect('/app/gpu_specs.db')
    cursor = conn.cursor()

    cursor.execute(
        "SELECT spec_name, spec_value FROM gpu_specs "
        "WHERE gpu_name=? AND spec_category='sm_resources'",
        (target_gpu,)
    )
    sm = {name: int(val) for name, val in cursor.fetchall()}

    cursor.execute(
        "SELECT spec_name, spec_value FROM gpu_specs "
        "WHERE gpu_name=? AND spec_category='registers'",
        (target_gpu,)
    )
    regs = {name: int(val) for name, val in cursor.fetchall()}

    cursor.execute(
        "SELECT spec_name, spec_value FROM gpu_specs "
        "WHERE gpu_name=? AND spec_category='shared_memory'",
        (target_gpu,)
    )
    smem = {name: int(val) for name, val in cursor.fetchall()}

    cursor.execute(
        "SELECT spec_value FROM gpu_specs "
        "WHERE gpu_name=? AND spec_name='fp16_element_size'",
        (target_gpu,)
    )
    element_size = int(cursor.fetchone()[0])

    cursor.execute(
        "SELECT value FROM kernel_profiles "
        "WHERE kernel_type='tiled_matmul' AND parameter='register_overhead_per_thread'"
    )
    reg_overhead = int(cursor.fetchone()[0])

    conn.close()

    hw = {
        'num_sms': sm['num_sms'],
        'max_warps_per_sm': sm['max_warps_per_sm'],
        'max_blocks_per_sm': sm['max_blocks_per_sm'],
        'warp_size': sm['warp_size'],
        'register_file_size': regs['register_file_size'],
        'max_registers_per_thread': regs['max_registers_per_thread'],
        'allocation_granularity': regs['allocation_granularity'],
        'shared_memory_per_sm': smem['shared_memory_per_sm'],
        'max_shared_memory_per_block': smem['max_shared_memory_per_block'],
        'element_size_bytes': element_size,
        'register_overhead': reg_overhead,
    }

    return hw, space, workloads


# ---------------------------------------------------------------------------
# Reference implementation — computes expected results from scratch
# ---------------------------------------------------------------------------

def generate_configs(space):
    configs = []
    for bm in space['BLOCK_SIZE_M']:
        for bn in space['BLOCK_SIZE_N']:
            for bk in space['BLOCK_SIZE_K']:
                for gm in space['GROUP_SIZE_M']:
                    for nw in space['num_warps']:
                        for ns in space['num_stages']:
                            configs.append({
                                'BLOCK_SIZE_M': bm, 'BLOCK_SIZE_N': bn,
                                'BLOCK_SIZE_K': bk, 'GROUP_SIZE_M': gm,
                                'num_warps': nw, 'num_stages': ns
                            })
    return configs


def sort_key(r):
    return (
        -r['score'],
        r['smem_bytes'],
        r['num_warps'],
        r['BLOCK_SIZE_M'],
        r['BLOCK_SIZE_N'],
        r['BLOCK_SIZE_K'],
        r['GROUP_SIZE_M'],
        r['num_stages'],
    )


def analyze_config(cfg, hw, wl):
    bm = cfg['BLOCK_SIZE_M']
    bn = cfg['BLOCK_SIZE_N']
    bk = cfg['BLOCK_SIZE_K']
    gm = cfg['GROUP_SIZE_M']
    nw = cfg['num_warps']
    ns = cfg['num_stages']
    M, N, K = wl['M'], wl['N'], wl['K']
    es = hw['element_size_bytes']
    ws = hw['warp_size']

    # Shared memory: num_stages * (A_tile + B_tile) * element_size
    smem = ns * (bm * bk + bk * bn) * es
    if smem > hw['max_shared_memory_per_block']:
        return None

    # Register pressure
    acc_regs = (bm * bn) // (nw * ws)
    total_regs = acc_regs + hw['register_overhead']
    if total_regs > hw['max_registers_per_thread']:
        return None

    alloc_regs = math.ceil(total_regs / hw['allocation_granularity']) * hw['allocation_granularity']
    threads = nw * ws
    rpb = alloc_regs * threads

    # Blocks per SM by each resource
    bbw = hw['max_warps_per_sm'] // nw
    bbs = hw['shared_memory_per_sm'] // smem if smem > 0 else hw['max_blocks_per_sm']
    bbr = hw['register_file_size'] // rpb if rpb > 0 else hw['max_blocks_per_sm']
    bbm = hw['max_blocks_per_sm']

    active = min(bbw, bbs, bbr, bbm)
    if active < 1:
        return None

    occ = active * nw / hw['max_warps_per_sm']

    # Bottleneck: resource yielding fewest blocks; ties by priority
    limits = [('smem', bbs), ('regs', bbr), ('warps', bbw), ('max_blocks', bbm)]
    priority = {'smem': 0, 'regs': 1, 'warps': 2, 'max_blocks': 3}
    bottleneck = min(limits, key=lambda x: (x[1], priority[x[0]]))[0]

    # Effective arithmetic intensity with L2 reuse
    nrt = math.ceil(M / bm)
    eg = min(gm, nrt)

    ba = bm * K * es
    bb = bn * K * es / eg
    bc = bm * bn * es
    eff_bytes = ba + bb + bc
    flops = 2.0 * bm * bn * K
    eai = flops / eff_bytes

    score = occ * eai

    return {
        'BLOCK_SIZE_M': bm, 'BLOCK_SIZE_N': bn, 'BLOCK_SIZE_K': bk,
        'GROUP_SIZE_M': gm, 'num_warps': nw, 'num_stages': ns,
        'occupancy': occ, 'effective_ai': eai, 'score': score,
        'smem_bytes': smem, 'bottleneck': bottleneck,
    }


def compute_pareto(valid_results):
    """Deduplicated Pareto frontier on (occupancy, effective_ai)."""
    points = {}
    for r in valid_results:
        key = (r['occupancy'], r['effective_ai'])
        if key not in points or sort_key(r) < sort_key(points[key]):
            points[key] = r

    reps = list(points.values())

    pareto = []
    for r in reps:
        dominated = False
        for other in reps:
            if other is r:
                continue
            if (other['occupancy'] >= r['occupancy']
                    and other['effective_ai'] >= r['effective_ai']
                    and (other['occupancy'] > r['occupancy']
                         or other['effective_ai'] > r['effective_ai'])):
                dominated = True
                break
        if not dominated:
            pareto.append(r)

    pareto.sort(key=sort_key)
    return pareto


def ref_compute():
    hw, space, workloads = load_inputs()
    configs = generate_configs(space)
    total_configs = len(configs)

    all_scores = {}

    result = {'workloads': []}

    for wi, wl in enumerate(workloads):
        valid = []
        for cfg in configs:
            r = analyze_config(cfg, hw, wl)
            if r is not None:
                valid.append(r)

        pareto = compute_pareto(valid)

        valid.sort(key=sort_key)
        best = valid[0] if valid else None

        result['workloads'].append({
            'M': wl['M'], 'N': wl['N'], 'K': wl['K'],
            'total_configs': total_configs,
            'num_valid': len(valid),
            'num_pareto': len(pareto),
            'best': best,
            'pareto_frontier': pareto,
        })

        for r in valid:
            key = (r['BLOCK_SIZE_M'], r['BLOCK_SIZE_N'], r['BLOCK_SIZE_K'],
                   r['GROUP_SIZE_M'], r['num_warps'], r['num_stages'])
            if key not in all_scores:
                all_scores[key] = {}
            all_scores[key][wi] = r['score']

    # Overall best by geometric mean
    num_wl = len(workloads)
    best_geo_score = -1.0
    best_geo_key = None
    for key, scores_map in all_scores.items():
        if len(scores_map) == num_wl:
            vals = [scores_map[i] for i in range(num_wl)]
            geo = math.prod(vals) ** (1.0 / num_wl)
            if geo > best_geo_score:
                best_geo_score = geo
                best_geo_key = key

    if best_geo_key:
        for r in result['workloads'][0]['best'], *result['workloads'][0]['pareto_frontier']:
            ck = (r['BLOCK_SIZE_M'], r['BLOCK_SIZE_N'], r['BLOCK_SIZE_K'],
                  r['GROUP_SIZE_M'], r['num_warps'], r['num_stages'])
            if ck == best_geo_key:
                overall = dict(r)
                overall['geo_mean_score'] = best_geo_score
                result['overall_best'] = overall
                break
        else:
            for cfg in configs:
                ck = (cfg['BLOCK_SIZE_M'], cfg['BLOCK_SIZE_N'], cfg['BLOCK_SIZE_K'],
                      cfg['GROUP_SIZE_M'], cfg['num_warps'], cfg['num_stages'])
                if ck == best_geo_key:
                    r = analyze_config(cfg, hw, workloads[0])
                    if r:
                        overall = dict(r)
                        overall['geo_mean_score'] = best_geo_score
                        result['overall_best'] = overall
                    break

    return result


# Cache the reference computation
_ref_cache = None

def get_ref():
    global _ref_cache
    if _ref_cache is None:
        _ref_cache = ref_compute()
    return _ref_cache


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestResultsExist:
    def test_file_exists(self):
        assert os.path.exists('/app/results.json'), "results.json not found at /app/"

    def test_valid_json(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        assert isinstance(data, dict)


class TestStructure:
    @pytest.fixture(autouse=True)
    def load(self):
        with open('/app/results.json') as f:
            self.actual = json.load(f)

    def test_has_workloads(self):
        assert 'workloads' in self.actual

    def test_workload_count(self):
        assert len(self.actual['workloads']) == 4

    def test_has_overall_best(self):
        assert 'overall_best' in self.actual

    def test_workload_fields(self):
        for w in self.actual['workloads']:
            for key in ['M', 'N', 'K', 'total_configs', 'num_valid',
                        'num_pareto', 'best', 'pareto_frontier']:
                assert key in w, f"Missing field {key} in workload entry"

    def test_config_result_fields(self):
        for w in self.actual['workloads']:
            b = w['best']
            for key in ['BLOCK_SIZE_M', 'BLOCK_SIZE_N', 'BLOCK_SIZE_K',
                        'GROUP_SIZE_M', 'num_warps', 'num_stages',
                        'occupancy', 'effective_ai', 'score',
                        'smem_bytes', 'bottleneck']:
                assert key in b, f"Missing field {key} in best config"


class TestCounts:
    @pytest.fixture(autouse=True)
    def load(self):
        with open('/app/results.json') as f:
            self.actual = json.load(f)
        self.expected = get_ref()

    def test_total_configs(self):
        for aw in self.actual['workloads']:
            assert aw['total_configs'] == 648, \
                f"Total configs should be 648, got {aw['total_configs']}"

    def test_num_valid(self):
        for aw, ew in zip(self.actual['workloads'], self.expected['workloads']):
            assert aw['num_valid'] == ew['num_valid'], \
                (f"Workload ({aw['M']},{aw['N']},{aw['K']}): "
                 f"expected {ew['num_valid']} valid, got {aw['num_valid']}")

    def test_num_pareto(self):
        for aw, ew in zip(self.actual['workloads'], self.expected['workloads']):
            assert aw['num_pareto'] == ew['num_pareto'], \
                (f"Workload ({aw['M']},{aw['N']},{aw['K']}): "
                 f"expected {ew['num_pareto']} pareto, got {aw['num_pareto']}")


class TestBestConfig:
    @pytest.fixture(autouse=True)
    def load(self):
        with open('/app/results.json') as f:
            self.actual = json.load(f)
        self.expected = get_ref()

    def test_best_config_tiling(self):
        for aw, ew in zip(self.actual['workloads'], self.expected['workloads']):
            ab, eb = aw['best'], ew['best']
            for key in ['BLOCK_SIZE_M', 'BLOCK_SIZE_N', 'BLOCK_SIZE_K',
                        'GROUP_SIZE_M', 'num_warps', 'num_stages']:
                assert ab[key] == eb[key], \
                    (f"Workload ({aw['M']},{aw['N']},{aw['K']}): "
                     f"best config {key}={ab[key]}, expected {eb[key]}")

    def test_best_occupancy(self):
        for aw, ew in zip(self.actual['workloads'], self.expected['workloads']):
            assert abs(aw['best']['occupancy'] - ew['best']['occupancy']) < 1e-6, \
                (f"Workload ({aw['M']},{aw['N']},{aw['K']}): "
                 f"occupancy {aw['best']['occupancy']}, expected {ew['best']['occupancy']}")

    def test_best_effective_ai(self):
        for aw, ew in zip(self.actual['workloads'], self.expected['workloads']):
            assert abs(aw['best']['effective_ai'] - ew['best']['effective_ai']) < 0.01, \
                (f"Workload ({aw['M']},{aw['N']},{aw['K']}): "
                 f"effective_ai {aw['best']['effective_ai']}, expected {ew['best']['effective_ai']}")

    def test_best_score(self):
        for aw, ew in zip(self.actual['workloads'], self.expected['workloads']):
            assert abs(aw['best']['score'] - ew['best']['score']) < 0.01, \
                (f"Workload ({aw['M']},{aw['N']},{aw['K']}): "
                 f"score {aw['best']['score']}, expected {ew['best']['score']}")

    def test_best_smem(self):
        for aw, ew in zip(self.actual['workloads'], self.expected['workloads']):
            assert aw['best']['smem_bytes'] == ew['best']['smem_bytes'], \
                (f"Workload ({aw['M']},{aw['N']},{aw['K']}): "
                 f"smem {aw['best']['smem_bytes']}, expected {ew['best']['smem_bytes']}")

    def test_best_bottleneck(self):
        for aw, ew in zip(self.actual['workloads'], self.expected['workloads']):
            assert aw['best']['bottleneck'] == ew['best']['bottleneck'], \
                (f"Workload ({aw['M']},{aw['N']},{aw['K']}): "
                 f"bottleneck {aw['best']['bottleneck']}, expected {ew['best']['bottleneck']}")


class TestScoreInvariant:
    @pytest.fixture(autouse=True)
    def load(self):
        with open('/app/results.json') as f:
            self.actual = json.load(f)

    def test_score_equals_occ_times_ai(self):
        for aw in self.actual['workloads']:
            b = aw['best']
            expected_score = b['occupancy'] * b['effective_ai']
            assert abs(b['score'] - expected_score) < 0.01, \
                (f"score={b['score']} != occupancy*effective_ai="
                 f"{b['occupancy']}*{b['effective_ai']}={expected_score}")

    def test_pareto_scores(self):
        for aw in self.actual['workloads']:
            for p in aw['pareto_frontier']:
                expected_score = p['occupancy'] * p['effective_ai']
                assert abs(p['score'] - expected_score) < 0.01


class TestParetoFrontier:
    @pytest.fixture(autouse=True)
    def load(self):
        with open('/app/results.json') as f:
            self.actual = json.load(f)
        self.expected = get_ref()

    def test_pareto_non_dominated(self):
        """Every config on the Pareto frontier must not be dominated."""
        for aw in self.actual['workloads']:
            pf = aw['pareto_frontier']
            for i, p in enumerate(pf):
                for j, q in enumerate(pf):
                    if i == j:
                        continue
                    dominated = (
                        q['occupancy'] >= p['occupancy']
                        and q['effective_ai'] >= p['effective_ai']
                        and (q['occupancy'] > p['occupancy']
                             or q['effective_ai'] > p['effective_ai'])
                    )
                    assert not dominated, \
                        (f"Pareto config {i} dominated by config {j} "
                         f"in workload ({aw['M']},{aw['N']},{aw['K']})")

    def test_pareto_sorted_by_score(self):
        for aw in self.actual['workloads']:
            pf = aw['pareto_frontier']
            scores = [p['score'] for p in pf]
            assert scores == sorted(scores, reverse=True), \
                f"Pareto frontier not sorted by score desc for workload ({aw['M']},{aw['N']},{aw['K']})"

    def test_pareto_occupancy_values(self):
        """Check that expected Pareto occupancy values appear."""
        for aw, ew in zip(self.actual['workloads'], self.expected['workloads']):
            expected_occs = sorted([p['occupancy'] for p in ew['pareto_frontier']])
            actual_occs = sorted([p['occupancy'] for p in aw['pareto_frontier']])
            assert actual_occs == expected_occs, \
                (f"Workload ({aw['M']},{aw['N']},{aw['K']}): "
                 f"Pareto occupancies {actual_occs} != expected {expected_occs}")


class TestOverallBest:
    @pytest.fixture(autouse=True)
    def load(self):
        with open('/app/results.json') as f:
            self.actual = json.load(f)
        self.expected = get_ref()

    def test_overall_best_config(self):
        ab = self.actual['overall_best']
        eb = self.expected['overall_best']
        for key in ['BLOCK_SIZE_M', 'BLOCK_SIZE_N', 'BLOCK_SIZE_K',
                    'GROUP_SIZE_M', 'num_warps', 'num_stages']:
            assert ab[key] == eb[key], \
                f"Overall best {key}={ab[key]}, expected {eb[key]}"

    def test_overall_best_geo_mean(self):
        ab = self.actual['overall_best']
        eb = self.expected['overall_best']
        assert abs(ab['geo_mean_score'] - eb['geo_mean_score']) < 0.1, \
            f"Geo mean score {ab['geo_mean_score']}, expected {eb['geo_mean_score']}"


class TestSpotChecks:
    """Verify specific known config computations."""

    @pytest.fixture(autouse=True)
    def load(self):
        self.hw, _, _ = load_inputs()

    def test_smem_computation(self):
        """Config (128,256,64,8,8,3): smem = 3*(128*64+64*256)*2 = 147456"""
        cfg = {'BLOCK_SIZE_M': 128, 'BLOCK_SIZE_N': 256, 'BLOCK_SIZE_K': 64,
               'GROUP_SIZE_M': 8, 'num_warps': 8, 'num_stages': 3}
        wl = {'M': 4096, 'N': 4096, 'K': 4096}
        r = analyze_config(cfg, self.hw, wl)
        assert r is not None
        assert r['smem_bytes'] == 147456

    def test_occupancy_low_block(self):
        """Config (64,64,32,8,8,2): occupancy 0.5"""
        cfg = {'BLOCK_SIZE_M': 64, 'BLOCK_SIZE_N': 64, 'BLOCK_SIZE_K': 32,
               'GROUP_SIZE_M': 8, 'num_warps': 8, 'num_stages': 2}
        wl = {'M': 4096, 'N': 4096, 'K': 4096}
        r = analyze_config(cfg, self.hw, wl)
        assert r is not None
        assert abs(r['occupancy'] - 0.5) < 1e-6

    def test_invalid_config_regs(self):
        """Config (256,256,32,8,4,2) should be invalid (too many regs)."""
        cfg = {'BLOCK_SIZE_M': 256, 'BLOCK_SIZE_N': 256, 'BLOCK_SIZE_K': 32,
               'GROUP_SIZE_M': 8, 'num_warps': 4, 'num_stages': 2}
        wl = {'M': 4096, 'N': 4096, 'K': 4096}
        r = analyze_config(cfg, self.hw, wl)
        assert r is None, "Config (256,256,*,*,4,*) should be invalid due to register pressure"

    def test_effective_ai_exact(self):
        """Config (64,256,32,8,8,2) with K=4096: eai = 163.84 exactly."""
        cfg = {'BLOCK_SIZE_M': 64, 'BLOCK_SIZE_N': 256, 'BLOCK_SIZE_K': 32,
               'GROUP_SIZE_M': 8, 'num_warps': 8, 'num_stages': 2}
        wl = {'M': 4096, 'N': 4096, 'K': 4096}
        r = analyze_config(cfg, self.hw, wl)
        assert r is not None
        assert abs(r['effective_ai'] - 163.84) < 0.01

    def test_group_size_capping(self):
        """For M=1024, BM=256: eff_group = min(8, ceil(1024/256)) = min(8,4) = 4.
        So GM=8 and GM=4 should give the same effective_ai."""
        wl = {'M': 1024, 'N': 16384, 'K': 2048}
        cfg8 = {'BLOCK_SIZE_M': 256, 'BLOCK_SIZE_N': 64, 'BLOCK_SIZE_K': 32,
                'GROUP_SIZE_M': 8, 'num_warps': 8, 'num_stages': 2}
        cfg4 = {'BLOCK_SIZE_M': 256, 'BLOCK_SIZE_N': 64, 'BLOCK_SIZE_K': 32,
                'GROUP_SIZE_M': 4, 'num_warps': 8, 'num_stages': 2}
        r8 = analyze_config(cfg8, self.hw, wl)
        r4 = analyze_config(cfg4, self.hw, wl)
        assert r8 is not None and r4 is not None
        assert abs(r8['effective_ai'] - r4['effective_ai']) < 1e-6, \
            "GM=8 and GM=4 should give same eai when eff_group is capped"

    def test_bottleneck_priority(self):
        """When smem and regs give same block count, bottleneck should be smem."""
        cfg = {'BLOCK_SIZE_M': 128, 'BLOCK_SIZE_N': 256, 'BLOCK_SIZE_K': 64,
               'GROUP_SIZE_M': 8, 'num_warps': 8, 'num_stages': 3}
        wl = {'M': 4096, 'N': 4096, 'K': 4096}
        r = analyze_config(cfg, self.hw, wl)
        assert r is not None
        assert r['bottleneck'] == 'smem'
