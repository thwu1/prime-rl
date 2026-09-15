#!/usr/bin/env python3
"""Tests for Wormhole NoC Simulation & Firmware Pipeline."""

import json
import os
import subprocess
import tempfile
import pytest
from collections import defaultdict

CONFIG_PATH = '/app/wormhole_grid.json'
PIPELINE_PATH = '/app/noc_pipeline.py'


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def run_pipeline(harvested_rows=None, output_path=None):
    """Run the pipeline and return parsed output."""
    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix='.json')
        os.close(fd)

    cmd = ['python3', PIPELINE_PATH, '--config', CONFIG_PATH, '--output', output_path]
    hr_str = ','.join(str(r) for r in harvested_rows) if harvested_rows else ''
    cmd.extend(['--harvested-rows', hr_str])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, f"Pipeline failed (exit {result.returncode}): {result.stderr}"

    with open(output_path) as f:
        data = json.load(f)
    os.unlink(output_path)
    return data


def compute_expected_route(bx, by, rx, ry, noc_id, W=10, H=12):
    """Independently compute the correct NoC route from bank to reader."""
    links = []
    cx, cy = bx, by
    if noc_id == 0:
        while cx != rx:
            nx = (cx + 1) % W
            links.append([[cx, cy], [nx, cy]])
            cx = nx
        while cy != ry:
            ny = (cy + 1) % H
            links.append([[cx, cy], [cx, ny]])
            cy = ny
    else:
        while cx != rx:
            nx = (cx - 1) % W
            links.append([[cx, cy], [nx, cy]])
            cx = nx
        while cy != ry:
            ny = (cy - 1) % H
            links.append([[cx, cy], [cx, ny]])
            cy = ny
    return links


def get_available_tiles(config, harvested_rows):
    tiles = set()
    for x in config['t_tile_columns']:
        for y in config['t_tile_rows']:
            if y not in harvested_rows:
                tiles.add((x, y))
    return tiles


def verify_valid_placement(output, config, harvested_rows):
    """Verify all placement constraints are satisfied."""
    available = get_available_tiles(config, set(harvested_rows or []))
    placed = set()
    bank_ids = set()

    for p in output['placements']:
        tile = (p['reader_x'], p['reader_y'])
        assert tile in available, f"Reader for bank {p['bank_id']} at {tile} is not a valid available T-tile"
        assert tile not in placed, f"Duplicate reader placement at {tile}"
        placed.add(tile)
        bank_ids.add(p['bank_id'])
        assert p['noc_id'] in [0, 1], f"Invalid noc_id: {p['noc_id']}"
        assert p['vc'] in [0, 1], f"Invalid vc: {p['vc']}"

        if harvested_rows:
            assert p['reader_y'] not in harvested_rows, \
                f"Reader for bank {p['bank_id']} placed in harvested row {p['reader_y']}"

    assert bank_ids == set(range(12)), f"Missing banks: {set(range(12)) - bank_ids}"


def recompute_link_loads(output):
    """Independently recompute link loads from routes."""
    link_loads = defaultdict(int)
    noc_map = {p['bank_id']: p['noc_id'] for p in output['placements']}

    for r in output['routes']:
        noc = noc_map[r['bank_id']]
        for link in r['links']:
            key = (noc, tuple(tuple(p) for p in link))
            link_loads[key] += 1

    return link_loads


# ---- Simulator Fix Tests ----

