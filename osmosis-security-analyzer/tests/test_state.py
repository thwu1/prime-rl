#!/usr/bin/env python3
"""
"""
import json
import os
import re
import pytest

ANALYSIS_PATH = "/app/output/analysis.json"


@pytest.fixture(scope="session")
def analysis():
    assert os.path.exists(ANALYSIS_PATH), f"Output file {ANALYSIS_PATH} does not exist"
    with open(ANALYSIS_PATH) as f:
        data = json.load(f)
    return data


def _get_iso(analysis, system, pd_a, pd_b):
    """Get isolation degree for a PD pair, handling key order."""
    iso = analysis[system]["isolation_degree"]
    key_fwd = f"{pd_a},{pd_b}"
    key_rev = f"{pd_b},{pd_a}"
    if key_fwd in iso:
        return iso[key_fwd]
    elif key_rev in iso:
        return iso[key_rev]
    else:
        sorted_key = ",".join(sorted([pd_a, pd_b]))
        if sorted_key in iso:
            return iso[sorted_key]
        pytest.fail(
            f"Isolation degree for ({pd_a}, {pd_b}) not found in {system}. "
            f"Available keys: {list(iso.keys())}"
        )


def _parse_dot_edges(filepath):
    """Parse DOT file edges, return dict of (src, dst) -> set of resource names."""
    with open(filepath) as f:
        content = f.read()
    edges = {}
    pattern = r'"?(\w+)"?\s*->\s*"?(\w+)"?\s*\[label="([^"]*)"\]'
    for m in re.finditer(pattern, content):
        src, dst, label = m.group(1), m.group(2), m.group(3)
        edges[(src, dst)] = set(r.strip() for r in label.split(","))
    return edges


def _find_blp(violations, src, dst):
    """Find a BLP violation entry by source and destination."""
    for v in violations:
        if v["from"] == src and v["to"] == dst:
            return v
    return None


def _find_biba(violations, src, dst):
    """Find a Biba violation entry by source and destination."""
    for v in violations:
        if v["from"] == src and v["to"] == dst:
            return v
    return None


def _find_refv(violations, src, dst):
    """Find a refinement violation entry by source and destination."""
    for v in violations:
        if v["from"] == src and v["to"] == dst:
            return v
    return None


# =============================================================================
# Pipeline entry point
# =============================================================================


class TestPipelineEntry:
    def test_run_analysis_exists(self):
        assert os.path.exists("/app/run_analysis.sh")


# =============================================================================
# Output structure tests
# =============================================================================


class TestOutputStructure:
    def test_output_file_exists(self, analysis):
        assert analysis is not None

    def test_all_systems_present(self, analysis):
        for name in ["avionics", "iot_gateway", "minimal"]:
            assert name in analysis, f"System '{name}' missing from output"

    def test_required_fields(self, analysis):
        for name in ["avionics", "iot_gateway", "minimal"]:
            sys = analysis[name]
            for field in [
                "tcb",
                "impact_boundary",
                "isolation_degree",
                "mls",
                "refinement_violations",
                "attack_surface",
                "policy_results",
            ]:
                assert field in sys, f"{name} missing '{field}'"

    def test_mls_subfields(self, analysis):
        for name in ["avionics", "iot_gateway", "minimal"]:
            mls = analysis[name]["mls"]
            for field in ["blp_violations", "biba_violations", "residual_leakage"]:
                assert field in mls, f"{name} mls missing '{field}'"


# =============================================================================
# Avionics system (5 PDs, two isolated clusters)
# =============================================================================


class TestAvionicsTCB:
    def test_critical_ctrl(self, analysis):
        assert set(analysis["avionics"]["tcb"]["critical_ctrl"]) == {"sensor_drv"}

    def test_sensor_drv(self, analysis):
        assert set(analysis["avionics"]["tcb"]["sensor_drv"]) == {"critical_ctrl"}

    def test_logger(self, analysis):
        assert set(analysis["avionics"]["tcb"]["logger"]) == {
            "critical_ctrl",
            "sensor_drv",
        }

    def test_network(self, analysis):
        assert set(analysis["avionics"]["tcb"]["network"]) == {"crypto"}

    def test_crypto(self, analysis):
        assert set(analysis["avionics"]["tcb"]["crypto"]) == {"network"}


