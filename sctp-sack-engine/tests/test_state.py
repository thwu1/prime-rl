#!/usr/bin/env python3
"""Tests for WebRTC SCTP session forensic analysis."""


import json
import pytest


# --- Association parameters (from pcap INIT / INIT-ACK) ---

EXPECTED_ASSOCIATION = {
    "a_initiate_tag": 1310171840,   # 0x4E17A2C0
    "b_initiate_tag": 2101042832,   # 0x7D3B5E90
    "a_initial_tsn": 4294967280,    # 0xFFFFFFF0
    "b_initial_tsn": 3000,
    "a_rwnd": 65535,
    "b_rwnd": 131072,
}

# --- Data channels (from DCEP binary) ---

EXPECTED_CHANNELS = [
    {"stream_id": 0, "label": "control", "channel_type": 0,
     "priority": 0, "reliability_param": 0, "protocol": ""},
    {"stream_id": 1, "label": "sensor-feed", "channel_type": 129,
     "priority": 128, "reliability_param": 3, "protocol": ""},
    {"stream_id": 2, "label": "video-meta", "channel_type": 2,
     "priority": 64, "reliability_param": 2000, "protocol": ""},
    {"stream_id": 3, "label": "bulk", "channel_type": 128,
     "priority": 256, "reliability_param": 0, "protocol": "binary"},
]

# --- SACK checkpoints (from trace with SCTP state machine) ---

EXPECTED_SACKS = {
    "s1":  {"cumulative_tsn": 4294967280, "gap_blocks": [], "dup_tsns": []},
    "s2":  {"cumulative_tsn": 4294967280, "gap_blocks": [[2, 2]], "dup_tsns": []},
    "s3":  {"cumulative_tsn": 4294967280, "gap_blocks": [[2, 2], [4, 5]], "dup_tsns": []},
    "s4":  {"cumulative_tsn": 4294967282, "gap_blocks": [[2, 3]], "dup_tsns": []},
    "s5":  {"cumulative_tsn": 4294967282, "gap_blocks": [[2, 3], [5, 5], [7, 7]], "dup_tsns": []},
    "s6":  {"cumulative_tsn": 4294967282, "gap_blocks": [[2, 3], [5, 5], [7, 7]], "dup_tsns": [4294967285]},
    "s7":  {"cumulative_tsn": 4294967285, "gap_blocks": [[2, 2], [4, 4]], "dup_tsns": []},
    "s8":  {"cumulative_tsn": 4294967285, "gap_blocks": [[2, 2], [4, 4], [6, 6], [8, 8], [10, 10], [12, 12]], "dup_tsns": []},
    "s9":  {"cumulative_tsn": 4294967295, "gap_blocks": [[2, 2]], "dup_tsns": []},
    "s10": {"cumulative_tsn": 1, "gap_blocks": [], "dup_tsns": []},
    "s11": {"cumulative_tsn": 1, "gap_blocks": [[2, 2], [4, 4], [6, 6]], "dup_tsns": []},
    "s12": {"cumulative_tsn": 3, "gap_blocks": [[2, 2], [4, 4]], "dup_tsns": []},
    "s13": {"cumulative_tsn": 7, "gap_blocks": [], "dup_tsns": []},
    "s14": {"cumulative_tsn": 7, "gap_blocks": [], "dup_tsns": [7]},
    "s15": {"cumulative_tsn": 9, "gap_blocks": [], "dup_tsns": []},
}

# --- Abandoned TSNs (from FORWARD-TSN analysis) ---

EXPECTED_ABANDONED = {
    "f1": [4294967286, 4294967288, 4294967290, 4294967292, 4294967294],
    "f2": [4, 6],
}