class TestSimulatorFix:
    """Verify the C simulator was correctly debugged and compiled."""

    def test_simulator_compiled(self):
        output = run_pipeline()
        assert output['simulator_validation']['compiled'] is True

    def test_bugs_identified_and_fixed(self):
        output = run_pipeline()
        assert len(output['simulator_validation']['bugs_fixed']) >= 2, \
            f"Expected at least 2 bug fixes, got: {output['simulator_validation']['bugs_fixed']}"

    def test_simulator_binary_exists(self):
        run_pipeline()
        assert os.path.exists('/app/noc_sim'), "Compiled simulator binary not found at /app/noc_sim"

    def test_simulator_noc1_routes_westward(self):
        """After fixing, NoC 1 horizontal routing must go west, not east."""
        run_pipeline()
        csv_path = '/tmp/test_noc1_direction.csv'
        with open(csv_path, 'w') as f:
            f.write("bank_id,bank_x,bank_y,reader_x,reader_y,noc_id\n")
            f.write("0,5,0,6,1,1\n")
        result = subprocess.run(['/app/noc_sim', csv_path],
                                capture_output=True, text=True, timeout=10)
        os.unlink(csv_path)
        assert result.returncode == 0, f"Simulator failed: {result.stderr}"
        sim_out = json.loads(result.stdout)
        route = sim_out['routes'][0]
        assert len(route['hops']) > 0, "Route should have hops"
        first_hop = route['hops'][0]
        assert first_hop == [[5, 0], [4, 0]], \
            f"NoC 1 first hop should go west (5->4), got {first_hop}"

    def test_simulator_separates_noc_fabric_loads(self):
        """Links on different NoC fabrics must not interfere."""
        run_pipeline()
        csv_path = '/tmp/test_noc_separation.csv'
        with open(csv_path, 'w') as f:
            f.write("bank_id,bank_x,bank_y,reader_x,reader_y,noc_id\n")
            f.write("0,0,0,1,0,0\n")
            f.write("1,1,0,0,0,1\n")
        result = subprocess.run(['/app/noc_sim', csv_path],
                                capture_output=True, text=True, timeout=10)
        os.unlink(csv_path)
        assert result.returncode == 0
        sim_out = json.loads(result.stdout)
        assert sim_out['max_link_load'] == 1, \
            f"Independent NoC fabrics should not conflict: max_link_load={sim_out['max_link_load']}"

    def test_validation_passed(self):
        output = run_pipeline()
        assert output['simulator_validation']['validation_passed'] is True


# ---- Output Format Tests ----

class TestOutputFormat:
    def test_has_all_top_level_keys(self):
        output = run_pipeline()
        for key in ('placements', 'routes', 'congestion',
                     'estimated_bandwidth_pct', 'simulator_validation', 'firmware'):
            assert key in output, f"Missing top-level key: {key}"

    def test_twelve_placements_with_fields(self):
        output = run_pipeline()
        assert len(output['placements']) == 12
        for p in output['placements']:
            for key in ('bank_id', 'reader_x', 'reader_y', 'noc_id', 'vc'):
                assert key in p, f"Missing placement key '{key}'"

    def test_twelve_routes(self):
        output = run_pipeline()
        assert len(output['routes']) == 12
        for r in output['routes']:
            assert 'bank_id' in r
            assert 'links' in r

    def test_congestion_fields(self):
        output = run_pipeline()
        c = output['congestion']
        for key in ('total_shared_links', 'max_link_load', 'total_excess_load'):
            assert key in c, f"Missing congestion key '{key}'"
            assert isinstance(c[key], int), f"Congestion '{key}' should be int"
        assert c['max_link_load'] >= 1

    def test_simulator_validation_fields(self):
        output = run_pipeline()
        sv = output['simulator_validation']
        for key in ('compiled', 'bugs_fixed', 'validation_passed'):
            assert key in sv, f"Missing simulator_validation key '{key}'"

    def test_firmware_section(self):
        output = run_pipeline()
        assert len(output['firmware']) == 12
        for fw in output['firmware']:
            for key in ('bank_id', 'rct_value_hex', 'asm_file', 'obj_verified'):
                assert key in fw, f"Missing firmware key '{key}'"


# ---- No-Harvest Tests ----

class TestNoHarvest:
    def test_valid_placement(self):
        config = load_config()
        output = run_pipeline()
        verify_valid_placement(output, config, [])

    def test_zero_congestion(self):
        output = run_pipeline()
        assert output['congestion']['max_link_load'] == 1, \
            f"Expected max_link_load=1, got {output['congestion']['max_link_load']}"
        assert output['congestion']['total_shared_links'] == 0
        assert output['congestion']['total_excess_load'] == 0

    def test_full_bandwidth(self):
        output = run_pipeline()
        assert abs(output['estimated_bandwidth_pct'] - 100.0) < 0.01, \
            f"Expected ~100% bandwidth, got {output['estimated_bandwidth_pct']}"


