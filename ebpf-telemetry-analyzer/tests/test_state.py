
import json
import os
import pytest

REPORT_PATH = '/app/report.json'


@pytest.fixture(scope='session')
def report():
    assert os.path.exists(REPORT_PATH), f"Report file not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict), "Report must be a JSON object"
    return data


def find_conn(report, src_ip, src_port, dst_ip, dst_port):
    for c in report['connections']:
        if (c['src_ip'] == src_ip and c['src_port'] == src_port and
                c['dst_ip'] == dst_ip and c['dst_port'] == dst_port):
            return c
    return None


def find_dns_corr(report, query_id):
    for c in report['dns_correlations']:
        if c['query_id'] == query_id:
            return c
    return None


# =====================================================================
# Connection Parsing
# =====================================================================
class TestConnectionParsing:
    def test_total_connections(self, report):
        assert len(report['connections']) == 12

    def test_tcp_connections(self, report):
        tcp = [c for c in report['connections'] if c['proto'] == 'TCP']
        assert len(tcp) == 10

    def test_udp_connections(self, report):
        udp = [c for c in report['connections'] if c['proto'] == 'UDP']
        assert len(udp) == 2

    def test_connection_ips(self, report):
        """All expected source IPs present with correct multiplicity."""
        src_ips = sorted(c['src_ip'] for c in report['connections'])
        expected = sorted([
            '10.0.1.10', '10.0.1.11', '10.0.1.12', '10.0.1.13',
            '10.0.1.14', '10.0.1.15', '10.0.1.16', '10.0.1.17',
            '10.0.1.18', '10.0.1.19', '10.0.1.20', '10.0.1.10',
        ])
        assert src_ips == expected

    def test_healthy_http_connection(self, report):
        conn = find_conn(report, '10.0.1.10', 45000, '10.0.2.10', 80)
        assert conn is not None, "conn1 not found"
        assert conn['proto'] == 'TCP'
        assert conn['bytes_tx'] == 524288
        assert conn['bytes_rx'] == 1048576
        assert conn['packets_tx'] == 512
        assert conn['packets_rx'] == 1024
        assert conn['direction'] == 'egress'

    def test_half_open_connection(self, report):
        conn = find_conn(report, '10.0.1.11', 45001, '10.0.2.10', 80)
        assert conn is not None, "conn2 not found"
        assert conn['bytes_rx'] == 0
        assert conn['packets_rx'] == 0
        assert conn['flags_summary']['tx']['syn'] == 3
        assert conn['flags_summary']['rx']['syn'] == 0

    def test_rst_storm_connection(self, report):
        conn = find_conn(report, '10.0.1.12', 45002, '10.0.2.11', 443)
        assert conn is not None, "conn3 not found"
        assert conn['flags_summary']['tx']['rst'] == 15
        assert conn['flags_summary']['rx']['rst'] == 12

    def test_udp_dns_connection(self, report):
        conn = find_conn(report, '10.0.1.13', 45003, '10.0.2.12', 53)
        assert conn is not None, "conn4 not found"
        assert conn['proto'] == 'UDP'
        assert conn['bytes_tx'] == 64
        assert conn['bytes_rx'] == 256

    def test_asymmetric_connection(self, report):
        conn = find_conn(report, '10.0.1.16', 45006, '10.0.2.14', 3306)
        assert conn is not None, "conn7 not found"
        assert conn['bytes_tx'] == 10485760
        assert conn['bytes_rx'] == 4096

    def test_direction_unknown(self, report):
        conn = find_conn(report, '10.0.1.18', 45009, '10.0.2.16', 9090)
        assert conn is not None, "conn10 not found"
        assert conn['is_direction_unknown'] is True

    def test_ingress_connection(self, report):
        conn = find_conn(report, '10.0.1.19', 45010, '10.0.2.17', 22)
        assert conn is not None, "conn11 not found"
        assert conn['direction'] == 'ingress'

    def test_redis_connection_bytes(self, report):
        conn = find_conn(report, '10.0.1.10', 45008, '10.0.2.15', 6379)
        assert conn is not None, "conn9 not found"
        assert conn['bytes_tx'] == 524288
        assert conn['bytes_rx'] == 524288
        assert conn['packets_tx'] == 1500
        assert conn['packets_rx'] == 1500

    def test_fin_wait_connection_flags(self, report):
        conn = find_conn(report, '10.0.1.20', 45011, '10.0.2.18', 5432)
        assert conn is not None, "conn12 not found"
        assert conn['flags_summary']['tx']['fin'] == 1
        assert conn['flags_summary']['rx']['fin'] == 0
        assert conn['is_closing'] is True


