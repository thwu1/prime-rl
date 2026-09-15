
import json
import os
import pytest


@pytest.fixture
def conformance():
    with open("/app/results/conformance.json") as f:
        return json.load(f)


@pytest.fixture
def nonconformance():
    with open("/app/results/nonconformance.json") as f:
        return json.load(f)


# ======== Type Hierarchy ========


def test_type_hierarchy_count(conformance):
    """Model contains exactly 29 part def types."""
    assert len(conformance["type_hierarchy"]) == 29


def test_type_hierarchy_root(conformance):
    """Abstract root Component has no ancestors."""
    assert conformance["type_hierarchy"]["Component"] == []


def test_type_hierarchy_physical(conformance):
    """PhysicalComponent directly specializes Component."""
    assert conformance["type_hierarchy"]["PhysicalComponent"] == ["Component"]


def test_type_hierarchy_electrical(conformance):
    """ElectricalComponent chain: PhysicalComponent -> Component."""
    assert conformance["type_hierarchy"]["ElectricalComponent"] == [
        "PhysicalComponent", "Component"
    ]


def test_type_hierarchy_instrument_chain(conformance):
    """Instrument has 3-level ancestor chain through ElectricalComponent."""
    assert conformance["type_hierarchy"]["Instrument"] == [
        "ElectricalComponent", "PhysicalComponent", "Component"
    ]


def test_type_hierarchy_optical_imager(conformance):
    """OpticalImager has full 4-level chain via Instrument."""
    expected = ["Instrument", "ElectricalComponent", "PhysicalComponent", "Component"]
    assert conformance["type_hierarchy"]["OpticalImager"] == expected


def test_type_hierarchy_subsystem(conformance):
    """Subsystem branches from PhysicalComponent, not ElectricalComponent."""
    assert conformance["type_hierarchy"]["Subsystem"] == [
        "PhysicalComponent", "Component"
    ]


def test_type_hierarchy_payload_subsystem(conformance):
    """PayloadSubsystem specializes Subsystem."""
    expected = ["Subsystem", "PhysicalComponent", "Component"]
    assert conformance["type_hierarchy"]["PayloadSubsystem"] == expected


def test_type_hierarchy_xband_is_instrument(conformance):
    """XBandTransmitter specializes Instrument (same chain as OpticalImager)."""
    expected = ["Instrument", "ElectricalComponent", "PhysicalComponent", "Component"]
    assert conformance["type_hierarchy"]["XBandTransmitter"] == expected


def test_type_hierarchy_reaction_wheel_not_electrical(conformance):
    """ReactionWheelCluster is PhysicalComponent, NOT ElectricalComponent."""
    expected = ["PhysicalComponent", "Component"]
    assert conformance["type_hierarchy"]["ReactionWheelCluster"] == expected


def test_type_hierarchy_antenna_not_electrical(conformance):
    """HighGainAntenna is PhysicalComponent (passive, no electrical)."""
    expected = ["PhysicalComponent", "Component"]
    assert conformance["type_hierarchy"]["HighGainAntenna"] == expected


# ======== Instrument Classification ========


def test_instruments(conformance):
    """Exactly three part defs transitively specialize Instrument."""
    assert conformance["instruments"] == [
        "OpticalImager", "SARUnit", "XBandTransmitter"
    ]


# ======== Verification Verdicts ========


def test_verification_verdict_count(conformance):
    """Six verification case usages exist."""
    assert len(conformance["verification_verdicts"]) == 6


def test_verification_verdicts_sorted(conformance):
    """Verdicts are sorted by case name."""
    cases = [v["case"] for v in conformance["verification_verdicts"]]
    assert cases == sorted(cases)


def test_verification_pointing_fails(conformance):
    """pointingCheck FAILS: starTracker.accuracy=3.0 violates <=0.01."""
    v = next(x for x in conformance["verification_verdicts"]
             if x["case"] == "pointingCheck")
    assert v["requirement_id"] == "REQ-ADC-001"
    assert v["verdict"] == "fail"


def test_verification_mass_passes(conformance):
    """systemMassCheck passes: 241.0 <= 250.0."""
    v = next(x for x in conformance["verification_verdicts"]
             if x["case"] == "systemMassCheck")
    assert v["requirement_id"] == "REQ-SYS-001"
    assert v["verdict"] == "pass"


def test_verification_power_passes(conformance):
    """powerCheck passes: 900.0 >= 800.0."""
    v = next(x for x in conformance["verification_verdicts"]
             if x["case"] == "powerCheck")
    assert v["requirement_id"] == "REQ-SYS-002"
    assert v["verdict"] == "pass"