# ---- Route Correctness Tests ----

class TestRouteCorrectness:
    def test_routes_match_noc_rules_no_harvest(self):
        """Each route must exactly follow NoC routing rules."""
        config = load_config()
        output = run_pipeline()
        banks = {b['id']: (b['x'], b['y']) for b in config['dram_banks']}
        W, H = config['grid_width'], config['grid_height']

        for p, r in zip(output['placements'], output['routes']):
            assert p['bank_id'] == r['bank_id']
            bx, by = banks[p['bank_id']]
            expected = compute_expected_route(bx, by, p['reader_x'], p['reader_y'],
                                              p['noc_id'], W, H)
            assert r['links'] == expected, \
                f"Route mismatch for bank {p['bank_id']}: expected {expected}, got {r['links']}"

    def test_routes_match_noc_rules_harvested(self):
        config = load_config()
        output = run_pipeline(harvested_rows=[2, 8])
        banks = {b['id']: (b['x'], b['y']) for b in config['dram_banks']}
        W, H = config['grid_width'], config['grid_height']

        for p, r in zip(output['placements'], output['routes']):
            assert p['bank_id'] == r['bank_id']
            bx, by = banks[p['bank_id']]
            expected = compute_expected_route(bx, by, p['reader_x'], p['reader_y'],
                                              p['noc_id'], W, H)
            assert r['links'] == expected, \
                f"Route mismatch for bank {p['bank_id']} with harvest [2,8]"

    def test_toroidal_wrapping(self):
        """Under extreme harvesting, some routes must wrap around grid edges."""
        config = load_config()
        output = run_pipeline(harvested_rows=[1, 2, 3, 4, 5])
        banks = {b['id']: (b['x'], b['y']) for b in config['dram_banks']}
        W, H = config['grid_width'], config['grid_height']

        for p, r in zip(output['placements'], output['routes']):
            bx, by = banks[p['bank_id']]
            expected = compute_expected_route(bx, by, p['reader_x'], p['reader_y'],
                                              p['noc_id'], W, H)
            assert r['links'] == expected, \
                f"Route mismatch (toroidal) for bank {p['bank_id']}"

        all_links = []
        for r in output['routes']:
            all_links.extend(r['links'])
        has_wrap = any(
            abs(link[0][0] - link[1][0]) > 1 or abs(link[0][1] - link[1][1]) > 1
            for link in all_links
        )
        assert has_wrap, "Expected toroidal wrapping under extreme harvesting"


# ---- Harvesting Tests ----

class TestHarvesting:
    def test_harvest_single_row(self):
        config = load_config()
        output = run_pipeline(harvested_rows=[2])
        verify_valid_placement(output, config, [2])
        assert output['congestion']['max_link_load'] == 1

    def test_harvest_two_rows(self):
        config = load_config()
        output = run_pipeline(harvested_rows=[1, 7])
        verify_valid_placement(output, config, [1, 7])
        assert output['congestion']['max_link_load'] <= 2

    def test_extreme_harvest(self):
        config = load_config()
        output = run_pipeline(harvested_rows=[1, 2, 3, 4, 5])
        verify_valid_placement(output, config, [1, 2, 3, 4, 5])
        assert output['congestion']['max_link_load'] <= 2, \
            f"Congestion too high: max_link_load={output['congestion']['max_link_load']}"
        assert output['estimated_bandwidth_pct'] >= 90.0, \
            f"Bandwidth too low: {output['estimated_bandwidth_pct']}%"

    def test_harvest_near_dram(self):
        config = load_config()
        output = run_pipeline(harvested_rows=[2, 4, 8, 10])
        verify_valid_placement(output, config, [2, 4, 8, 10])
        assert output['congestion']['max_link_load'] <= 2


# ---- VC Assignment Tests ----

