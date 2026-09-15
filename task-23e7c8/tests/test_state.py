
import json
import os
import sqlite3

import pytest

EXPECTED = {
    "config_1": {
        "reachable_maps": sorted([
            ".rodata", "acl_map", "conn_track_map", "lb_backends_map",
            "lb_services_map", "log_events_map", "metrics_map",
            "policy_map", "rate_limit_map", "tail_call_map",
        ]),
        "eliminable_maps": sorted([
            "encap_params_map", "monitor_ring_buf", "nat_map",
            "session_map", "tunnel_map",
        ]),
        "reachable_programs": sorted([
            "xdp_acl", "xdp_lb", "xdp_main", "xdp_policy",
        ]),
        "eliminable_programs": sorted([
            "xdp_encap", "xdp_monitor", "xdp_nat", "xdp_tunnel",
        ]),
    },
    "config_2": {
        "reachable_maps": sorted([
            ".rodata", "conn_track_map", "encap_params_map",
            "nat_map", "tail_call_map", "tunnel_map",
        ]),
        "eliminable_maps": sorted([
            "acl_map", "lb_backends_map", "lb_services_map",
            "log_events_map", "metrics_map", "monitor_ring_buf",
            "policy_map", "rate_limit_map", "session_map",
        ]),
        "reachable_programs": sorted([
            "xdp_encap", "xdp_main", "xdp_nat", "xdp_tunnel",
        ]),
        "eliminable_programs": sorted([
            "xdp_acl", "xdp_lb", "xdp_monitor", "xdp_policy",
        ]),
    },
    "config_3": {
        "reachable_maps": sorted([
            ".rodata", "conn_track_map", "lb_backends_map",
            "lb_services_map", "log_events_map", "metrics_map",
            "monitor_ring_buf", "nat_map", "policy_map",
            "rate_limit_map", "session_map", "tail_call_map",
            "tunnel_map",
        ]),
        "eliminable_maps": sorted([
            "acl_map", "encap_params_map",
        ]),
        "reachable_programs": sorted([
            "xdp_lb", "xdp_main", "xdp_monitor", "xdp_nat",
            "xdp_policy", "xdp_tunnel",
        ]),
        "eliminable_programs": sorted([
            "xdp_acl", "xdp_encap",
        ]),
    },
    "config_4": {
        "reachable_maps": sorted([
            ".rodata", "lb_backends_map", "lb_services_map",
            "metrics_map", "monitor_ring_buf", "session_map",
            "tail_call_map", "tunnel_map",
        ]),
        "eliminable_maps": sorted([
            "acl_map", "conn_track_map", "encap_params_map",
            "log_events_map", "nat_map", "policy_map",
            "rate_limit_map",
        ]),
        "reachable_programs": sorted([
            "xdp_lb", "xdp_main", "xdp_monitor", "xdp_tunnel",
        ]),
        "eliminable_programs": sorted([
            "xdp_acl", "xdp_encap", "xdp_nat", "xdp_policy",
        ]),
    },
    "config_5": {
        "reachable_maps": sorted([
            ".rodata",
        ]),
        "eliminable_maps": sorted([
            "acl_map", "conn_track_map", "encap_params_map",
            "lb_backends_map", "lb_services_map", "log_events_map",
            "metrics_map", "monitor_ring_buf", "nat_map",
            "policy_map", "rate_limit_map", "session_map",
            "tail_call_map", "tunnel_map",
        ]),
        "reachable_programs": sorted([
            "xdp_main",
        ]),
        "eliminable_programs": sorted([
            "xdp_acl", "xdp_encap", "xdp_lb", "xdp_monitor",
            "xdp_nat", "xdp_policy", "xdp_tunnel",
        ]),
    },
}


def load_result(config_name):
    path = f"/app/results/{config_name}_result.json"
    assert os.path.exists(path), f"Result file {path} does not exist"
    with open(path) as f:
        return json.load(f)


def get_all_maps():
    conn = sqlite3.connect("/app/ebpf_programs.db")
    names = sorted(
        r[0] for r in conn.execute("SELECT name FROM maps").fetchall()
    )
    conn.close()
    return names


def get_all_programs():
    conn = sqlite3.connect("/app/ebpf_programs.db")
    names = sorted(
        r[0] for r in conn.execute("SELECT name FROM programs").fetchall()
    )
    conn.close()
    return names


