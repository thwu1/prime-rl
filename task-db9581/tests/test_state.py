
import json
import struct
import zlib
import os


FLASH_DUMP_PATH = '/app/flash_dump.bin'
RESULTS_DIR = '/app/results'


def _parse_flash_dump():
    """Reference parser for the flash dump binary."""
    with open(FLASH_DUMP_PATH, 'rb') as f:
        data = f.read()

    magic, version, page_size, ppb, total_blocks, jcount, pcount, tbw, mfg_ts, cur_ts = \
        struct.unpack_from('<IHHHHIIQII', data, 0)
    assert magic == 0x464C5348, f"Bad magic: {hex(magic)}"

    block_size = page_size * ppb
    offset = 64

    # Block mapping table
    block_mapping = {}
    for _ in range(total_blocks):
        l, p = struct.unpack_from('<HH', data, offset)
        block_mapping[l] = p
        offset += 4

    # Erase count table
    erase_counts = []
    for _ in range(total_blocks):
        ec, = struct.unpack_from('<I', data, offset)
        erase_counts.append(ec)
        offset += 4

    # Journal
    corrupt_count = 0
    valid_writes = []
    write_heat = [0] * total_blocks
    process_bytes = {}

    for _ in range(jcount):
        prefix = data[offset:offset + 24]
        stored_crc, _ = struct.unpack_from('<II', data, offset + 24)
        computed_crc = zlib.crc32(prefix) & 0xFFFFFFFF

        if stored_crc != computed_crc:
            corrupt_count += 1
            offset += 32
            continue

        ts, lb, sp, pc, pid, flags, dh = struct.unpack_from('<IHHHHIQ', prefix)

        if flags == 0:  # write
            valid_writes.append((lb, sp, pc, pid))
            write_heat[lb] += pc
            process_bytes[pid] = process_bytes.get(pid, 0) + pc * page_size

        offset += 32

    # Process table
    processes = {}
    for _ in range(pcount):
        pid, _ = struct.unpack_from('<HH', data, offset)
        name = data[offset + 4:offset + 68].split(b'\x00')[0].decode('ascii')
        processes[pid] = name
        offset += 68

    return {
        'page_size': page_size,
        'pages_per_block': ppb,
        'total_blocks': total_blocks,
        'block_size': block_size,
        'tbw_rating': tbw,
        'manufacture_ts': mfg_ts,
        'current_ts': cur_ts,
        'block_mapping': block_mapping,
        'erase_counts': erase_counts,
        'corrupt_count': corrupt_count,
        'valid_writes': valid_writes,
        'write_heat': write_heat,
        'process_bytes': process_bytes,
        'processes': processes,
    }