class TestVCAssignment:
    def test_vc_values_valid(self):
        output = run_pipeline()
        for p in output['placements']:
            assert p['vc'] in [0, 1], f"Invalid VC {p['vc']} for bank {p['bank_id']}"

    def test_same_row_same_noc_different_vc(self):
        output = run_pipeline()
        row_noc_vc = defaultdict(list)
        for p in output['placements']:
            key = (p['reader_y'], p['noc_id'])
            row_noc_vc[key].append((p['bank_id'], p['vc']))

        for (row, noc), entries in row_noc_vc.items():
            if len(entries) > 1:
                vcs = [vc for _, vc in entries]
                assert len(set(vcs)) == len(vcs), \
                    f"VC conflict in row {row}, noc {noc}: {entries}"

    def test_vc_constraint_under_harvesting(self):
        output = run_pipeline(harvested_rows=[1, 7])
        row_noc_vc = defaultdict(list)
        for p in output['placements']:
            key = (p['reader_y'], p['noc_id'])
            row_noc_vc[key].append((p['bank_id'], p['vc']))

        for (row, noc), entries in row_noc_vc.items():
            if len(entries) > 1:
                vcs = [vc for _, vc in entries]
                assert len(set(vcs)) == len(vcs), \
                    f"VC conflict in row {row}, noc {noc}: {entries}"


# ---- Bandwidth Consistency Tests ----

class TestBandwidth:
    def test_bandwidth_formula_consistency(self):
        config = load_config()
        output = run_pipeline(harvested_rows=[1, 2])
        per_bank_bw = config['per_bank_bandwidth_gbps']
        noc_link_bw = config['noc_link_bandwidth_gbps']

        link_loads = recompute_link_loads(output)
        noc_map = {p['bank_id']: p['noc_id'] for p in output['placements']}

        total_eff = 0.0
        for r in output['routes']:
            noc = noc_map[r['bank_id']]
            if not r['links']:
                max_load = 1
            else:
                max_load = max(
                    link_loads[(noc, tuple(tuple(p) for p in link))]
                    for link in r['links']
                )
            eff = min(per_bank_bw, noc_link_bw / max_load)
            total_eff += eff

        expected_pct = total_eff / (12 * per_bank_bw) * 100
        assert abs(output['estimated_bandwidth_pct'] - round(expected_pct, 2)) < 0.02, \
            f"Bandwidth mismatch: got {output['estimated_bandwidth_pct']}, computed {expected_pct}"

    def test_bandwidth_range(self):
        output = run_pipeline(harvested_rows=[1, 2, 3, 4, 5])
        assert 0 < output['estimated_bandwidth_pct'] <= 100.0

    def test_congestion_metrics_consistent(self):
        output = run_pipeline(harvested_rows=[3, 9])
        link_loads = recompute_link_loads(output)

        expected_max = max(link_loads.values()) if link_loads else 1
        expected_shared = sum(1 for v in link_loads.values() if v > 1)
        expected_excess = sum(v - 1 for v in link_loads.values() if v > 1)

        assert output['congestion']['max_link_load'] == expected_max, \
            f"max_link_load: got {output['congestion']['max_link_load']}, expected {expected_max}"
        assert output['congestion']['total_shared_links'] == expected_shared
        assert output['congestion']['total_excess_load'] == expected_excess


# ---- Firmware Tests ----

