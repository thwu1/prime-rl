"""
Tests for the network QoS pipeline: tshark extraction, tc configuration,
and hierarchical traffic shaper output.

Validates pcap extraction accuracy, tc config bug fixes, and all per-class
SLAs plus global constraints on the shaper output.

"""

import csv
import json
import os
import re
import subprocess
from collections import defaultdict

import pytest

OUTPUT_PATH = '/app/output.csv'
TRACE_PATH = '/app/trace.csv'
SPEC_PATH = '/app/sla_spec.json'
PCAP_PATH = '/app/capture.pcap'
TC_CONFIG_PATH = '/app/tc_config.sh'
EXTRACT_SCRIPT_PATH = '/app/tshark_extract.sh'


def load_output():
    if not os.path.exists(OUTPUT_PATH):
        return []
    rows = []
    with open(OUTPUT_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                'dequeue_ns': int(float(row['dequeue_ns'])),
                'flow_id': int(float(row['flow_id'])),
                'size_bytes': int(float(row['size_bytes'])),
                'dscp': int(float(row['dscp'])),
                'class_name': row['class_name'],
                'queue_id': int(float(row['queue_id'])),
                'scheduling_delay_ns': int(float(row['scheduling_delay_ns'])),
            })
    return rows


def load_trace():
    if not os.path.exists(TRACE_PATH):
        return []
    rows = []
    with open(TRACE_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                'arrival_ns': int(row['arrival_ns']),
                'flow_id': int(row['flow_id']),
                'size_bytes': int(row['size_bytes']),
                'dscp': int(row['dscp']),
            })
    return rows


def load_spec():
    with open(SPEC_PATH) as f:
        return json.load(f)


def get_flow_ids_for_class(spec, class_name):
    for tc in spec['traffic_classes']:
        if tc['name'] == class_name:
            return {f['flow_id'] for f in tc['flows']}
    return set()


def _tshark_flow_counts():
    """Run tshark independently to get per-flow packet counts from pcap."""
    result = subprocess.run(
        ['tshark', '-r', PCAP_PATH, '-Y', 'udp', '-T', 'fields',
         '-e', 'udp.srcport'],
        capture_output=True, text=True, timeout=60
    )
    counts = {}
    for line in result.stdout.strip().split('\n'):
        port = line.strip()
        if port:
            fid = int(port) - 10000
            counts[fid] = counts.get(fid, 0) + 1
    return counts


def _tshark_flow_dscp():
    """Run tshark independently to get DSCP per flow from pcap."""
    result = subprocess.run(
        ['tshark', '-r', PCAP_PATH, '-Y', 'udp', '-T', 'fields',
         '-e', 'udp.srcport', '-e', 'ip.dsfield.dscp'],
        capture_output=True, text=True, timeout=60
    )
    dscp_map = {}
    for line in result.stdout.strip().split('\n'):
        parts = line.strip().split('\t')
        if len(parts) == 2 and parts[0] and parts[1]:
            fid = int(parts[0]) - 10000
            dscp = int(parts[1])
            if fid not in dscp_map:
                dscp_map[fid] = dscp
    return dscp_map


# ───────────────────────────────────────────────────────────────
# Test: tshark extraction
# ───────────────────────────────────────────────────────────────

class TestTsharkExtraction:
    """Verify the tshark extraction script and its output."""

    def test_extraction_script_exists(self):
        assert os.path.exists(EXTRACT_SCRIPT_PATH), \
            "tshark_extract.sh not found at /app/"

    def test_script_uses_tshark(self):
        with open(EXTRACT_SCRIPT_PATH) as f:
            content = f.read()
        assert 'tshark' in content, \
            "tshark_extract.sh must use tshark for pcap analysis"

    def test_trace_exists(self):
        assert os.path.exists(TRACE_PATH), \
            "trace.csv not produced — tshark extraction may have failed"

    def test_trace_has_required_columns(self):
        trace = load_trace()
        assert len(trace) > 0, "trace.csv is empty"
        required = {'arrival_ns', 'flow_id', 'size_bytes', 'dscp'}
        actual = set(trace[0].keys())
        assert required.issubset(actual), \
            f"trace.csv missing columns: {required - actual}"

    def test_flow_counts_match_pcap(self):
        """Cross-verify per-flow packet counts against independent tshark run."""
        pcap_counts = _tshark_flow_counts()
        trace = load_trace()
        trace_counts = {}
        for p in trace:
            fid = p['flow_id']
            trace_counts[fid] = trace_counts.get(fid, 0) + 1

        for fid in pcap_counts:
            assert fid in trace_counts, \
                f"Flow {fid} present in pcap but missing from trace.csv"
            assert trace_counts[fid] == pcap_counts[fid], \
                f"Flow {fid}: pcap={pcap_counts[fid]}, " \
                f"trace={trace_counts[fid]}"

    def test_dscp_values_match_pcap(self):
        """Verify DSCP extraction accuracy per flow."""
        pcap_dscp = _tshark_flow_dscp()
        trace = load_trace()
        trace_dscp = {}
        for p in trace:
            fid = p['flow_id']
            if fid not in trace_dscp:
                trace_dscp[fid] = p['dscp']

        for fid, expected_dscp in pcap_dscp.items():
            assert fid in trace_dscp, \
                f"Flow {fid} missing from trace.csv"
            assert trace_dscp[fid] == expected_dscp, \
                f"Flow {fid}: pcap DSCP={expected_dscp}, " \
                f"trace DSCP={trace_dscp[fid]}"

    def test_total_packet_count(self):
        """Total packets in trace must match pcap."""
        pcap_counts = _tshark_flow_counts()
        trace = load_trace()
        pcap_total = sum(pcap_counts.values())
        assert len(trace) == pcap_total, \
            f"Total packets: pcap={pcap_total}, trace={len(trace)}"