class TestAvionicsIB:
    def test_critical_ctrl(self, analysis):
        assert set(analysis["avionics"]["impact_boundary"]["critical_ctrl"]) == {
            "sensor_drv",
            "logger",
        }

    def test_sensor_drv(self, analysis):
        assert set(analysis["avionics"]["impact_boundary"]["sensor_drv"]) == {
            "critical_ctrl",
            "logger",
        }

    def test_logger_empty(self, analysis):
        assert set(analysis["avionics"]["impact_boundary"]["logger"]) == set()

    def test_network(self, analysis):
        assert set(analysis["avionics"]["impact_boundary"]["network"]) == {"crypto"}

    def test_crypto(self, analysis):
        assert set(analysis["avionics"]["impact_boundary"]["crypto"]) == {"network"}


class TestAvionicsIsolation:
    def test_critical_ctrl_sensor_drv(self, analysis):
        assert _get_iso(analysis, "avionics", "critical_ctrl", "sensor_drv") == 2

    def test_critical_ctrl_logger(self, analysis):
        assert _get_iso(analysis, "avionics", "critical_ctrl", "logger") == 1

    def test_crypto_network(self, analysis):
        assert _get_iso(analysis, "avionics", "crypto", "network") == 3

    def test_critical_ctrl_network_isolated(self, analysis):
        assert _get_iso(analysis, "avionics", "critical_ctrl", "network") == 0

    def test_logger_network_isolated(self, analysis):
        assert _get_iso(analysis, "avionics", "logger", "network") == 0

    def test_sensor_drv_crypto_isolated(self, analysis):
        assert _get_iso(analysis, "avionics", "sensor_drv", "crypto") == 0


class TestAvionicsBLP:
    def test_violation_count(self, analysis):
        assert len(analysis["avionics"]["mls"]["blp_violations"]) == 3

    def test_critical_ctrl_to_logger_declassified(self, analysis):
        v = _find_blp(analysis["avionics"]["mls"]["blp_violations"],
                       "critical_ctrl", "logger")
        assert v is not None
        assert v["resources"] == ["ctrl_out"]
        assert v["declassified"] is True

    def test_critical_ctrl_to_sensor_drv_undeclassified(self, analysis):
        v = _find_blp(analysis["avionics"]["mls"]["blp_violations"],
                       "critical_ctrl", "sensor_drv")
        assert v is not None
        assert v["resources"] == ["channel_critical_ctrl_sensor_drv"]
        assert v["declassified"] is False

    def test_crypto_to_network_undeclassified(self, analysis):
        v = _find_blp(analysis["avionics"]["mls"]["blp_violations"],
                       "crypto", "network")
        assert v is not None
        assert set(v["resources"]) == {"channel_crypto_network", "crypto_buf"}
        assert v["declassified"] is False


class TestAvionicsBiba:
    def test_violation_count(self, analysis):
        assert len(analysis["avionics"]["mls"]["biba_violations"]) == 2

    def test_sensor_drv_to_critical_ctrl(self, analysis):
        v = _find_biba(analysis["avionics"]["mls"]["biba_violations"],
                        "sensor_drv", "critical_ctrl")
        assert v is not None
        assert set(v["resources"]) == {"channel_critical_ctrl_sensor_drv", "sensor_buf"}

    def test_network_to_crypto(self, analysis):
        v = _find_biba(analysis["avionics"]["mls"]["biba_violations"],
                        "network", "crypto")
        assert v is not None
        assert set(v["resources"]) == {"channel_crypto_network", "net_buf"}


class TestAvionicsResidualLeakage:
    def test_leakage_pairs(self, analysis):
        pairs = analysis["avionics"]["mls"]["residual_leakage"]
        pair_set = {tuple(p) for p in pairs}
        assert pair_set == {
            ("critical_ctrl", "sensor_drv"),
            ("crypto", "network"),
        }


