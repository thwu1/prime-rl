"""Tests for TCP state machine correctness, congestion control, and network analysis.

Verifies:
  - TCP state machine protocol fixes (segment acceptability, SRTT,
    connection teardown, handshake completion)
  - CongestionController interface compliance
  - Slow-start, congestion-avoidance, and fast-recovery behaviour
  - Timeout handling
  - Performance targets on three network scenarios
  - Correct analysis output (analysis.json)
  - SQLite analysis database schema and data
"""


import sys
sys.path.insert(0, '/app')

import json
import os
import sqlite3
import pytest

MSS = 1460


# ── State machine helpers ─────────────────────────────────────────

def _establish_connection(clock=None):
    """Complete a three-way handshake and return the Connection."""
    from tcp_sim.connection import Connection, State
    from tcp_sim.segment import Segment

    conn = Connection(iss=100, clock=clock)
    # Client SYN
    syn = Segment(seq=1000, ack=0, flags=Segment.SYN, window=65535)
    conn.on_segment(syn)
    # Client ACK completing handshake
    ack = Segment(seq=1001, ack=101, flags=Segment.ACK, window=65535)
    conn.on_segment(ack)
    return conn


# ── TCP State Machine Tests ───────────────────────────────────────

class TestStateMachine:
    """Verify protocol correctness of the TCP state machine."""

    def test_boundary_segment_accepted(self):
        """Segment that partially overlaps the receive window boundary
        must be accepted, not silently dropped."""
        from tcp_sim.segment import Segment
        from tcp_sim.sequence import wrapping_add, wrapping_sub

        conn = _establish_connection()
        wend = wrapping_add(conn.rcv_nxt, conn.rcv_wnd)
        # Start 50 bytes inside window, extend 200 bytes past boundary
        seg = Segment(
            seq=wrapping_sub(wend, 50),
            ack=conn.snd_nxt,
            flags=Segment.ACK,
            data=b'\x00' * 200,
            window=65535,
        )
        conn.on_segment(seg)
        assert len(conn.incoming) > 0, \
            "Segment crossing window boundary was incorrectly rejected"

    def test_srtt_outlier_dampened(self):
        """A single large RTT sample must not dominate the smoothed RTT."""
        from tcp_sim.connection import Connection, State
        from tcp_sim.segment import Segment

        t = [0.0]
        conn = Connection(iss=100, clock=lambda: t[0])
        # Set up known ESTABLISHED state directly
        conn.state = State.ESTABLISHED
        conn.snd_una = 100
        conn.snd_nxt = 300
        conn.rcv_nxt = 500
        conn.rcv_wnd = 65535
        conn.srtt = 0.05  # stable 50ms history
        conn.send_times = {200: 10.0}

        # ACK arrives at t=11.0 → RTT sample = 1.0s (20× outlier)
        t[0] = 11.0
        ack = Segment(seq=500, ack=300, flags=Segment.ACK, window=65535)
        conn.on_segment(ack)

        # Correct smoothing damps: 0.8*0.05 + 0.2*1.0 = 0.24
        # Wrong weights would give: 0.2*0.05 + 0.8*1.0 = 0.81
        assert conn.srtt < 0.5, \
            f"SRTT {conn.srtt:.3f} too high — smoothing must dampen outliers"

    def test_simultaneous_close(self):
        """FIN received in FIN_WAIT_1 must transition to CLOSING."""
        from tcp_sim.connection import State
        from tcp_sim.segment import Segment

        conn = _establish_connection()
        conn.close()
        assert conn.state == State.FIN_WAIT_1

        # Simultaneous close: peer sends FIN before receiving ours,
        # so their ACK only covers data up to snd_una (not our FIN).
        fin = Segment(seq=conn.rcv_nxt, ack=conn.snd_una,
                      flags=Segment.FIN | Segment.ACK, window=65535)
        conn.on_segment(fin)
        assert conn.state == State.CLOSING, \
            f"Expected CLOSING after simultaneous close, got {conn.state}"

    def test_active_close_fin_acknowledged(self):
        """ACK of sent FIN must advance from FIN_WAIT_1 to FIN_WAIT_2."""
        from tcp_sim.connection import State
        from tcp_sim.segment import Segment

        conn = _establish_connection()
        conn.close()
        assert conn.state == State.FIN_WAIT_1

        ack = Segment(seq=conn.rcv_nxt, ack=conn.snd_nxt,
                      flags=Segment.ACK, window=65535)
        conn.on_segment(ack)
        assert conn.state == State.FIN_WAIT_2, \
            f"Expected FIN_WAIT_2 after FIN ACK, got {conn.state}"

    def test_handshake_snd_una_updated(self):
        """snd_una must advance to ISS+1 after handshake completion."""
        conn = _establish_connection()
        assert conn.snd_una == 101, \
            f"snd_una is {conn.snd_una}, expected 101 after handshake"


