
import pytest
import subprocess
import os
import csv
import io
import struct
import sqlite3 as sqlite3_mod
import glob


PROFILE_HEADERS = [
    'policytc_id', 'calcrule_id', 'deductible_1', 'deductible_2',
    'deductible_3', 'attachment_1', 'limit_1', 'share_1', 'share_2', 'share_3'
]
PROGRAMME_HEADERS = ['from_agg_id', 'level_id', 'to_agg_id']
POLICYTC_HEADERS = ['layer_id', 'level_id', 'agg_id', 'policytc_id']
XREF_HEADERS = ['output_id', 'agg_id', 'layer_id']
GUL_HEADER = 'event_id,item_id,sidx,loss\n'


def write_csv(filepath, headers, rows):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)


def run_fmcalc(input_dir, gul_csv, alloc_rule=0, net=False, timeout=60):
    cmd = ['python3', '/app/fmcalc.py', '-p', input_dir]
    if alloc_rule != 0:
        cmd.extend(['-a', str(alloc_rule)])
    if net:
        cmd.append('-n')
    result = subprocess.run(
        cmd, input=gul_csv, capture_output=True, text=True, timeout=timeout
    )
    assert result.returncode == 0, (
        f"fmcalc failed with exit code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return result.stdout


def parse_output(output_csv):
    reader = csv.DictReader(io.StringIO(output_csv))
    results = []
    for row in reader:
        results.append((
            int(row['event_id']),
            int(row['output_id']),
            int(row['sidx']),
            float(row['loss'])
        ))
    return sorted(results, key=lambda r: (r[0], r[1], r[2]))


def assert_results(actual, expected, tol=0.01):
    assert len(actual) == len(expected), (
        f"Row count mismatch: got {len(actual)}, expected {len(expected)}.\n"
        f"Actual: {actual}\nExpected: {expected}"
    )
    for i, (a, e) in enumerate(zip(actual, expected)):
        assert a[0] == e[0] and a[1] == e[1] and a[2] == e[2], (
            f"Row {i} key mismatch: got ({a[0]},{a[1]},{a[2]}), "
            f"expected ({e[0]},{e[1]},{e[2]})"
        )
        assert abs(a[3] - e[3]) < tol, (
            f"Row {i} loss mismatch for (event={a[0]}, output={a[1]}, sidx={a[2]}): "
            f"got {a[3]}, expected {e[3]}"
        )


def make_profile_row(ptc_id, calcrule, d1=0, d2=0, d3=0, a1=0, l1=0,
                     sh1=0, sh2=0, sh3=0):
    return (ptc_id, calcrule, d1, d2, d3, a1, l1, sh1, sh2, sh3)


class TestSimpleDedLimit:
    """Calcrule 1: deductible and limit, single level, alloc=0"""

    def test_single_level(self, tmp_path):
        d = str(tmp_path / 'test1')
        write_csv(f'{d}/fm_programme.csv', PROGRAMME_HEADERS,
                  [(1, 1, 1), (2, 1, 1), (3, 1, 2)])
        write_csv(f'{d}/fm_profile.csv', PROFILE_HEADERS, [
            make_profile_row(1, 1, d1=10000, l1=100000),
            make_profile_row(2, 1, d1=500, l1=5000),
        ])
        write_csv(f'{d}/fm_policytc.csv', POLICYTC_HEADERS,
                  [(1, 1, 1, 1), (1, 1, 2, 2)])
        write_csv(f'{d}/fm_xref.csv', XREF_HEADERS,
                  [(1, 1, 1), (2, 2, 1)])

        gul = GUL_HEADER + (
            '1,1,1,100000.0\n'
            '1,2,1,50000.0\n'
            '1,3,1,2000.0\n'
        )

        output = run_fmcalc(d, gul)
        results = parse_output(output)
        expected = [(1, 1, 1, 100000.0), (1, 2, 1, 1500.0)]
        assert_results(results, expected)


class TestTwoLevelHierarchy:
    """Calcrules 1, 12, 2 across two levels"""

    def test_two_levels(self, tmp_path):
        d = str(tmp_path / 'test2')
        write_csv(f'{d}/fm_programme.csv', PROGRAMME_HEADERS, [
            (1, 1, 1), (2, 1, 1), (3, 1, 2),
            (1, 2, 1), (2, 2, 1),
        ])
        write_csv(f'{d}/fm_profile.csv', PROFILE_HEADERS, [
            make_profile_row(1, 1, d1=10000, l1=200000),
            make_profile_row(2, 12, d1=500),
            make_profile_row(3, 2, a1=5000, l1=80000, sh1=0.5),
        ])
        write_csv(f'{d}/fm_policytc.csv', POLICYTC_HEADERS, [
            (1, 1, 1, 1), (1, 1, 2, 2), (1, 2, 1, 3),
        ])
        write_csv(f'{d}/fm_xref.csv', XREF_HEADERS, [(1, 1, 1)])

        gul = GUL_HEADER + (
            '1,1,1,100000.0\n'
            '1,2,1,50000.0\n'
            '1,3,1,2000.0\n'
        )

        output = run_fmcalc(d, gul)
        results = parse_output(output)
        expected = [(1, 1, 1, 40000.0)]
        assert_results(results, expected)


class TestMultiLayerExcess:
    """Calcrule 2 with two excess layers"""

    def test_two_layers(self, tmp_path):
        d = str(tmp_path / 'test3')
        write_csv(f'{d}/fm_programme.csv', PROGRAMME_HEADERS, [(1, 1, 1)])
        write_csv(f'{d}/fm_profile.csv', PROFILE_HEADERS, [
            make_profile_row(1, 2, a1=0, l1=50000, sh1=1.0),
            make_profile_row(2, 2, a1=50000, l1=50000, sh1=1.0),
        ])
        write_csv(f'{d}/fm_policytc.csv', POLICYTC_HEADERS, [
            (1, 1, 1, 1), (2, 1, 1, 2),
        ])
        write_csv(f'{d}/fm_xref.csv', XREF_HEADERS, [
            (1, 1, 1), (2, 1, 2),
        ])

        gul = GUL_HEADER + '1,1,1,80000.0\n'

        output = run_fmcalc(d, gul)
        results = parse_output(output)
        expected = [(1, 1, 1, 50000.0), (1, 2, 1, 30000.0)]
        assert_results(results, expected)


class TestReinsurancePipeline:
    """Calcrules 1 and 25, piped, net loss"""

    def test_quota_share_net(self, tmp_path):
        d_direct = str(tmp_path / 'direct')
        d_ri = str(tmp_path / 'ri1')

        write_csv(f'{d_direct}/fm_programme.csv', PROGRAMME_HEADERS,
                  [(1, 1, 1)])
        write_csv(f'{d_direct}/fm_profile.csv', PROFILE_HEADERS, [
            make_profile_row(1, 1, d1=10000, l1=500000),
        ])
        write_csv(f'{d_direct}/fm_policytc.csv', POLICYTC_HEADERS,
                  [(1, 1, 1, 1)])
        write_csv(f'{d_direct}/fm_xref.csv', XREF_HEADERS, [(1, 1, 1)])

        write_csv(f'{d_ri}/fm_programme.csv', PROGRAMME_HEADERS,
                  [(1, 1, 1)])
        write_csv(f'{d_ri}/fm_profile.csv', PROFILE_HEADERS, [
            make_profile_row(1, 25, sh1=0.5, sh2=1.0, sh3=1.0),
        ])
        write_csv(f'{d_ri}/fm_policytc.csv', POLICYTC_HEADERS,
                  [(1, 1, 1, 1)])
        write_csv(f'{d_ri}/fm_xref.csv', XREF_HEADERS, [(1, 1, 1)])

        gul = GUL_HEADER + '1,1,1,200000.0\n'

        direct_output = run_fmcalc(d_direct, gul)
        direct_results = parse_output(direct_output)
        assert_results(direct_results, [(1, 1, 1, 190000.0)])

        ri_output = run_fmcalc(d_ri, direct_output, net=True)
        ri_results = parse_output(ri_output)
        assert_results(ri_results, [(1, 1, 1, 95000.0)])


class TestBackAllocation:
    """Calcrule 14 with alloc rule 1 (proportional to input)"""

    def test_alloc_rule_1(self, tmp_path):
        d = str(tmp_path / 'test5')
        write_csv(f'{d}/fm_programme.csv', PROGRAMME_HEADERS,
                  [(1, 1, 1), (2, 1, 1)])
        write_csv(f'{d}/fm_profile.csv', PROFILE_HEADERS, [
            make_profile_row(1, 14, l1=100000),
        ])
        write_csv(f'{d}/fm_policytc.csv', POLICYTC_HEADERS,
                  [(1, 1, 1, 1)])
        write_csv(f'{d}/fm_xref.csv', XREF_HEADERS, [
            (1, 1, 1), (2, 2, 1),
        ])

        gul = GUL_HEADER + '1,1,1,80000.0\n1,2,1,120000.0\n'

        output = run_fmcalc(d, gul, alloc_rule=1)
        results = parse_output(output)
        expected = [(1, 1, 1, 40000.0), (1, 2, 1, 60000.0)]
        assert_results(results, expected)


class TestMultiEventSample:
    """Calcrules 3 (franchise) and 16 (ded % loss), multiple events/samples"""

    def test_multi_event_multi_sample(self, tmp_path):
        d = str(tmp_path / 'test6')
        write_csv(f'{d}/fm_programme.csv', PROGRAMME_HEADERS,
                  [(1, 1, 1), (2, 1, 2)])
        write_csv(f'{d}/fm_profile.csv', PROFILE_HEADERS, [
            make_profile_row(1, 3, d1=50000, l1=500000),
            make_profile_row(2, 16, d1=0.1),
        ])
        write_csv(f'{d}/fm_policytc.csv', POLICYTC_HEADERS,
                  [(1, 1, 1, 1), (1, 1, 2, 2)])
        write_csv(f'{d}/fm_xref.csv', XREF_HEADERS, [
            (1, 1, 1), (2, 2, 1),
        ])

        gul = GUL_HEADER + (
            '1,1,1,30000.0\n'
            '1,1,2,80000.0\n'
            '1,2,1,200000.0\n'
            '1,2,2,150000.0\n'
            '2,1,1,60000.0\n'
            '2,2,1,100000.0\n'
        )

        output = run_fmcalc(d, gul)
        results = parse_output(output)
        expected = [
            (1, 1, 1, 0.0),
            (1, 1, 2, 80000.0),
            (1, 2, 1, 180000.0),
            (1, 2, 2, 135000.0),
            (2, 1, 1, 60000.0),
            (2, 2, 1, 90000.0),
        ]
        assert_results(results, expected)


class TestReinsuranceExcess:
    """Calcrule 24: reinsurance excess terms"""

    def test_calcrule_24(self, tmp_path):
        d = str(tmp_path / 'test7')
        write_csv(f'{d}/fm_programme.csv', PROGRAMME_HEADERS, [(1, 1, 1)])
        write_csv(f'{d}/fm_profile.csv', PROFILE_HEADERS, [
            make_profile_row(1, 24, a1=100000, l1=200000,
                             sh1=1.0, sh2=0.9, sh3=1.0),
        ])
        write_csv(f'{d}/fm_policytc.csv', POLICYTC_HEADERS,
                  [(1, 1, 1, 1)])
        write_csv(f'{d}/fm_xref.csv', XREF_HEADERS, [(1, 1, 1)])

        gul = GUL_HEADER + '1,1,1,250000.0\n'

        output = run_fmcalc(d, gul)
        results = parse_output(output)
        expected = [(1, 1, 1, 135000.0)]
        assert_results(results, expected)


class TestAdditionalCalcrules:
    """Calcrules 5, 20, 22 in one scenario"""

    def test_calcrules_5_20_22(self, tmp_path):
        d = str(tmp_path / 'test8')
        write_csv(f'{d}/fm_programme.csv', PROGRAMME_HEADERS, [
            (1, 1, 1), (2, 1, 2), (3, 1, 3),
        ])
        write_csv(f'{d}/fm_profile.csv', PROFILE_HEADERS, [
            make_profile_row(1, 5, d1=0.1, l1=0.3),
            make_profile_row(2, 20, d1=100000),
            make_profile_row(3, 22, l1=200000, sh1=0.8, sh2=0.9, sh3=1.0),
        ])
        write_csv(f'{d}/fm_policytc.csv', POLICYTC_HEADERS, [
            (1, 1, 1, 1), (1, 1, 2, 2), (1, 1, 3, 3),
        ])
        write_csv(f'{d}/fm_xref.csv', XREF_HEADERS, [
            (1, 1, 1), (2, 2, 1), (3, 3, 1),
        ])

        gul = GUL_HEADER + (
            '1,1,1,100000.0\n'
            '1,2,1,50000.0\n'
            '1,2,2,150000.0\n'
            '1,3,1,300000.0\n'
        )

        output = run_fmcalc(d, gul)
        results = parse_output(output)

        expected = [
            (1, 1, 1, 30000.0),
            (1, 2, 1, 50000.0),
            (1, 2, 2, 0.0),
            (1, 3, 1, 180000.0),
        ]
        assert_results(results, expected)


# --- Binary format tests ---


class TestBinaryRoundTrip:
    """fmtobin -> fmtocsv round-trip must preserve data values"""

    def test_roundtrip_item_id(self):
        csv_input = (
            'event_id,item_id,sidx,loss\n'
            '1,1,1,100000.0\n'
            '1,1,2,75000.0\n'
            '1,2,1,50000.0\n'
            '2,1,1,30000.0\n'
            '2,3,1,200000.0\n'
        )

        p1 = subprocess.Popen(
            ['python3', '/app/fmtobin.py'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )
        p2 = subprocess.Popen(
            ['python3', '/app/fmtocsv.py'],
            stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        p1.stdout.close()
        p1.stdin.write(csv_input.encode())
        p1.stdin.close()
        output, stderr = p2.communicate(timeout=30)

        assert p1.wait() == 0, "fmtobin failed"
        assert p2.returncode == 0, f"fmtocsv failed: {stderr.decode()}"

        reader = csv.DictReader(io.StringIO(output.decode()))
        results = []
        for row in reader:
            item_col = 'output_id' if 'output_id' in row else 'item_id'
            results.append((
                int(row['event_id']),
                int(row[item_col]),
                int(row['sidx']),
                float(row['loss'])
            ))
        results.sort(key=lambda r: (r[0], r[1], r[2]))

        expected = [
            (1, 1, 1, 100000.0),
            (1, 1, 2, 75000.0),
            (1, 2, 1, 50000.0),
            (2, 1, 1, 30000.0),
            (2, 3, 1, 200000.0),
        ]
        assert_results(results, expected)

    def test_roundtrip_output_id(self):
        csv_input = (
            'event_id,output_id,sidx,loss\n'
            '1,10,1,55555.55\n'
            '1,20,1,33333.33\n'
        )

        p1 = subprocess.Popen(
            ['python3', '/app/fmtobin.py'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )
        p2 = subprocess.Popen(
            ['python3', '/app/fmtocsv.py'],
            stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        p1.stdout.close()
        p1.stdin.write(csv_input.encode())
        p1.stdin.close()
        output, _ = p2.communicate(timeout=30)

        assert p1.wait() == 0
        assert p2.returncode == 0

        reader = csv.DictReader(io.StringIO(output.decode()))
        results = []
        for row in reader:
            results.append((
                int(row['event_id']),
                int(row['output_id']),
                int(row['sidx']),
                float(row['loss'])
            ))
        results.sort(key=lambda r: (r[0], r[1], r[2]))
        expected = [(1, 10, 1, 55555.55), (1, 20, 1, 33333.33)]
        assert_results(results, expected)


class TestBinaryPipelineEquivalence:
    """Binary pipeline must produce identical results to CSV mode"""

    def test_equivalence_two_level(self, tmp_path):
        d = str(tmp_path / 'equiv_test')
        write_csv(f'{d}/fm_programme.csv', PROGRAMME_HEADERS, [
            (1, 1, 1), (2, 1, 1), (3, 1, 2),
            (1, 2, 1), (2, 2, 1),
        ])
        write_csv(f'{d}/fm_profile.csv', PROFILE_HEADERS, [
            make_profile_row(1, 1, d1=10000, l1=200000),
            make_profile_row(2, 12, d1=500),
            make_profile_row(3, 2, a1=5000, l1=80000, sh1=0.5),
        ])
        write_csv(f'{d}/fm_policytc.csv', POLICYTC_HEADERS, [
            (1, 1, 1, 1), (1, 1, 2, 2), (1, 2, 1, 3),
        ])
        write_csv(f'{d}/fm_xref.csv', XREF_HEADERS, [(1, 1, 1)])

        gul = GUL_HEADER + '1,1,1,100000.0\n1,2,1,50000.0\n1,3,1,2000.0\n'

        csv_output = run_fmcalc(d, gul)
        csv_results = parse_output(csv_output)

        p1 = subprocess.Popen(
            ['python3', '/app/fmtobin.py'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )
        p2 = subprocess.Popen(
            ['python3', '/app/fmcalc.py', '--binary', '-p', d],
            stdin=p1.stdout, stdout=subprocess.PIPE
        )
        p3 = subprocess.Popen(
            ['python3', '/app/fmtocsv.py'],
            stdin=p2.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        p1.stdout.close()
        p2.stdout.close()
        p1.stdin.write(gul.encode())
        p1.stdin.close()
        output, _ = p3.communicate(timeout=30)

        assert p1.wait() == 0, "fmtobin failed"
        assert p2.wait() == 0, "fmcalc --binary failed"
        assert p3.returncode == 0, "fmtocsv failed"

        bin_results = parse_output(output.decode())
        assert_results(bin_results, csv_results)

    def test_equivalence_multi_event(self, tmp_path):
        d = str(tmp_path / 'equiv_multi')
        write_csv(f'{d}/fm_programme.csv', PROGRAMME_HEADERS,
                  [(1, 1, 1), (2, 1, 2)])
        write_csv(f'{d}/fm_profile.csv', PROFILE_HEADERS, [
            make_profile_row(1, 3, d1=50000, l1=500000),
            make_profile_row(2, 16, d1=0.1),
        ])
        write_csv(f'{d}/fm_policytc.csv', POLICYTC_HEADERS,
                  [(1, 1, 1, 1), (1, 1, 2, 2)])
        write_csv(f'{d}/fm_xref.csv', XREF_HEADERS,
                  [(1, 1, 1), (2, 2, 1)])

        gul = GUL_HEADER + (
            '1,1,1,30000.0\n1,1,2,80000.0\n'
            '1,2,1,200000.0\n1,2,2,150000.0\n'
            '2,1,1,60000.0\n2,2,1,100000.0\n'
        )

        csv_output = run_fmcalc(d, gul)
        csv_results = parse_output(csv_output)

        p1 = subprocess.Popen(
            ['python3', '/app/fmtobin.py'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )
        p2 = subprocess.Popen(
            ['python3', '/app/fmcalc.py', '--binary', '-p', d],
            stdin=p1.stdout, stdout=subprocess.PIPE
        )
        p3 = subprocess.Popen(
            ['python3', '/app/fmtocsv.py'],
            stdin=p2.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        p1.stdout.close()
        p2.stdout.close()
        p1.stdin.write(gul.encode())
        p1.stdin.close()
        output, _ = p3.communicate(timeout=30)

        assert p1.wait() == 0
        assert p2.wait() == 0
        assert p3.returncode == 0

        bin_results = parse_output(output.decode())
        assert_results(bin_results, csv_results)


class TestBinaryReinsuranceChain:
    """Full 4-stage binary reinsurance chain"""

    def test_binary_chain(self, tmp_path):
        d_direct = str(tmp_path / 'direct')
        d_ri = str(tmp_path / 'ri1')

        write_csv(f'{d_direct}/fm_programme.csv', PROGRAMME_HEADERS,
                  [(1, 1, 1)])
        write_csv(f'{d_direct}/fm_profile.csv', PROFILE_HEADERS, [
            make_profile_row(1, 1, d1=10000, l1=500000),
        ])
        write_csv(f'{d_direct}/fm_policytc.csv', POLICYTC_HEADERS,
                  [(1, 1, 1, 1)])
        write_csv(f'{d_direct}/fm_xref.csv', XREF_HEADERS, [(1, 1, 1)])

        write_csv(f'{d_ri}/fm_programme.csv', PROGRAMME_HEADERS,
                  [(1, 1, 1)])
        write_csv(f'{d_ri}/fm_profile.csv', PROFILE_HEADERS, [
            make_profile_row(1, 25, sh1=0.5, sh2=1.0, sh3=1.0),
        ])
        write_csv(f'{d_ri}/fm_policytc.csv', POLICYTC_HEADERS,
                  [(1, 1, 1, 1)])
        write_csv(f'{d_ri}/fm_xref.csv', XREF_HEADERS, [(1, 1, 1)])

        gul = GUL_HEADER + '1,1,1,200000.0\n'

        # 4-stage pipe: fmtobin | fmcalc --binary direct | fmcalc --binary ri -n | fmtocsv
        p1 = subprocess.Popen(
            ['python3', '/app/fmtobin.py'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )
        p2 = subprocess.Popen(
            ['python3', '/app/fmcalc.py', '--binary', '-p', d_direct],
            stdin=p1.stdout, stdout=subprocess.PIPE
        )
        p3 = subprocess.Popen(
            ['python3', '/app/fmcalc.py', '--binary', '-p', d_ri, '-n'],
            stdin=p2.stdout, stdout=subprocess.PIPE
        )
        p4 = subprocess.Popen(
            ['python3', '/app/fmtocsv.py'],
            stdin=p3.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        p1.stdout.close()
        p2.stdout.close()
        p3.stdout.close()
        p1.stdin.write(gul.encode())
        p1.stdin.close()
        output, _ = p4.communicate(timeout=30)

        for p in [p1, p2, p3]:
            p.wait()
        assert p4.returncode == 0, "Binary reinsurance chain failed"

        results = parse_output(output.decode())
        expected = [(1, 1, 1, 95000.0)]
        assert_results(results, expected)


# --- Pipeline orchestrator tests ---


def _setup_pipeline_scenario(tmp_path):
    """Set up a basic direct + RI scenario for run_pipeline.sh tests."""
    d_direct = str(tmp_path / 'direct')
    d_ri = str(tmp_path / 'ri1')

    write_csv(f'{d_direct}/fm_programme.csv', PROGRAMME_HEADERS, [(1, 1, 1)])
    write_csv(f'{d_direct}/fm_profile.csv', PROFILE_HEADERS, [
        make_profile_row(1, 1, d1=10000, l1=500000),
    ])
    write_csv(f'{d_direct}/fm_policytc.csv', POLICYTC_HEADERS,
              [(1, 1, 1, 1)])
    write_csv(f'{d_direct}/fm_xref.csv', XREF_HEADERS, [(1, 1, 1)])

    write_csv(f'{d_ri}/fm_programme.csv', PROGRAMME_HEADERS, [(1, 1, 1)])
    write_csv(f'{d_ri}/fm_profile.csv', PROFILE_HEADERS, [
        make_profile_row(1, 25, sh1=0.5, sh2=1.0, sh3=1.0),
    ])
    write_csv(f'{d_ri}/fm_policytc.csv', POLICYTC_HEADERS, [(1, 1, 1, 1)])
    write_csv(f'{d_ri}/fm_xref.csv', XREF_HEADERS, [(1, 1, 1)])

    return d_direct, d_ri


class TestRunPipelineBasic:
    """Verify run_pipeline.sh gross/net/summary with single event"""

    def test_basic_db_output(self, tmp_path):
        d_direct, d_ri = _setup_pipeline_scenario(tmp_path)

        gul_file = str(tmp_path / 'gul.csv')
        with open(gul_file, 'w') as f:
            f.write('event_id,item_id,sidx,loss\n')
            f.write('1,1,1,200000.0\n')

        db_path = str(tmp_path / 'output.db')

        result = subprocess.run(
            ['bash', '/app/run_pipeline.sh', gul_file, d_direct, d_ri,
             db_path],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"run_pipeline.sh failed: stderr={result.stderr}"
        )
        assert os.path.exists(db_path), "Output database not created"

        conn = sqlite3_mod.connect(db_path)

        # Verify gross_loss table
        gross = conn.execute(
            'SELECT event_id, output_id, sidx, loss '
            'FROM gross_loss ORDER BY event_id, output_id, sidx'
        ).fetchall()
        assert len(gross) == 1, f"Expected 1 gross row, got {len(gross)}"
        assert gross[0][0] == 1 and gross[0][1] == 1 and gross[0][2] == 1
        # direct: 200000 - 10000 ded = 190000 (limit 500000 not hit)
        assert abs(gross[0][3] - 190000.0) < 0.01, (
            f"Gross loss {gross[0][3]} != 190000.0"
        )

        # Verify net_loss table
        net = conn.execute(
            'SELECT event_id, output_id, sidx, loss '
            'FROM net_loss ORDER BY event_id, output_id, sidx'
        ).fetchall()
        assert len(net) == 1, f"Expected 1 net row, got {len(net)}"
        # RI ceded = 190000 * 0.5 = 95000; net = 190000 - 95000 = 95000
        assert abs(net[0][3] - 95000.0) < 0.01, (
            f"Net loss {net[0][3]} != 95000.0"
        )

        # Verify summary table
        summary = conn.execute(
            'SELECT event_id, gross_total, net_total, ceded_total '
            'FROM summary ORDER BY event_id'
        ).fetchall()
        assert len(summary) == 1
        assert abs(summary[0][1] - 190000.0) < 0.01
        assert abs(summary[0][2] - 95000.0) < 0.01
        assert abs(summary[0][3] - 95000.0) < 0.01  # ceded = gross - net

        conn.close()


class TestRunPipelineMultiEvent:
    """Verify per-event aggregation in summary table"""

    def test_multi_event_aggregation(self, tmp_path):
        d_direct, d_ri = _setup_pipeline_scenario(tmp_path)

        gul_file = str(tmp_path / 'gul.csv')
        with open(gul_file, 'w') as f:
            f.write('event_id,item_id,sidx,loss\n')
            f.write('1,1,1,200000.0\n')
            f.write('2,1,1,100000.0\n')

        db_path = str(tmp_path / 'output.db')

        result = subprocess.run(
            ['bash', '/app/run_pipeline.sh', gul_file, d_direct, d_ri,
             db_path],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"run_pipeline.sh failed: stderr={result.stderr}"
        )

        conn = sqlite3_mod.connect(db_path)

        summary = conn.execute(
            'SELECT event_id, gross_total, net_total, ceded_total '
            'FROM summary ORDER BY event_id'
        ).fetchall()
        assert len(summary) == 2, (
            f"Expected 2 summary rows (per event), got {len(summary)}"
        )

        # Event 1: direct = 200000 - 10000 = 190000
        # RI ceded = 190000 * 0.5 = 95000; net = 95000
        assert abs(summary[0][1] - 190000.0) < 0.01
        assert abs(summary[0][2] - 95000.0) < 0.01
        assert abs(summary[0][3] - 95000.0) < 0.01

        # Event 2: direct = 100000 - 10000 = 90000
        # RI ceded = 90000 * 0.5 = 45000; net = 45000
        assert abs(summary[1][1] - 90000.0) < 0.01
        assert abs(summary[1][2] - 45000.0) < 0.01
        assert abs(summary[1][3] - 45000.0) < 0.01

        conn.close()


class TestRunPipelineFifoCleanup:
    """Verify named pipes are cleaned up after execution"""

    def test_no_fifo_leak(self, tmp_path):
        d_direct, d_ri = _setup_pipeline_scenario(tmp_path)

        gul_file = str(tmp_path / 'gul.csv')
        with open(gul_file, 'w') as f:
            f.write('event_id,item_id,sidx,loss\n')
            f.write('1,1,1,200000.0\n')

        db_path = str(tmp_path / 'output.db')

        # Record existing FIFOs in /tmp before running
        before_out = subprocess.run(
            ['find', '/tmp', '-maxdepth', '3', '-type', 'p'],
            capture_output=True, text=True
        ).stdout.strip()
        before = set(before_out.split('\n')) if before_out else set()

        result = subprocess.run(
            ['bash', '/app/run_pipeline.sh', gul_file, d_direct, d_ri,
             db_path],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0

        # Check no new FIFOs remain
        after_out = subprocess.run(
            ['find', '/tmp', '-maxdepth', '3', '-type', 'p'],
            capture_output=True, text=True
        ).stdout.strip()
        after = set(after_out.split('\n')) if after_out else set()

        leaked = after - before
        assert len(leaked) == 0, f"Named pipes leaked after execution: {leaked}"
