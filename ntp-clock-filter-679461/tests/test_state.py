"""
Tests for the NTPv4 multi-peer clock synchronization pipeline (RFC 5905).

Generates deterministic multi-peer exchange data, runs the C program,
and verifies output against a Python reference implementation of the
complete pipeline: clock filter, intersection, cluster, and combine.

"""

import math
import os
import subprocess
import pytest

# ================================================================
# Constants (must match C implementation)
# ================================================================

JAN_1970     = 2208988800
BASE_UNIX    = 1700000000
PROCESSING   = 0.0005
POLL         = 16.0
SERVER_PREC  = -20
N_ROUNDS     = 10
N_PEERS      = 6
NSTAGE       = 8
MAXDISP      = 16.0
MAXDIST      = 1.0
PHI          = 15e-6
MINDISP      = 0.01
PRECISION    = -20
MAXSTRAT     = 16
NMIN         = 3
NSANE        = 1

PEER_PARAMS = [
    (1, 2, 0.010, 0.005, 0.005),
    (2, 2, 0.015, 0.003, 0.0052),
    (3, 3, 0.020, 0.008, 0.0048),
    (4, 2, 0.012, 0.004, 0.0051),
    (5, 2, 0.008, 0.002, 0.100),
    (6, 3, 0.018, 0.006, -0.080),
]

BASE_FWD = [0.010, 0.0125, 0.015, 0.011, 0.0075, 0.014]
BASE_RET = [0.010, 0.0125, 0.015, 0.011, 0.0075, 0.014]

JITTER_TABLE = [
    (0.0000, -0.0003),
    (0.0010, -0.0005),
    (-0.0005, 0.0008),
    (0.0015, -0.0010),
    (-0.0008, 0.0003),
    (0.0012, -0.0002),
    (-0.0003, 0.0007),
    (0.0007, -0.0004),
    (-0.0011, 0.0006),
    (0.0004, -0.0001),
]


# ================================================================
# NTP timestamp helpers
# ================================================================

def log2d(a):
    if a < 0:
        return 1.0 / (1 << (-a))
    return float(1 << a)


def to_ntp(unix_float):
    sec = int(math.floor(unix_float))
    frac_f = unix_float - sec
    ntp_sec  = (sec + JAN_1970) & 0xFFFFFFFF
    ntp_frac = int(round(frac_f * (2**32))) & 0xFFFFFFFF
    return (ntp_sec, ntp_frac)


def ts_hex(t):
    return f"{(t[0] << 32) | t[1]:016x}"


def ntp_diff(a, b):
    a64 = (a[0] << 32) | a[1]
    b64 = (b[0] << 32) | b[1]
    d = (a64 - b64) & 0xFFFFFFFFFFFFFFFF
    if d >= 0x8000000000000000:
        d -= 0x10000000000000000
    return d / (2**32)


# ================================================================
# Reference implementation: clock filter
# ================================================================

class Stage:
    __slots__ = ('offset', 'delay', 'disp', 'time')
    def __init__(self, offset=0.0, delay=MAXDISP, disp=MAXDISP, time=0.0):
        self.offset = offset
        self.delay  = delay
        self.disp   = disp
        self.time   = time
    def clone(self):
        return Stage(self.offset, self.delay, self.disp, self.time)


class RefPeer:
    def __init__(self, pid, stratum, rootdelay, rootdisp):
        self.id        = pid
        self.stratum   = stratum
        self.rootdelay = rootdelay
        self.rootdisp  = rootdisp
        self.f         = [Stage() for _ in range(NSTAGE)]
        self.offset    = 0.0
        self.delay     = 0.0
        self.disp      = 0.0
        self.jitter    = log2d(PRECISION)
        self.t         = 0.0
        self.initialized = False

    def clock_filter(self, offset, delay, disp, ct):
        # Correct shift: backward iteration
        for i in range(NSTAGE - 1, 0, -1):
            self.f[i] = self.f[i - 1].clone()
            self.f[i].disp += PHI * (ct - self.t)
        self.f[0] = Stage(offset, delay, disp, ct)

        # Sort copy by delay
        sf = sorted([s.clone() for s in self.f], key=lambda s: s.delay)

        self.offset = sf[0].offset
        self.delay  = sf[0].delay

        # Peer dispersion
        self.disp = sum(sf[i].disp / (2 ** (i + 1)) for i in range(NSTAGE))

        # Jitter: RMS of offset differences from best sample
        n  = 0
        js = 0.0
        for i in range(1, NSTAGE):
            if sf[i].disp < MAXDISP:
                js += (sf[i].offset - sf[0].offset) ** 2
                n  += 1
        if n > 0:
            self.jitter = max(math.sqrt(js / n), log2d(PRECISION))
        else:
            self.jitter = log2d(PRECISION)

        # Prime directive
        if sf[0].time <= self.t and self.initialized:
            return
        self.t = sf[0].time
        self.initialized = True


