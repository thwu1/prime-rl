
import json
import os
import pytest


def load_report(name):
    path = f"/app/reports/{name}.json"
    assert os.path.exists(path), f"Report {path} does not exist"
    with open(path) as f:
        return json.load(f)


def get_user_maps(report):
    """Return only user-defined maps, excluding compiler-generated ones."""
    return [m for m in report.get("maps", []) if not m["name"].startswith(".")]


# ============================================================
# simple_xdp.o — XDP pass-through, no helpers, no maps
# ============================================================

class TestSimpleXdpReport:
    def test_report_exists(self):
        assert os.path.exists("/app/reports/simple_xdp.json")

    def test_license(self):
        r = load_report("simple_xdp")
        assert r["license"] == "Dual BSD/GPL"

    def test_single_program(self):
        r = load_report("simple_xdp")
        assert len(r["programs"]) == 1

    def test_program_name(self):
        r = load_report("simple_xdp")
        assert r["programs"][0]["name"] == "xdp_pass"

    def test_program_section(self):
        r = load_report("simple_xdp")
        assert r["programs"][0]["section"] == "xdp"

    def test_program_type(self):
        r = load_report("simple_xdp")
        assert r["programs"][0]["prog_type"] == "xdp"

    def test_no_helpers(self):
        r = load_report("simple_xdp")
        assert r["programs"][0]["helpers_called"] == []

    def test_no_packet_access(self):
        r = load_report("simple_xdp")
        assert r["programs"][0]["has_packet_access"] is False

    def test_no_user_maps(self):
        r = load_report("simple_xdp")
        assert len(get_user_maps(r)) == 0

    def test_instruction_count_positive(self):
        r = load_report("simple_xdp")
        assert r["programs"][0]["num_instructions"] > 0


# ============================================================
# icmp_filter.o — XDP ICMP dropper with packet access
# ============================================================

class TestIcmpFilterReport:
    def test_report_exists(self):
        assert os.path.exists("/app/reports/icmp_filter.json")

    def test_license(self):
        r = load_report("icmp_filter")
        assert r["license"] == "GPL"

    def test_single_program(self):
        r = load_report("icmp_filter")
        assert len(r["programs"]) == 1

    def test_program_name(self):
        r = load_report("icmp_filter")
        assert r["programs"][0]["name"] == "xdp_drop_icmp"

    def test_program_section(self):
        r = load_report("icmp_filter")
        assert r["programs"][0]["section"] == "xdp"

    def test_program_type(self):
        r = load_report("icmp_filter")
        assert r["programs"][0]["prog_type"] == "xdp"

    def test_no_helpers(self):
        r = load_report("icmp_filter")
        assert r["programs"][0]["helpers_called"] == []

    def test_packet_access(self):
        r = load_report("icmp_filter")
        assert r["programs"][0]["has_packet_access"] is True

    def test_no_user_maps(self):
        r = load_report("icmp_filter")
        assert len(get_user_maps(r)) == 0

    def test_instruction_count(self):
        r = load_report("icmp_filter")
        # Packet parsing requires multiple instructions
        assert r["programs"][0]["num_instructions"] >= 10


# ============================================================
# execve_monitor.o — kprobe with HASH map
# ============================================================

class TestExecveMonitorReport:
    def test_report_exists(self):
        assert os.path.exists("/app/reports/execve_monitor.json")

    def test_license(self):
        r = load_report("execve_monitor")
        assert r["license"] == "Dual BSD/GPL"

    def test_single_program(self):
        r = load_report("execve_monitor")
        assert len(r["programs"]) == 1

    def test_program_name(self):
        r = load_report("execve_monitor")
        assert r["programs"][0]["name"] == "count_execve"

    def test_program_section(self):
        r = load_report("execve_monitor")
        assert r["programs"][0]["section"] == "kprobe/do_execve"

    def test_program_type(self):
        r = load_report("execve_monitor")
        assert r["programs"][0]["prog_type"] == "kprobe"

    def test_helpers_present(self):
        r = load_report("execve_monitor")
        helpers = set(r["programs"][0]["helpers_called"])
        assert "bpf_get_current_uid_gid" in helpers
        assert "bpf_map_lookup_elem" in helpers
        assert "bpf_map_update_elem" in helpers

    def test_helpers_count(self):
        r = load_report("execve_monitor")
        assert len(r["programs"][0]["helpers_called"]) == 3

    def test_no_packet_access(self):
        r = load_report("execve_monitor")
        assert r["programs"][0]["has_packet_access"] is False

    def test_one_user_map(self):
        r = load_report("execve_monitor")
        maps = get_user_maps(r)
        assert len(maps) == 1

    def test_map_name(self):
        r = load_report("execve_monitor")
        maps = get_user_maps(r)
        assert maps[0]["name"] == "call_count"

    def test_map_type(self):
        r = load_report("execve_monitor")
        maps = get_user_maps(r)
        assert maps[0]["map_type"] == "BPF_MAP_TYPE_HASH"

    def test_map_key_size(self):
        r = load_report("execve_monitor")
        maps = get_user_maps(r)
        assert maps[0]["key_size"] == 4

    def test_map_value_size(self):
        r = load_report("execve_monitor")
        maps = get_user_maps(r)
        assert maps[0]["value_size"] == 8

    def test_map_max_entries(self):
        r = load_report("execve_monitor")
        maps = get_user_maps(r)
        assert maps[0]["max_entries"] == 1024


# ============================================================
# tc_stats.o — TC classifier with ARRAY map and packet access
# ============================================================