# =====================================================================
# TCP State Machine
# =====================================================================
class TestTcpStateMachine:
    def test_time_wait_state(self, report):
        """conn1: both FIN seen -> TIME_WAIT"""
        conn = find_conn(report, '10.0.1.10', 45000, '10.0.2.10', 80)
        assert conn['state'] == 'TIME_WAIT'

    def test_syn_sent_state(self, report):
        """conn2: SYN TX only -> SYN_SENT"""
        conn = find_conn(report, '10.0.1.11', 45001, '10.0.2.10', 80)
        assert conn['state'] == 'SYN_SENT'

    def test_reset_state(self, report):
        """conn3: RST present -> RESET (priority over FIN/SYN)"""
        conn = find_conn(report, '10.0.1.12', 45002, '10.0.2.11', 443)
        assert conn['state'] == 'RESET'

    def test_established_state(self, report):
        """conn9: SYN both ways, no FIN/RST -> ESTABLISHED"""
        conn = find_conn(report, '10.0.1.10', 45008, '10.0.2.15', 6379)
        assert conn['state'] == 'ESTABLISHED'

    def test_established_no_syn(self, report):
        """conn10: no SYN either way, pre-existing -> ESTABLISHED"""
        conn = find_conn(report, '10.0.1.18', 45009, '10.0.2.16', 9090)
        assert conn['state'] == 'ESTABLISHED'

    def test_fin_wait_state(self, report):
        """conn12: FIN TX but not RX -> FIN_WAIT"""
        conn = find_conn(report, '10.0.1.20', 45011, '10.0.2.18', 5432)
        assert conn['state'] == 'FIN_WAIT'

    def test_udp_active_state(self, report):
        """UDP connections -> ACTIVE"""
        conn = find_conn(report, '10.0.1.13', 45003, '10.0.2.12', 53)
        assert conn['state'] == 'ACTIVE'

    def test_time_wait_with_retransmits(self, report):
        """conn6: both FIN -> TIME_WAIT despite heavy retransmits"""
        conn = find_conn(report, '10.0.1.15', 45005, '10.0.2.13', 8080)
        assert conn['state'] == 'TIME_WAIT'


# =====================================================================
# Anomaly Detection
# =====================================================================
class TestAnomalyDetection:
    def test_total_anomaly_count(self, report):
        assert len(report['anomalies']) == 6

    def test_half_open_anomaly(self, report):
        anomalies = [a for a in report['anomalies'] if a['type'] == 'half_open']
        assert len(anomalies) == 1
        assert '10.0.1.11:45001' in anomalies[0]['connection']

    def test_rst_storm_anomaly(self, report):
        anomalies = [a for a in report['anomalies'] if a['type'] == 'rst_storm']
        assert len(anomalies) == 1
        assert '10.0.1.12:45002' in anomalies[0]['connection']

    def test_retransmit_heavy_anomaly(self, report):
        anomalies = [a for a in report['anomalies'] if a['type'] == 'retransmit_heavy']
        assert len(anomalies) == 1
        assert '10.0.1.15:45005' in anomalies[0]['connection']

    def test_dns_no_response_anomaly(self, report):
        anomalies = [a for a in report['anomalies'] if a['type'] == 'dns_no_response']
        assert len(anomalies) == 1
        assert '10.0.1.14:45004' in anomalies[0]['connection']

    def test_asymmetric_flow_anomaly(self, report):
        anomalies = [a for a in report['anomalies'] if a['type'] == 'asymmetric_flow']
        assert len(anomalies) == 1
        assert '10.0.1.16:45006' in anomalies[0]['connection']

    def test_fin_not_acked_anomaly(self, report):
        anomalies = [a for a in report['anomalies'] if a['type'] == 'fin_not_acked']
        assert len(anomalies) == 1
        assert '10.0.1.20:45011' in anomalies[0]['connection']

    def test_no_false_positives_healthy(self, report):
        """Healthy connections should not trigger anomalies."""
        anomaly_conns = set(a['connection'] for a in report['anomalies'])
        # conn1 (healthy HTTP) should not appear
        assert not any('10.0.1.10:45000' in c for c in anomaly_conns)
        # conn9 (healthy Redis) should not appear
        assert not any('10.0.1.10:45008' in c for c in anomaly_conns)
        # conn11 (healthy SSH) should not appear
        assert not any('10.0.1.19:45010' in c for c in anomaly_conns)


