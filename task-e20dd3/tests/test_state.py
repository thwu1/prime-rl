"""
TCP Host Profiler — verification tests.

Runs the profiler against the synthetic capture and validates OS
identification, p0f signatures, clock analysis, NAT detection,
hop distance estimation, filtering, and output format.

"""
import subprocess
import json
import pytest

OUTPUT_PATH = '/tmp/test_report.json'
REPORT = None
SETUP_ERROR = None


def setup_module():
    global REPORT, SETUP_ERROR
    try:
        result = subprocess.run(
            ['python3', '/app/profiler.py', '/app/capture.pcap',
             '/app/fingerprints.db', OUTPUT_PATH],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            SETUP_ERROR = (
                f"profiler.py exited {result.returncode}:\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
            return
        with open(OUTPUT_PATH) as f:
            REPORT = json.load(f)
    except FileNotFoundError:
        SETUP_ERROR = "/app/profiler.py not found"
    except Exception as e:
        SETUP_ERROR = str(e)


def _require():
    if SETUP_ERROR:
        pytest.fail(f"Setup: {SETUP_ERROR}")
    assert REPORT is not None


def _host(ip):
    for h in REPORT:
        if h.get('ip') == ip:
            return h
    return None


def _sig_fields(sig):
    parts = sig.split(':')
    assert len(parts) == 8, f"Signature has {len(parts)} parts: {sig}"
    return {
        'ver': parts[0],
        'ittl': parts[1],
        'olen': parts[2],
        'mss': parts[3],
        'wsize_scale': parts[4],
        'olayout': parts[5],
        'quirks': set(parts[6].split(',')) if parts[6] else set(),
        'pclass': parts[7],
    }


def _assert_sig(observed, expected):
    o = _sig_fields(observed)
    e = _sig_fields(expected)
    for k in ('ver', 'ittl', 'olen', 'mss', 'wsize_scale', 'olayout', 'pclass'):
        assert o[k] == e[k], (
            f"Signature field '{k}': got '{o[k]}', expected '{e[k]}' "
            f"(full: {observed} vs {expected})"
        )
    assert o['quirks'] == e['quirks'], (
        f"Quirks mismatch: got {o['quirks']}, expected {e['quirks']}"
    )


# Expected signatures
LINUX_SIG = '4:64:0:1460:mss*10,7:mss,sok,ts,nop,ws:df,id+:0'
LINUX_1400_SIG = '4:64:0:1400:mss*10,7:mss,sok,ts,nop,ws:df,id+:0'
WINDOWS_SIG = '4:128:0:1460:8192,8:mss,nop,ws,nop,nop,sok:df,id+:0'
MACOS_SIG = '4:64:0:1460:65535,6:mss,nop,ws,nop,nop,ts,sok,eol+1:df:0'


# ---------------------------------------------------------------------------
# Report structure
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_is_list(self):
        _require()
        assert isinstance(REPORT, list)

    def test_host_count(self):
        """19 packets total, only 15 SYN-only, from 4 distinct IPs."""
        _require()
        assert len(REPORT) == 4, f"Expected 4 hosts, got {len(REPORT)}"

    def test_sorted_by_ip(self):
        _require()
        ips = [h['ip'] for h in REPORT]
        assert ips == sorted(ips), f"Not sorted: {ips}"

    def test_required_fields(self):
        _require()
        required = {'ip', 'os', 'signature', 'distance',
                     'uptime_seconds', 'timestamp_frequency_hz',
                     'nat_detected', 'syn_count'}
        for h in REPORT:
            missing = required - set(h.keys())
            assert not missing, f"Missing fields in {h['ip']}: {missing}"


# ---------------------------------------------------------------------------
# Host A: Linux 4.x, direct connection
# ---------------------------------------------------------------------------

class TestLinuxDirect:
    IP = '10.0.0.1'

    def test_present(self):
        _require()
        assert _host(self.IP) is not None

    def test_os(self):
        _require()
        assert _host(self.IP)['os'] == 's:Linux:4.x:'

    def test_signature(self):
        _require()
        _assert_sig(_host(self.IP)['signature'], LINUX_SIG)

    def test_distance_zero(self):
        _require()
        assert _host(self.IP)['distance'] == 0

    def test_uptime(self):
        """TSval starts at 1000000, freq 250 Hz -> uptime ~4000s."""
        _require()
        h = _host(self.IP)
        assert h['uptime_seconds'] is not None
        assert abs(h['uptime_seconds'] - 4000) <= 10

    def test_frequency(self):
        """5 SYN packets 1s apart, TSval increments of 250 -> 250 Hz."""
        _require()
        h = _host(self.IP)
        assert h['timestamp_frequency_hz'] is not None
        assert abs(h['timestamp_frequency_hz'] - 250) <= 5

    def test_not_nat(self):
        _require()
        assert _host(self.IP)['nat_detected'] is False

    def test_syn_count(self):
        _require()
        assert _host(self.IP)['syn_count'] == 5


# ---------------------------------------------------------------------------
# Host B: Windows 10, 3 hops
# ---------------------------------------------------------------------------

class TestWindowsRemote:
    IP = '192.168.1.100'

    def test_present(self):
        _require()
        assert _host(self.IP) is not None

    def test_os(self):
        _require()
        assert _host(self.IP)['os'] == 's:Windows:10:'

    def test_signature(self):
        _require()
        _assert_sig(_host(self.IP)['signature'], WINDOWS_SIG)

    def test_distance(self):
        """TTL=125, ittl=128, distance=3."""
        _require()
        assert _host(self.IP)['distance'] == 3

    def test_no_timestamps(self):
        """Windows SYN has no timestamp option -> null clock."""
        _require()
        h = _host(self.IP)
        assert h['uptime_seconds'] is None
        assert h['timestamp_frequency_hz'] is None

    def test_not_nat(self):
        _require()
        assert _host(self.IP)['nat_detected'] is False

    def test_syn_count(self):
        _require()
        assert _host(self.IP)['syn_count'] == 3

    def test_window_literal(self):
        """Window=8192, MSS=1460 -> not a multiple, should be literal."""
        _require()
        fields = _sig_fields(_host(self.IP)['signature'])
        wsize = fields['wsize_scale'].split(',')[0]
        assert wsize == '8192', f"Expected literal 8192, got {wsize}"


# ---------------------------------------------------------------------------
# Host C: NAT gateway (mixed Linux + macOS)
# ---------------------------------------------------------------------------

class TestNATGateway:
    IP = '172.16.0.1'

    def test_present(self):
        _require()
        assert _host(self.IP) is not None

    def test_nat_detected(self):
        _require()
        assert _host(self.IP)['nat_detected'] is True

    def test_signatures_array_exists(self):
        _require()
        h = _host(self.IP)
        assert 'signatures' in h, "NAT host missing 'signatures' array"

    def test_signatures_count(self):
        _require()
        assert len(_host(self.IP)['signatures']) == 2

    def test_linux_sig_in_array(self):
        _require()
        sigs = _host(self.IP)['signatures']
        has_linux = any(
            _sig_fields(s)['olayout'] == 'mss,sok,ts,nop,ws'
            for s in sigs
        )
        assert has_linux, "Linux signature not in NAT signatures"

    def test_macos_sig_in_array(self):
        _require()
        sigs = _host(self.IP)['signatures']
        has_macos = any(
            'eol+1' in _sig_fields(s)['olayout']
            for s in sigs
        )
        assert has_macos, "macOS signature not in NAT signatures"

    def test_primary_os(self):
        """Linux has 3/4 SYNs -> most frequent -> primary OS."""
        _require()
        assert _host(self.IP)['os'] == 's:Linux:4.x:'

    def test_nat_nulls_clock(self):
        """NAT host should have null clock fields."""
        _require()
        h = _host(self.IP)
        assert h['uptime_seconds'] is None
        assert h['timestamp_frequency_hz'] is None

    def test_syn_count(self):
        _require()
        assert _host(self.IP)['syn_count'] == 4

    def test_distance(self):
        _require()
        assert _host(self.IP)['distance'] == 0

    def test_signatures_sorted(self):
        """Signatures array must be sorted."""
        _require()
        sigs = _host(self.IP)['signatures']
        assert sigs == sorted(sigs), f"Not sorted: {sigs}"

    def test_macos_no_id_plus(self):
        """macOS packet has ID=0, DF=1 -> only 'df', no 'id+'."""
        _require()
        sigs = _host(self.IP)['signatures']
        for s in sigs:
            f = _sig_fields(s)
            if 'eol+1' in f['olayout']:
                assert 'df' in f['quirks'], "macOS sig should have df"
                assert 'id+' not in f['quirks'], "macOS sig should not have id+"


# ---------------------------------------------------------------------------
# Host D: Linux 4.x, 9 hops, MSS=1400
# ---------------------------------------------------------------------------

class TestLinuxRemote:
    IP = '10.1.1.1'

    def test_present(self):
        _require()
        assert _host(self.IP) is not None

    def test_os(self):
        _require()
        assert _host(self.IP)['os'] == 's:Linux:4.x:'

    def test_distance(self):
        """TTL=55, ittl=64, distance=9."""
        _require()
        assert _host(self.IP)['distance'] == 9

    def test_ittl_normalized(self):
        """Observed TTL 55 normalizes to initial TTL 64."""
        _require()
        fields = _sig_fields(_host(self.IP)['signature'])
        assert fields['ittl'] == '64'

    def test_mss(self):
        """MSS=1400 (different from standard 1460)."""
        _require()
        fields = _sig_fields(_host(self.IP)['signature'])
        assert fields['mss'] == '1400'

    def test_window_mss_ratio(self):
        """Window=14000, MSS=1400 -> mss*10."""
        _require()
        fields = _sig_fields(_host(self.IP)['signature'])
        wsize = fields['wsize_scale'].split(',')[0]
        assert wsize == 'mss*10', f"Expected mss*10, got {wsize}"

    def test_uptime(self):
        """TSval starts at 3000000, freq 250 Hz -> uptime ~12000s."""
        _require()
        h = _host(self.IP)
        assert h['uptime_seconds'] is not None
        assert abs(h['uptime_seconds'] - 12000) <= 10

    def test_frequency(self):
        _require()
        h = _host(self.IP)
        assert h['timestamp_frequency_hz'] is not None
        assert abs(h['timestamp_frequency_hz'] - 250) <= 5

    def test_not_nat(self):
        _require()
        assert _host(self.IP)['nat_detected'] is False

    def test_syn_count(self):
        _require()
        assert _host(self.IP)['syn_count'] == 3


# ---------------------------------------------------------------------------
# Signature format and types
# ---------------------------------------------------------------------------

class TestSignatureFormat:
    def test_all_sigs_have_8_fields(self):
        _require()
        for h in REPORT:
            parts = h['signature'].split(':')
            assert len(parts) == 8, (
                f"Sig has {len(parts)} parts for {h['ip']}: {h['signature']}"
            )

    def test_pclass_zero(self):
        """All test SYN packets carry no payload."""
        _require()
        for h in REPORT:
            assert _sig_fields(h['signature'])['pclass'] == '0'

    def test_all_ipv4(self):
        _require()
        for h in REPORT:
            assert _sig_fields(h['signature'])['ver'] == '4'

    def test_no_ip_options(self):
        _require()
        for h in REPORT:
            assert _sig_fields(h['signature'])['olen'] == '0'


class TestFieldTypes:
    def test_distance_int(self):
        _require()
        for h in REPORT:
            assert isinstance(h['distance'], int), f"{h['ip']}: {type(h['distance'])}"

    def test_syn_count_int(self):
        _require()
        for h in REPORT:
            assert isinstance(h['syn_count'], int), f"{h['ip']}: {type(h['syn_count'])}"

    def test_nat_bool(self):
        _require()
        for h in REPORT:
            assert isinstance(h['nat_detected'], bool), f"{h['ip']}: {type(h['nat_detected'])}"

    def test_uptime_int_or_none(self):
        _require()
        for h in REPORT:
            v = h['uptime_seconds']
            assert v is None or isinstance(v, int), f"{h['ip']}: uptime={type(v)}"

    def test_freq_int_or_none(self):
        _require()
        for h in REPORT:
            v = h['timestamp_frequency_hz']
            assert v is None or isinstance(v, int), f"{h['ip']}: freq={type(v)}"


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

class TestFiltering:
    def test_no_noise_ips(self):
        """Only 4 IPs should appear — noise traffic filtered."""
        _require()
        ips = {h['ip'] for h in REPORT}
        expected = {'10.0.0.1', '10.1.1.1', '172.16.0.1', '192.168.1.100'}
        assert ips == expected, f"Unexpected IPs: {ips - expected}"

    def test_total_syn_count(self):
        """15 SYN-only packets across 4 hosts."""
        _require()
        total = sum(h['syn_count'] for h in REPORT)
        assert total == 15, f"Expected 15 total SYNs, got {total}"