class TestTcStatsReport:
    def test_report_exists(self):
        assert os.path.exists("/app/reports/tc_stats.json")

    def test_license(self):
        r = load_report("tc_stats")
        assert r["license"] == "Dual BSD/GPL"

    def test_single_program(self):
        r = load_report("tc_stats")
        assert len(r["programs"]) == 1

    def test_program_name(self):
        r = load_report("tc_stats")
        assert r["programs"][0]["name"] == "tc_classify"

    def test_program_section(self):
        r = load_report("tc_stats")
        assert r["programs"][0]["section"] == "tc"

    def test_program_type(self):
        r = load_report("tc_stats")
        assert r["programs"][0]["prog_type"] == "tc"

    def test_helpers_present(self):
        r = load_report("tc_stats")
        helpers = set(r["programs"][0]["helpers_called"])
        assert "bpf_map_lookup_elem" in helpers

    def test_helpers_count(self):
        r = load_report("tc_stats")
        assert len(r["programs"][0]["helpers_called"]) == 1

    def test_packet_access(self):
        r = load_report("tc_stats")
        assert r["programs"][0]["has_packet_access"] is True

    def test_one_user_map(self):
        r = load_report("tc_stats")
        maps = get_user_maps(r)
        assert len(maps) == 1

    def test_map_name(self):
        r = load_report("tc_stats")
        maps = get_user_maps(r)
        assert maps[0]["name"] == "protocol_stats"

    def test_map_type(self):
        r = load_report("tc_stats")
        maps = get_user_maps(r)
        assert maps[0]["map_type"] == "BPF_MAP_TYPE_ARRAY"

    def test_map_key_size(self):
        r = load_report("tc_stats")
        maps = get_user_maps(r)
        assert maps[0]["key_size"] == 4

    def test_map_value_size(self):
        r = load_report("tc_stats")
        maps = get_user_maps(r)
        assert maps[0]["value_size"] == 8

    def test_map_max_entries(self):
        r = load_report("tc_stats")
        maps = get_user_maps(r)
        assert maps[0]["max_entries"] == 256


# ============================================================
# multi_probe.o — Two tracepoints, perf event array + hash map
# ============================================================

class TestMultiProbeReport:
    def test_report_exists(self):
        assert os.path.exists("/app/reports/multi_probe.json")

    def test_license(self):
        r = load_report("multi_probe")
        assert r["license"] == "Dual BSD/GPL"

    def test_two_programs(self):
        r = load_report("multi_probe")
        assert len(r["programs"]) == 2

    def test_program_names(self):
        r = load_report("multi_probe")
        names = sorted([p["name"] for p in r["programs"]])
        assert names == ["trace_execve", "trace_openat"]

    def test_program_sections(self):
        r = load_report("multi_probe")
        progs = {p["name"]: p for p in r["programs"]}
        assert progs["trace_execve"]["section"] == "tracepoint/syscalls/sys_enter_execve"
        assert progs["trace_openat"]["section"] == "tracepoint/syscalls/sys_enter_openat"

    def test_program_types(self):
        r = load_report("multi_probe")
        for p in r["programs"]:
            assert p["prog_type"] == "tracepoint"

    def test_execve_helpers_present(self):
        r = load_report("multi_probe")
        progs = {p["name"]: p for p in r["programs"]}
        helpers = set(progs["trace_execve"]["helpers_called"])
        assert "bpf_get_current_pid_tgid" in helpers
        assert "bpf_get_current_uid_gid" in helpers
        assert "bpf_get_current_comm" in helpers
        assert "bpf_map_lookup_elem" in helpers
        assert "bpf_perf_event_output" in helpers

    def test_execve_helpers_count(self):
        r = load_report("multi_probe")
        progs = {p["name"]: p for p in r["programs"]}
        assert len(progs["trace_execve"]["helpers_called"]) == 5

    def test_openat_helpers_present(self):
        r = load_report("multi_probe")
        progs = {p["name"]: p for p in r["programs"]}
        helpers = set(progs["trace_openat"]["helpers_called"])
        assert "bpf_get_current_pid_tgid" in helpers
        assert "bpf_get_current_uid_gid" in helpers
        assert "bpf_get_current_comm" in helpers
        assert "bpf_perf_event_output" in helpers

    def test_openat_helpers_count(self):
        r = load_report("multi_probe")
        progs = {p["name"]: p for p in r["programs"]}
        assert len(progs["trace_openat"]["helpers_called"]) == 4

    def test_openat_no_map_lookup(self):
        r = load_report("multi_probe")
        progs = {p["name"]: p for p in r["programs"]}
        helpers = set(progs["trace_openat"]["helpers_called"])
        assert "bpf_map_lookup_elem" not in helpers

    def test_no_packet_access(self):
        r = load_report("multi_probe")
        for p in r["programs"]:
            assert p["has_packet_access"] is False

    def test_two_user_maps(self):
        r = load_report("multi_probe")
        maps = get_user_maps(r)
        assert len(maps) == 2

    def test_perf_event_array_map(self):
        r = load_report("multi_probe")
        maps = {m["name"]: m for m in get_user_maps(r)}
        assert "events" in maps
        m = maps["events"]
        assert m["map_type"] == "BPF_MAP_TYPE_PERF_EVENT_ARRAY"
        assert m["key_size"] == 4
        assert m["value_size"] == 4

    def test_filter_uid_map(self):
        r = load_report("multi_probe")
        maps = {m["name"]: m for m in get_user_maps(r)}
        assert "filter_uid" in maps
        m = maps["filter_uid"]
        assert m["map_type"] == "BPF_MAP_TYPE_HASH"
        assert m["key_size"] == 4
        assert m["value_size"] == 4
        assert m["max_entries"] == 10240
