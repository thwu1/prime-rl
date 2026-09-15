
import json
import math
import os
import sqlite3
import subprocess
import pytest


# ========== Reference implementations for anti-cheat ==========

def ref_crc24(data):
    crc = 0
    for byte in data:
        crc ^= (byte << 16)
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1FFF409
    return crc & 0xFFFFFF


def ref_nl(lat):
    lat = abs(lat)
    if lat >= 87.0:
        return 1
    if lat < 1e-14:
        return 60
    nz = 15
    a = 1 - math.cos(math.pi / (2 * nz))
    b = math.cos(math.pi * lat / 180.0) ** 2
    val = 1 - a / b
    if val < -1 or val > 1:
        return 1
    return int(math.floor(2 * math.pi / math.acos(val)))


def ref_encode_char(ch):
    if 'A' <= ch <= 'Z':
        return ord(ch) - ord('A') + 1
    if ch == ' ':
        return 32
    if '0' <= ch <= '9':
        return ord(ch) - ord('0') + 48
    return 32


def ref_encode_callsign(cs):
    padded = (cs + '        ')[:8]
    bits = 0
    for ch in padded:
        bits = (bits << 6) | (ref_encode_char(ch) & 0x3F)
    return bits


def ref_make_id_me(tc, ec, callsign):
    cs_bits = ref_encode_callsign(callsign)
    me = ((tc & 0x1F) << 51) | ((ec & 0x07) << 48) | (cs_bits & 0xFFFFFFFFFFFF)
    return me.to_bytes(7, 'big')


def ref_encode_altitude(alt_ft):
    n = (alt_ft + 1000) // 25
    upper = (n >> 4) & 0x7F
    lower = n & 0x0F
    return (upper << 5) | (1 << 4) | lower


def ref_cpr_encode(lat, lon, fflag):
    nz = 15
    d_lat = 360.0 / (4 * nz - fflag)
    yz = math.floor(2**17 * ((lat % d_lat) / d_lat) + 0.5)
    lat_cpr = yz % (2**17)
    nl = ref_nl(lat)
    n_lon = max(nl - fflag, 1)
    d_lon = 360.0 / n_lon
    xz = math.floor(2**17 * ((lon % d_lon) / d_lon) + 0.5)
    lon_cpr = xz % (2**17)
    return lat_cpr, lon_cpr


def ref_make_pos_me(tc, ss, alt_ft, fflag, lat, lon):
    alt_code = ref_encode_altitude(alt_ft)
    lat_cpr, lon_cpr = ref_cpr_encode(lat, lon, fflag)
    me = 0
    me |= (tc & 0x1F) << 51
    me |= (ss & 0x03) << 49
    me |= (alt_code & 0xFFF) << 36
    me |= (fflag & 0x01) << 34
    me |= (lat_cpr & 0x1FFFF) << 17
    me |= (lon_cpr & 0x1FFFF)
    return me.to_bytes(7, 'big')


def ref_make_vel_me(gs_knots, heading_deg, vr_fpm):
    heading_rad = math.radians(heading_deg)
    vew_actual = gs_knots * math.sin(heading_rad)
    vns_actual = gs_knots * math.cos(heading_rad)
    dew = 0 if vew_actual >= 0 else 1
    dns = 0 if vns_actual >= 0 else 1
    vew_enc = int(round(abs(vew_actual))) + 1
    vns_enc = int(round(abs(vns_actual))) + 1
    svr = 0 if vr_fpm >= 0 else 1
    vr_enc = int(round(abs(vr_fpm) / 64.0)) + 1
    me = 0
    me |= (19 & 0x1F) << 51
    me |= (1 & 0x07) << 48
    me |= (dew & 0x01) << 42
    me |= (vew_enc & 0x3FF) << 32
    me |= (dns & 0x01) << 31
    me |= (vns_enc & 0x3FF) << 21
    me |= (svr & 0x01) << 19
    me |= (vr_enc & 0x1FF) << 10
    return me.to_bytes(7, 'big')


def ref_make_df17(icao, me_bytes):
    data = bytes([0x8D]) + icao.to_bytes(3, 'big') + me_bytes
    crc = ref_crc24(data)
    return data + crc.to_bytes(3, 'big')


def ref_flip_bit(msg_bytes, bit_pos):
    msg = bytearray(msg_bytes)
    byte_idx = bit_pos // 8
    bit_idx = 7 - (bit_pos % 8)
    msg[byte_idx] ^= (1 << bit_idx)
    return bytes(msg)


# ========== Helper to run the pipeline ==========

