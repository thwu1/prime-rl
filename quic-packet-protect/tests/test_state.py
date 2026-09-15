"""Tests for QUIC packet protection pipeline — hash-verified against RFC 9001/9369 vectors."""
import hashlib
import json
import os
import pytest



def _h(value: str) -> str:
    """SHA-256 of a lowercase hex string, used to verify without embedding answers."""
    return hashlib.sha256(value.lower().encode("ascii")).hexdigest()


# SHA-256 hashes of the correct lowercase hex values (RFC 9001 Appendix A / RFC 9369 Appendix A).
# Storing only hashes prevents trivial extraction of ground-truth answers.

V1_KEY_HASHES = {
    "initial_secret": "db05dee92a8660d622278c038426515f4ed1b166af79b216bd473bb57bc5a874",
    "client_initial_secret": "2affa341a6983709de892965d6217f8ecea842712153d0063a29eec2a35701ea",
    "client_key": "8db9d9cf394f231c15996d23f2e88479d3913128ac47289d19d5f80e15e7cf4d",
    "client_iv": "42a6b9ab0f353fbdd8aabb2f09c6b9e28dd9b29523ac7073afb9b4c630eed11c",
    "client_hp": "1a6cccc82ec19146846ccec05001a96aa384b384554862a0e25c223895d4d934",
    "server_initial_secret": "6545264fc7430ebd09ed2435ffb8c993d3777b658806b20d7828596726d27839",
    "server_key": "291e2477b8a354fbdc1abc82ff661c9428f6c232d5a07276ee23f0e50db91817",
    "server_iv": "1fe454efcd1ad88c15e057b8d6df773f19384925825d8c43cc1bc74b0a8851a5",
    "server_hp": "453405044f41b940a6e15287edb3bd843aa7a6a0008d6a1628735ac34c07c6a1",
}

V2_KEY_HASHES = {
    "initial_secret": "54520290b32c2beeeea85edb1ddea3aca3ad390d4c2f5addde43538051367120",
    "client_initial_secret": "02ad0a07d086f072487a2c69aab56a162a7e48acc99ba2bcea9e70c0f0426de8",
    "client_key": "25f3f53b3cae87346070d59c3edea83af4e34298b079d365de4b34f7d3ae90fc",
    "client_iv": "591c6dc9b16b8b2ddb58233a1f5024a5b5857b39bb242fcfee4ea890c9d906c4",
    "client_hp": "b505bb696dd94e6498d5a442126d1419742bc7ff0f1a4008376f04c6480618ed",
    "server_initial_secret": "9fbf24cba48c3dc8fa4b4af859348ceb85df13380b843bd717fe16a25a8d01d6",
    "server_key": "331a1b8e39da02064ea63893a2bf62b83daffa38a5dea2ae3ccf4c74324b8dd4",
    "server_iv": "91aeac435e2e9692f1aff9f04b6925ebae2bec351b311fe0f8d574f7a5f3eff9",
    "server_hp": "7d304aafdcf1023cc407e9b72d9ba2a2458793099b2fa34d3f43738288451a92",
}

# Hashes of protected packet header prefixes
V1_CLIENT_INITIAL_HEADER_HASH = "4b5920fdf0f49b3d089ab9d9f3014e2465316f67f10388bc5ecb5af9162eaf38"
V1_SERVER_INITIAL_HEADER_HASH = "a5ef3b48b0e96d460d45a4c20e611b0a746cd9c1bae32fde9fe55cf758ac2b15"
V2_CLIENT_INITIAL_HEADER_HASH = "5fd9a721f506b606e8f92f752160ec6943ae27e43d5072b36fff1dbce847646b"
V2_SERVER_INITIAL_HEADER_HASH = "974b82429c9ef7825644a8ada59160719b1ece24777eb260784ac9a0828d32c6"

# Header lengths in hex chars (bytes * 2)
V1_CLIENT_INITIAL_HEADER_LEN = 44
V1_SERVER_INITIAL_HEADER_LEN = 40
V2_CLIENT_INITIAL_HEADER_LEN = 44
V2_SERVER_INITIAL_HEADER_LEN = 40

