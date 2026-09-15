
"""Tests for corrected eBPF Plugin analysis report."""

import json
import os
import pytest

REPORT_PATH = "/app/corrected_report.json"


@pytest.fixture(scope="session")
def report():
    """Load and return the corrected report."""
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


def _get_maps_by_name(report, plugin):
    """Helper to get maps dict keyed by name for a plugin."""
    return {m["name"]: m for m in report["plugins"][plugin]["maps"]}


# ── Structure tests ──


def test_report_is_valid_json():
    """Report file exists and is valid JSON with required top-level keys."""
    assert os.path.exists(REPORT_PATH)
    with open(REPORT_PATH) as f:
        data = json.load(f)
    assert "plugins" in data
    assert "shared_maps" in data
    assert "total_memory_bytes" in data


def test_all_plugins_present(report):
    """All 6 plugin files are analyzed."""
    expected = {
        "dropreason.c", "dns.c", "conntrack.c",
        "packetparser.c", "packetforward.c", "tcpretrans.c",
    }
    assert set(report["plugins"].keys()) == expected


# ── Map count tests ──


@pytest.mark.parametrize("plugin,expected_count", [
    ("dropreason.c", 5),
    ("dns.c", 2),
    ("conntrack.c", 1),
    ("packetparser.c", 1),
    ("packetforward.c", 1),
    ("tcpretrans.c", 1),
])
def test_map_counts(report, plugin, expected_count):
    """Each plugin has the correct number of BPF maps."""
    assert len(report["plugins"][plugin]["maps"]) == expected_count


# ── Struct size tests (the core alignment challenge) ──


@pytest.mark.parametrize("plugin,struct_name,expected_size", [
    # dropreason.c
    ("dropreason.c", "metrics_map_key", 8),
    ("dropreason.c", "metrics_map_value", 16),
    ("dropreason.c", "dr_packet", 32),
    # dns.c: trailing padding from u64 alignment
    ("dns.c", "dnshdr", 12),
    ("dns.c", "dns_event", 72),
    # conntrack.c: nested structs with alignment
    ("conntrack.c", "tcpflagscount", 36),
    ("conntrack.c", "conntrackmetadata", 24),
    ("conntrack.c", "ct_v4_key", 16),
    ("conntrack.c", "ct_entry", 128),
    # packetparser.c: multiple internal padding points
    ("packetparser.c", "pp_tcpmetadata", 16),
    ("packetparser.c", "pp_tcpflagscount", 36),
    ("packetparser.c", "pp_conntrackmetadata", 24),
    ("packetparser.c", "pp_packet", 120),
    # packetforward.c
    ("packetforward.c", "pf_metric", 16),
    # tcpretrans.c: trailing padding from u64
    ("tcpretrans.c", "tcpretrans_event", 64),
])
def test_struct_sizes(report, plugin, struct_name, expected_size):
    """Struct sizes follow C natural alignment rules."""
    structs = report["plugins"][plugin]["structs"]
    assert struct_name in structs, f"Struct {struct_name} not found in {plugin}"
    assert structs[struct_name]["size"] == expected_size


# ── Struct alignment tests ──


@pytest.mark.parametrize("plugin,struct_name,expected_align", [
    ("conntrack.c", "ct_v4_key", 4),
    ("conntrack.c", "ct_entry", 8),
    ("dns.c", "dns_event", 8),
    ("packetparser.c", "pp_packet", 8),
    ("tcpretrans.c", "tcpretrans_event", 8),
])
def test_struct_alignments(report, plugin, struct_name, expected_align):
    """Struct alignments are correct."""
    structs = report["plugins"][plugin]["structs"]
    assert struct_name in structs
    assert structs[struct_name]["alignment"] == expected_align


# ── Map property tests ──