@pytest.fixture(scope="session")
def results():
    try:
        with open("/app/results.json", "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        pytest.fail("/app/results.json not found")
    except json.JSONDecodeError as e:
        pytest.fail(f"/app/results.json is not valid JSON: {e}")
    return data


# ========== Association tests ==========

class TestAssociation:
    def test_association_key_exists(self, results):
        assert "association" in results, "Missing 'association' key"

    @pytest.mark.parametrize("field", list(EXPECTED_ASSOCIATION.keys()))
    def test_association_field(self, results, field):
        actual = results["association"][field]
        expected = EXPECTED_ASSOCIATION[field]
        assert actual == expected, (
            f"association.{field}: expected {expected}, got {actual}"
        )


# ========== Data channel tests ==========

class TestDataChannels:
    def test_data_channels_key_exists(self, results):
        assert "data_channels" in results, "Missing 'data_channels' key"

    def test_data_channels_count(self, results):
        assert len(results["data_channels"]) == len(EXPECTED_CHANNELS), (
            f"Expected {len(EXPECTED_CHANNELS)} channels, "
            f"got {len(results['data_channels'])}"
        )

    @pytest.mark.parametrize("idx", range(len(EXPECTED_CHANNELS)))
    def test_channel_stream_id(self, results, idx):
        actual = results["data_channels"][idx]["stream_id"]
        expected = EXPECTED_CHANNELS[idx]["stream_id"]
        assert actual == expected

    @pytest.mark.parametrize("idx", range(len(EXPECTED_CHANNELS)))
    def test_channel_label(self, results, idx):
        actual = results["data_channels"][idx]["label"]
        expected = EXPECTED_CHANNELS[idx]["label"]
        assert actual == expected

    @pytest.mark.parametrize("idx", range(len(EXPECTED_CHANNELS)))
    def test_channel_type(self, results, idx):
        actual = results["data_channels"][idx]["channel_type"]
        expected = EXPECTED_CHANNELS[idx]["channel_type"]
        assert actual == expected

    @pytest.mark.parametrize("idx", range(len(EXPECTED_CHANNELS)))
    def test_channel_priority(self, results, idx):
        actual = results["data_channels"][idx]["priority"]
        expected = EXPECTED_CHANNELS[idx]["priority"]
        assert actual == expected

    @pytest.mark.parametrize("idx", range(len(EXPECTED_CHANNELS)))
    def test_channel_reliability_param(self, results, idx):
        actual = results["data_channels"][idx]["reliability_param"]
        expected = EXPECTED_CHANNELS[idx]["reliability_param"]
        assert actual == expected

    @pytest.mark.parametrize("idx", range(len(EXPECTED_CHANNELS)))
    def test_channel_protocol(self, results, idx):
        actual = results["data_channels"][idx]["protocol"]
        expected = EXPECTED_CHANNELS[idx]["protocol"]
        assert actual == expected


# ========== SACK tests ==========

class TestSacks:
    def test_sacks_key_exists(self, results):
        assert "sacks" in results, "Missing 'sacks' key"

    def test_all_sack_ids_present(self, results):
        for sid in EXPECTED_SACKS:
            assert sid in results["sacks"], f"Missing SACK checkpoint '{sid}'"

    @pytest.mark.parametrize("sack_id", list(EXPECTED_SACKS.keys()))
    def test_cumulative_tsn(self, results, sack_id):
        actual = results["sacks"][sack_id]["cumulative_tsn"]
        expected = EXPECTED_SACKS[sack_id]["cumulative_tsn"]
        assert actual == expected, (
            f"SACK {sack_id}: cumulative_tsn expected {expected}, got {actual}"
        )

    @pytest.mark.parametrize("sack_id", list(EXPECTED_SACKS.keys()))
    def test_gap_blocks(self, results, sack_id):
        actual = [tuple(b) for b in results["sacks"][sack_id]["gap_blocks"]]
        expected = [tuple(b) for b in EXPECTED_SACKS[sack_id]["gap_blocks"]]
        assert actual == expected, (
            f"SACK {sack_id}: gap_blocks expected {expected}, got {actual}"
        )

    @pytest.mark.parametrize("sack_id", list(EXPECTED_SACKS.keys()))
    def test_dup_tsns(self, results, sack_id):
        actual = sorted(results["sacks"][sack_id]["dup_tsns"])
        expected = sorted(EXPECTED_SACKS[sack_id]["dup_tsns"])
        assert actual == expected, (
            f"SACK {sack_id}: dup_tsns expected {expected}, got {actual}"
        )


# ========== Abandoned TSN tests ==========

class TestAbandonedTsns:
    def test_abandoned_key_exists(self, results):
        assert "abandoned_tsns" in results, "Missing 'abandoned_tsns' key"

    @pytest.mark.parametrize("fwd_id", list(EXPECTED_ABANDONED.keys()))
    def test_abandoned_tsns(self, results, fwd_id):
        assert fwd_id in results["abandoned_tsns"], (
            f"Missing FORWARD-TSN id '{fwd_id}' in abandoned_tsns"
        )
        actual = sorted(results["abandoned_tsns"][fwd_id])
        expected = sorted(EXPECTED_ABANDONED[fwd_id])
        assert actual == expected, (
            f"abandoned_tsns[{fwd_id}]: expected {expected}, got {actual}"
        )