def test_verification_storage_passes(conformance):
    """storageCheck passes: storageCapacity 2.0 >= 1.0."""
    v = next(x for x in conformance["verification_verdicts"]
             if x["case"] == "storageCheck")
    assert v["requirement_id"] == "REQ-PAY-003"
    assert v["verdict"] == "pass"


def test_verification_isp_passes(conformance):
    """ispCheck passes: specificImpulse 230.0 >= 220.0."""
    v = next(x for x in conformance["verification_verdicts"]
             if x["case"] == "ispCheck")
    assert v["requirement_id"] == "REQ-PRO-002"
    assert v["verdict"] == "pass"


def test_verification_thermal_passes(conformance):
    """thermalCheck passes: -20.0 >= -20.0 and 50.0 <= 50.0 (boundary)."""
    v = next(x for x in conformance["verification_verdicts"]
             if x["case"] == "thermalCheck")
    assert v["requirement_id"] == "REQ-STR-002"
    assert v["verdict"] == "pass"


def test_verification_exactly_one_fail(conformance):
    """Only pointingCheck fails among all verification cases."""
    fails = [v for v in conformance["verification_verdicts"]
             if v["verdict"] == "fail"]
    assert len(fails) == 1
    assert fails[0]["case"] == "pointingCheck"


# ======== Orphan Requirements ========


def test_orphan_requirements(conformance):
    """Four requirements have no satisfy relationship."""
    expected = ["REQ-PRO-002", "REQ-PWR-002", "REQ-SYS-003", "REQ-THR-001"]
    assert conformance["orphan_requirements"] == expected


# ======== Unverified Requirements ========


def test_unverified_requirements(conformance):
    """Twelve requirements have no verification case."""
    expected = [
        "REQ-ADC-002", "REQ-COM-001", "REQ-COM-002", "REQ-PAY-001",
        "REQ-PAY-002", "REQ-PRO-001", "REQ-PWR-001", "REQ-PWR-002",
        "REQ-STR-001", "REQ-SYS-003", "REQ-SYS-004", "REQ-THR-001"
    ]
    assert conformance["unverified_requirements"] == expected


# ======== Mass Analysis ========


def test_mass_subsystem_payload(conformance):
    m = conformance["mass_analysis"]["subsystem_masses"]
    assert m["payloadSubsystem"] == pytest.approx(83.0, abs=0.01)


def test_mass_subsystem_power(conformance):
    m = conformance["mass_analysis"]["subsystem_masses"]
    assert m["powerSubsystem"] == pytest.approx(46.0, abs=0.01)


def test_mass_subsystem_adcs(conformance):
    m = conformance["mass_analysis"]["subsystem_masses"]
    assert m["adcsSubsystem"] == pytest.approx(18.0, abs=0.01)


def test_mass_subsystem_comm(conformance):
    m = conformance["mass_analysis"]["subsystem_masses"]
    assert m["commSubsystem"] == pytest.approx(18.0, abs=0.01)


def test_mass_subsystem_propulsion(conformance):
    m = conformance["mass_analysis"]["subsystem_masses"]
    assert m["propulsionSubsystem"] == pytest.approx(26.0, abs=0.01)


def test_mass_subsystem_structure(conformance):
    m = conformance["mass_analysis"]["subsystem_masses"]
    assert m["structureSubsystem"] == pytest.approx(50.0, abs=0.01)


def test_mass_total(conformance):
    assert conformance["mass_analysis"]["total_mass"] == pytest.approx(241.0, abs=0.01)


def test_mass_violations_count(conformance):
    assert len(conformance["mass_analysis"]["violations"]) == 2


def test_mass_violation_adcs(conformance):
    v = conformance["mass_analysis"]["violations"]
    assert v[0]["subsystem"] == "adcsSubsystem"
    assert v[0]["computed_mass"] == pytest.approx(18.0, abs=0.01)
    assert v[0]["budget"] == pytest.approx(15.0, abs=0.01)
    assert v[0]["overrun"] == pytest.approx(3.0, abs=0.01)


def test_mass_violation_structure(conformance):
    v = conformance["mass_analysis"]["violations"]
    assert v[1]["subsystem"] == "structureSubsystem"
    assert v[1]["computed_mass"] == pytest.approx(50.0, abs=0.01)
    assert v[1]["budget"] == pytest.approx(45.0, abs=0.01)
    assert v[1]["overrun"] == pytest.approx(5.0, abs=0.01)


# ======== Power Analysis ========