class TestAvionicsRefinement:
    def test_no_violations(self, analysis):
        assert len(analysis["avionics"]["refinement_violations"]) == 0


class TestAvionicsAttackSurface:
    def test_critical_ctrl(self, analysis):
        assert analysis["avionics"]["attack_surface"]["critical_ctrl"] == 12

    def test_sensor_drv(self, analysis):
        assert analysis["avionics"]["attack_surface"]["sensor_drv"] == 10

    def test_logger(self, analysis):
        assert analysis["avionics"]["attack_surface"]["logger"] == 9

    def test_network(self, analysis):
        assert analysis["avionics"]["attack_surface"]["network"] == 12

    def test_crypto(self, analysis):
        assert analysis["avionics"]["attack_surface"]["crypto"] == 12


class TestAvionicsPolicies:
    def test_results(self, analysis):
        assert analysis["avionics"]["policy_results"] == [
            "pass", "fail", "pass", "fail", "pass", "fail",
            "pass", "fail", "fail", "pass",
        ]


# =============================================================================
# IoT Gateway system (8 PDs, complex topology, isolated ota_updater)
# =============================================================================


class TestIoTGatewayTCB:
    def test_ota_updater_empty(self, analysis):
        assert set(analysis["iot_gateway"]["tcb"]["ota_updater"]) == set()

    def test_secure_store(self, analysis):
        assert set(analysis["iot_gateway"]["tcb"]["secure_store"]) == {
            "data_processor",
            "sensor_collector",
        }

    def test_data_processor(self, analysis):
        assert set(analysis["iot_gateway"]["tcb"]["data_processor"]) == {
            "sensor_collector",
            "secure_store",
        }

    def test_sensor_collector(self, analysis):
        assert set(analysis["iot_gateway"]["tcb"]["sensor_collector"]) == {
            "data_processor",
            "secure_store",
        }

    def test_watchdog(self, analysis):
        assert set(analysis["iot_gateway"]["tcb"]["watchdog"]) == {
            "eth_driver",
            "ip_stack",
            "mqtt_broker",
            "data_processor",
            "sensor_collector",
            "secure_store",
        }

    def test_eth_driver(self, analysis):
        assert set(analysis["iot_gateway"]["tcb"]["eth_driver"]) == {
            "ip_stack",
            "watchdog",
            "mqtt_broker",
            "data_processor",
            "sensor_collector",
            "secure_store",
        }

    def test_mqtt_broker(self, analysis):
        assert set(analysis["iot_gateway"]["tcb"]["mqtt_broker"]) == {
            "ip_stack",
            "data_processor",
            "watchdog",
            "eth_driver",
            "sensor_collector",
            "secure_store",
        }

    def test_ip_stack(self, analysis):
        assert set(analysis["iot_gateway"]["tcb"]["ip_stack"]) == {
            "eth_driver",
            "mqtt_broker",
            "watchdog",
            "data_processor",
            "sensor_collector",
            "secure_store",
        }


class TestIoTGatewayIB:
    def test_ota_updater_empty(self, analysis):
        assert set(analysis["iot_gateway"]["impact_boundary"]["ota_updater"]) == set()

    def test_sensor_collector(self, analysis):
        assert set(analysis["iot_gateway"]["impact_boundary"]["sensor_collector"]) == {
            "data_processor",
            "mqtt_broker",
            "secure_store",
            "ip_stack",
            "eth_driver",
            "watchdog",
        }

    def test_watchdog(self, analysis):
        assert set(analysis["iot_gateway"]["impact_boundary"]["watchdog"]) == {
            "eth_driver",
            "ip_stack",
            "mqtt_broker",
        }

    def test_eth_driver(self, analysis):
        assert set(analysis["iot_gateway"]["impact_boundary"]["eth_driver"]) == {
            "ip_stack",
            "watchdog",
            "mqtt_broker",
        }

    def test_data_processor(self, analysis):
        assert set(analysis["iot_gateway"]["impact_boundary"]["data_processor"]) == {
            "sensor_collector",
            "mqtt_broker",
            "secure_store",
            "ip_stack",
            "eth_driver",
            "watchdog",
        }

    def test_secure_store(self, analysis):
        assert set(analysis["iot_gateway"]["impact_boundary"]["secure_store"]) == {
            "data_processor",
            "sensor_collector",
            "mqtt_broker",
            "ip_stack",
            "eth_driver",
            "watchdog",
        }

    def test_mqtt_broker(self, analysis):
        assert set(analysis["iot_gateway"]["impact_boundary"]["mqtt_broker"]) == {
            "ip_stack",
            "eth_driver",
            "watchdog",
        }

    def test_ip_stack(self, analysis):
        assert set(analysis["iot_gateway"]["impact_boundary"]["ip_stack"]) == {
            "eth_driver",
            "mqtt_broker",
            "watchdog",
        }