# =====================================================================
# DNS Correlation
# =====================================================================
class TestDnsCorrelation:
    def test_dns_correlations_count(self, report):
        assert len(report['dns_correlations']) == 4

    def test_matched_query_noerror(self, report):
        """Query 0x1234 matched with NOERROR, 2 answers"""
        corr = find_dns_corr(report, 0x1234)
        assert corr is not None
        assert corr['has_response'] is True
        assert corr['response_code'] == 'NOERROR'
        assert corr['answer_count'] == 2
        assert corr['query_type'] == 'A'

    def test_unmatched_query(self, report):
        """Query 0x5678 has no response"""
        corr = find_dns_corr(report, 0x5678)
        assert corr is not None
        assert corr['has_response'] is False

    def test_nxdomain_response(self, report):
        """Query 0xABCD got NXDOMAIN"""
        corr = find_dns_corr(report, 0xABCD)
        assert corr is not None
        assert corr['has_response'] is True
        assert corr['response_code'] == 'NXDOMAIN'
        assert corr['answer_count'] == 0
        assert corr['query_type'] == 'AAAA'

    def test_matched_query_single_answer(self, report):
        """Query 0xBEEF matched with NOERROR, 1 answer"""
        corr = find_dns_corr(report, 0xBEEF)
        assert corr is not None
        assert corr['has_response'] is True
        assert corr['response_code'] == 'NOERROR'
        assert corr['answer_count'] == 1

    def test_dns_latency(self, report):
        """Matched queries should have latency_ns."""
        corr = find_dns_corr(report, 0x1234)
        assert 'latency_ns' in corr
        assert corr['latency_ns'] == 500

        corr2 = find_dns_corr(report, 0xABCD)
        assert corr2['latency_ns'] == 100


# =====================================================================
# DNS Query Names (from pcap)
# =====================================================================
class TestDnsQueryNames:
    def test_query_name_api(self, report):
        """Query 0x1234 should have domain name from pcap."""
        corr = find_dns_corr(report, 0x1234)
        assert corr is not None
        assert corr['query_name'] == 'api.cluster.local'

    def test_query_name_db(self, report):
        """Query 0x5678 should have domain name from pcap."""
        corr = find_dns_corr(report, 0x5678)
        assert corr is not None
        assert corr['query_name'] == 'db.internal.svc'

    def test_query_name_cache(self, report):
        """Query 0xABCD should have domain name from pcap."""
        corr = find_dns_corr(report, 0xABCD)
        assert corr is not None
        assert corr['query_name'] == 'cache.external.io'

    def test_query_name_metrics(self, report):
        """Query 0xBEEF should have domain name from pcap."""
        corr = find_dns_corr(report, 0xBEEF)
        assert corr is not None
        assert corr['query_name'] == 'metrics.cluster.local'


# =====================================================================
# PCAP Analysis
# =====================================================================
class TestPcapAnalysis:
    def test_pcap_analysis_exists(self, report):
        assert 'pcap_analysis' in report
        assert isinstance(report['pcap_analysis'], dict)

    def test_total_packets(self, report):
        assert report['pcap_analysis']['total_packets'] == 13

    def test_capture_duration(self, report):
        assert report['pcap_analysis']['capture_duration_secs'] == 6


