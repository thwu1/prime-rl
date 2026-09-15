
import json
import hashlib
import subprocess
import os
import time
import pytest


class TestRSAKeyPair:
    """Verify RSA key infrastructure is correctly set up."""

    def test_private_key_exists(self):
        assert os.path.exists('/app/auth/private.pem'), "private.pem not found"

    def test_public_key_exists(self):
        assert os.path.exists('/app/auth/public.pem'), "public.pem not found"

    def test_private_key_valid(self):
        r = subprocess.run(
            ['openssl', 'rsa', '-in', '/app/auth/private.pem', '-check', '-noout'],
            capture_output=True, text=True
        )
        assert r.returncode == 0, f"Invalid private key: {r.stderr}"

    def test_public_key_valid(self):
        r = subprocess.run(
            ['openssl', 'rsa', '-pubin', '-in', '/app/auth/public.pem', '-noout'],
            capture_output=True, text=True
        )
        assert r.returncode == 0, f"Invalid public key: {r.stderr}"

    def test_key_pair_matches(self):
        r1 = subprocess.run(
            ['openssl', 'rsa', '-in', '/app/auth/private.pem', '-modulus', '-noout'],
            capture_output=True, text=True
        )
        r2 = subprocess.run(
            ['openssl', 'rsa', '-pubin', '-in', '/app/auth/public.pem', '-modulus', '-noout'],
            capture_output=True, text=True
        )
        assert r1.returncode == 0 and r2.returncode == 0
        assert r1.stdout.strip() == r2.stdout.strip(), "Key pair modulus mismatch"

    def test_key_is_2048_bit(self):
        r = subprocess.run(
            ['openssl', 'rsa', '-in', '/app/auth/private.pem', '-text', '-noout'],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert '2048' in r.stdout, "Key is not 2048-bit"


class TestCredentials:
    """Verify iperf3 credential file has correct format and hashes."""

    def _load_credentials(self):
        with open('/app/auth/credentials.csv', 'r') as f:
            lines = [l.strip() for l in f.readlines()
                     if l.strip() and not l.strip().startswith('#')]
        users = {}
        for line in lines:
            parts = line.split(',', 1)
            assert len(parts) == 2, f"Invalid credential line: {line}"
            users[parts[0].strip()] = parts[1].strip()
        return users

    def test_credentials_file_exists(self):
        assert os.path.exists('/app/auth/credentials.csv')

    def test_three_users_present(self):
        users = self._load_credentials()
        assert len(users) >= 3, f"Expected at least 3 users, got {len(users)}"
        for name in ['alice', 'bob', 'charlie']:
            assert name in users, f"User '{name}' not found in credentials"

    def test_alice_hash(self):
        users = self._load_credentials()
        expected = hashlib.sha256(b'{alice}benchmark2024').hexdigest()
        assert users['alice'] == expected, (
            f"Hash mismatch for alice: got {users['alice']}, expected {expected}"
        )

    def test_bob_hash(self):
        users = self._load_credentials()
        expected = hashlib.sha256(b'{bob}netperf#secure').hexdigest()
        assert users['bob'] == expected, (
            f"Hash mismatch for bob: got {users['bob']}, expected {expected}"
        )

    def test_charlie_hash(self):
        users = self._load_credentials()
        expected = hashlib.sha256(b'{charlie}thr0ughput!').hexdigest()
        assert users['charlie'] == expected, (
            f"Hash mismatch for charlie: got {users['charlie']}, expected {expected}"
        )


class TestAnalysisReport:
    """Verify the performance analysis tool produces correct metrics."""

    @pytest.fixture(autouse=True, scope='class')
    def run_analyzer(self):
        """Run analyze.py before testing its output."""
        assert os.path.exists('/app/analyze.py'), "analyze.py not found"
        r = subprocess.run(
            ['python3', '/app/analyze.py'],
            capture_output=True, text=True, timeout=30
        )
        assert r.returncode == 0, f"analyze.py failed: {r.stderr}"
        assert os.path.exists('/app/analysis_report.json'), \
            "analysis_report.json not created by analyze.py"

    def _load_report(self):
        with open('/app/analysis_report.json', 'r') as f:
            return json.load(f)

    # --- TCP single-stream ---

    def test_tcp_single_sender_bps(self):
        tcp = self._load_report()['tcp_single']
        assert abs(tcp['sender_bps'] - 4194298368.82) < 100

    def test_tcp_single_receiver_bps(self):
        tcp = self._load_report()['tcp_single']
        assert abs(tcp['receiver_bps'] - 4192661815.67) < 100

    def test_tcp_single_retransmits(self):
        tcp = self._load_report()['tcp_single']
        assert tcp['retransmits'] == 15

    def test_tcp_single_retransmit_rate(self):
        tcp = self._load_report()['tcp_single']
        # 15 retransmits / 5000 MB = 0.003
        assert abs(tcp['retransmit_rate_per_mb'] - 0.003) < 0.0005

    def test_tcp_single_mean_rtt(self):
        tcp = self._load_report()['tcp_single']
        # 42 microseconds = 0.042 ms
        assert abs(tcp['mean_rtt_ms'] - 0.042) < 0.001

    def test_tcp_single_efficiency(self):
        tcp = self._load_report()['tcp_single']
        # receiver/sender * 100 ≈ 99.961%
        assert abs(tcp['throughput_efficiency'] - 99.961) < 0.1

    def test_tcp_single_cpu(self):
        tcp = self._load_report()['tcp_single']
        assert abs(tcp['cpu_host_total'] - 5.52) < 0.01

    def test_tcp_single_classification(self):
        tcp = self._load_report()['tcp_single']
        assert tcp['classification'] == 'optimal'

    # --- UDP ---

    def test_udp_sender_bps(self):
        udp = self._load_report()['udp_test']
        assert abs(udp['sender_bps'] - 9968071.29) < 100

    def test_udp_jitter(self):
        udp = self._load_report()['udp_test']
        assert abs(udp['jitter_ms'] - 0.052) < 0.001

    def test_udp_lost_packets(self):
        udp = self._load_report()['udp_test']
        assert udp['lost_packets'] == 3

    def test_udp_total_packets(self):
        udp = self._load_report()['udp_test']
        assert udp['total_packets'] == 8535

    def test_udp_lost_percent(self):
        udp = self._load_report()['udp_test']
        assert abs(udp['lost_percent'] - 0.035149) < 0.001

    def test_udp_out_of_order(self):
        udp = self._load_report()['udp_test']
        assert udp['out_of_order'] == 1

    def test_udp_cpu(self):
        udp = self._load_report()['udp_test']
        assert abs(udp['cpu_host_total'] - 0.85) < 0.01

    def test_udp_classification(self):
        udp = self._load_report()['udp_test']
        assert udp['classification'] == 'optimal'

    # --- TCP parallel ---

    def test_parallel_num_streams(self):
        par = self._load_report()['tcp_parallel']
        assert par['num_streams'] == 4

    def test_parallel_aggregate_sender(self):
        par = self._load_report()['tcp_parallel']
        assert abs(par['aggregate_sender_bps'] - 4000000000.0) < 1000

    def test_parallel_aggregate_receiver(self):
        par = self._load_report()['tcp_parallel']
        assert abs(par['aggregate_receiver_bps'] - 3998400000.0) < 1000

    def test_parallel_per_stream_count(self):
        par = self._load_report()['tcp_parallel']
        assert len(par['per_stream_sender_bps']) == 4

    def test_parallel_per_stream_values(self):
        par = self._load_report()['tcp_parallel']
        expected = sorted([1000000000.0, 950000000.0, 1050000000.0, 1000000000.0])
        actual = sorted(par['per_stream_sender_bps'])
        for a, e in zip(actual, expected):
            assert abs(a - e) < 1000, f"Stream bps mismatch: got {a}, expected {e}"

    def test_parallel_retransmits(self):
        par = self._load_report()['tcp_parallel']
        assert par['total_retransmits'] == 15

    def test_parallel_fairness(self):
        par = self._load_report()['tcp_parallel']
        # Jain's fairness for [1000, 950, 1050, 1000] Mbps ≈ 0.998752
        assert abs(par['jains_fairness_index'] - 0.998752) < 0.002

    def test_parallel_cpu(self):
        par = self._load_report()['tcp_parallel']
        assert abs(par['cpu_host_total'] - 12.34) < 0.01

    def test_parallel_classification(self):
        par = self._load_report()['tcp_parallel']
        assert par['classification'] == 'optimal'

    # --- TCP bidirectional ---

    def test_bidir_upload(self):
        bid = self._load_report()['tcp_bidir']
        assert abs(bid['upload_sender_bps'] - 3500000000.0) < 1000

    def test_bidir_download(self):
        bid = self._load_report()['tcp_bidir']
        assert abs(bid['download_sender_bps'] - 2800000000.0) < 1000

    def test_bidir_asymmetry(self):
        bid = self._load_report()['tcp_bidir']
        # 3500/2800 = 1.25
        assert abs(bid['asymmetry_ratio'] - 1.25) < 0.01

    def test_bidir_cpu(self):
        bid = self._load_report()['tcp_bidir']
        assert abs(bid['cpu_host_total'] - 18.76) < 0.01

    def test_bidir_classification(self):
        bid = self._load_report()['tcp_bidir']
        assert bid['classification'] == 'acceptable'


class TestCVEReport:
    """Verify CVE applicability assessment."""

    def _load_cve_report(self):
        with open('/app/cve_report.json', 'r') as f:
            return json.load(f)

    def test_cve_report_exists(self):
        assert os.path.exists('/app/cve_report.json')

    def test_all_cves_present(self):
        cve = self._load_cve_report()
        for cve_id in ['CVE-2023-38403', 'CVE-2024-26306',
                       'CVE-2024-53580', 'CVE-2025-54351']:
            assert cve_id in cve, f"Missing {cve_id} in CVE report"

    def test_cve_2023_38403_not_applicable(self):
        """Fixed in 3.14; version 3.16 is not affected."""
        entry = self._load_cve_report()['CVE-2023-38403']
        assert entry['applicable'] is False

    def test_cve_2024_26306_applicable(self):
        """Affects 3.2 through 3.16 inclusive; version 3.16 is affected."""
        entry = self._load_cve_report()['CVE-2024-26306']
        assert entry['applicable'] is True

    def test_cve_2024_53580_applicable(self):
        """Affects all versions prior to 3.18; version 3.16 is affected."""
        entry = self._load_cve_report()['CVE-2024-53580']
        assert entry['applicable'] is True

    def test_cve_2025_54351_not_applicable(self):
        """Only affects version 3.19; 3.16 does not have the feature."""
        entry = self._load_cve_report()['CVE-2025-54351']
        assert entry['applicable'] is False

    def test_cve_2023_38403_severity(self):
        entry = self._load_cve_report()['CVE-2023-38403']
        assert entry['severity'] == 'high'

    def test_cve_2024_26306_severity(self):
        entry = self._load_cve_report()['CVE-2024-26306']
        assert entry['severity'] == 'medium'

    def test_cve_2024_53580_severity(self):
        entry = self._load_cve_report()['CVE-2024-53580']
        assert entry['severity'] == 'high'

    def test_cve_2025_54351_severity(self):
        entry = self._load_cve_report()['CVE-2025-54351']
        assert entry['severity'] == 'high'

    def test_all_entries_have_reason(self):
        cve = self._load_cve_report()
        for cve_id, entry in cve.items():
            assert 'reason' in entry, f"Missing reason for {cve_id}"
            assert isinstance(entry['reason'], str)
            assert len(entry['reason']) > 10, f"Reason too short for {cve_id}"


class TestAuthenticatedTest:
    """Verify end-to-end authenticated iperf3 test works."""

    def test_auth_test_script_exists(self):
        assert os.path.exists('/app/run_auth_test.sh'), \
            "run_auth_test.sh not found"

    def test_auth_test_executes_successfully(self):
        # Clean up any leftover iperf3 processes
        subprocess.run(['pkill', '-9', 'iperf3'], capture_output=True)
        time.sleep(1)

        r = subprocess.run(
            ['bash', '/app/run_auth_test.sh'],
            capture_output=True, text=True, timeout=60
        )
        # Clean up again
        subprocess.run(['pkill', '-9', 'iperf3'], capture_output=True)

        assert r.returncode == 0, (
            f"Auth test failed (exit {r.returncode}): "
            f"stdout={r.stdout[-500:]}, stderr={r.stderr[-500:]}"
        )

    def test_auth_test_output_valid(self):
        assert os.path.exists('/app/auth_test_result.json'), \
            "auth_test_result.json not created"

        with open('/app/auth_test_result.json', 'r') as f:
            content = f.read().strip()
        assert len(content) > 0, "auth_test_result.json is empty"

        result = json.loads(content)
        assert 'start' in result, "Missing 'start' in auth test result"
        assert 'end' in result, "Missing 'end' in auth test result"
