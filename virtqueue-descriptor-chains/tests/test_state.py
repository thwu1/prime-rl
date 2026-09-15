
import json
import os
import pytest

REPORT_PATH = "/app/analysis_report.json"


def normalize_mac(mac_str):
    """Normalize MAC to lowercase colon-separated."""
    m = str(mac_str).strip().lower().replace('-', ':')
    return m


def parse_ethertype(et):
    """Parse ethertype to integer."""
    s = str(et).strip().lower()
    if s.startswith('0x'):
        return int(s, 16)
    try:
        return int(s)
    except ValueError:
        return int(s, 16)


@pytest.fixture(scope='session')
def report():
    with open(REPORT_PATH, 'r') as f:
        return json.load(f)


# =====================================================================
# Report Structure
# =====================================================================

class TestReportStructure:
    def test_file_exists(self):
        assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"

    def test_valid_json(self):
        with open(REPORT_PATH, 'r') as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_has_required_sections(self, report):
        for key in ('device', 'features', 'queues', 'packets', 'crash'):
            assert key in report, f"Missing top-level key: {key}"


# =====================================================================
# Device Information
# =====================================================================

class TestDeviceInfo:
    def test_mac_address(self, report):
        mac = report['device']['mac']
        assert normalize_mac(mac) == "52:54:00:12:34:56"

    def test_device_status(self, report):
        status = int(report['device']['status'])
        assert status == 79, f"Expected status 79 (0x4F), got {status}"

    def test_mtu(self, report):
        assert int(report['device']['mtu']) == 1500

    def test_num_queues(self, report):
        assert int(report['device']['num_queues']) == 3


# =====================================================================
# Feature Negotiation
# =====================================================================

class TestFeatures:
    def test_feature_word0(self, report):
        w0 = int(report['features']['word0'])
        assert w0 == 491560, f"Expected 491560 (0x78028), got {w0} (0x{w0:x})"

    def test_feature_word1(self, report):
        w1 = int(report['features']['word1'])
        assert w1 == 1, f"Expected 1 (VIRTIO_F_VERSION_1), got {w1}"


# =====================================================================
# Queue Analysis
# =====================================================================

class TestQueueAnalysis:
    def _find_queue(self, report, index):
        for q in report['queues']:
            if int(q['index']) == index:
                return q
        pytest.fail(f"Queue {index} not found in report")

    def test_three_queues_reported(self, report):
        assert len(report['queues']) == 3

    # --- Queue 0 (RX) ---
    def test_q0_size(self, report):
        assert int(self._find_queue(report, 0)['size']) == 256

    def test_q0_avail_idx(self, report):
        assert int(self._find_queue(report, 0)['avail_idx']) == 128

    def test_q0_used_idx(self, report):
        assert int(self._find_queue(report, 0)['used_idx']) == 3

    def test_q0_no_errors(self, report):
        q = self._find_queue(report, 0)
        assert len(q.get('errors', [])) == 0, "RX queue should have no chain errors"

    # --- Queue 1 (TX) ---
    def test_q1_size(self, report):
        assert int(self._find_queue(report, 1)['size']) == 256

    def test_q1_avail_idx(self, report):
        assert int(self._find_queue(report, 1)['avail_idx']) == 5

    def test_q1_used_idx(self, report):
        assert int(self._find_queue(report, 1)['used_idx']) == 1

    def test_q1_has_errors(self, report):
        q = self._find_queue(report, 1)
        errors = q.get('errors', [])
        assert len(errors) >= 2, f"TX queue should have >=2 errors, got {len(errors)}"

    def test_q1_circular_chain_at_head3(self, report):
        q = self._find_queue(report, 1)
        found = False
        for e in q.get('errors', []):
            if int(e.get('chain_head', -1)) == 3:
                etype = str(e.get('type', '')).lower()
                assert 'circular' in etype or 'cycle' in etype, \
                    f"Error at chain_head 3 should be circular/cycle, got: {etype}"
                found = True
        assert found, "Missing circular chain error at head 3"

    def test_q1_oob_at_head8(self, report):
        q = self._find_queue(report, 1)
        found = False
        for e in q.get('errors', []):
            if int(e.get('chain_head', -1)) == 8:
                etype = str(e.get('type', '')).lower()
                assert any(k in etype for k in ['invalid', 'out_of_bounds', 'oob', 'bound']), \
                    f"Error at chain_head 8 should be out-of-bounds, got: {etype}"
                found = True
        assert found, "Missing out-of-bounds error at head 8"

    # --- Queue 2 (CTL) ---
    def test_q2_size(self, report):
        assert int(self._find_queue(report, 2)['size']) == 64

    def test_q2_avail_idx(self, report):
        assert int(self._find_queue(report, 2)['avail_idx']) == 0

    def test_q2_used_idx(self, report):
        assert int(self._find_queue(report, 2)['used_idx']) == 0

    def test_q2_no_errors(self, report):
        q = self._find_queue(report, 2)
        assert len(q.get('errors', [])) == 0, "CTL queue should have no chain errors"