# =====================================================================
# Drop Events
# =====================================================================
class TestDropEvents:
    def test_drop_count(self, report):
        assert len(report['drops']) == 4

    def test_total_drop_packets(self, report):
        total = sum(d['count'] for d in report['drops'])
        assert total == 11

    def test_total_drop_bytes(self, report):
        total = sum(d['bytes'] for d in report['drops'])
        assert total == 2864

    def test_drop_type_names(self, report):
        names = set(d['drop_type_name'] for d in report['drops'])
        assert 'IPTABLES_RULE_DROP' in names
        assert 'CONNTRACK_DROP' in names
        assert 'TCP_CONNECT_BASIC' in names
        assert 'UNKNOWN_DROP' in names

    def test_drop_return_vals(self, report):
        """Verify signed return values parsed correctly."""
        iptables = [d for d in report['drops'] if d['drop_type_name'] == 'IPTABLES_RULE_DROP']
        assert len(iptables) == 1
        assert iptables[0]['return_val'] == -1

        conntrack = [d for d in report['drops'] if d['drop_type_name'] == 'CONNTRACK_DROP']
        assert len(conntrack) == 1
        assert conntrack[0]['return_val'] == -110


# =====================================================================
# Retransmit Enrichment
# =====================================================================
class TestRetransmitEnrichment:
    def test_retransmit_count_heavy(self, report):
        """conn6 should have 25 retransmits"""
        conn = find_conn(report, '10.0.1.15', 45005, '10.0.2.13', 8080)
        assert conn['retransmit_count'] == 25

    def test_retransmit_count_rst_storm(self, report):
        """conn3 should have 2 retransmits"""
        conn = find_conn(report, '10.0.1.12', 45002, '10.0.2.11', 443)
        assert conn['retransmit_count'] == 2

    def test_retransmit_count_dropped(self, report):
        """conn8 should have 1 retransmit"""
        conn = find_conn(report, '10.0.1.17', 45007, '10.0.2.10', 80)
        assert conn['retransmit_count'] == 1

    def test_retransmit_count_healthy(self, report):
        """conn1 should have 0 retransmits"""
        conn = find_conn(report, '10.0.1.10', 45000, '10.0.2.10', 80)
        assert conn['retransmit_count'] == 0

    def test_retransmit_count_udp(self, report):
        """UDP connections should have 0 retransmits"""
        conn = find_conn(report, '10.0.1.13', 45003, '10.0.2.12', 53)
        assert conn['retransmit_count'] == 0


# =====================================================================
# Summary Statistics
# =====================================================================
class TestSummary:
    def test_total_connections(self, report):
        assert report['summary']['total_connections'] == 12

    def test_tcp_udp_split(self, report):
        assert report['summary']['tcp_connections'] == 10
        assert report['summary']['udp_connections'] == 2

    def test_total_bytes_tx(self, report):
        assert report['summary']['total_bytes_tx'] == 14004532

    def test_total_bytes_rx(self, report):
        assert report['summary']['total_bytes_rx'] == 2976000

    def test_total_packets_tx(self, report):
        assert report['summary']['total_packets_tx'] == 9671

    def test_total_packets_rx(self, report):
        assert report['summary']['total_packets_rx'] == 4661

    def test_total_retransmits(self, report):
        assert report['summary']['total_retransmits'] == 28

    def test_drop_summary(self, report):
        assert report['summary']['total_drop_count'] == 11
        assert report['summary']['total_drop_bytes'] == 2864

    def test_dns_summary(self, report):
        assert report['summary']['dns_queries'] == 4
        assert report['summary']['dns_responses'] == 3

    def test_anomaly_summary(self, report):
        assert report['summary']['total_anomalies'] == 6
        assert report['summary']['connections_with_anomalies'] == 6

    def test_anomaly_types_list(self, report):
        types = set(report['summary']['anomaly_types'])
        expected = {'half_open', 'rst_storm', 'retransmit_heavy',
                    'dns_no_response', 'asymmetric_flow', 'fin_not_acked'}
        assert types == expected