# ── CC helpers ────────────────────────────────────────────────────

def _make_cc():
    from tcp_sim.congestion import CongestionController
    return CongestionController()


def _enter_ca():
    """Return a CC instance in congestion_avoidance state."""
    cc = _make_cc()
    for _ in range(20):
        cc.on_ack(MSS, 0.05)
    cc.on_timeout()
    while cc.get_cwnd() < cc.get_ssthresh():
        cc.on_ack(MSS, 0.05)
    return cc


def _expand_events(spec):
    """Mirror of harness.expand_events (kept self-contained for tests)."""
    base_rtt = spec['base_rtt']
    jitter = spec.get('rtt_jitter', 0.0)
    n_acks = spec['num_acks']
    dup_set = set(spec['loss_pattern'].get('dup_ack_sets', []))
    to_set = set(spec['loss_pattern'].get('timeouts', []))
    events = []
    t = 0.0
    for i in range(n_acks):
        t += base_rtt
        if i in dup_set:
            for j in range(3):
                events.append({'time': round(t + j * base_rtt / 100, 6),
                               'type': 'dup_ack'})
            t += base_rtt
        if i in to_set:
            events.append({'time': round(t, 6), 'type': 'timeout'})
            t += base_rtt
        rtt_var = (i % 7 - 3) * jitter / 3
        rtt = base_rtt + rtt_var
        events.append({'time': round(t, 6), 'type': 'ack',
                       'bytes': MSS, 'rtt': round(abs(rtt), 6)})
    return events


def _run_scenario(path):
    """Run a scenario file and return average cwnd."""
    cc = _make_cc()
    with open(path) as f:
        spec = json.load(f)
    cwnd_samples = []
    for ev in _expand_events(spec):
        if ev['type'] == 'ack':
            cc.on_ack(ev['bytes'], ev['rtt'])
        elif ev['type'] == 'dup_ack':
            cc.on_duplicate_ack()
        elif ev['type'] == 'timeout':
            cc.on_timeout()
        cwnd_samples.append(cc.get_cwnd())
    return sum(cwnd_samples) / len(cwnd_samples) if cwnd_samples else 0


# ── Module existence and interface ─────────────────────────────────

class TestCCModule:
    def test_module_file_exists(self):
        assert os.path.exists('/app/tcp_sim/congestion.py'), \
            '/app/tcp_sim/congestion.py must exist'

    def test_class_importable(self):
        cc = _make_cc()
        assert cc is not None

    def test_has_on_ack(self):
        cc = _make_cc()
        assert callable(getattr(cc, 'on_ack', None))

    def test_has_on_duplicate_ack(self):
        cc = _make_cc()
        assert callable(getattr(cc, 'on_duplicate_ack', None))

    def test_has_on_timeout(self):
        cc = _make_cc()
        assert callable(getattr(cc, 'on_timeout', None))

    def test_has_get_cwnd(self):
        cc = _make_cc()
        assert callable(getattr(cc, 'get_cwnd', None))

    def test_has_get_ssthresh(self):
        cc = _make_cc()
        assert callable(getattr(cc, 'get_ssthresh', None))

    def test_has_get_state(self):
        cc = _make_cc()
        assert callable(getattr(cc, 'get_state', None))


# ── Slow start ─────────────────────────────────────────────────────