# =====================================================================
# Packet Forensics
# =====================================================================

class TestPacketForensics:
    # --- TX packets ---
    def test_tx_has_packets(self, report):
        tx = report['packets']['tx_sent']
        assert len(tx) >= 1, "Should have at least 1 TX packet from used ring"

    def test_tx_chain0_dst_mac(self, report):
        tx = report['packets']['tx_sent']
        p = next((p for p in tx if int(p['chain_head']) == 0), None)
        assert p is not None, "Missing TX packet for chain head 0"
        assert normalize_mac(p['dst_mac']) == "ff:ff:ff:ff:ff:ff"

    def test_tx_chain0_src_mac(self, report):
        tx = report['packets']['tx_sent']
        p = next((p for p in tx if int(p['chain_head']) == 0), None)
        assert p is not None
        assert normalize_mac(p['src_mac']) == "52:54:00:12:34:56"

    def test_tx_chain0_ethertype(self, report):
        tx = report['packets']['tx_sent']
        p = next((p for p in tx if int(p['chain_head']) == 0), None)
        assert p is not None
        assert parse_ethertype(p['ethertype']) == 0x0806, "Chain 0 should be ARP (0x0806)"

    # --- RX packets ---
    def test_rx_packet_count(self, report):
        rx = report['packets']['rx_received']
        assert len(rx) == 3, f"Expected 3 RX packets, got {len(rx)}"

    def test_rx_desc0_src_mac(self, report):
        rx = report['packets']['rx_received']
        p = next((p for p in rx if int(p['desc_id']) == 0), None)
        assert p is not None, "Missing RX packet for desc_id 0"
        assert normalize_mac(p['src_mac']) == "52:54:00:ab:cd:ef"

    def test_rx_desc0_ethertype(self, report):
        rx = report['packets']['rx_received']
        p = next((p for p in rx if int(p['desc_id']) == 0), None)
        assert p is not None
        assert parse_ethertype(p['ethertype']) == 0x0800

    def test_rx_desc1_src_mac(self, report):
        rx = report['packets']['rx_received']
        p = next((p for p in rx if int(p['desc_id']) == 1), None)
        assert p is not None, "Missing RX packet for desc_id 1"
        assert normalize_mac(p['src_mac']) == "52:54:00:fe:dc:ba"

    def test_rx_desc2_is_arp_broadcast(self, report):
        rx = report['packets']['rx_received']
        p = next((p for p in rx if int(p['desc_id']) == 2), None)
        assert p is not None, "Missing RX packet for desc_id 2"
        assert normalize_mac(p['dst_mac']) == "ff:ff:ff:ff:ff:ff"
        assert normalize_mac(p['src_mac']) == "52:54:00:11:22:33"
        assert parse_ethertype(p['ethertype']) == 0x0806


# =====================================================================
# Crash Diagnosis
# =====================================================================

class TestCrashDiagnosis:
    def test_crash_queue(self, report):
        assert int(report['crash']['queue_index']) == 1, "Crash triggered by TX queue (1)"

    def test_crash_timestamp(self, report):
        assert int(report['crash']['timestamp_ns']) == 1500000

    def test_msix_issues_present(self, report):
        issues = report['crash']['msix_issues']
        assert len(issues) >= 1, "Should report at least 1 MSI-X issue"

    def test_msix_vector2_flagged(self, report):
        issues = report['crash']['msix_issues']
        found = any(int(i.get('vector_index', -1)) == 2 for i in issues)
        assert found, "MSI-X vector 2 should be flagged (masked with zero address)"