# ================================================================
# Reference implementation: selection pipeline
# ================================================================

def root_dist(peer, current_time):
    return max(MINDISP, peer.rootdelay + peer.delay) / 2.0 \
         + peer.rootdisp \
         + peer.disp \
         + PHI * (current_time - peer.t) \
         + peer.jitter


def peer_fit(peer, current_time):
    if peer.stratum >= MAXSTRAT:
        return False
    if root_dist(peer, current_time) > MAXDIST + PHI * log2d(6):
        return False
    if not peer.initialized:
        return False
    return True


def ref_intersection(fit_peers, current_time):
    """Marzullo's algorithm variant per RFC 5905 / ntpd reference."""
    chime = []
    for p in fit_peers:
        rd = root_dist(p, current_time)
        chime.append((-1, p.offset - rd, p))
        chime.append((0,  p.offset,      p))
        chime.append((+1, p.offset + rd, p))

    chime.sort(key=lambda x: x[1])
    n = len(fit_peers)
    nlist = len(chime)

    low  = -2e9
    high = 2e9

    for allow in range(n):
        if 2 * allow >= n:
            break

        found = 0
        c = 0
        for i in range(nlist):
            c -= chime[i][0]
            if c >= n - allow:
                low = chime[i][1]
                break
            if chime[i][0] == 0:
                found += 1

        c = 0
        for i in range(nlist - 1, -1, -1):
            c += chime[i][0]
            if c >= n - allow:
                high = chime[i][1]
                break
            if chime[i][0] == 0:
                found += 1

        if found > allow:
            continue
        if high > low:
            break

    if high <= low:
        return []

    # Select truechimers: peers with midpoints in [low, high]
    truechimers = []
    for t, edge, p in chime:
        if t != 0:
            continue
        if edge >= low and edge <= high:
            truechimers.append(p)

    return truechimers


def ref_cluster(truechimers, current_time):
    """Clustering algorithm: iteratively remove highest selection jitter."""
    survivors = list(truechimers)
    # Sort by metric (stratum * MAXDIST + root_dist)
    survivors.sort(key=lambda p: MAXDIST * p.stratum + root_dist(p, current_time))

    while len(survivors) > NMIN:
        max_sel_jitter = -1.0
        min_peer_jitter = 1e9
        max_idx = 0

        for i in range(len(survivors)):
            if survivors[i].jitter < min_peer_jitter:
                min_peer_jitter = survivors[i].jitter

            sj = 0.0
            for j in range(len(survivors)):
                sj += (survivors[i].offset - survivors[j].offset) ** 2
            sj = math.sqrt(sj)

            if sj > max_sel_jitter:
                max_sel_jitter = sj
                max_idx = i

        if max_sel_jitter < min_peer_jitter:
            break

        survivors.pop(max_idx)

    return survivors


def ref_combine(survivors, current_time):
    """Combine survivor offsets via weighted average by root distance."""
    y = z = w = 0.0
    for p in survivors:
        x = root_dist(p, current_time)
        y += 1.0 / x
        z += p.offset / x
        w += (p.offset - survivors[0].offset) ** 2 / x

    offset = z / y
    jitter = math.sqrt(w / y)
    rootdelay = survivors[0].rootdelay + survivors[0].delay
    rootdisp  = survivors[0].rootdisp  + survivors[0].disp
    stratum   = survivors[0].stratum + 1

    return offset, jitter, rootdelay, rootdisp, stratum


# ================================================================
# Data generation
# ================================================================

