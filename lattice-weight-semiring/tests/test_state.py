
import math
import os
import struct
import subprocess
import tempfile


def _ensure_built():
    """Build the project, return True if successful."""
    result = subprocess.run(
        ["make", "-C", "/app"],
        capture_output=True, text=True, timeout=60
    )
    return result.returncode == 0


def _create_binary_file(arcs, path):
    """Create a binary lattice arc file.
    arcs: list of (src, dst, v1, v2, string_elements_list)
    """
    with open(path, 'wb') as f:
        f.write(struct.pack('<I', len(arcs)))
        for src, dst, v1, v2, string_elts in arcs:
            f.write(struct.pack('<II', src, dst))
            f.write(struct.pack('<ff', v1, v2))
            f.write(struct.pack('<I', len(string_elts)))
            for s in string_elts:
                f.write(struct.pack('<i', s))


def _parse_clw_text(text):
    """Parse CompactLatticeWeight text format 'v1,v2,s1_s2_...'"""
    pos = text.rfind(',')
    if pos == -1:
        raise ValueError(f"Bad CLW text: {text}")
    weight_str = text[:pos]
    string_str = text[pos + 1:]

    comma = weight_str.find(',')
    v1_str = weight_str[:comma]
    v2_str = weight_str[comma + 1:]

    def parse_f(s):
        if s == 'Infinity':
            return float('inf')
        elif s == '-Infinity':
            return float('-inf')
        elif s == 'BadNumber':
            return float('nan')
        return float(s)

    v1 = parse_f(v1_str)
    v2 = parse_f(v2_str)

    if string_str:
        string_elts = [int(x) for x in string_str.split('_')]
    else:
        string_elts = []

    return v1, v2, string_elts


