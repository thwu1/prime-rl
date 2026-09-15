"""Verify SRv6 SRH forensic audit output."""

import hashlib
import json
import ipaddress
import os
import socket
import struct

import pytest


# ---------------------------------------------------------------------------
# DNA: load build-specific expected values generated at Docker build time.
# Each build uses a random seed to produce unique SRH tag values, making
# the digests and analysis results unpredictable across builds.
# ---------------------------------------------------------------------------
def _load_dna():
    with open('/app/.task_dna.json') as f:
        return json.load(f)


DNA = _load_dna()
EXPECTED_DIGESTS = DNA['digests']
EXPECTED_ANALYSIS = DNA['expected_analysis']
EXPECTED_SUMMARY = DNA['expected_summary']


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _norm(addr):
    return str(ipaddress.IPv6Address(addr))


def _parse_pcap(path):
    packets = []
    with open(path, 'rb') as f:
        hdr = f.read(24)
        magic = struct.unpack('<I', hdr[:4])[0]
        assert magic == 0xa1b2c3d4

        while True:
            phdr = f.read(16)
            if len(phdr) < 16:
                break
            _, _, incl_len, _ = struct.unpack('<IIII', phdr)
            data = f.read(incl_len)
            if len(data) < 40:
                continue

            nxt_hdr = data[6]
            dst = socket.inet_ntop(socket.AF_INET6, data[24:40])

            pkt = {'dst': _norm(dst), 'raw': data}

            if nxt_hdr == 43:
                srh_len = data[41]
                srh_sl = data[43]
                srh_le = data[44]

                segs = []
                for i in range(srh_le + 1):
                    off = 48 + i * 16
                    if off + 16 <= len(data):
                        segs.append(_norm(
                            socket.inet_ntop(socket.AF_INET6,
                                             data[off:off + 16])))

                pkt['srh'] = {
                    'len': srh_len,
                    'segleft': srh_sl,
                    'lastentry': srh_le,
                    'addresses': segs,
                }

                srh_size = (srh_len + 1) * 8
                srh_bytes = data[40:40 + srh_size]
                pkt['srh_digest'] = hashlib.sha256(srh_bytes).hexdigest()[:16]

            packets.append(pkt)
    return packets


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def analysis():
    path = '/app/output/analysis.json'
    assert os.path.exists(path), f"analysis.json not found at {path}"
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, list), "analysis.json must be a JSON array"
    return data


@pytest.fixture(scope='module')
def summary():
    path = '/app/output/summary.json'
    assert os.path.exists(path), f"summary.json not found at {path}"
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, dict), "summary.json must be a JSON object"
    return data


@pytest.fixture(scope='module')
def topology():
    with open('/app/topology.json') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def raw_packets():
    return _parse_pcap('/app/captures/traffic.pcap')


# ---------------------------------------------------------------------------
# structural tests
# ---------------------------------------------------------------------------

class TestStructure:
    def test_packet_count(self, analysis):
        assert len(analysis) == 12

    def test_required_fields(self, analysis):
        for entry in analysis:
            for key in ('packet_index', 'is_valid', 'errors',
                        'matched_path', 'srh_digest'):
                assert key in entry, f"Missing key '{key}' in entry {entry}"
            assert isinstance(entry['is_valid'], bool)
            assert isinstance(entry['errors'], list)
            assert isinstance(entry['srh_digest'], str)
            assert len(entry['srh_digest']) == 16

    def test_errors_sorted(self, analysis):
        for entry in analysis:
            assert entry['errors'] == sorted(entry['errors']), \
                f"Errors not sorted for packet {entry['packet_index']}"


# ---------------------------------------------------------------------------
# SRH digest DNA tests — values from build-time randomized generation
# ---------------------------------------------------------------------------

class TestSRHDigests:
    @pytest.mark.parametrize("idx", range(12))
    def test_digest_matches_dna(self, analysis, idx):
        """Each digest must match the build-specific DNA value."""
        assert analysis[idx]['srh_digest'] == EXPECTED_DIGESTS[idx], \
            (f"Packet {idx}: expected digest {EXPECTED_DIGESTS[idx]}, "
             f"got {analysis[idx]['srh_digest']}")

    def test_digests_match_raw_pcap(self, analysis, raw_packets):
        """Digests must also match independent computation from raw pcap."""
        for i, rp in enumerate(raw_packets):
            if 'srh_digest' in rp:
                assert analysis[i]['srh_digest'] == rp['srh_digest']


# ---------------------------------------------------------------------------
# per-packet analysis tests — validated against build-time DNA
# ---------------------------------------------------------------------------