class TestFirmware:
    """Verify RISC-V firmware generation, cross-assembly, and encoding."""

    def test_twelve_firmware_entries(self):
        output = run_pipeline()
        assert len(output['firmware']) == 12
        bids = {fw['bank_id'] for fw in output['firmware']}
        assert bids == set(range(12))

    def test_asm_files_exist(self):
        output = run_pipeline()
        for fw in output['firmware']:
            assert os.path.exists(fw['asm_file']), \
                f"Missing ASM file: {fw['asm_file']}"

    def test_obj_files_exist(self):
        output = run_pipeline()
        for fw in output['firmware']:
            obj_path = fw['asm_file'].replace('.s', '.o')
            assert os.path.exists(obj_path), \
                f"Missing object file: {obj_path}"

    def test_objdump_shows_sw_instructions(self):
        """Cross-assembled firmware must contain sw (store word) instructions."""
        output = run_pipeline()
        for fw in output['firmware']:
            obj_path = fw['asm_file'].replace('.s', '.o')
            result = subprocess.run(
                ['riscv64-linux-gnu-objdump', '-d', obj_path],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"objdump failed for bank {fw['bank_id']}"
            assert 'sw' in result.stdout, \
                f"No sw instruction in firmware for bank {fw['bank_id']}"

    def test_objdump_shows_lui_instruction(self):
        """Firmware must use lui to load register base address."""
        output = run_pipeline()
        for fw in output['firmware']:
            obj_path = fw['asm_file'].replace('.s', '.o')
            result = subprocess.run(
                ['riscv64-linux-gnu-objdump', '-d', obj_path],
                capture_output=True, text=True
            )
            assert 'lui' in result.stdout, \
                f"No lui instruction in firmware for bank {fw['bank_id']}"

    def test_rct_encoding_target_coordinates(self):
        """RCT value must encode the correct DRAM bank tile coordinates."""
        config = load_config()
        output = run_pipeline()
        banks = {b['id']: (b['x'], b['y']) for b in config['dram_banks']}

        for fw in output['firmware']:
            bid = fw['bank_id']
            bx, by = banks[bid]
            rct_val = int(fw['rct_value_hex'], 16)
            low32 = rct_val & 0xFFFFFFFF

            target_x = low32 & 0x3F
            target_y = (low32 >> 6) & 0x3F

            assert target_x == bx, \
                f"Bank {bid}: RCT target_x={target_x}, expected {bx}"
            assert target_y == by, \
                f"Bank {bid}: RCT target_y={target_y}, expected {by}"

    def test_rct_encoding_noc_vc_enable(self):
        """RCT value must encode correct NoC selection, VC, and enable bit."""
        output = run_pipeline()
        placement_map = {p['bank_id']: p for p in output['placements']}

        for fw in output['firmware']:
            bid = fw['bank_id']
            p = placement_map[bid]
            rct_val = int(fw['rct_value_hex'], 16)
            low32 = rct_val & 0xFFFFFFFF

            enable = (low32 >> 31) & 1
            noc_sel = (low32 >> 12) & 1
            vc = (low32 >> 13) & 3

            assert enable == 1, f"Bank {bid}: enable bit not set"
            assert noc_sel == p['noc_id'], \
                f"Bank {bid}: RCT noc_sel={noc_sel}, placement noc_id={p['noc_id']}"
            assert vc == p['vc'], \
                f"Bank {bid}: RCT vc={vc}, placement vc={p['vc']}"

    def test_all_firmware_verified(self):
        output = run_pipeline()
        for fw in output['firmware']:
            assert fw['obj_verified'] is True, \
                f"Bank {fw['bank_id']} firmware not verified by objdump"

    def test_rct_hex_format(self):
        """RCT value hex must be 16-char zero-padded."""
        output = run_pipeline()
        for fw in output['firmware']:
            hex_val = fw['rct_value_hex']
            assert len(hex_val) == 16, \
                f"Bank {fw['bank_id']}: rct_value_hex length={len(hex_val)}, expected 16"
            assert all(c in '0123456789abcdef' for c in hex_val), \
                f"Bank {fw['bank_id']}: rct_value_hex contains invalid chars"


# ---- Multi-Scenario Validation ----

class TestMultipleScenarios:
    @pytest.mark.parametrize("harvested", [
        [],
        [2],
        [1, 7],
        [3, 9],
        [1, 2, 3],
        [2, 4, 8, 10],
        [1, 2, 3, 4, 5],
    ])
    def test_always_valid(self, harvested):
        config = load_config()
        output = run_pipeline(harvested_rows=harvested)
        verify_valid_placement(output, config, harvested)

        assert output['estimated_bandwidth_pct'] > 0
        assert output['estimated_bandwidth_pct'] <= 100.0
        assert output['congestion']['max_link_load'] <= 3, \
            f"max_link_load={output['congestion']['max_link_load']} for harvest={harvested}"
        assert output['simulator_validation']['validation_passed'] is True