# Hashes of full protected packets
V1_CLIENT_INITIAL_PACKET_HASH = "6b5c2bd1f5c0e86bc6d420a8a6105bb4a4dd776eed95adba917edf986a57a5eb"
V2_CLIENT_INITIAL_PACKET_HASH = "4265107b324b461bfbd9cd922dea93a70c17d61c5c5190bb017827e50ef9112a"
V1_SERVER_INITIAL_PACKET_HASH = "7df5610c95aeb7644c2dc738a493a1977c9fa0b19ac97d9addc215ed19374448"
V2_SERVER_INITIAL_PACKET_HASH = "e29644c4aa5e7c157e0676f284021b3ec6b219e04b299ab1727e3dd05f02665d"

# Hashes of Retry packets (including integrity tag)
V1_RETRY_PACKET_HASH = "7e5b7359440ffa42306a249118a8630bb7d959eb7a890638f73f7b001c5b35f5"
V2_RETRY_PACKET_HASH = "4dccb1fabe9f996ebb075106df17defd674c8601197c171fb507654df52a60e4"

# Hashes of ChaCha20-Poly1305 protected short header packets
V1_CHACHA20_PACKET_HASH = "bb8eddd48b978c79d0c26b21646c5b6af1465995d3c8408e2a3e291ed8b13907"
V2_CHACHA20_PACKET_HASH = "524eef1332b3ce5ab6e0497eb3a001dd5ee4f6b12a2eda10b52d97b9d38c8e73"


@pytest.fixture(scope="session")
def results():
    results_path = "/app/output/results.json"
    assert os.path.exists(results_path), f"Output file {results_path} not found"
    with open(results_path) as f:
        data = json.load(f)
    assert "v1" in data, "Missing 'v1' key in results"
    assert "v2" in data, "Missing 'v2' key in results"
    return data


# --- V1 Key Derivation Tests ---

class TestV1KeyDerivation:
    @pytest.mark.parametrize("key_name", [
        "initial_secret",
        "client_initial_secret",
        "client_key",
        "client_iv",
        "client_hp",
        "server_initial_secret",
        "server_key",
        "server_iv",
        "server_hp",
    ])
    def test_v1_key(self, results, key_name):
        actual = results["v1"][key_name].lower()
        actual_hash = _h(actual)
        expected_hash = V1_KEY_HASHES[key_name]
        assert actual_hash == expected_hash, (
            f"V1 {key_name}: SHA-256 verification failed "
            f"(got hash {actual_hash[:16]}..., expected {expected_hash[:16]}...)"
        )


# --- V2 Key Derivation Tests ---

class TestV2KeyDerivation:
    @pytest.mark.parametrize("key_name", [
        "initial_secret",
        "client_initial_secret",
        "client_key",
        "client_iv",
        "client_hp",
        "server_initial_secret",
        "server_key",
        "server_iv",
        "server_hp",
    ])
    def test_v2_key(self, results, key_name):
        actual = results["v2"][key_name].lower()
        actual_hash = _h(actual)
        expected_hash = V2_KEY_HASHES[key_name]
        assert actual_hash == expected_hash, (
            f"V2 {key_name}: SHA-256 verification failed "
            f"(got hash {actual_hash[:16]}..., expected {expected_hash[:16]}...)"
        )


# --- Protected Header Tests ---

class TestProtectedHeaders:
    def test_v1_client_initial_header(self, results):
        pkt = results["v1"]["client_initial_protected_packet"].lower()
        header = pkt[:V1_CLIENT_INITIAL_HEADER_LEN]
        assert _h(header) == V1_CLIENT_INITIAL_HEADER_HASH, (
            "V1 client Initial protected header: SHA-256 verification failed"
        )

    def test_v1_server_initial_header(self, results):
        pkt = results["v1"]["server_initial_protected_packet"].lower()
        header = pkt[:V1_SERVER_INITIAL_HEADER_LEN]
        assert _h(header) == V1_SERVER_INITIAL_HEADER_HASH, (
            "V1 server Initial protected header: SHA-256 verification failed"
        )

    def test_v2_client_initial_header(self, results):
        pkt = results["v2"]["client_initial_protected_packet"].lower()
        header = pkt[:V2_CLIENT_INITIAL_HEADER_LEN]
        assert _h(header) == V2_CLIENT_INITIAL_HEADER_HASH, (
            "V2 client Initial protected header: SHA-256 verification failed"
        )

    def test_v2_server_initial_header(self, results):
        pkt = results["v2"]["server_initial_protected_packet"].lower()
        header = pkt[:V2_SERVER_INITIAL_HEADER_LEN]
        assert _h(header) == V2_SERVER_INITIAL_HEADER_HASH, (
            "V2 server Initial protected header: SHA-256 verification failed"
        )