# ───────────────────────────────────────────────────────────────
# Test: tc configuration
# ───────────────────────────────────────────────────────────────

class TestTcConfig:
    """Verify the corrected tc/HTB configuration."""

    def setup_method(self):
        assert os.path.exists(TC_CONFIG_PATH), \
            "tc_config.sh not found at /app/"
        with open(TC_CONFIG_PATH) as f:
            self.raw = f.read()
        # Join line continuations for easier parsing
        self.joined = self.raw.replace('\\\n', ' ')
        self.lines = [l.strip() for l in self.joined.split('\n')
                      if l.strip() and not l.strip().startswith('#')]

    def test_voice_rate_fixed(self):
        """Bug 1: Voice class rate must not be 2kbit (should be ~2mbit)."""
        voice_lines = [l for l in self.lines if 'classid 1:10' in l]
        assert voice_lines, "Voice class (classid 1:10) not found"
        for line in voice_lines:
            assert '2kbit' not in line.lower(), \
                f"Voice class still has buggy rate 2kbit: {line}"

    def test_video_filter_present(self):
        """Bug 2: Must have filter for DSCP 34 (AF41) → class 1:20."""
        filter_lines = [l for l in self.lines
                        if 'filter' in l and 'flowid' in l]
        video_filters = [l for l in filter_lines if '1:20' in l]
        assert video_filters, \
            "No tc filter directing traffic to video class 1:20"
        assert any('0x88' in l for l in video_filters), \
            "Video filter should match TOS 0x88 (DSCP 34 << 2)"

    def test_background_hierarchy_fixed(self):
        """Bug 3: Background class parent must be 1:1, not root 1:."""
        bg_lines = [l for l in self.lines if 'classid 1:40' in l]
        assert bg_lines, "Background class (classid 1:40) not found"
        for line in bg_lines:
            parts = line.split()
            try:
                idx = parts.index('parent')
                parent = parts[idx + 1]
                assert parent == '1:1', \
                    f"Background parent should be 1:1, got {parent}"
            except (ValueError, IndexError):
                pytest.fail(f"Cannot parse parent in: {line}")

    def test_all_classes_defined(self):
        """All four HTB classes must exist."""
        for cid in ['1:10', '1:20', '1:30', '1:40']:
            assert any(f'classid {cid}' in l for l in self.lines), \
                f"HTB class {cid} not defined"

    def test_all_filters_present(self):
        """Filters for all four traffic classes must exist."""
        filter_lines = [l for l in self.lines
                        if 'filter' in l and 'flowid' in l]
        for flowid in ['1:10', '1:20', '1:30', '1:40']:
            assert any(flowid in l for l in filter_lines), \
                f"No filter directing traffic to class {flowid}"

    def test_leaf_qdiscs_present(self):
        """All four fq_codel leaf qdiscs must be present."""
        for parent in ['1:10', '1:20', '1:30', '1:40']:
            assert any(f'parent {parent}' in l and 'fq_codel' in l
                       for l in self.lines), \
                f"No fq_codel leaf qdisc for parent {parent}"


# ───────────────────────────────────────────────────────────────
# Test: shaper output completeness
# ───────────────────────────────────────────────────────────────