class TestIoTGatewayIsolation:
    def test_eth_driver_ip_stack(self, analysis):
        assert _get_iso(analysis, "iot_gateway", "eth_driver", "ip_stack") == 4

    def test_sensor_collector_data_processor(self, analysis):
        assert (
            _get_iso(analysis, "iot_gateway", "sensor_collector", "data_processor") == 2
        )

    def test_data_processor_secure_store(self, analysis):
        assert _get_iso(analysis, "iot_gateway", "data_processor", "secure_store") == 3

    def test_ota_updater_secure_store_isolated(self, analysis):
        assert _get_iso(analysis, "iot_gateway", "ota_updater", "secure_store") == 0

    def test_eth_driver_watchdog(self, analysis):
        assert _get_iso(analysis, "iot_gateway", "eth_driver", "watchdog") == 2

    def test_mqtt_broker_watchdog(self, analysis):
        assert _get_iso(analysis, "iot_gateway", "mqtt_broker", "watchdog") == 1

    def test_mqtt_broker_data_processor(self, analysis):
        assert _get_iso(analysis, "iot_gateway", "mqtt_broker", "data_processor") == 1

    def test_ip_stack_mqtt_broker(self, analysis):
        assert _get_iso(analysis, "iot_gateway", "ip_stack", "mqtt_broker") == 4

    def test_ota_updater_watchdog_isolated(self, analysis):
        assert _get_iso(analysis, "iot_gateway", "ota_updater", "watchdog") == 0


class TestIoTGatewayBLP:
    def test_violation_count(self, analysis):
        assert len(analysis["iot_gateway"]["mls"]["blp_violations"]) == 3

    def test_data_processor_to_mqtt_declassified(self, analysis):
        v = _find_blp(analysis["iot_gateway"]["mls"]["blp_violations"],
                       "data_processor", "mqtt_broker")
        assert v is not None
        assert v["resources"] == ["processed_data"]
        assert v["declassified"] is True

    def test_data_processor_to_sensor_collector_undeclassified(self, analysis):
        v = _find_blp(analysis["iot_gateway"]["mls"]["blp_violations"],
                       "data_processor", "sensor_collector")
        assert v is not None
        assert v["resources"] == ["channel_data_processor_sensor_collector"]
        assert v["declassified"] is False

    def test_ip_stack_to_eth_driver_undeclassified(self, analysis):
        v = _find_blp(analysis["iot_gateway"]["mls"]["blp_violations"],
                       "ip_stack", "eth_driver")
        assert v is not None
        assert set(v["resources"]) == {"channel_eth_driver_ip_stack", "eth_tx_buf"}
        assert v["declassified"] is False


class TestIoTGatewayBiba:
    def test_violation_count(self, analysis):
        assert len(analysis["iot_gateway"]["mls"]["biba_violations"]) == 2

    def test_eth_driver_to_ip_stack(self, analysis):
        v = _find_biba(analysis["iot_gateway"]["mls"]["biba_violations"],
                        "eth_driver", "ip_stack")
        assert v is not None
        assert set(v["resources"]) == {"channel_eth_driver_ip_stack", "eth_rx_buf"}

    def test_eth_driver_to_watchdog(self, analysis):
        v = _find_biba(analysis["iot_gateway"]["mls"]["biba_violations"],
                        "eth_driver", "watchdog")
        assert v is not None
        assert v["resources"] == ["channel_eth_driver_watchdog"]