def run_pipeline(station_dir, db_path, report_path):
    result = subprocess.run(
        ['python3', '/app/pipeline.py', station_dir, db_path, report_path],
        capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, f"Pipeline exited {result.returncode}: {result.stderr}"
    with open(report_path) as f:
        return json.load(f)


# ========== Fixtures ==========

@pytest.fixture(scope="session")
def report():
    assert os.path.exists('/app/report.json'), "/app/report.json not found"
    with open('/app/report.json') as f:
        return json.load(f)


@pytest.fixture(scope="session")
def db():
    assert os.path.exists('/app/tracks.db'), "/app/tracks.db not found"
    conn = sqlite3.connect('/app/tracks.db')
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ========== Report structure tests ==========

class TestReportStructure:
    def test_has_aircraft(self, report):
        assert 'aircraft' in report

    def test_has_stats(self, report):
        assert 'stats' in report

    def test_aircraft_count(self, report):
        assert report['stats']['aircraft_count'] == 6

    def test_stats_total(self, report):
        assert report['stats']['total_messages'] == 38

    def test_stats_unique(self, report):
        assert report['stats']['unique_messages'] == 28

    def test_stats_corrected(self, report):
        assert report['stats']['corrected_messages'] == 3

    def test_stats_invalid(self, report):
        assert report['stats']['invalid_messages'] == 2


# ========== Callsign tests ==========

class TestCallsigns:
    @pytest.mark.parametrize("icao,expected", [
        ("A1B2C3", "UAL1234"),
        ("3C4586", "DLH9876"),
        ("780ABC", "ANA567"),
        ("C0FFEE", "SWA789"),
        ("BEEF42", "SPOOF1"),
        ("DEAD01", "N12345"),
    ])
    def test_callsign(self, report, icao, expected):
        assert icao in report['aircraft'], f"Aircraft {icao} not found"
        assert report['aircraft'][icao]['callsign'] == expected


# ========== Position tests ==========

class TestPositions:
    POS_TOL = 0.01

    @pytest.mark.parametrize("icao,lat,lon,alt", [
        ("A1B2C3", 40.6413, -73.7781, 38000),
        ("3C4586", 51.4700, -0.4543, 35000),
        ("780ABC", 35.5494, 139.7798, 3000),
        ("C0FFEE", -33.9461, 151.1772, 28000),
    ])
    def test_position(self, report, icao, lat, lon, alt):
        ac = report['aircraft'][icao]
        assert len(ac['positions']) >= 1, f"No positions for {icao}"
        pos = ac['positions'][0]
        assert abs(pos['lat'] - lat) < self.POS_TOL, \
            f"{icao} lat: expected {lat}, got {pos['lat']}"
        assert abs(pos['lon'] - lon) < self.POS_TOL, \
            f"{icao} lon: expected {lon}, got {pos['lon']}"
        assert pos['alt'] == alt, \
            f"{icao} alt: expected {alt}, got {pos['alt']}"

    def test_spoof_has_two_positions(self, report):
        ac = report['aircraft']['BEEF42']
        assert len(ac['positions']) >= 2, \
            f"BEEF42 should have >=2 positions, got {len(ac['positions'])}"

    def test_spoof_position_1(self, report):
        pos = report['aircraft']['BEEF42']['positions'][0]
        assert abs(pos['lat'] - 40.0) < self.POS_TOL
        assert abs(pos['lon'] - (-74.0)) < self.POS_TOL
        assert pos['alt'] == 32000

    def test_spoof_position_2(self, report):
        pos = report['aircraft']['BEEF42']['positions'][1]
        assert abs(pos['lat'] - 55.0) < self.POS_TOL
        assert abs(pos['lon'] - (-74.0)) < self.POS_TOL
        assert pos['alt'] == 32000

    def test_dead01_no_position(self, report):
        ac = report['aircraft']['DEAD01']
        assert len(ac['positions']) == 0


# ========== Velocity tests ==========

class TestVelocities:
    GS_TOL = 5.0
    HDG_TOL = 2.0
    VR_TOL = 64

    @pytest.mark.parametrize("icao,gs,hdg,vr", [
        ("A1B2C3", 450.0, 90.0, 0),
        ("3C4586", 480.0, 270.0, -1024),
        ("780ABC", 180.0, 180.0, -1536),
        ("C0FFEE", 400.0, 135.0, 512),
        ("BEEF42", 200.0, 0.0, 0),
    ])
    def test_velocity(self, report, icao, gs, hdg, vr):
        ac = report['aircraft'][icao]
        assert len(ac['velocities']) >= 1, f"No velocities for {icao}"
        vel = ac['velocities'][0]
        assert abs(vel['gs'] - gs) < self.GS_TOL, \
            f"{icao} gs: expected {gs}, got {vel['gs']}"
        hdg_diff = abs(vel['hdg'] - hdg)
        if hdg_diff > 180:
            hdg_diff = 360 - hdg_diff
        assert hdg_diff < self.HDG_TOL, \
            f"{icao} hdg: expected {hdg}, got {vel['hdg']}"
        assert abs(vel['vr'] - vr) <= self.VR_TOL, \
            f"{icao} vr: expected {vr}, got {vel['vr']}"


# ========== Station coverage tests ==========

class TestStations:
    @pytest.mark.parametrize("icao,expected", [
        ("A1B2C3", ["alpha", "bravo"]),
        ("3C4586", ["alpha", "bravo", "charlie"]),
        ("780ABC", ["bravo", "charlie"]),
        ("C0FFEE", ["charlie"]),
        ("BEEF42", ["alpha", "bravo"]),
        ("DEAD01", ["bravo"]),
    ])
    def test_station_coverage(self, report, icao, expected):
        ac = report['aircraft'][icao]
        assert sorted(ac['stations']) == sorted(expected), \
            f"{icao} stations: expected {expected}, got {ac['stations']}"


# ========== Anomaly detection tests ==========

class TestAnomalyDetection:
    def test_spoofed_icao(self, report):
        assert report['stats']['spoofed_icao'] == 'BEEF42'

    def test_spoof_flagged(self, report):
        assert report['aircraft']['BEEF42']['anomaly'] is True

    def test_normal_not_flagged(self, report):
        for icao in ['A1B2C3', '3C4586', '780ABC', 'C0FFEE', 'DEAD01']:
            assert report['aircraft'][icao]['anomaly'] is False, \
                f"{icao} should not be flagged as anomalous"


# ========== Database tests ==========

class TestDatabase:
    def test_tables_exist(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor}
        for t in ['raw_messages', 'aircraft', 'positions', 'velocities']:
            assert t in tables, f"Table '{t}' not found in database"

    def test_raw_message_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM raw_messages").fetchone()[0]
        assert count == 38, f"Expected 38 raw messages, got {count}"

    def test_aircraft_count_db(self, db):
        count = db.execute("SELECT COUNT(*) FROM aircraft").fetchone()[0]
        assert count == 6, f"Expected 6 aircraft, got {count}"

    def test_corrected_count_db(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM raw_messages WHERE status='corrected'"
        ).fetchone()[0]
        assert count == 3, f"Expected 3 corrected, got {count}"

    def test_invalid_count_db(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM raw_messages WHERE status='invalid'"
        ).fetchone()[0]
        assert count == 2, f"Expected 2 invalid, got {count}"

    def test_positions_exist(self, db):
        count = db.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        assert count >= 6, f"Expected >=6 positions, got {count}"

    def test_velocities_exist(self, db):
        count = db.execute("SELECT COUNT(*) FROM velocities").fetchone()[0]
        assert count >= 5, f"Expected >=5 velocities, got {count}"


# ========== Anti-cheat: dynamically generated data ==========

class TestAntiCheatDecoding:
    """Generate brand-new messages at test time and verify pipeline decodes them."""

    def _make_station_dir(self, tmp_path, hex_lines, station_name='test'):
        station_dir = str(tmp_path / 'stations')
        os.makedirs(station_dir, exist_ok=True)
        with open(os.path.join(station_dir, f'{station_name}.hex'), 'w') as f:
            for line in hex_lines:
                f.write(line + '\n')
        with open(os.path.join(station_dir, 'stations.json'), 'w') as f:
            json.dump({station_name: {"latitude": 40.0, "longitude": -75.0,
                                       "description": "test station"}}, f)
        return station_dir

    def test_new_aircraft_full_decode(self, tmp_path):
        """Generate a new aircraft and verify all fields decode correctly."""
        id_msg = ref_make_df17(0xABCDEF, ref_make_id_me(4, 0, 'NEWONE'))
        pos_e = ref_make_df17(0xABCDEF,
                              ref_make_pos_me(11, 0, 25000, 0, 48.8566, 2.3522))
        pos_o = ref_make_df17(0xABCDEF,
                              ref_make_pos_me(11, 0, 25000, 1, 48.8566, 2.3522))
        vel = ref_make_df17(0xABCDEF, ref_make_vel_me(300, 60, 500))

        hex_lines = [m.hex().upper() for m in [id_msg, pos_e, pos_o, vel]]
        station_dir = self._make_station_dir(tmp_path, hex_lines)
        db_path = str(tmp_path / 'test.db')
        report_path = str(tmp_path / 'test.json')

        data = run_pipeline(station_dir, db_path, report_path)

        ac = data['aircraft'].get('ABCDEF')
        assert ac is not None, "New aircraft ABCDEF not decoded"
        assert ac['callsign'] == 'NEWONE'
        assert len(ac['positions']) >= 1
        assert abs(ac['positions'][0]['lat'] - 48.8566) < 0.01
        assert abs(ac['positions'][0]['lon'] - 2.3522) < 0.01
        assert ac['positions'][0]['alt'] == 25000
        assert len(ac['velocities']) >= 1

    def test_error_correction_new_data(self, tmp_path):
        """Verify error correction works on fresh messages."""
        id_msg = ref_make_df17(0x888888, ref_make_id_me(4, 0, 'FIXME'))
        corrupted = ref_flip_bit(id_msg, 55)

        hex_lines = [corrupted.hex().upper()]
        station_dir = self._make_station_dir(tmp_path, hex_lines)
        db_path = str(tmp_path / 'test.db')
        report_path = str(tmp_path / 'test.json')

        data = run_pipeline(station_dir, db_path, report_path)

        ac = data['aircraft'].get('888888')
        assert ac is not None, "Error-corrected aircraft 888888 not found"
        assert ac['callsign'] == 'FIXME'
        assert data['stats']['corrected_messages'] == 1
        assert data['stats']['invalid_messages'] == 0

    def test_anomaly_detection_new_data(self, tmp_path):
        """Generate a spoofed aircraft and verify detection generalizes."""
        # Normal aircraft — single position
        normal_id = ref_make_df17(0xAAAA00, ref_make_id_me(4, 0, 'NORMAL'))
        normal_pe = ref_make_df17(0xAAAA00,
                                  ref_make_pos_me(11, 0, 30000, 0, 40.0, -75.0))
        normal_po = ref_make_df17(0xAAAA00,
                                  ref_make_pos_me(11, 0, 30000, 1, 40.0, -75.0))

        # Spoofed aircraft — two positions 20deg latitude apart (~1200nm)
        spoof_id = ref_make_df17(0xFFFF00, ref_make_id_me(4, 0, 'FAKE'))
        spoof_pe1 = ref_make_df17(0xFFFF00,
                                  ref_make_pos_me(11, 0, 30000, 0, 30.0, -80.0))
        spoof_po1 = ref_make_df17(0xFFFF00,
                                  ref_make_pos_me(11, 0, 30000, 1, 30.0, -80.0))
        spoof_pe2 = ref_make_df17(0xFFFF00,
                                  ref_make_pos_me(11, 0, 30000, 0, 50.0, -80.0))
        spoof_po2 = ref_make_df17(0xFFFF00,
                                  ref_make_pos_me(11, 0, 30000, 1, 50.0, -80.0))

        msgs = [normal_id, normal_pe, normal_po,
                spoof_id, spoof_pe1, spoof_po1, spoof_pe2, spoof_po2]
        hex_lines = [m.hex().upper() for m in msgs]
        station_dir = self._make_station_dir(tmp_path, hex_lines)
        db_path = str(tmp_path / 'test.db')
        report_path = str(tmp_path / 'test.json')

        data = run_pipeline(station_dir, db_path, report_path)

        assert data['stats']['spoofed_icao'] == 'FFFF00', \
            f"Expected spoofed FFFF00, got {data['stats'].get('spoofed_icao')}"
        assert data['aircraft']['FFFF00']['anomaly'] is True
        assert data['aircraft']['AAAA00']['anomaly'] is False

    def test_reject_multi_bit_error(self, tmp_path):
        """Verify multi-bit corruption is rejected."""
        id_msg = ref_make_df17(0x999999, ref_make_id_me(4, 0, 'REJECT'))
        corrupted = bytearray(id_msg)
        corrupted[3] ^= 0xAA
        corrupted[7] ^= 0x55

        hex_lines = [bytes(corrupted).hex().upper()]
        station_dir = self._make_station_dir(tmp_path, hex_lines)
        db_path = str(tmp_path / 'test.db')
        report_path = str(tmp_path / 'test.json')

        data = run_pipeline(station_dir, db_path, report_path)

        assert data['stats']['invalid_messages'] == 1
        assert data['stats']['corrected_messages'] == 0