class TestCompleteness:
    """All input packets must appear in the output."""

    def test_output_exists(self):
        assert os.path.exists(OUTPUT_PATH), \
            "Output file /app/output.csv not found"
        output = load_output()
        assert len(output) > 0, "Output file is empty"

    def test_packet_count(self):
        trace = load_trace()
        output = load_output()
        assert len(output) == len(trace), \
            f"Packet count mismatch: trace={len(trace)}, output={len(output)}"

    def test_byte_conservation(self):
        trace = load_trace()
        output = load_output()
        trace_bytes = sum(p['size_bytes'] for p in trace)
        output_bytes = sum(p['size_bytes'] for p in output)
        assert output_bytes == trace_bytes, \
            f"Total bytes mismatch: trace={trace_bytes}, output={output_bytes}"

    def test_per_flow_packet_count(self):
        trace = load_trace()
        output = load_output()
        trace_counts = defaultdict(int)
        output_counts = defaultdict(int)
        for p in trace:
            trace_counts[p['flow_id']] += 1
        for p in output:
            output_counts[p['flow_id']] += 1
        for fid in trace_counts:
            assert output_counts[fid] == trace_counts[fid], \
                f"Flow {fid}: trace={trace_counts[fid]}, " \
                f"output={output_counts.get(fid, 0)}"


# ───────────────────────────────────────────────────────────────
# Test: throughput
# ───────────────────────────────────────────────────────────────

class TestThroughput:
    """Output rate must match configured link rate."""

    def test_overall_rate(self):
        spec = load_spec()
        output = load_output()
        assert len(output) > 100, "Not enough output packets"

        target_mbps = spec['link_rate_mbps']
        first_ns = output[0]['dequeue_ns']
        last_ns = output[-1]['dequeue_ns']
        span = last_ns - first_ns
        assert span > 0, "All packets have the same dequeue time"

        t0 = first_ns + span // 10
        t1 = last_ns - span // 10

        window_bytes = sum(
            p['size_bytes'] for p in output
            if t0 <= p['dequeue_ns'] <= t1
        )
        window_ns = t1 - t0
        measured_mbps = window_bytes * 8 / (window_ns / 1e9) / 1e6

        error_pct = abs(measured_mbps - target_mbps) / target_mbps
        assert error_pct < 0.05, \
            f"Rate {measured_mbps:.1f} Mbps deviates {error_pct*100:.1f}% " \
            f"from target {target_mbps} Mbps (tolerance 5%)"


# ───────────────────────────────────────────────────────────────
# Test: Voice SLA
# ───────────────────────────────────────────────────────────────

class TestVoiceSLA:
    """Voice: p99 delay < 5ms, zero loss."""

    def test_voice_packet_count(self):
        trace = load_trace()
        output = load_output()
        spec = load_spec()
        voice_ids = get_flow_ids_for_class(spec, 'voice')

        trace_voice = sum(1 for p in trace if p['flow_id'] in voice_ids)
        output_voice = sum(1 for p in output if p['flow_id'] in voice_ids)
        assert output_voice == trace_voice, \
            f"Voice packet loss: trace={trace_voice}, output={output_voice}"

    def test_voice_latency_p99(self):
        output = load_output()
        spec = load_spec()
        voice_ids = get_flow_ids_for_class(spec, 'voice')

        delays = [p['scheduling_delay_ns'] for p in output
                  if p['flow_id'] in voice_ids]
        assert len(delays) > 50, "Not enough voice packets for p99"

        delays.sort()
        p99_idx = int(len(delays) * 0.99)
        p99_ms = delays[p99_idx] / 1e6

        assert p99_ms < 5.0, \
            f"Voice p99 delay {p99_ms:.2f} ms >= 5.0 ms"

    def test_voice_classification(self):
        output = load_output()
        spec = load_spec()
        voice_ids = get_flow_ids_for_class(spec, 'voice')

        for p in output:
            if p['flow_id'] in voice_ids:
                assert p['class_name'] == 'voice', \
                    f"Voice flow {p['flow_id']} classified as {p['class_name']}"


# ───────────────────────────────────────────────────────────────
# Test: Video SLA
# ───────────────────────────────────────────────────────────────

class TestVideoSLA:
    """Video: per-flow >= 4.5 Mbps, p99 delay < 30ms."""

    def test_video_per_flow_throughput(self):
        output = load_output()
        spec = load_spec()
        video_ids = get_flow_ids_for_class(spec, 'video')

        for fid in video_ids:
            pkts = [p for p in output if p['flow_id'] == fid]
            assert len(pkts) > 10, f"Too few packets for video flow {fid}"

            total_bytes = sum(p['size_bytes'] for p in pkts)
            first_ns = min(p['dequeue_ns'] for p in pkts)
            last_ns = max(p['dequeue_ns'] for p in pkts)
            span_s = (last_ns - first_ns) / 1e9
            assert span_s > 0, f"Video flow {fid} has zero dequeue span"

            throughput = total_bytes * 8 / span_s / 1e6
            assert throughput >= 4.5, \
                f"Video flow {fid}: {throughput:.2f} Mbps < 4.5 Mbps"

    def test_video_latency_p99(self):
        output = load_output()
        spec = load_spec()
        video_ids = get_flow_ids_for_class(spec, 'video')

        delays = [p['scheduling_delay_ns'] for p in output
                  if p['flow_id'] in video_ids]
        assert len(delays) > 50, "Not enough video packets for p99"

        delays.sort()
        p99_idx = int(len(delays) * 0.99)
        p99_ms = delays[p99_idx] / 1e6

        assert p99_ms < 30.0, \
            f"Video p99 delay {p99_ms:.2f} ms >= 30.0 ms"