def generate_input(path):
    """Generate the test input file and return exchange records."""
    lines = [
        "# NTP multi-peer exchange data for clock synchronization pipeline\n",
        "# Format: PEER id stratum rootdelay rootdisp\n",
        "# Format: XCHG peer_id T1_hex T2_hex T3_hex T4_hex server_precision poll\n",
        "#\n",
    ]

    for pid, strat, rd, rdisp, _ in PEER_PARAMS:
        lines.append(f"PEER {pid} {strat} {rd:.6f} {rdisp:.6f}\n")

    lines.append("#\n")

    all_exchanges = []
    for r in range(N_ROUNDS):
        for p_idx in range(N_PEERS):
            pid, _, _, _, true_off = PEER_PARAMS[p_idx]
            jidx = (r + p_idx) % N_ROUNDS
            fwd = BASE_FWD[p_idx] + JITTER_TABLE[jidx][0]
            ret = BASE_RET[p_idx] + JITTER_TABLE[jidx][1]

            exch_idx = r * N_PEERS + p_idx
            pt = (exch_idx + 1) * POLL
            ct = BASE_UNIX + pt

            t1 = to_ntp(ct)
            t2 = to_ntp(ct + fwd + true_off)
            t3 = to_ntp(ct + fwd + true_off + PROCESSING)
            t4 = to_ntp(ct + fwd + PROCESSING + ret)

            all_exchanges.append((p_idx, t1, t2, t3, t4))
            lines.append(
                f"XCHG {pid} {ts_hex(t1)} {ts_hex(t2)} "
                f"{ts_hex(t3)} {ts_hex(t4)} {SERVER_PREC} {POLL:.0f}\n"
            )

    with open(path, 'w') as f:
        f.writelines(lines)

    return all_exchanges


def compute_reference(all_exchanges):
    """Run Python reference implementation of the full pipeline."""
    peers = []
    for pid, strat, rd, rdisp, _ in PEER_PARAMS:
        peers.append(RefPeer(pid, strat, rd, rdisp))

    process_time = 0.0

    for p_idx, t1, t2, t3, t4 in all_exchanges:
        process_time += POLL

        offset = (ntp_diff(t2, t1) + ntp_diff(t3, t4)) / 2.0
        delay  = max(ntp_diff(t4, t1) - ntp_diff(t3, t2), log2d(PRECISION))
        disp_  = log2d(SERVER_PREC) + log2d(PRECISION) \
                 + PHI * abs(ntp_diff(t4, t1))

        peers[p_idx].clock_filter(offset, delay, disp_, process_time)

    # Run selection pipeline
    fit_peers = [p for p in peers if peer_fit(p, process_time)]
    truechimers = ref_intersection(fit_peers, process_time)
    survivors = ref_cluster(truechimers, process_time)

    if len(survivors) > 0:
        sys_offset, sys_jitter, sys_rootdelay, sys_rootdisp, sys_stratum = \
            ref_combine(survivors, process_time)
    else:
        sys_offset = sys_jitter = sys_rootdelay = sys_rootdisp = 0.0

    survivor_ids = set(p.id for p in survivors)

    return peers, process_time, survivor_ids, \
           sys_offset, sys_jitter, sys_rootdelay, sys_rootdisp


def approx_eq(a, b, rel_tol=1e-6, abs_tol=1e-9):
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


# ================================================================
# Tests
# ================================================================

def test_compilation():
    """The project must compile without errors."""
    subprocess.run(['make', '-C', '/app', 'clean'],
                   capture_output=True, check=False)
    r = subprocess.run(['make', '-C', '/app'],
                       capture_output=True, timeout=60)
    assert r.returncode == 0, \
        f"Compilation failed:\n{r.stderr.decode()}"