def test_power_generation(conformance):
    assert conformance["power_analysis"]["total_generation"] == pytest.approx(
        900.0, abs=0.01)


def test_power_consumption(conformance):
    assert conformance["power_analysis"]["total_consumption"] == pytest.approx(
        484.0, abs=0.01)


def test_power_margin(conformance):
    assert conformance["power_analysis"]["margin"] == pytest.approx(416.0, abs=0.01)


def test_power_margin_percent(conformance):
    assert conformance["power_analysis"]["margin_percent"] == pytest.approx(
        46.22, abs=0.01)


def test_power_subsystem_payload(conformance):
    p = conformance["power_analysis"]["subsystem_power"]
    assert p["payloadSubsystem"] == pytest.approx(335.0, abs=0.01)


def test_power_subsystem_adcs(conformance):
    p = conformance["power_analysis"]["subsystem_power"]
    assert p["adcsSubsystem"] == pytest.approx(52.0, abs=0.01)


def test_power_subsystem_comm(conformance):
    p = conformance["power_analysis"]["subsystem_power"]
    assert p["commSubsystem"] == pytest.approx(75.0, abs=0.01)


def test_power_violations_count(conformance):
    assert len(conformance["power_analysis"]["power_violations"]) == 1


def test_power_violation_adcs(conformance):
    v = conformance["power_analysis"]["power_violations"][0]
    assert v["subsystem"] == "adcsSubsystem"
    assert v["computed_power"] == pytest.approx(52.0, abs=0.01)
    assert v["budget"] == pytest.approx(45.0, abs=0.01)
    assert v["overrun"] == pytest.approx(7.0, abs=0.01)


# ======== Requirement Coverage ========


def test_requirement_coverage(conformance):
    cov = conformance["requirement_coverage"]
    assert cov["total"] == 18
    assert cov["satisfied"] == 14
    assert cov["coverage_percent"] == pytest.approx(77.78, abs=0.01)


# ======== Verification Coverage ========


def test_verification_coverage(conformance):
    cov = conformance["verification_coverage"]
    assert cov["total"] == 18
    assert cov["verified"] == 6
    assert cov["coverage_percent"] == pytest.approx(33.33, abs=0.01)


# ======== Action Allocation ========


def test_action_allocation(conformance):
    alloc = conformance["action_allocation"]
    assert alloc["total"] == 10
    assert alloc["allocated"] == 7


def test_unallocated_actions(conformance):
    expected = ["AcquireTarget", "MonitorHealth", "PerformCalibration"]
    assert conformance["unallocated_actions"] == expected


# ======== Traceability Graph ========


def test_traceability_svg_exists():
    """SVG file must exist and contain valid SVG content."""
    assert os.path.exists("/app/results/traceability.svg"), \
        "traceability.svg not found"
    with open("/app/results/traceability.svg") as f:
        content = f.read()
    assert "<svg" in content or "<?xml" in content, \
        "traceability.svg does not contain valid SVG"


def test_traceability_dot_structure():
    """DOT file must contain expected graph structure."""
    assert os.path.exists("/app/results/traceability.dot"), \
        "traceability.dot not found"
    with open("/app/results/traceability.dot") as f:
        content = f.read()
    assert "digraph" in content
    assert "REQ-SYS-001" in content
    assert "REQ-ADC-001" in content
    assert "note" in content.lower() or "shape=note" in content
    assert "diamond" in content.lower() or "shape=diamond" in content


# ======== Nonconformance Summary ========


def test_nonconformance_structure(nonconformance):
    """Nonconformance JSON must have exactly the required keys."""
    required = {"failed_verifications", "mass_violations", "power_violations",
                "orphan_requirements", "unallocated_actions"}
    assert required.issubset(set(nonconformance.keys()))


def test_nonconformance_failed_verifications(nonconformance):
    fails = nonconformance["failed_verifications"]
    assert len(fails) == 1
    assert fails[0]["case"] == "pointingCheck"
    assert fails[0]["verdict"] == "fail"


def test_nonconformance_mass_violations(nonconformance):
    assert len(nonconformance["mass_violations"]) == 2


def test_nonconformance_power_violations(nonconformance):
    assert len(nonconformance["power_violations"]) == 1


def test_nonconformance_orphans(nonconformance):
    assert nonconformance["orphan_requirements"] == [
        "REQ-PRO-002", "REQ-PWR-002", "REQ-SYS-003", "REQ-THR-001"
    ]


def test_nonconformance_unallocated(nonconformance):
    assert nonconformance["unallocated_actions"] == [
        "AcquireTarget", "MonitorHealth", "PerformCalibration"
    ]