class TestPacketAnalysis:
    @pytest.mark.parametrize("idx", range(12))
    def test_validity(self, analysis, idx):
        expected = EXPECTED_ANALYSIS[idx]
        assert analysis[idx]['is_valid'] == expected['is_valid'], \
            f"Packet {idx}: expected is_valid={expected['is_valid']}"

    @pytest.mark.parametrize("idx", range(12))
    def test_errors(self, analysis, idx):
        expected = EXPECTED_ANALYSIS[idx]
        assert analysis[idx]['errors'] == expected['errors'], \
            (f"Packet {idx}: expected errors={expected['errors']}, "
             f"got {analysis[idx]['errors']}")

    @pytest.mark.parametrize("idx", range(12))
    def test_matched_path(self, analysis, idx):
        expected = EXPECTED_ANALYSIS[idx]
        assert analysis[idx]['matched_path'] == expected['matched_path'], \
            (f"Packet {idx}: expected path={expected['matched_path']}, "
             f"got {analysis[idx]['matched_path']}")


# ---------------------------------------------------------------------------
# summary tests — validated against build-time DNA
# ---------------------------------------------------------------------------

class TestSummary:
    def test_total_packets(self, summary):
        assert summary['total_packets'] == EXPECTED_SUMMARY['total_packets']

    def test_valid_count(self, summary):
        assert summary['valid_count'] == EXPECTED_SUMMARY['valid_count']

    def test_invalid_count(self, summary):
        assert summary['invalid_count'] == EXPECTED_SUMMARY['invalid_count']

    def test_violation_score(self, summary):
        assert summary['violation_score'] == EXPECTED_SUMMARY['violation_score']

    def test_unique_paths_seen(self, summary):
        assert summary['unique_paths_seen'] == EXPECTED_SUMMARY['unique_paths_seen']


# ---------------------------------------------------------------------------
# cross-validation against raw pcap data
# ---------------------------------------------------------------------------

class TestCrossValidation:
    def test_valid_packets_rfc_compliant(self, analysis, raw_packets, topology):
        """All packets marked valid must pass RFC 8754 structural checks."""
        valid_sids = {_norm(s) for s in topology['valid_sids']}
        for i in range(len(analysis)):
            e = analysis[i]
            if not e['is_valid']:
                continue
            p = raw_packets[i]
            srh = p['srh']
            assert srh['segleft'] <= srh['lastentry']
            active = srh['addresses'][srh['segleft']]
            assert _norm(p['dst']) == _norm(active)
            assert srh['len'] == 2 * (srh['lastentry'] + 1)
            for seg in srh['addresses']:
                assert _norm(seg) in valid_sids

    def test_error_packets_consistent(self, analysis, raw_packets, topology):
        """Each reported error must be verifiable from raw packet fields."""
        valid_sids = {_norm(s) for s in topology['valid_sids']}
        for i in range(len(analysis)):
            e = analysis[i]
            if e['is_valid']:
                continue
            p = raw_packets[i]
            srh = p['srh']

            if "segments_left_exceeds_last_entry" in e['errors']:
                assert srh['segleft'] > srh['lastentry']

            if "destination_mismatch" in e['errors']:
                if srh['segleft'] <= srh['lastentry']:
                    active = _norm(srh['addresses'][srh['segleft']])
                    assert _norm(p['dst']) != active

            if "header_length_mismatch" in e['errors']:
                assert srh['len'] != 2 * (srh['lastentry'] + 1)

            if "invalid_sid" in e['errors']:
                assert any(_norm(s) not in valid_sids
                           for s in srh['addresses'])

    def test_path_matching_consistent(self, analysis, raw_packets, topology):
        """Forward-order segment reconstruction and path matching verified."""
        path_map = {p['name']: [_norm(s) for s in p['segments']]
                    for p in topology['valid_paths']}
        for i, e in enumerate(analysis):
            p = raw_packets[i]
            srh = p['srh']
            forward = list(reversed(
                [_norm(a) for a in srh['addresses']]))

            if e['matched_path'] is not None:
                assert e['matched_path'] in path_map
                assert path_map[e['matched_path']] == forward, \
                    (f"Packet {i}: matched_path={e['matched_path']} "
                     f"but forward segments {forward} don't match")
            else:
                for name, segs in path_map.items():
                    assert segs != forward, \
                        (f"Packet {i}: matched_path is null but "
                         f"segments match {name}")

    def test_violation_score_computation(self, analysis, topology):
        """Violation score must equal sum of per-error weights."""
        weights = topology['violation_weights']
        total = 0
        for e in analysis:
            for err in e['errors']:
                total += weights.get(err, 0)
        assert total == EXPECTED_SUMMARY['violation_score']