def test_compilation():
    """Test that the project compiles successfully with the user-created Makefile."""
    assert os.path.exists("/app/Makefile"), "No Makefile found at /app/Makefile"
    result = subprocess.run(
        ["make", "-C", "/app"],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, (
        f"Compilation failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert os.path.exists("/app/test_main"), "test_main binary not produced"
    assert os.path.exists("/app/lattice_proc"), "lattice_proc binary not produced"


def test_unit_tests():
    """Test all semiring axioms via randomized property testing."""
    assert _ensure_built(), "Build failed"
    result = subprocess.run(
        ["/app/test_main"],
        capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, (
        f"Tests failed (exit code {result.returncode}):\n"
        f"stdout:\n{result.stdout[-3000:]}\n"
        f"stderr:\n{result.stderr[-3000:]}"
    )
    assert "All tests passed!" in result.stdout, (
        f"Expected 'All tests passed!' in output:\n{result.stdout[-2000:]}"
    )


def test_valgrind_memory_safety():
    """Verify no memory leaks or errors under valgrind."""
    assert _ensure_built(), "Build failed"
    result = subprocess.run(
        ["valgrind", "--leak-check=full",
         "--errors-for-leak-kinds=definite,indirect,possible",
         "--error-exitcode=42", "/app/test_main"],
        capture_output=True, text=True, timeout=300
    )
    assert result.returncode != 42, (
        f"Valgrind detected memory errors:\n"
        f"stderr:\n{result.stderr[-4000:]}"
    )
    assert result.returncode == 0, (
        f"test_main failed under valgrind (exit code {result.returncode}):\n"
        f"stdout:\n{result.stdout[-2000:]}\n"
        f"stderr:\n{result.stderr[-2000:]}"
    )
    # Also check valgrind summary for no leaks
    assert "no leaks are possible" in result.stderr or \
           "All heap blocks were freed" in result.stderr or \
           "definitely lost: 0 bytes" in result.stderr, (
        f"Valgrind reports possible leaks:\n{result.stderr[-3000:]}"
    )


def test_lattice_proc_stats():
    """Test the stats command with known arc data."""
    assert _ensure_built(), "Build failed"

    # Arc weights chosen for exact float representation
    arcs = [
        (0, 1, 1.5, 2.5, [3, 7]),     # total=4.0
        (1, 2, 0.5, 1.5, [1]),         # total=2.0
        (0, 2, 2.5, 0.5, []),          # total=3.0
    ]

    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
        tmppath = f.name
    try:
        _create_binary_file(arcs, tmppath)
        result = subprocess.run(
            ["/app/lattice_proc", "stats", tmppath],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"lattice_proc stats failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        lines = result.stdout.strip().split('\n')
        stats = {}
        for line in lines:
            key, value = line.split(': ', 1)
            stats[key.strip()] = value.strip()

        assert stats['arcs'] == '3', f"Expected 3 arcs, got {stats.get('arcs')}"

        # times_fold: Times of all three weights
        # Times((1.5,2.5,[3,7]), (0.5,1.5,[1])) = (2,4,[3,7,1])
        # Times((2,4,[3,7,1]), (2.5,0.5,[])) = (4.5,4.5,[3,7,1])
        tv1, tv2, ts = _parse_clw_text(stats['times_fold'])
        assert abs(tv1 - 4.5) < 0.01, f"times_fold v1: expected 4.5, got {tv1}"
        assert abs(tv2 - 4.5) < 0.01, f"times_fold v2: expected 4.5, got {tv2}"
        assert ts == [3, 7, 1], f"times_fold string: expected [3,7,1], got {ts}"

        # plus_fold: Plus selects smallest total cost
        # arc2 has total=2.0 (smallest), so plus_fold = arc2 weight
        pv1, pv2, ps = _parse_clw_text(stats['plus_fold'])
        assert abs(pv1 - 0.5) < 0.01, f"plus_fold v1: expected 0.5, got {pv1}"
        assert abs(pv2 - 1.5) < 0.01, f"plus_fold v2: expected 1.5, got {pv2}"
        assert ps == [1], f"plus_fold string: expected [1], got {ps}"

        assert stats['distinct_quantized'] == '3', (
            f"Expected 3 distinct quantized, got {stats.get('distinct_quantized')}"
        )
    finally:
        os.unlink(tmppath)


def test_lattice_proc_stats_empty():
    """Test stats command with zero arcs."""
    assert _ensure_built(), "Build failed"

    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
        tmppath = f.name
    try:
        _create_binary_file([], tmppath)
        result = subprocess.run(
            ["/app/lattice_proc", "stats", tmppath],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"lattice_proc stats (empty) failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        lines = result.stdout.strip().split('\n')
        stats = {}
        for line in lines:
            key, value = line.split(': ', 1)
            stats[key.strip()] = value.strip()

        assert stats['arcs'] == '0'

        # times_fold identity is One() = (0,0,[])
        tv1, tv2, ts = _parse_clw_text(stats['times_fold'])
        assert tv1 == 0.0 and tv2 == 0.0 and ts == []

        # plus_fold identity is Zero() = (inf,inf,[])
        pv1, pv2, ps = _parse_clw_text(stats['plus_fold'])
        assert math.isinf(pv1) and math.isinf(pv2) and ps == []

        assert stats['distinct_quantized'] == '0'
    finally:
        os.unlink(tmppath)


def test_lattice_proc_text():
    """Test the text command converts binary to text correctly."""
    assert _ensure_built(), "Build failed"

    arcs = [
        (0, 1, 1.5, 2.5, [3, 7]),
        (1, 2, 0.5, 1.5, [1]),
        (0, 2, 2.5, 0.5, []),
    ]

    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
        tmppath = f.name
    try:
        _create_binary_file(arcs, tmppath)
        result = subprocess.run(
            ["/app/lattice_proc", "text", tmppath],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"lattice_proc text failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        lines = result.stdout.strip().split('\n')
        assert len(lines) == 3, f"Expected 3 lines, got {len(lines)}"

        # Parse each line: <src> <dst> <CLW_text>
        for i, (src, dst, v1, v2, string_elts) in enumerate(arcs):
            parts = lines[i].split(None, 2)
            assert len(parts) == 3, f"Line {i} has wrong format: {lines[i]}"
            assert int(parts[0]) == src, f"Line {i} src mismatch"
            assert int(parts[1]) == dst, f"Line {i} dst mismatch"
            pv1, pv2, ps = _parse_clw_text(parts[2])
            assert abs(pv1 - v1) < 0.01, f"Line {i} v1 mismatch: {pv1} vs {v1}"
            assert abs(pv2 - v2) < 0.01, f"Line {i} v2 mismatch: {pv2} vs {v2}"
            assert ps == string_elts, f"Line {i} string mismatch: {ps} vs {string_elts}"
    finally:
        os.unlink(tmppath)


def test_lattice_proc_roundtrip():
    """Test text -> binary -> text roundtrip preserves data."""
    assert _ensure_built(), "Build failed"

    arcs = [
        (0, 1, 1.5, 2.5, [3, 7]),
        (1, 2, 0.5, 1.5, [1]),
        (2, 3, 0.25, 0.75, [4, 5, 6]),
        (0, 3, 2.5, 0.5, []),
    ]

    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
        orig_path = f.name
    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
        roundtrip_path = f.name
    try:
        _create_binary_file(arcs, orig_path)

        # Binary -> text
        text_result = subprocess.run(
            ["/app/lattice_proc", "text", orig_path],
            capture_output=True, text=True, timeout=30
        )
        assert text_result.returncode == 0, "text command failed"

        # Text -> binary
        bin_result = subprocess.run(
            ["/app/lattice_proc", "binary", roundtrip_path],
            input=text_result.stdout,
            capture_output=True, text=True, timeout=30
        )
        assert bin_result.returncode == 0, (
            f"binary command failed:\nstderr: {bin_result.stderr}"
        )

        # Compare binary files
        with open(orig_path, 'rb') as f1, open(roundtrip_path, 'rb') as f2:
            orig_bytes = f1.read()
            rt_bytes = f2.read()

        assert orig_bytes == rt_bytes, (
            f"Binary roundtrip mismatch: original {len(orig_bytes)} bytes, "
            f"roundtrip {len(rt_bytes)} bytes"
        )
    finally:
        os.unlink(orig_path)
        os.unlink(roundtrip_path)


def test_lattice_proc_normalize_with_prefix():
    """Test normalize where common divisor has a non-empty string prefix."""
    assert _ensure_built(), "Build failed"

    # Arcs share string prefix [5]
    arcs = [
        (0, 1, 1.0, 2.0, [5, 3]),   # total=3.0
        (1, 2, 0.0, 0.0, [5]),       # total=0.0
    ]

    # Common divisor fold:
    #   Start: arc[0] = (1.0, 2.0, [5,3])
    #   CD with arc[1]:
    #     weight = Plus((1.0,2.0), (0.0,0.0)) selects smaller total => (0.0, 0.0)
    #     string = common prefix of [5,3] and [5] => [5]
    #   CD = (0.0, 0.0, [5])
    #
    # Normalized (left-divide by CD):
    #   arc[0]: weight=(1.0,2.0), string=[5,3] minus prefix [5] => [3]
    #   arc[1]: weight=(0.0,0.0), string=[5] minus prefix [5] => []

    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
        tmppath = f.name
    try:
        _create_binary_file(arcs, tmppath)
        result = subprocess.run(
            ["/app/lattice_proc", "normalize", tmppath],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"normalize failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        lines = result.stdout.strip().split('\n')
        assert len(lines) == 2, f"Expected 2 lines, got {len(lines)}: {result.stdout}"

        p0 = lines[0].split(None, 2)
        assert int(p0[0]) == 0 and int(p0[1]) == 1
        v1, v2, s = _parse_clw_text(p0[2])
        assert abs(v1 - 1.0) < 0.01, f"Line 0 v1: expected 1.0, got {v1}"
        assert abs(v2 - 2.0) < 0.01, f"Line 0 v2: expected 2.0, got {v2}"
        assert s == [3], f"Line 0 string: expected [3], got {s}"

        p1 = lines[1].split(None, 2)
        assert int(p1[0]) == 1 and int(p1[1]) == 2
        v1, v2, s = _parse_clw_text(p1[2])
        assert abs(v1 - 0.0) < 0.01, f"Line 1 v1: expected 0.0, got {v1}"
        assert abs(v2 - 0.0) < 0.01, f"Line 1 v2: expected 0.0, got {v2}"
        assert s == [], f"Line 1 string: expected [], got {s}"
    finally:
        os.unlink(tmppath)


def test_lattice_proc_normalize_no_prefix():
    """Test normalize where common divisor has empty string prefix."""
    assert _ensure_built(), "Build failed"

    arcs = [
        (0, 1, 1.5, 2.5, [3, 7]),     # total=4.0
        (1, 2, 0.5, 1.5, [1]),         # total=2.0
        (0, 2, 2.5, 0.5, []),          # total=3.0
    ]

    # Common divisor fold:
    #   Start: arc[0] = (1.5, 2.5, [3,7])
    #   CD with arc[1]: weight=Plus => (0.5,1.5), prefix of [3,7],[1] => []
    #   CD with arc[2]: weight=Plus => (0.5,1.5), prefix of [],[] => []
    #   CD = (0.5, 1.5, [])
    #
    # Normalized (left-divide by CD):
    #   arc[0]: weight=(1.0, 1.0), string=[3,7]
    #   arc[1]: weight=(0.0, 0.0), string=[1]
    #   arc[2]: weight=(2.0, -1.0), string=[]

    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
        tmppath = f.name
    try:
        _create_binary_file(arcs, tmppath)
        result = subprocess.run(
            ["/app/lattice_proc", "normalize", tmppath],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"normalize failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        lines = result.stdout.strip().split('\n')
        assert len(lines) == 3, f"Expected 3 lines, got {len(lines)}"

        p0 = lines[0].split(None, 2)
        v1, v2, s = _parse_clw_text(p0[2])
        assert abs(v1 - 1.0) < 0.01 and abs(v2 - 1.0) < 0.01, (
            f"Line 0 weight: expected (1.0,1.0), got ({v1},{v2})"
        )
        assert s == [3, 7], f"Line 0 string: expected [3,7], got {s}"

        p1 = lines[1].split(None, 2)
        v1, v2, s = _parse_clw_text(p1[2])
        assert abs(v1 - 0.0) < 0.01 and abs(v2 - 0.0) < 0.01, (
            f"Line 1 weight: expected (0.0,0.0), got ({v1},{v2})"
        )
        assert s == [1], f"Line 1 string: expected [1], got {s}"

        p2 = lines[2].split(None, 2)
        v1, v2, s = _parse_clw_text(p2[2])
        assert abs(v1 - 2.0) < 0.01 and abs(v2 - (-1.0)) < 0.01, (
            f"Line 2 weight: expected (2.0,-1.0), got ({v1},{v2})"
        )
        assert s == [], f"Line 2 string: expected [], got {s}"
    finally:
        os.unlink(tmppath)


def test_lattice_proc_normalize_empty():
    """Test normalize with zero arcs produces no output."""
    assert _ensure_built(), "Build failed"

    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
        tmppath = f.name
    try:
        _create_binary_file([], tmppath)
        result = subprocess.run(
            ["/app/lattice_proc", "normalize", tmppath],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"normalize (empty) failed:\nstderr: {result.stderr}"
        )
        assert result.stdout.strip() == '', (
            f"Expected empty output for empty file, got: {result.stdout}"
        )
    finally:
        os.unlink(tmppath)


def test_lattice_proc_normalize_single_arc():
    """Test normalize with a single arc — divisor equals the arc weight itself."""
    assert _ensure_built(), "Build failed"

    arcs = [
        (2, 5, 3.0, 4.0, [10, 20]),
    ]

    # Common divisor of a single element is itself: (3.0, 4.0, [10, 20])
    # Divide by itself: weight=(0,0), string=[]
    # Output: identity weight with empty string

    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
        tmppath = f.name
    try:
        _create_binary_file(arcs, tmppath)
        result = subprocess.run(
            ["/app/lattice_proc", "normalize", tmppath],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"normalize (single) failed:\nstderr: {result.stderr}"
        )

        lines = result.stdout.strip().split('\n')
        assert len(lines) == 1, f"Expected 1 line, got {len(lines)}"

        p0 = lines[0].split(None, 2)
        assert int(p0[0]) == 2 and int(p0[1]) == 5
        v1, v2, s = _parse_clw_text(p0[2])
        assert abs(v1 - 0.0) < 0.01 and abs(v2 - 0.0) < 0.01, (
            f"Single arc normalize: expected (0,0), got ({v1},{v2})"
        )
        assert s == [], f"Single arc normalize: expected [], got {s}"
    finally:
        os.unlink(tmppath)
