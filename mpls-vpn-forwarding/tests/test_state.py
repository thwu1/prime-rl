"""
Tests for MPLS VPN Network Analysis.

"""

import json
import os
import pytest

RESULTS_PATH = "/app/results.json"


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


def test_q1_igp_shortest_path_pe1_pe3(results):
    r = results["q1"]
    assert r["path"] == ["PE1", "P1", "P2", "PE3"]
    assert r["metric"] == 30


def test_q2_igp_shortest_path_pe2_pe3(results):
    r = results["q2"]
    assert r["path"] == ["PE2", "P3", "P4", "PE3"]
    assert r["metric"] == 30


def test_q3_ecmp_paths_pe1_pe3(results):
    r = results["q3"]
    assert r["metric"] == 30
    paths = [tuple(p) for p in r["paths"]]
    expected = [
        ("PE1", "P1", "P2", "PE3"),
        ("PE1", "P1", "P4", "PE3"),
    ]
    assert sorted(paths) == sorted([tuple(e) for e in expected])


def test_q4_cspf_pe1_pe3_bw8000(results):
    r = results["q4"]
    assert r["path"] == ["PE1", "P1", "P2", "PE3"]
    assert r["metric"] == 30


def test_q5_cspf_pe1_pe2_bw3000(results):
    r = results["q5"]
    assert r["path"] == ["PE1", "P1", "P4", "P3", "PE2"]
    assert r["metric"] == 40


def test_q6_vrf_routes_customerA_pe1(results):
    r = results["q6"]
    assert sorted(r["prefixes"]) == sorted([
        "172.16.1.0/24",
        "172.16.2.0/24",
        "172.16.10.0/24",
    ])


def test_q7_vrf_routes_customerB_pe2(results):
    r = results["q7"]
    assert sorted(r["prefixes"]) == sorted([
        "172.16.3.0/24",
        "172.16.4.0/24",
        "172.16.10.0/24",
    ])


def test_q8_vrf_routes_customerC_pe3(results):
    r = results["q8"]
    assert sorted(r["prefixes"]) == sorted([
        "172.16.5.0/24",
        "172.16.6.0/24",
        "172.16.7.0/24",
    ])


def test_q9_forwarding_pe1_custA_to_172_16_2(results):
    r = results["q9"]
    hops = r["hops"]
    assert len(hops) == 4

    h0 = hops[0]
    assert h0["router"] == "PE1"
    assert h0["action"] == "push"
    assert h0["labels"] == [1103, 5002]
    assert h0["forward_to"] == "P1"

    h1 = hops[1]
    assert h1["router"] == "P1"
    assert h1["action"] == "swap"
    assert h1["in_label"] == 1103
    assert h1["out_label"] == 1203
    assert h1["forward_to"] == "P2"

    h2 = hops[2]
    assert h2["router"] == "P2"
    assert h2["action"] == "php"
    assert h2["in_label"] == 1203
    assert h2["forward_to"] == "PE3"

    h3 = hops[3]
    assert h3["router"] == "PE3"
    assert h3["action"] == "dispose"
    assert h3["in_label"] == 5002
    assert h3["vrf"] == "CustomerA"


def test_q10_forwarding_pe3_custC_spoke_to_spoke(results):
    r = results["q10"]
    hops = r["hops"]
    assert len(hops) == 6

    h0 = hops[0]
    assert h0["router"] == "PE3"
    assert h0["action"] == "push"
    assert h0["labels"] == [1201, 5016]
    assert h0["forward_to"] == "P2"

    h1 = hops[1]
    assert h1["router"] == "P2"
    assert h1["action"] == "swap"
    assert h1["in_label"] == 1201
    assert h1["out_label"] == 1101
    assert h1["forward_to"] == "P1"

    h2 = hops[2]
    assert h2["router"] == "P1"
    assert h2["action"] == "php"
    assert h2["in_label"] == 1101
    assert h2["forward_to"] == "PE1"

    h3 = hops[3]
    assert h3["router"] == "PE1"
    assert h3["action"] == "hub_forward"
    assert h3["in_label"] == 5016
    assert h3["labels"] == [1302, 5006]
    assert h3["forward_to"] == "P3"

    h4 = hops[4]
    assert h4["router"] == "P3"
    assert h4["action"] == "php"
    assert h4["in_label"] == 1302
    assert h4["forward_to"] == "PE2"

    h5 = hops[5]
    assert h5["router"] == "PE2"
    assert h5["action"] == "dispose"
    assert h5["in_label"] == 5006
    assert h5["vrf"] == "CustomerC"
