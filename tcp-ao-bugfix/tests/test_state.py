#!/usr/bin/env python3
"""
Pytest tests verifying TCP-AO packet forensics auditor output.

Validates audit.json content, traffic keys (via SHA-256 digest comparison),
MAC results, pcap validity, and tshark cross-verification.
"""

import hashlib
import json
import os
import struct
import subprocess
import pytest


def _d(s):
    """Compute SHA-256 hex digest of a string."""
    return hashlib.sha256(s.encode()).hexdigest()


# Pre-computed SHA-256 verification digests of expected values.
# Keyed by client_port. Fields: ck=client_syn_key, sk=server_synack_key,
# ka=kdf_algorithm, ci=client_isn, si=server_isn, co=covers_options, iv=ip_version.
_VD = {
    59863: {
        "ck": "c93857916024b8b30ea5be0844605be5cc18b8f843ae2bde0d630fbc3f29d1cf",
        "sk": "4fd7d92b512fab04bad5773c93f26bd66df466b546beb8d165bdd3ec5dfb22c8",
        "ka": "6429dd2457596a04cb7b826bb089726bca7530f87f548cfbad142a3d83706e1c",
        "ci": "35f3b2bb8a80e317a5c0753ab9cdf15af56844c9bbb9eae88ae5db4dd7dfed8c",
        "si": "09dc6746936cdf70894bcac68e18a9db2d673c6e3d1469f8a96bcf8ec1a1ac5f",
        "co": True,
        "iv": 4,
    },
    65298: {
        "ck": "0e3ec3a94d44972eaddc364c656aa2cf653be34fc3ff7bde91b394e6c1eece98",
        "sk": "7425a307d63e3616dfffc563ee99e0d1444659c61436b6efe753157f3ea2e4fd",
        "ka": "6429dd2457596a04cb7b826bb089726bca7530f87f548cfbad142a3d83706e1c",
        "ci": "7b5eced6d3de06a5c6c1c78174f54138d0f8dc1c0922155c5bb79af6a4ebea41",
        "si": "923796237c84ffee611c17cf325e3d07b97c793cfa57f6bdfe5a978c11abdf82",
        "co": False,
        "iv": 4,
    },
    50426: {
        "ck": "3413ac05a61180c892f31987d55daa6c57f443fc08ea51b49252487a08cd19cc",
        "sk": "1563bcab1db73f096ba2fc242696654182189862b476c019ea80dd01e4415259",
        "ka": "7d4df8528b65e42b165ec1ca354c74217ac4fc395a91130497b5176f19565f4b",
        "ci": "284990d4b82229c5697d9a19cbc509a0c0b058e133570cbbdf7c246c9c49160f",
        "si": "f38472dcb5767d778cd93c3ccdd495f46d9df5b5fa5adfd4cb90cfcde0f8c641",
        "co": True,
        "iv": 4,
    },
    55836: {
        "ck": "e69e21ef434cd3a0388f5c3b698b0902d8f43a9b2e44dc94efc9e27407e46ca8",
        "sk": "0c13c88c540373097fa9912a647f624c443bce65bc00b4ea6c202591bf4286ef",
        "ka": "7d4df8528b65e42b165ec1ca354c74217ac4fc395a91130497b5176f19565f4b",
        "ci": "6d6d3a2779808974333514281dd89d084e7aa2374593ed55d146eba49435884f",
        "si": "1953f3afe233fcc23eb58b0d93be0c4febef5943058b8070e8a43398ae6e9d04",
        "co": False,
        "iv": 4,
    },
    63460: {
        "ck": "097a756f83f817957138da2c24f24f7c025158b04be06fa9a156fb5755899620",
        "sk": "1a0af3e7ac395f864a8ea1f4e0d634e82368a29c880b4d54f207d474d357e96a",
        "ka": "6429dd2457596a04cb7b826bb089726bca7530f87f548cfbad142a3d83706e1c",
        "ci": "fb32f0b56a31e56839bfcc65ae589b4f15796fb0006266fdbaa700c2448fcb7d",
        "si": "eb611b02106cea174cda1173a06a95916950d699dbdff44668704c991f3a0744",
        "co": True,
        "iv": 6,
    },
    50893: {
        "ck": "d4e7be85bd85f8b6ea3950329501144524ff928f9cfba96e09a5f9f7b7a25afb",
        "sk": "c6182d139b244551f35f50cee09c6461f5acb8e279c8234661588a6ea4efe125",
        "ka": "6429dd2457596a04cb7b826bb089726bca7530f87f548cfbad142a3d83706e1c",
        "ci": "a193706798a74c9682213d6e71a8762304234db37a886e0acc79bcfc4af58117",
        "si": "2cda248e929d8ca25d679647f8a5b956700ab4fb3e1924b5e9289210cb56e973",
        "co": False,
        "iv": 6,
    },
    63578: {
        "ck": "142643bda63aae193bd512a28066f1e02984c6e672361dc48e68f955ca1e7f41",
        "sk": "237acda119b325da0abb41b2c477a4977cc6ee563be8f0206d07a74051768933",
        "ka": "7d4df8528b65e42b165ec1ca354c74217ac4fc395a91130497b5176f19565f4b",
        "ci": "36dce94a5ba190221afccafe47424fe139d1876950ba220e37b18ab52ffb8526",
        "si": "eee0c384ac98a43a85d6a026e6b93da6e905ce3def9c6c3b7ba3ef0b5c00aa25",
        "co": True,
        "iv": 6,
    },
    62088: {
        "ck": "4d0d5f0576ef6cf73f60ea939cbe4ed1f41f9b510f4d19d48591252ea2f262a5",
        "sk": "91146aea0ed4eec4ba709b31433588bf65755ecc001a4b779f650e25e67dc6fe",
        "ka": "7d4df8528b65e42b165ec1ca354c74217ac4fc395a91130497b5176f19565f4b",
        "ci": "98b3747d877096d3330eab4a14aa977df2d188c1c5a6948068404dfe4fcebf47",
        "si": "1e447d2aa766cc5ab442cd78372cbf73aebf1d00663c328fb0f1846ac9d0ab8f",
        "co": False,
        "iv": 6,
    },
}