# --- Full Packet Tests ---

class TestClientInitialPackets:
    def test_v1_client_initial_length(self, results):
        pkt_hex = results["v1"]["client_initial_protected_packet"].lower()
        pkt_bytes = len(pkt_hex) // 2
        assert pkt_bytes == 1200, f"V1 client Initial packet should be 1200 bytes, got {pkt_bytes}"

    def test_v1_client_initial_full(self, results):
        actual = results["v1"]["client_initial_protected_packet"].lower()
        assert _h(actual) == V1_CLIENT_INITIAL_PACKET_HASH, (
            "V1 client Initial full packet: SHA-256 verification failed"
        )

    def test_v2_client_initial_length(self, results):
        pkt_hex = results["v2"]["client_initial_protected_packet"].lower()
        pkt_bytes = len(pkt_hex) // 2
        assert pkt_bytes == 1200, f"V2 client Initial packet should be 1200 bytes, got {pkt_bytes}"

    def test_v2_client_initial_full(self, results):
        actual = results["v2"]["client_initial_protected_packet"].lower()
        assert _h(actual) == V2_CLIENT_INITIAL_PACKET_HASH, (
            "V2 client Initial full packet: SHA-256 verification failed"
        )


class TestServerInitialPackets:
    def test_v1_server_initial_length(self, results):
        pkt_hex = results["v1"]["server_initial_protected_packet"].lower()
        pkt_bytes = len(pkt_hex) // 2
        assert pkt_bytes == 135, f"V1 server Initial packet should be 135 bytes, got {pkt_bytes}"

    def test_v1_server_initial_full(self, results):
        actual = results["v1"]["server_initial_protected_packet"].lower()
        assert _h(actual) == V1_SERVER_INITIAL_PACKET_HASH, (
            "V1 server Initial full packet: SHA-256 verification failed"
        )

    def test_v2_server_initial_length(self, results):
        pkt_hex = results["v2"]["server_initial_protected_packet"].lower()
        pkt_bytes = len(pkt_hex) // 2
        assert pkt_bytes == 135, f"V2 server Initial packet should be 135 bytes, got {pkt_bytes}"

    def test_v2_server_initial_full(self, results):
        actual = results["v2"]["server_initial_protected_packet"].lower()
        assert _h(actual) == V2_SERVER_INITIAL_PACKET_HASH, (
            "V2 server Initial full packet: SHA-256 verification failed"
        )


class TestRetryPackets:
    def test_v1_retry(self, results):
        actual = results["v1"]["retry_packet"].lower()
        assert _h(actual) == V1_RETRY_PACKET_HASH, (
            "V1 Retry packet: SHA-256 verification failed"
        )

    def test_v2_retry(self, results):
        actual = results["v2"]["retry_packet"].lower()
        assert _h(actual) == V2_RETRY_PACKET_HASH, (
            "V2 Retry packet: SHA-256 verification failed"
        )


class TestChaCha20Packets:
    def test_v1_chacha20(self, results):
        actual = results["v1"]["chacha20_protected_packet"].lower()
        assert _h(actual) == V1_CHACHA20_PACKET_HASH, (
            "V1 ChaCha20 packet: SHA-256 verification failed"
        )

    def test_v2_chacha20(self, results):
        actual = results["v2"]["chacha20_protected_packet"].lower()
        assert _h(actual) == V2_CHACHA20_PACKET_HASH, (
            "V2 ChaCha20 packet: SHA-256 verification failed"
        )