@pytest.mark.parametrize(
    "config_name",
    ["config_1", "config_2", "config_3", "config_4", "config_5"],
)
class TestReachabilityResults:

    def test_result_file_exists(self, config_name):
        path = f"/app/results/{config_name}_result.json"
        assert os.path.exists(path), f"Result file {path} not found"

    def test_result_has_required_fields(self, config_name):
        result = load_result(config_name)
        for field in [
            "reachable_maps", "eliminable_maps",
            "reachable_programs", "eliminable_programs",
        ]:
            assert field in result, (
                f"Missing field '{field}' in {config_name} result"
            )

    def test_reachable_maps(self, config_name):
        result = load_result(config_name)
        expected = EXPECTED[config_name]["reachable_maps"]
        actual = sorted(result["reachable_maps"])
        assert actual == expected, (
            f"{config_name}: reachable_maps mismatch.\n"
            f"Expected: {expected}\n"
            f"Got:      {actual}\n"
            f"Missing:  {sorted(set(expected) - set(actual))}\n"
            f"Extra:    {sorted(set(actual) - set(expected))}"
        )

    def test_eliminable_maps(self, config_name):
        result = load_result(config_name)
        expected = EXPECTED[config_name]["eliminable_maps"]
        actual = sorted(result["eliminable_maps"])
        assert actual == expected, (
            f"{config_name}: eliminable_maps mismatch.\n"
            f"Expected: {expected}\n"
            f"Got:      {actual}\n"
            f"Missing:  {sorted(set(expected) - set(actual))}\n"
            f"Extra:    {sorted(set(actual) - set(expected))}"
        )

    def test_reachable_programs(self, config_name):
        result = load_result(config_name)
        expected = EXPECTED[config_name]["reachable_programs"]
        actual = sorted(result["reachable_programs"])
        assert actual == expected, (
            f"{config_name}: reachable_programs mismatch.\n"
            f"Expected: {expected}\n"
            f"Got:      {actual}\n"
            f"Missing:  {sorted(set(expected) - set(actual))}\n"
            f"Extra:    {sorted(set(actual) - set(expected))}"
        )

    def test_eliminable_programs(self, config_name):
        result = load_result(config_name)
        expected = EXPECTED[config_name]["eliminable_programs"]
        actual = sorted(result["eliminable_programs"])
        assert actual == expected, (
            f"{config_name}: eliminable_programs mismatch.\n"
            f"Expected: {expected}\n"
            f"Got:      {actual}\n"
            f"Missing:  {sorted(set(expected) - set(actual))}\n"
            f"Extra:    {sorted(set(actual) - set(expected))}"
        )

    def test_maps_partition(self, config_name):
        """Verify reachable + eliminable = all maps."""
        result = load_result(config_name)
        all_maps = sorted(
            result["reachable_maps"] + result["eliminable_maps"]
        )
        expected_all = get_all_maps()
        assert all_maps == expected_all, (
            f"{config_name}: maps partition check failed.\n"
            f"Expected all maps: {expected_all}\n"
            f"Got union:         {all_maps}"
        )

    def test_programs_partition(self, config_name):
        """Verify reachable + eliminable = all programs."""
        result = load_result(config_name)
        all_progs = sorted(
            result["reachable_programs"] + result["eliminable_programs"]
        )
        expected_all = get_all_programs()
        assert all_progs == expected_all, (
            f"{config_name}: programs partition check failed.\n"
            f"Expected all programs: {expected_all}\n"
            f"Got union:             {all_progs}"
        )

    def test_no_duplicates_maps(self, config_name):
        result = load_result(config_name)
        overlap = set(result["reachable_maps"]) & set(
            result["eliminable_maps"]
        )
        assert len(overlap) == 0, (
            f"Maps in both reachable and eliminable: {overlap}"
        )

    def test_no_duplicates_programs(self, config_name):
        result = load_result(config_name)
        overlap = set(result["reachable_programs"]) & set(
            result["eliminable_programs"]
        )
        assert len(overlap) == 0, (
            f"Programs in both reachable and eliminable: {overlap}"
        )

    def test_entry_program_always_reachable(self, config_name):
        result = load_result(config_name)
        assert "xdp_main" in result["reachable_programs"], (
            "Entry program xdp_main must always be reachable"
        )