AUDIT_PATH = "/app/audit.json"
PCAP_PATH = "/app/validated.pcap"
TSHARK_PATH = "/app/tshark_verify.txt"


@pytest.fixture(scope="session")
def audit_data():
    """Load and return audit.json data."""
    assert os.path.exists(AUDIT_PATH), f"{AUDIT_PATH} does not exist"
    with open(AUDIT_PATH) as f:
        return json.load(f)


def _find_session(audit_data, client_port):
    """Find a session by client port in audit data."""
    for s in audit_data["sessions"]:
        if s["client_port"] == client_port:
            return s
    return None


# ============================================================================
# Structure tests
# ============================================================================

class TestAuditStructure:
    def test_audit_json_exists(self):
        assert os.path.exists(AUDIT_PATH), "audit.json not found"

    def test_audit_json_valid(self, audit_data):
        assert "sessions" in audit_data
        assert "total_packets" in audit_data
        assert "total_valid" in audit_data

    def test_session_count(self, audit_data):
        assert len(audit_data["sessions"]) == 8, (
            f"Expected 8 sessions, got {len(audit_data['sessions'])}"
        )

    def test_total_packets(self, audit_data):
        assert audit_data["total_packets"] == 16

    def test_all_macs_valid(self, audit_data):
        assert audit_data["total_valid"] == 16
        assert audit_data.get("total_invalid", 0) == 0


# ============================================================================
# Session identification tests (digest-verified)
# ============================================================================

class TestSessionIdentification:
    @pytest.mark.parametrize("client_port", list(_VD.keys()))
    def test_session_found(self, audit_data, client_port):
        session = _find_session(audit_data, client_port)
        assert session is not None, (
            f"Session with client_port={client_port} not found in audit"
        )

    @pytest.mark.parametrize("client_port", list(_VD.keys()))
    def test_algorithm_detection(self, audit_data, client_port):
        vd = _VD[client_port]
        session = _find_session(audit_data, client_port)
        assert session is not None
        actual_digest = _d(session["kdf_algorithm"])
        assert actual_digest == vd["ka"], (
            f"Port {client_port}: kdf_algorithm value incorrect"
        )

    @pytest.mark.parametrize("client_port", list(_VD.keys()))
    def test_coverage_detection(self, audit_data, client_port):
        vd = _VD[client_port]
        session = _find_session(audit_data, client_port)
        assert session is not None
        assert session["covers_options"] == vd["co"], (
            f"Port {client_port}: covers_options incorrect"
        )

    @pytest.mark.parametrize("client_port", list(_VD.keys()))
    def test_client_isn(self, audit_data, client_port):
        vd = _VD[client_port]
        session = _find_session(audit_data, client_port)
        assert session is not None
        actual = session["client_isn"].lower().removeprefix("0x")
        actual_digest = _d(actual)
        assert actual_digest == vd["ci"], (
            f"Port {client_port}: client_isn value incorrect"
        )

    @pytest.mark.parametrize("client_port", list(_VD.keys()))
    def test_server_isn(self, audit_data, client_port):
        vd = _VD[client_port]
        session = _find_session(audit_data, client_port)
        assert session is not None
        actual = session["server_isn"].lower().removeprefix("0x")
        actual_digest = _d(actual)
        assert actual_digest == vd["si"], (
            f"Port {client_port}: server_isn value incorrect"
        )

    @pytest.mark.parametrize("client_port", list(_VD.keys()))
    def test_ip_version(self, audit_data, client_port):
        vd = _VD[client_port]
        session = _find_session(audit_data, client_port)
        assert session is not None
        assert session["ip_version"] == vd["iv"], (
            f"Port {client_port}: ip_version incorrect"
        )