def test_full_pipeline():
    """
    Complete pipeline test: per-peer values AND system variables
    must match the Python reference implementation.
    """
    # Compile
    subprocess.run(['make', '-C', '/app', 'clean'],
                   capture_output=True, check=False)
    r = subprocess.run(['make', '-C', '/app'],
                       capture_output=True, timeout=60)
    assert r.returncode == 0, \
        f"Compilation failed:\n{r.stderr.decode()}"

    # Generate input
    input_path  = '/app/peers_input.txt'
    output_path = '/app/output.txt'
    all_exchanges = generate_input(input_path)

    # Run program
    r = subprocess.run(
        ['/app/ntp_pipeline', input_path, output_path],
        capture_output=True, timeout=30,
    )
    assert r.returncode == 0, \
        f"Program exited with code {r.returncode}:\n{r.stderr.decode()}"
    assert os.path.isfile(output_path), "Output file not created"

    # Read output
    with open(output_path) as f:
        lines = [l.strip() for l in f if l.strip()]

    # Compute reference
    ref_peers, pt, survivor_ids, sys_off, sys_jit, sys_rd, sys_rdisp = \
        compute_reference(all_exchanges)

    # Parse output
    peer_lines = [l for l in lines if l.startswith('PEER')]
    sys_lines  = [l for l in lines if l.startswith('SYSTEM')]

    assert len(peer_lines) == N_PEERS, \
        f"Expected {N_PEERS} PEER lines, got {len(peer_lines)}"
    assert len(sys_lines) == 1, \
        f"Expected 1 SYSTEM line, got {len(sys_lines)}"

    # Check per-peer values
    for i, line in enumerate(peer_lines):
        parts = line.split()
        pid        = int(parts[1])
        got_offset = float(parts[2])
        got_delay  = float(parts[3])
        got_disp   = float(parts[4])
        got_jitter = float(parts[5])
        got_rdist  = float(parts[6])
        got_status = parts[7]

        ref = ref_peers[i]
        assert pid == ref.id, f"Peer ID mismatch at line {i}"

        assert approx_eq(got_offset, ref.offset), \
            (f"Peer {pid} offset: expected {ref.offset:.12e}, "
             f"got {got_offset:.12e}")
        assert approx_eq(got_delay, ref.delay), \
            (f"Peer {pid} delay: expected {ref.delay:.12e}, "
             f"got {got_delay:.12e}")
        assert approx_eq(got_disp, ref.disp), \
            (f"Peer {pid} disp: expected {ref.disp:.12e}, "
             f"got {got_disp:.12e}")
        assert approx_eq(got_jitter, ref.jitter), \
            (f"Peer {pid} jitter: expected {ref.jitter:.12e}, "
             f"got {got_jitter:.12e}")

        exp_rdist = root_dist(ref, pt)
        assert approx_eq(got_rdist, exp_rdist), \
            (f"Peer {pid} root_dist: expected {exp_rdist:.12e}, "
             f"got {got_rdist:.12e}")

        exp_status = "selected" if pid in survivor_ids else "rejected"
        assert got_status == exp_status, \
            (f"Peer {pid}: expected {exp_status}, got {got_status}")

    # Check system variables
    sparts = sys_lines[0].split()
    got_sys_offset = float(sparts[1])
    got_sys_jitter = float(sparts[2])
    got_sys_rd     = float(sparts[3])
    got_sys_rdisp  = float(sparts[4])
    got_n_surv     = int(sparts[5])

    assert approx_eq(got_sys_offset, sys_off), \
        (f"System offset: expected {sys_off:.12e}, "
         f"got {got_sys_offset:.12e}")
    assert approx_eq(got_sys_jitter, sys_jit), \
        (f"System jitter: expected {sys_jit:.12e}, "
         f"got {got_sys_jitter:.12e}")
    assert approx_eq(got_sys_rd, sys_rd), \
        (f"System rootdelay: expected {sys_rd:.12e}, "
         f"got {got_sys_rd:.12e}")
    assert approx_eq(got_sys_rdisp, sys_rdisp), \
        (f"System rootdisp: expected {sys_rdisp:.12e}, "
         f"got {got_sys_rdisp:.12e}")
    assert got_n_surv == len(survivor_ids), \
        f"Survivors: expected {len(survivor_ids)}, got {got_n_surv}"


def test_falseticker_rejection():
    """
    Peers with large offset deviations must be rejected by the
    intersection algorithm.  The input data includes peers whose
    offsets are tens of milliseconds away from the majority.
    """
    subprocess.run(['make', '-C', '/app', 'clean'],
                   capture_output=True, check=False)
    r = subprocess.run(['make', '-C', '/app'],
                       capture_output=True, timeout=60)
    if r.returncode != 0:
        pytest.skip("Compilation failed")

    input_path  = '/app/peers_input.txt'
    output_path = '/app/output.txt'
    generate_input(input_path)

    r = subprocess.run(
        ['/app/ntp_pipeline', input_path, output_path],
        capture_output=True, timeout=30,
    )
    if r.returncode != 0:
        pytest.fail(f"Program failed: {r.stderr.decode()}")

    with open(output_path) as f:
        lines = [l.strip() for l in f if l.strip()]

    for line in lines:
        if not line.startswith('PEER'):
            continue
        parts = line.split()
        pid    = int(parts[1])
        status = parts[7]

        if pid in (5, 6):
            assert status == "rejected", \
                (f"Peer {pid} should be rejected as a falseticker, "
                 f"got '{status}'. Check intersection algorithm.")