class TestSlowStart:
    def test_initial_cwnd_equals_mss(self):
        cc = _make_cc()
        assert cc.get_cwnd() == MSS

    def test_initial_state(self):
        cc = _make_cc()
        assert cc.get_state() == 'slow_start'

    def test_cwnd_grows_fast(self):
        cc = _make_cc()
        for _ in range(10):
            cc.on_ack(MSS, 0.05)
        assert cc.get_cwnd() > 5 * MSS

    def test_transitions_to_ca_at_ssthresh(self):
        cc = _make_cc()
        for _ in range(20):
            cc.on_ack(MSS, 0.05)
        cc.on_timeout()
        ssthresh = cc.get_ssthresh()
        assert cc.get_state() == 'slow_start'
        while cc.get_cwnd() < ssthresh:
            cc.on_ack(MSS, 0.05)
        assert cc.get_state() == 'congestion_avoidance'


# ── Congestion avoidance ───────────────────────────────────────────

class TestCongestionAvoidance:
    def test_state_name(self):
        cc = _enter_ca()
        assert cc.get_state() == 'congestion_avoidance'

    def test_growth_slower_than_slow_start(self):
        # slow-start growth
        cc_ss = _make_cc()
        for _ in range(10):
            cc_ss.on_ack(MSS, 0.05)
        ss_growth = cc_ss.get_cwnd() - MSS

        # CA growth
        cc_ca = _enter_ca()
        ca_start = cc_ca.get_cwnd()
        for _ in range(10):
            cc_ca.on_ack(MSS, 0.05)
        ca_growth = cc_ca.get_cwnd() - ca_start

        assert ca_growth < ss_growth

    def test_cwnd_still_increases(self):
        cc = _enter_ca()
        cwnd0 = cc.get_cwnd()
        for _ in range(20):
            cc.on_ack(MSS, 0.05)
        assert cc.get_cwnd() > cwnd0


# ── Fast recovery ──────────────────────────────────────────────────