# ============================================================================
# Traffic key verification (digest-verified)
# ============================================================================

class TestTrafficKeys:
    @pytest.mark.parametrize("client_port", list(_VD.keys()))
    def test_client_syn_key(self, audit_data, client_port):
        vd = _VD[client_port]
        session = _find_session(audit_data, client_port)
        assert session is not None
        tk = session.get("traffic_keys", {})
        actual = tk.get("client_syn", "").lower().strip()
        actual_digest = _d(actual)
        assert actual_digest == vd["ck"], (
            f"Port {client_port}: client_syn traffic key incorrect"
        )

    @pytest.mark.parametrize("client_port", list(_VD.keys()))
    def test_server_synack_key(self, audit_data, client_port):
        vd = _VD[client_port]
        session = _find_session(audit_data, client_port)
        assert session is not None
        tk = session.get("traffic_keys", {})
        actual = tk.get("server_synack", "").lower().strip()
        actual_digest = _d(actual)
        assert actual_digest == vd["sk"], (
            f"Port {client_port}: server_synack traffic key incorrect"
        )


# ============================================================================
# MAC validation tests
# ============================================================================

class TestMACValidation:
    @pytest.mark.parametrize("client_port", list(_VD.keys()))
    def test_all_packets_valid(self, audit_data, client_port):
        session = _find_session(audit_data, client_port)
        assert session is not None
        packets = session.get("packets", [])
        assert len(packets) == 2, (
            f"Port {client_port}: expected 2 packets, got {len(packets)}"
        )
        for pkt in packets:
            assert pkt["mac_valid"] is True, (
                f"Port {client_port}: packet {pkt.get('type', '?')} "
                f"MAC not valid"
            )


# ============================================================================
# PCAP validation tests
# ============================================================================

class TestPcapOutput:
    def test_pcap_exists(self):
        assert os.path.exists(PCAP_PATH), f"{PCAP_PATH} not found"

    def test_pcap_magic_number(self):
        with open(PCAP_PATH, "rb") as f:
            magic = f.read(4)
        assert magic in (b'\xd4\xc3\xb2\xa1', b'\xa1\xb2\xc3\xd4'), (
            f"Invalid pcap magic: {magic.hex()}"
        )

    def test_pcap_link_type(self):
        with open(PCAP_PATH, "rb") as f:
            header = f.read(24)
        assert len(header) == 24, "pcap global header too short"
        magic = struct.unpack("<I", header[0:4])[0]
        if magic == 0xa1b2c3d4:
            fmt = "<"
        else:
            fmt = ">"
        link_type = struct.unpack(f"{fmt}I", header[20:24])[0]
        assert link_type == 101, (
            f"Expected LINKTYPE_RAW (101), got {link_type}"
        )

    def test_pcap_has_packets(self):
        file_size = os.path.getsize(PCAP_PATH)
        assert file_size > 24, "pcap file has no packet data"


# ============================================================================
# tshark cross-validation tests
# ============================================================================

class TestTsharkVerification:
    def test_tshark_output_exists(self):
        assert os.path.exists(TSHARK_PATH), (
            f"{TSHARK_PATH} not found - tshark verification was not run"
        )

    def test_tshark_can_parse_pcap(self):
        if not os.path.exists(PCAP_PATH):
            pytest.skip("pcap not found")
        try:
            result = subprocess.run(
                ["tshark", "-r", PCAP_PATH, "-T", "fields",
                 "-e", "frame.number", "-e", "tcp.srcport"],
                capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, (
                f"tshark failed: {result.stderr}"
            )
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            assert len(lines) == 16, (
                f"tshark found {len(lines)} frames, expected 16"
            )
        except FileNotFoundError:
            pytest.skip("tshark not installed")

    def test_tshark_finds_tcp_ao_options(self):
        if not os.path.exists(PCAP_PATH):
            pytest.skip("pcap not found")
        try:
            result = subprocess.run(
                ["tshark", "-r", PCAP_PATH, "-Y", "tcp.option_kind == 29",
                 "-T", "fields", "-e", "frame.number"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                pytest.skip(f"tshark filter failed: {result.stderr}")
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            assert len(lines) >= 8, (
                f"tshark found TCP-AO in {len(lines)} frames, expected >= 8"
            )
        except FileNotFoundError:
            pytest.skip("tshark not installed")