class TestIoTGatewayResidualLeakage:
    def test_leakage_pairs(self, analysis):
        pairs = analysis["iot_gateway"]["mls"]["residual_leakage"]
        pair_set = {tuple(p) for p in pairs}
        assert pair_set == {
            ("data_processor", "sensor_collector"),
            ("ip_stack", "eth_driver"),
            ("ip_stack", "watchdog"),
            ("mqtt_broker", "eth_driver"),
            ("mqtt_broker", "watchdog"),
            ("secure_store", "sensor_collector"),
        }


class TestIoTGatewayRefinement:
    def test_violation_count(self, analysis):
        assert len(analysis["iot_gateway"]["refinement_violations"]) == 2

    def test_data_processor_to_sensor_collector(self, analysis):
        v = _find_refv(analysis["iot_gateway"]["refinement_violations"],
                        "data_processor", "sensor_collector")
        assert v is not None
        assert v["from_domain"] == "processing"
        assert v["to_domain"] == "sensing"

    def test_eth_driver_to_watchdog(self, analysis):
        v = _find_refv(analysis["iot_gateway"]["refinement_violations"],
                        "eth_driver", "watchdog")
        assert v is not None
        assert v["from_domain"] == "network"
        assert v["to_domain"] == "platform"


class TestIoTGatewayAttackSurface:
    def test_eth_driver(self, analysis):
        assert analysis["iot_gateway"]["attack_surface"]["eth_driver"] == 70

    def test_ip_stack(self, analysis):
        assert analysis["iot_gateway"]["attack_surface"]["ip_stack"] == 91

    def test_mqtt_broker(self, analysis):
        assert analysis["iot_gateway"]["attack_surface"]["mqtt_broker"] == 56

    def test_sensor_collector(self, analysis):
        assert analysis["iot_gateway"]["attack_surface"]["sensor_collector"] == 15

    def test_data_processor(self, analysis):
        assert analysis["iot_gateway"]["attack_surface"]["data_processor"] == 30

    def test_secure_store(self, analysis):
        assert analysis["iot_gateway"]["attack_surface"]["secure_store"] == 18

    def test_ota_updater(self, analysis):
        assert analysis["iot_gateway"]["attack_surface"]["ota_updater"] == 2

    def test_watchdog(self, analysis):
        assert analysis["iot_gateway"]["attack_surface"]["watchdog"] == 35


class TestIoTGatewayPolicies:
    def test_results(self, analysis):
        assert analysis["iot_gateway"]["policy_results"] == [
            "pass", "fail", "pass", "fail", "pass", "fail",
            "fail", "fail", "fail", "fail",
        ]


# =============================================================================
# Minimal system (3 PDs, cycles, multi-reader resource, observer pattern)
# =============================================================================


class TestMinimalTCB:
    def test_producer(self, analysis):
        assert set(analysis["minimal"]["tcb"]["producer"]) == {"consumer"}

    def test_consumer(self, analysis):
        assert set(analysis["minimal"]["tcb"]["consumer"]) == {"producer"}

    def test_auditor(self, analysis):
        assert set(analysis["minimal"]["tcb"]["auditor"]) == {
            "producer",
            "consumer",
        }


class TestMinimalIB:
    def test_producer(self, analysis):
        assert set(analysis["minimal"]["impact_boundary"]["producer"]) == {
            "consumer",
            "auditor",
        }

    def test_consumer(self, analysis):
        assert set(analysis["minimal"]["impact_boundary"]["consumer"]) == {
            "producer",
            "auditor",
        }

    def test_auditor_empty(self, analysis):
        assert set(analysis["minimal"]["impact_boundary"]["auditor"]) == set()