@pytest.mark.parametrize("plugin,map_name,expected", [
    ("conntrack.c", "retina_conntrack", {
        "type": "LRU_HASH",
        "key_size": 16,
        "value_size": 128,
        "max_entries": 131072,
        "pinned": True,
    }),
    ("dropreason.c", "retina_dropreason_metrics", {
        "type": "PERCPU_HASH",
        "key_size": 8,
        "value_size": 16,
        "max_entries": 512,
    }),
    ("dns.c", "tmp_dns_events", {
        "type": "PERCPU_ARRAY",
        "value_size": 72,
        "max_entries": 1,
    }),
    ("packetforward.c", "retina_packetforward_metrics", {
        "type": "PERCPU_HASH",
        "key_size": 4,
        "value_size": 16,
        "max_entries": 2,
    }),
    ("dropreason.c", "retina_dropreason_drop_pids", {
        "type": "HASH",
        "key_size": 4,
        "value_size": 32,
        "max_entries": 16384,
    }),
])
def test_map_properties(report, plugin, map_name, expected):
    """Map properties are correctly extracted."""
    maps = _get_maps_by_name(report, plugin)
    assert map_name in maps, f"Map {map_name} not found in {plugin}"
    for key, value in expected.items():
        assert maps[map_name][key] == value, (
            f"{map_name}.{key}: expected {value}, got {maps[map_name].get(key)}"
        )


def test_dropreason_events_not_pinned(report):
    """PERF_EVENT_ARRAY maps without LIBBPF_PIN_BY_NAME must not be marked pinned."""
    maps = _get_maps_by_name(report, "dropreason.c")
    assert maps["retina_dropreason_events"]["pinned"] is False


# ── Memory calculation tests ──


@pytest.mark.parametrize("plugin,map_name,expected_memory", [
    ("conntrack.c", "retina_conntrack", 18874368),
    ("dropreason.c", "retina_dropreason_metrics", 69632),
    ("dropreason.c", "retina_dropreason_drop_pids", 589824),
    ("dns.c", "tmp_dns_events", 576),
    ("packetforward.c", "retina_packetforward_metrics", 264),
    ("dropreason.c", "retina_dropreason_events", 0),
])
def test_map_memory(report, plugin, map_name, expected_memory):
    """Per-map memory budget is correctly calculated."""
    maps = _get_maps_by_name(report, plugin)
    assert maps[map_name]["memory_bytes"] == expected_memory


def test_total_memory(report):
    """Total memory across all maps is correct."""
    assert report["total_memory_bytes"] == 20321096


# ── Shared maps tests ──


def test_shared_maps_contains_conntrack(report):
    """Pinned conntrack map is detected as shared."""
    assert "retina_conntrack" in report["shared_maps"]


def test_shared_maps_count(report):
    """Only maps with LIBBPF_PIN_BY_NAME pinning are shared."""
    assert len(report["shared_maps"]) == 1


# ── Attachment tests ──


@pytest.mark.parametrize("plugin,expected_count", [
    ("dropreason.c", 10),
    ("dns.c", 1),
    ("conntrack.c", 0),
    ("packetparser.c", 4),
    ("packetforward.c", 1),
    ("tcpretrans.c", 1),
])
def test_attachment_counts(report, plugin, expected_count):
    """Each plugin has the correct number of kernel attachment points."""
    assert len(report["plugins"][plugin]["attachments"]) == expected_count


def test_dropreason_attachment_types(report):
    """Dropreason plugin uses kprobe, kretprobe, and fexit."""
    types = {a["type"] for a in report["plugins"]["dropreason.c"]["attachments"]}
    assert "kprobe" in types
    assert "kretprobe" in types
    assert "fexit" in types


def test_tcpretrans_attachment_type(report):
    """TCP retransmit plugin uses tracepoint."""
    types = {a["type"] for a in report["plugins"]["tcpretrans.c"]["attachments"]}
    assert "tracepoint" in types


def test_packetparser_attachment_type(report):
    """Packet parser plugin uses TC classifier."""
    types = {a["type"] for a in report["plugins"]["packetparser.c"]["attachments"]}
    assert "classifier" in types


def test_dns_attachment_type(report):
    """DNS plugin uses socket filter."""
    types = {a["type"] for a in report["plugins"]["dns.c"]["attachments"]}
    assert "socket_filter" in types


def test_packetforward_attachment_type(report):
    """Packet forward plugin uses socket filter."""
    types = {a["type"] for a in report["plugins"]["packetforward.c"]["attachments"]}
    assert "socket_filter" in types


# ── Consistency checks ──


@pytest.mark.parametrize("plugin", [
    "conntrack.c", "dns.c", "dropreason.c",
    "packetparser.c", "packetforward.c", "tcpretrans.c",
])
def test_struct_size_alignment_consistency(report, plugin):
    """Every struct size must be a multiple of its alignment."""
    for name, info in report["plugins"][plugin]["structs"].items():
        assert info["size"] % info["alignment"] == 0, (
            f"{plugin}:{name} size={info['size']} not multiple of alignment={info['alignment']}"
        )