def test_system_offset_sanity():
    """
    The combined system offset should be close to the true clock
    offset (~5ms), not corrupted by falsetickers or formula bugs.
    """
    subprocess.run(['make', '-C', '/app', 'clean'],
                   capture_output=True, check=False)
    r = subprocess.run(['make', '-C', '/app'],
                       capture_output=True, timeout=60)
    if r.returncode != 0:
        pytest.skip("Compilation failed")

    input_path  = '/app/peers_input.txt'
    output_path = '/app/output.txt'
    generate_input(input_path)

    r = subprocess.run(
        ['/app/ntp_pipeline', input_path, output_path],
        capture_output=True, timeout=30,
    )
    if r.returncode != 0:
        pytest.fail(f"Program failed: {r.stderr.decode()}")

    with open(output_path) as f:
        for line in f:
            if line.startswith('SYSTEM'):
                sys_offset = float(line.split()[1])
                assert abs(sys_offset - 0.005) < 0.003, \
                    (f"System offset {sys_offset:.6f} is too far from "
                     f"expected ~0.005 (true clock offset)")
                return

    pytest.fail("No SYSTEM line in output")


def test_peer_offset_sign():
    """
    Per-peer offsets for truechimers must reflect the actual clock
    offset (~5ms), not the half round-trip time.
    """
    subprocess.run(['make', '-C', '/app', 'clean'],
                   capture_output=True, check=False)
    r = subprocess.run(['make', '-C', '/app'],
                       capture_output=True, timeout=60)
    if r.returncode != 0:
        pytest.skip("Compilation failed")

    input_path  = '/app/peers_input.txt'
    output_path = '/app/output.txt'
    generate_input(input_path)

    r = subprocess.run(
        ['/app/ntp_pipeline', input_path, output_path],
        capture_output=True, timeout=30,
    )
    if r.returncode != 0:
        pytest.fail(f"Program failed: {r.stderr.decode()}")

    with open(output_path) as f:
        lines = [l.strip() for l in f if l.strip()]

    for line in lines:
        if not line.startswith('PEER'):
            continue
        parts = line.split()
        pid    = int(parts[1])
        offset = float(parts[2])

        if pid == 1:
            # True offset is ~5ms; half-RTT would be ~10ms
            assert abs(offset - 0.005) < 0.003, \
                (f"Peer 1 offset {offset:.6f} is wrong "
                 f"(expected ~0.005, possibly computing half-RTT)")
            return

    pytest.fail("Peer 1 not found in output")


def test_dispersion_finite():
    """
    Peer dispersion must be a finite number, not inf or nan.
    Catches the C XOR-vs-exponentiation bug.
    """
    subprocess.run(['make', '-C', '/app', 'clean'],
                   capture_output=True, check=False)
    r = subprocess.run(['make', '-C', '/app'],
                       capture_output=True, timeout=60)
    if r.returncode != 0:
        pytest.skip("Compilation failed")

    input_path  = '/app/peers_input.txt'
    output_path = '/app/output.txt'
    generate_input(input_path)

    r = subprocess.run(
        ['/app/ntp_pipeline', input_path, output_path],
        capture_output=True, timeout=30,
    )
    if r.returncode != 0:
        pytest.fail(f"Program failed: {r.stderr.decode()}")

    with open(output_path) as f:
        lines = [l.strip() for l in f if l.strip()]

    for line in lines:
        if not line.startswith('PEER'):
            continue
        parts = line.split()
        pid  = int(parts[1])
        disp = float(parts[4])
        assert math.isfinite(disp), \
            f"Peer {pid}: dispersion is {parts[4]} (expected finite)"


def test_survivor_count():
    """
    With 6 peers (4 truechimers, 2 falsetickers), the cluster
    algorithm should produce at least NMIN (3) survivors.
    """
    subprocess.run(['make', '-C', '/app', 'clean'],
                   capture_output=True, check=False)
    r = subprocess.run(['make', '-C', '/app'],
                       capture_output=True, timeout=60)
    if r.returncode != 0:
        pytest.skip("Compilation failed")

    input_path  = '/app/peers_input.txt'
    output_path = '/app/output.txt'
    generate_input(input_path)

    r = subprocess.run(
        ['/app/ntp_pipeline', input_path, output_path],
        capture_output=True, timeout=30,
    )
    if r.returncode != 0:
        pytest.fail(f"Program failed: {r.stderr.decode()}")

    with open(output_path) as f:
        for line in f:
            if line.startswith('SYSTEM'):
                n_surv = int(line.split()[5])
                assert 3 <= n_surv <= 4, \
                    (f"Expected 3-4 survivors after clustering, "
                     f"got {n_surv}")
                return

    pytest.fail("No SYSTEM line in output")