def _compute_expected(p):
    """Compute expected results from parsed data."""
    page_size = p['page_size']
    total_blocks = p['total_blocks']
    block_size = p['block_size']
    erase_counts = p['erase_counts']

    total_host_writes = sum(pc * page_size for _, _, pc, _ in p['valid_writes'])
    total_nand_erase = sum(erase_counts) * block_size
    waf = total_nand_erase / total_host_writes if total_host_writes else 0.0

    elapsed_sec = p['current_ts'] - p['manufacture_ts']
    elapsed_days_float = elapsed_sec / 86400.0
    elapsed_days = int(elapsed_days_float)

    daily_nand = total_nand_erase / elapsed_days_float if elapsed_days_float > 0 else 0.0
    remaining = int((p['tbw_rating'] - total_nand_erase) / daily_nand) if daily_nand > 0 else 0

    summary = {
        'corrupt_entries': p['corrupt_count'],
        'valid_write_entries': len(p['valid_writes']),
        'total_host_writes_bytes': total_host_writes,
        'total_nand_erase_bytes': total_nand_erase,
        'write_amplification_factor': round(waf, 6),
        'elapsed_days': elapsed_days,
        'remaining_lifetime_days': remaining,
        'max_erase_count': max(erase_counts),
        'min_erase_count': min(erase_counts),
        'mean_erase_count': round(sum(erase_counts) / len(erase_counts), 2),
    }

    # Process writes sorted by bytes desc, pid asc
    pw_list = []
    for pid in sorted(p['process_bytes'].keys(), key=lambda x: (-p['process_bytes'][x], x)):
        pw_list.append({
            'pid': pid,
            'name': p['processes'].get(pid, f'unknown-{pid}'),
            'bytes_written': p['process_bytes'][pid],
        })

    # Hot blocks
    hot_blocks = sorted(
        [{'physical_block': i, 'erase_count': erase_counts[i]} for i in range(total_blocks)],
        key=lambda x: (-x['erase_count'], x['physical_block'])
    )[:20]

    # Current mapping cost
    write_heat = p['write_heat']
    bm = p['block_mapping']
    current_costs = [erase_counts[bm[l]] + write_heat[l] for l in range(total_blocks)]
    current_max = max(current_costs)

    # Optimized mapping (minimax assignment)
    logical_sorted = sorted(range(total_blocks), key=lambda l: -write_heat[l])
    physical_sorted = sorted(range(total_blocks), key=lambda pb: erase_counts[pb])
    opt_mapping = [0] * total_blocks
    for i, l in enumerate(logical_sorted):
        opt_mapping[l] = physical_sorted[i]
    projected_max = max(erase_counts[opt_mapping[l]] + write_heat[l] for l in range(total_blocks))

    return {
        'summary': summary,
        'process_writes': pw_list,
        'hot_blocks': hot_blocks,
        'optimized': {
            'projected_max_total': projected_max,
            'current_max_total': current_max,
        },
        'write_heat': write_heat,
        'erase_counts': erase_counts,
        'total_blocks': total_blocks,
    }


# Module-level computation (runs once at import)
_PARSED = _parse_flash_dump()
_EXPECTED = _compute_expected(_PARSED)


def _load_result(name):
    path = os.path.join(RESULTS_DIR, name)
    assert os.path.exists(path), f"Missing output file: {path}"
    with open(path) as f:
        return json.load(f)


# ──────────────────────────── summary.json ────────────────────────────


class TestSummary:

    def test_file_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, 'summary.json'))

    def test_corrupt_entries(self):
        r = _load_result('summary.json')
        assert r['corrupt_entries'] == _EXPECTED['summary']['corrupt_entries']

    def test_valid_write_entries(self):
        r = _load_result('summary.json')
        assert r['valid_write_entries'] == _EXPECTED['summary']['valid_write_entries']

    def test_total_host_writes_bytes(self):
        r = _load_result('summary.json')
        assert r['total_host_writes_bytes'] == _EXPECTED['summary']['total_host_writes_bytes']

    def test_total_nand_erase_bytes(self):
        r = _load_result('summary.json')
        assert r['total_nand_erase_bytes'] == _EXPECTED['summary']['total_nand_erase_bytes']

    def test_write_amplification_factor(self):
        r = _load_result('summary.json')
        assert abs(r['write_amplification_factor'] - _EXPECTED['summary']['write_amplification_factor']) < 0.001

    def test_elapsed_days(self):
        r = _load_result('summary.json')
        assert r['elapsed_days'] == _EXPECTED['summary']['elapsed_days']

    def test_remaining_lifetime_days(self):
        r = _load_result('summary.json')
        assert r['remaining_lifetime_days'] == _EXPECTED['summary']['remaining_lifetime_days']

    def test_max_erase_count(self):
        r = _load_result('summary.json')
        assert r['max_erase_count'] == _EXPECTED['summary']['max_erase_count']

    def test_min_erase_count(self):
        r = _load_result('summary.json')
        assert r['min_erase_count'] == _EXPECTED['summary']['min_erase_count']

    def test_mean_erase_count(self):
        r = _load_result('summary.json')
        assert abs(r['mean_erase_count'] - _EXPECTED['summary']['mean_erase_count']) < 0.1


# ──────────────────────── process_writes.json ─────────────────────────