class TestMinimalIsolation:
    def test_producer_consumer(self, analysis):
        assert _get_iso(analysis, "minimal", "producer", "consumer") == 3

    def test_producer_auditor(self, analysis):
        assert _get_iso(analysis, "minimal", "producer", "auditor") == 1

    def test_consumer_auditor(self, analysis):
        assert _get_iso(analysis, "minimal", "consumer", "auditor") == 1


class TestMinimalBLP:
    def test_violation_count(self, analysis):
        assert len(analysis["minimal"]["mls"]["blp_violations"]) == 1

    def test_producer_to_auditor(self, analysis):
        v = _find_blp(analysis["minimal"]["mls"]["blp_violations"],
                       "producer", "auditor")
        assert v is not None
        assert v["resources"] == ["data_buf"]
        assert v["declassified"] is False


class TestMinimalBiba:
    def test_violation_count(self, analysis):
        assert len(analysis["minimal"]["mls"]["biba_violations"]) == 1

    def test_producer_to_auditor(self, analysis):
        v = _find_biba(analysis["minimal"]["mls"]["biba_violations"],
                        "producer", "auditor")
        assert v is not None
        assert v["resources"] == ["data_buf"]


class TestMinimalResidualLeakage:
    def test_leakage_pairs(self, analysis):
        pairs = analysis["minimal"]["mls"]["residual_leakage"]
        pair_set = {tuple(p) for p in pairs}
        assert pair_set == {
            ("consumer", "auditor"),
            ("producer", "auditor"),
        }


class TestMinimalRefinement:
    def test_no_violations(self, analysis):
        assert len(analysis["minimal"]["refinement_violations"]) == 0


class TestMinimalAttackSurface:
    def test_producer(self, analysis):
        assert analysis["minimal"]["attack_surface"]["producer"] == 12

    def test_consumer(self, analysis):
        assert analysis["minimal"]["attack_surface"]["consumer"] == 12

    def test_auditor(self, analysis):
        assert analysis["minimal"]["attack_surface"]["auditor"] == 9


class TestMinimalPolicies:
    def test_results(self, analysis):
        assert analysis["minimal"]["policy_results"] == [
            "pass", "pass", "fail", "fail", "fail", "fail", "pass",
        ]


# =============================================================================
# DOT/SVG graph output tests
# =============================================================================


class TestGraphFileExistence:
    @pytest.mark.parametrize("system", ["avionics", "iot_gateway", "minimal"])
    def test_dot_exists(self, system):
        assert os.path.exists(f"/app/output/{system}_flow.dot"), (
            f"DOT file /app/output/{system}_flow.dot not found"
        )

    @pytest.mark.parametrize("system", ["avionics", "iot_gateway", "minimal"])
    def test_svg_exists_and_nontrivial(self, system):
        path = f"/app/output/{system}_flow.svg"
        assert os.path.exists(path), f"SVG file {path} not found"
        assert os.path.getsize(path) > 100, f"SVG file {path} is too small"


class TestAvionicsFlowGraph:
    @pytest.fixture(scope="class")
    def edges(self):
        return _parse_dot_edges("/app/output/avionics_flow.dot")

    def test_sensor_drv_to_critical_ctrl(self, edges):
        assert ("sensor_drv", "critical_ctrl") in edges
        assert edges[("sensor_drv", "critical_ctrl")] == {
            "channel_critical_ctrl_sensor_drv", "sensor_buf"
        }

    def test_critical_ctrl_to_sensor_drv(self, edges):
        assert ("critical_ctrl", "sensor_drv") in edges
        assert edges[("critical_ctrl", "sensor_drv")] == {
            "channel_critical_ctrl_sensor_drv"
        }

    def test_critical_ctrl_to_logger(self, edges):
        assert ("critical_ctrl", "logger") in edges
        assert edges[("critical_ctrl", "logger")] == {"ctrl_out"}

    def test_network_to_crypto(self, edges):
        assert ("network", "crypto") in edges
        assert edges[("network", "crypto")] == {
            "channel_crypto_network", "net_buf"
        }

    def test_crypto_to_network(self, edges):
        assert ("crypto", "network") in edges
        assert edges[("crypto", "network")] == {
            "channel_crypto_network", "crypto_buf"
        }

    def test_logger_no_outgoing(self, edges):
        outgoing = [e for e in edges if e[0] == "logger"]
        assert len(outgoing) == 0, f"Logger should have no outgoing flows, found: {outgoing}"

    def test_no_cross_cluster_flows(self, edges):
        cross = [
            ("network", "critical_ctrl"), ("critical_ctrl", "network"),
            ("network", "sensor_drv"), ("sensor_drv", "network"),
            ("network", "logger"), ("logger", "network"),
            ("crypto", "critical_ctrl"), ("critical_ctrl", "crypto"),
            ("crypto", "sensor_drv"), ("sensor_drv", "crypto"),
            ("crypto", "logger"), ("logger", "crypto"),
        ]
        for e in cross:
            assert e not in edges, f"Unexpected cross-cluster flow: {e[0]} -> {e[1]}"

    def test_total_edge_count(self, edges):
        assert len(edges) == 5, f"Expected 5 flow edges, got {len(edges)}: {list(edges.keys())}"