# ───────────────────────────────────────────────────────────────
# Test: Best-effort SLA
# ───────────────────────────────────────────────────────────────

class TestBestEffortSLA:
    """Best-effort: JFI > 0.95, per-flow >= 0.3 Mbps."""

    def test_be_fairness_jfi(self):
        output = load_output()
        spec = load_spec()
        be_ids = get_flow_ids_for_class(spec, 'best_effort')

        first_ns = output[0]['dequeue_ns']
        last_ns = output[-1]['dequeue_ns']
        span = last_ns - first_ns
        t0 = first_ns + span // 10
        t1 = last_ns - span // 10

        flow_bytes = defaultdict(int)
        for p in output:
            if p['flow_id'] in be_ids and t0 <= p['dequeue_ns'] <= t1:
                flow_bytes[p['flow_id']] += p['size_bytes']

        assert len(flow_bytes) >= 2, "Need >= 2 BE flows for fairness test"

        throughputs = list(flow_bytes.values())
        n = len(throughputs)
        s = sum(throughputs)
        s2 = sum(x * x for x in throughputs)
        jfi = (s * s) / (n * s2) if s2 > 0 else 0

        assert jfi > 0.95, \
            f"BE Jain's Fairness Index {jfi:.4f} <= 0.95. " \
            f"Per-flow bytes: {dict(sorted(flow_bytes.items()))}"

    def test_be_min_throughput(self):
        output = load_output()
        spec = load_spec()
        be_ids = get_flow_ids_for_class(spec, 'best_effort')

        for fid in be_ids:
            pkts = [p for p in output if p['flow_id'] == fid]
            assert len(pkts) > 0, f"No output for BE flow {fid}"

            total_bytes = sum(p['size_bytes'] for p in pkts)
            first_ns = min(p['dequeue_ns'] for p in pkts)
            last_ns = max(p['dequeue_ns'] for p in pkts)
            span_s = (last_ns - first_ns) / 1e9
            assert span_s > 0, f"BE flow {fid} has zero dequeue span"

            throughput = total_bytes * 8 / span_s / 1e6
            assert throughput >= 0.3, \
                f"BE flow {fid}: {throughput:.2f} Mbps < 0.3 Mbps"


# ───────────────────────────────────────────────────────────────
# Test: Background SLA
# ───────────────────────────────────────────────────────────────

class TestBackgroundSLA:
    """Background: per-flow >= 0.1 Mbps (anti-starvation)."""

    def test_bg_min_throughput(self):
        output = load_output()
        spec = load_spec()
        bg_ids = get_flow_ids_for_class(spec, 'background')

        for fid in bg_ids:
            pkts = [p for p in output if p['flow_id'] == fid]
            assert len(pkts) > 0, f"No output for BG flow {fid}"

            total_bytes = sum(p['size_bytes'] for p in pkts)
            first_ns = min(p['dequeue_ns'] for p in pkts)
            last_ns = max(p['dequeue_ns'] for p in pkts)
            span_s = (last_ns - first_ns) / 1e9
            assert span_s > 0, f"BG flow {fid} has zero dequeue span"

            throughput = total_bytes * 8 / span_s / 1e6
            assert throughput >= 0.1, \
                f"BG flow {fid}: {throughput:.2f} Mbps < 0.1 Mbps"


# ───────────────────────────────────────────────────────────────
# Test: ordering and isolation
# ───────────────────────────────────────────────────────────────

class TestOrdering:
    """Dequeue timestamps must be monotonically non-decreasing."""

    def test_monotonic_dequeue(self):
        output = load_output()
        for i in range(1, len(output)):
            assert output[i]['dequeue_ns'] >= output[i - 1]['dequeue_ns'], \
                f"Non-monotonic at index {i}: " \
                f"{output[i-1]['dequeue_ns']} > {output[i]['dequeue_ns']}"


class TestFlowIsolation:
    """Each queue_id must map to exactly one flow_id."""

    def test_queue_flow_mapping(self):
        output = load_output()
        assert len(output) > 0, "No output to check"

        queue_flows = defaultdict(set)
        for p in output:
            queue_flows[p['queue_id']].add(p['flow_id'])

        shared = {
            qid: flows
            for qid, flows in queue_flows.items()
            if len(flows) > 1
        }
        assert not shared, \
            f"Queues serving multiple flows: {shared}"