class TestProcessWrites:

    def test_file_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, 'process_writes.json'))

    def test_entry_count(self):
        r = _load_result('process_writes.json')
        assert len(r) == len(_EXPECTED['process_writes'])

    def test_pids_and_bytes(self):
        r = _load_result('process_writes.json')
        expected = _EXPECTED['process_writes']
        for actual, exp in zip(r, expected):
            assert actual['pid'] == exp['pid'], \
                f"PID mismatch: got {actual['pid']}, expected {exp['pid']}"
            assert actual['bytes_written'] == exp['bytes_written'], \
                f"bytes_written mismatch for PID {exp['pid']}: got {actual['bytes_written']}, expected {exp['bytes_written']}"

    def test_sorted_descending(self):
        r = _load_result('process_writes.json')
        for i in range(len(r) - 1):
            assert r[i]['bytes_written'] >= r[i + 1]['bytes_written'], \
                f"Not sorted at index {i}: {r[i]['bytes_written']} < {r[i+1]['bytes_written']}"

    def test_names_present(self):
        r = _load_result('process_writes.json')
        for entry in r:
            assert 'name' in entry and isinstance(entry['name'], str) and len(entry['name']) > 0


# ──────────────────────── hot_blocks.json ─────────────────────────────


class TestHotBlocks:

    def test_file_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, 'hot_blocks.json'))

    def test_count(self):
        r = _load_result('hot_blocks.json')
        assert len(r) == 20

    def test_values(self):
        r = _load_result('hot_blocks.json')
        expected = _EXPECTED['hot_blocks']
        for actual, exp in zip(r, expected):
            assert actual['physical_block'] == exp['physical_block'], \
                f"Block mismatch: got {actual['physical_block']}, expected {exp['physical_block']}"
            assert actual['erase_count'] == exp['erase_count'], \
                f"Erase count mismatch for block {exp['physical_block']}"

    def test_sorted_descending(self):
        r = _load_result('hot_blocks.json')
        for i in range(len(r) - 1):
            assert r[i]['erase_count'] >= r[i + 1]['erase_count']


# ──────────────────── optimized_mapping.json ──────────────────────────


class TestOptimizedMapping:

    def test_file_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, 'optimized_mapping.json'))

    def test_mapping_is_permutation(self):
        r = _load_result('optimized_mapping.json')
        mapping = r['mapping']
        n = _EXPECTED['total_blocks']
        assert len(mapping) == n, f"Mapping length {len(mapping)} != {n}"
        assert sorted(mapping) == list(range(n)), "Mapping is not a valid permutation"

    def test_projected_max_consistent(self):
        """Verify projected_max_total is correctly computed from the mapping."""
        r = _load_result('optimized_mapping.json')
        mapping = r['mapping']
        wh = _EXPECTED['write_heat']
        ec = _EXPECTED['erase_counts']
        n = _EXPECTED['total_blocks']
        actual_max = max(ec[mapping[l]] + wh[l] for l in range(n))
        assert r['projected_max_total'] == actual_max, \
            f"projected_max_total {r['projected_max_total']} != computed {actual_max}"

    def test_current_max_correct(self):
        r = _load_result('optimized_mapping.json')
        assert r['current_max_total'] == _EXPECTED['optimized']['current_max_total'], \
            f"current_max_total {r['current_max_total']} != expected {_EXPECTED['optimized']['current_max_total']}"

    def test_improvement(self):
        """Optimized mapping should not be worse than current."""
        r = _load_result('optimized_mapping.json')
        assert r['projected_max_total'] <= r['current_max_total'], \
            f"No improvement: projected {r['projected_max_total']} > current {r['current_max_total']}"

    def test_optimality(self):
        """Verify the mapping achieves the optimal projected_max_total."""
        r = _load_result('optimized_mapping.json')
        assert r['projected_max_total'] <= _EXPECTED['optimized']['projected_max_total'], \
            f"Sub-optimal: {r['projected_max_total']} > reference optimal {_EXPECTED['optimized']['projected_max_total']}"