class TestFastRecovery:
    def test_three_dup_acks_enter_fr(self):
        cc = _make_cc()
        for _ in range(20):
            cc.on_ack(MSS, 0.05)
        for _ in range(3):
            cc.on_duplicate_ack()
        assert cc.get_state() == 'fast_recovery'

    def test_ssthresh_halved(self):
        cc = _make_cc()
        for _ in range(20):
            cc.on_ack(MSS, 0.05)
        cwnd_before = cc.get_cwnd()
        for _ in range(3):
            cc.on_duplicate_ack()
        assert cc.get_ssthresh() == max(cwnd_before // 2, 2 * MSS)

    def test_cwnd_inflated_in_fr(self):
        cc = _make_cc()
        for _ in range(20):
            cc.on_ack(MSS, 0.05)
        for _ in range(3):
            cc.on_duplicate_ack()
        ssthresh = cc.get_ssthresh()
        expected = ssthresh + 3 * MSS
        assert cc.get_cwnd() == expected

    def test_new_ack_exits_fr(self):
        cc = _make_cc()
        for _ in range(20):
            cc.on_ack(MSS, 0.05)
        for _ in range(3):
            cc.on_duplicate_ack()
        cc.on_ack(MSS, 0.05)
        assert cc.get_state() == 'congestion_avoidance'

    def test_cwnd_deflated_on_fr_exit(self):
        cc = _make_cc()
        for _ in range(20):
            cc.on_ack(MSS, 0.05)
        for _ in range(3):
            cc.on_duplicate_ack()
        ssthresh = cc.get_ssthresh()
        cc.on_ack(MSS, 0.05)
        assert cc.get_cwnd() == ssthresh

    def test_additional_dup_acks_inflate(self):
        cc = _make_cc()
        for _ in range(20):
            cc.on_ack(MSS, 0.05)
        for _ in range(3):
            cc.on_duplicate_ack()
        cwnd_at_entry = cc.get_cwnd()
        cc.on_duplicate_ack()
        assert cc.get_cwnd() == cwnd_at_entry + MSS


# ── Timeout ────────────────────────────────────────────────────────

class TestTimeout:
    def test_cwnd_reset_to_mss(self):
        cc = _make_cc()
        for _ in range(20):
            cc.on_ack(MSS, 0.05)
        cc.on_timeout()
        assert cc.get_cwnd() == MSS

    def test_enters_slow_start(self):
        cc = _make_cc()
        for _ in range(20):
            cc.on_ack(MSS, 0.05)
        cc.on_timeout()
        assert cc.get_state() == 'slow_start'

    def test_ssthresh_set(self):
        cc = _make_cc()
        for _ in range(20):
            cc.on_ack(MSS, 0.05)
        cwnd_before = cc.get_cwnd()
        cc.on_timeout()
        assert cc.get_ssthresh() == max(cwnd_before // 2, 2 * MSS)

    def test_timeout_during_fr(self):
        cc = _make_cc()
        for _ in range(20):
            cc.on_ack(MSS, 0.05)
        for _ in range(3):
            cc.on_duplicate_ack()
        assert cc.get_state() == 'fast_recovery'
        cc.on_timeout()
        assert cc.get_state() == 'slow_start'
        assert cc.get_cwnd() == MSS


# ── Scenario performance ──────────────────────────────────────────

class TestScenarioPerformance:
    def test_scenario_a(self):
        avg = _run_scenario('/app/scenarios/scenario_a.json')
        assert avg >= 10000, f'scenario_a avg_cwnd {avg:.0f} < 10000'

    def test_scenario_b(self):
        avg = _run_scenario('/app/scenarios/scenario_b.json')
        assert avg >= 3000, f'scenario_b avg_cwnd {avg:.0f} < 3000'

    def test_scenario_c(self):
        avg = _run_scenario('/app/scenarios/scenario_c.json')
        assert avg >= 2000, f'scenario_c avg_cwnd {avg:.0f} < 2000'


# ── analysis.json ──────────────────────────────────────────────────

class TestAnalysisJSON:
    @pytest.fixture(autouse=True)
    def _load(self):
        assert os.path.exists('/app/analysis.json'), \
            '/app/analysis.json must exist'
        with open('/app/analysis.json') as f:
            self.data = json.load(f)

    def test_has_all_scenarios(self):
        for s in ('scenario_a', 'scenario_b', 'scenario_c'):
            assert s in self.data, f'{s} missing from analysis.json'

    def test_required_keys(self):
        for s in ('scenario_a', 'scenario_b', 'scenario_c'):
            for k in ('avg_rtt_ms', 'retransmission_pct', 'packet_count'):
                assert k in self.data[s], f'{s}.{k} missing'

    def test_scenario_a_rtt(self):
        rtt = self.data['scenario_a']['avg_rtt_ms']
        assert 0.3 <= rtt <= 5.0, \
            f'scenario_a RTT {rtt:.2f} ms outside [0.3, 5.0]'

    def test_scenario_b_rtt(self):
        rtt = self.data['scenario_b']['avg_rtt_ms']
        assert 20.0 <= rtt <= 80.0, \
            f'scenario_b RTT {rtt:.2f} ms outside [20, 80]'

    def test_scenario_c_rtt(self):
        rtt = self.data['scenario_c']['avg_rtt_ms']
        assert 100.0 <= rtt <= 500.0, \
            f'scenario_c RTT {rtt:.2f} ms outside [100, 500]'

    def test_packet_counts_positive(self):
        for s in ('scenario_a', 'scenario_b', 'scenario_c'):
            assert self.data[s]['packet_count'] > 0


# ── SQLite analysis database ──────────────────────────────────────

class TestAnalysisDB:
    DB = '/app/metrics/analysis.db'

    def test_db_exists(self):
        assert os.path.exists(self.DB), f'{self.DB} must exist'

    def test_table_exists(self):
        conn = sqlite3.connect(self.DB)
        cur = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='network_metrics'")
        assert cur.fetchone() is not None, 'network_metrics table missing'
        conn.close()

    def test_schema_columns(self):
        conn = sqlite3.connect(self.DB)
        cur = conn.execute('PRAGMA table_info(network_metrics)')
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        for c in ('scenario', 'avg_rtt_ms', 'retransmission_pct',
                   'packet_count', 'bdp_bytes'):
            assert c in cols, f'column {c} missing from network_metrics'

    def test_all_scenarios_present(self):
        conn = sqlite3.connect(self.DB)
        cur = conn.execute('SELECT scenario FROM network_metrics')
        rows = {r[0] for r in cur.fetchall()}
        conn.close()
        for s in ('scenario_a', 'scenario_b', 'scenario_c'):
            assert s in rows, f'{s} missing from network_metrics'

    def test_rtt_values_positive(self):
        conn = sqlite3.connect(self.DB)
        cur = conn.execute('SELECT scenario, avg_rtt_ms FROM network_metrics')
        for scenario, rtt in cur.fetchall():
            assert rtt > 0, f'{scenario} avg_rtt_ms <= 0'
        conn.close()