class TestIoTGatewayFlowGraph:
    @pytest.fixture(scope="class")
    def edges(self):
        return _parse_dot_edges("/app/output/iot_gateway_flow.dot")

    def test_ota_updater_isolated(self, edges):
        ota_edges = [e for e in edges if "ota_updater" in e]
        assert len(ota_edges) == 0, f"ota_updater should be isolated, found edges: {ota_edges}"

    def test_watchdog_to_eth_driver(self, edges):
        assert ("watchdog", "eth_driver") in edges
        assert "watchdog_status" in edges[("watchdog", "eth_driver")]

    def test_watchdog_to_ip_stack(self, edges):
        assert ("watchdog", "ip_stack") in edges
        assert edges[("watchdog", "ip_stack")] == {"watchdog_status"}

    def test_watchdog_to_mqtt_broker(self, edges):
        assert ("watchdog", "mqtt_broker") in edges
        assert edges[("watchdog", "mqtt_broker")] == {"watchdog_status"}

    def test_data_processor_to_mqtt_broker(self, edges):
        assert ("data_processor", "mqtt_broker") in edges
        assert edges[("data_processor", "mqtt_broker")] == {"processed_data"}

    def test_sensor_collector_to_data_processor(self, edges):
        assert ("sensor_collector", "data_processor") in edges
        assert edges[("sensor_collector", "data_processor")] == {
            "channel_data_processor_sensor_collector", "sensor_data"
        }

    def test_no_watchdog_to_data_pipeline(self, edges):
        assert ("watchdog", "sensor_collector") not in edges
        assert ("watchdog", "data_processor") not in edges
        assert ("watchdog", "secure_store") not in edges

    def test_total_edge_count(self, edges):
        assert len(edges) == 13, f"Expected 13 flow edges, got {len(edges)}: {list(edges.keys())}"


class TestMinimalFlowGraph:
    @pytest.fixture(scope="class")
    def edges(self):
        return _parse_dot_edges("/app/output/minimal_flow.dot")

    def test_producer_to_consumer(self, edges):
        assert ("producer", "consumer") in edges
        assert edges[("producer", "consumer")] == {
            "channel_consumer_producer", "data_buf"
        }

    def test_consumer_to_producer(self, edges):
        assert ("consumer", "producer") in edges
        assert edges[("consumer", "producer")] == {
            "channel_consumer_producer", "feedback"
        }

    def test_producer_to_auditor(self, edges):
        assert ("producer", "auditor") in edges
        assert edges[("producer", "auditor")] == {"data_buf"}

    def test_auditor_no_outgoing(self, edges):
        outgoing = [e for e in edges if e[0] == "auditor"]
        assert len(outgoing) == 0, f"Auditor should have no outgoing flows, found: {outgoing}"

    def test_total_edge_count(self, edges):
        assert len(edges) == 3, f"Expected 3 flow edges, got {len(edges)}: {list(edges.keys())}"
