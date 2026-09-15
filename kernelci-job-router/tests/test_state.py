
import json
import os
import pytest


@pytest.fixture(scope="session")
def report():
    report_path = "/app/output/routing_report.json"
    assert os.path.exists(report_path), f"Routing report not found at {report_path}"
    with open(report_path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def decisions(report):
    return {d["event_id"]: d for d in report["routing_decisions"]}


# ── Report Structure ──────────────────────────────────────────────────────


class TestReportStructure:
    def test_has_routing_decisions(self, report):
        assert "routing_decisions" in report
        assert isinstance(report["routing_decisions"], list)

    def test_has_validation_errors(self, report):
        assert "validation_errors" in report
        assert isinstance(report["validation_errors"], list)

    def test_has_summary(self, report):
        assert "summary" in report
        assert isinstance(report["summary"], dict)

    def test_has_capacity_impact(self, report):
        assert "capacity_impact" in report
        assert isinstance(report["capacity_impact"], dict)

    def test_all_events_present(self, report):
        event_ids = [d["event_id"] for d in report["routing_decisions"]]
        for i in range(1, 16):
            assert f"evt_{i:03d}" in event_ids, f"evt_{i:03d} missing"

    def test_event_order_preserved(self, report):
        event_ids = [d["event_id"] for d in report["routing_decisions"]]
        expected = [f"evt_{i:03d}" for i in range(1, 16)]
        assert event_ids == expected


# ── Summary ───────────────────────────────────────────────────────────────


class TestSummary:
    def test_total_events(self, report):
        assert report["summary"]["total_events"] == 15

    def test_routed_count(self, report):
        assert report["summary"]["routed"] == 11

    def test_unroutable_count(self, report):
        assert report["summary"]["unroutable"] == 4

    def test_unroutable_by_spec(self, report):
        assert report["summary"]["unroutable_by_spec"] == 3

    def test_unroutable_by_capacity(self, report):
        assert report["summary"]["unroutable_by_capacity"] == 1

    def test_validation_error_count(self, report):
        assert report["summary"]["validation_error_count"] == 3

    def test_labs_used_keys_sorted(self, report):
        keys = list(report["summary"]["labs_used"].keys())
        assert keys == sorted(keys)


# ── Validation Errors ─────────────────────────────────────────────────────


class TestValidationErrors:
    def test_exactly_three_errors(self, report):
        assert len(report["validation_errors"]) == 3

    def test_errors_sorted_by_lab(self, report):
        labs = [e["lab"] for e in report["validation_errors"]]
        assert labs == sorted(labs)

    def test_cip_invalid_priority_range(self, report):
        errors = report["validation_errors"]
        cip = [e for e in errors if e["lab"] == "lava-cip"]
        assert len(cip) == 1
        assert cip[0]["error_type"] == "invalid_priority_range"

    def test_kontron_insecure_url(self, report):
        errors = report["validation_errors"]
        kontron = [e for e in errors if e["lab"] == "lava-kontron"]
        assert len(kontron) == 1
        assert kontron[0]["error_type"] == "insecure_url"

    def test_riscv_missing_callback(self, report):
        errors = report["validation_errors"]
        riscv = [e for e in errors if e["lab"] == "lava-riscv"]
        assert len(riscv) == 1
        assert riscv[0]["error_type"] == "missing_callback_token"

    def test_no_non_lava_errors(self, report):
        error_labs = {e["lab"] for e in report["validation_errors"]}
        assert "docker-host" not in error_labs
        assert "k8s-all" not in error_labs


# ── Routing Decisions (Scoring-Driven Selection) ─────────────────────────


class TestRoutingDecisions:
    def test_evt_001_mainline_qemu_arm64(self, decisions):
        """Pengutronix wins via scoring: high reliability + medium cost +
        full capacity. Priority 50 fits [30,70]."""
        d = decisions["evt_001"]
        assert d["selected_lab"] == "lava-pengutronix"
        assert d["assigned_priority"] == 50
        assert d["priority_clamped"] is False
        assert len(d["eligible_labs"]) == 5

    def test_evt_001_eligible_labs_sorted(self, decisions):
        d = decisions["evt_001"]
        expected = [
            "lava-baylibre",
            "lava-broonie",
            "lava-collabora",
            "lava-internal",
            "lava-pengutronix",
        ]
        assert d["eligible_labs"] == expected

    def test_evt_002_next_rk3399(self, decisions):
        """Collabora wins: highest rk3399 reliability (0.98) overcomes its
        high cost. All labs at full or near-full capacity."""
        d = decisions["evt_002"]
        assert d["selected_lab"] == "lava-collabora"
        assert d["assigned_priority"] == 45
        assert d["priority_clamped"] is False
        assert len(d["eligible_labs"]) == 3

    def test_evt_002_eligible_labs(self, decisions):
        expected = ["lava-baylibre", "lava-collabora", "lava-pengutronix"]
        assert decisions["evt_002"]["eligible_labs"] == expected

    def test_evt_003_stable_x86(self, decisions):
        """Collabora wins: capacity headroom advantage (3/4 = 0.75) over
        pengutronix (1/2) more than offsets cost difference."""
        d = decisions["evt_003"]
        assert d["selected_lab"] == "lava-collabora"
        assert d["assigned_priority"] == 55
        assert d["priority_clamped"] is False
        assert "lava-kontron" not in d["eligible_labs"]

    def test_evt_003_eligible_labs(self, decisions):
        expected = ["lava-collabora", "lava-internal", "lava-pengutronix"]
        assert decisions["evt_003"]["eligible_labs"] == expected

    def test_evt_004_android_only_baylibre(self, decisions):
        """Only baylibre has db410c and matches android-* tree."""
        d = decisions["evt_004"]
        assert d["selected_lab"] == "lava-baylibre"
        assert d["assigned_priority"] == 30
        assert d["eligible_labs"] == ["lava-baylibre"]

    def test_evt_005_unroutable_excluded_lab(self, decisions):
        """sifive-hifive-unmatched only at lava-riscv (excluded)."""
        d = decisions["evt_005"]
        assert d["selected_lab"] is None
        assert d["eligible_labs"] == []
        assert d["assigned_priority"] is None
        assert d["lava_job"] is None

    def test_evt_006_unroutable_no_device(self, decisions):
        """unknown-prototype-board not in any lab's catalog."""
        d = decisions["evt_006"]
        assert d["selected_lab"] is None
        assert d["eligible_labs"] == []
        assert d["lava_job"] is None

    def test_evt_007_unroutable_stable_rc_excluded(self, decisions):
        """stable-rc-6.12 matches collabora's stable* inclusion but is blocked
        by the !stable-rc-* exclusion, and doesn't match any other lab's
        exact 'stable' pattern."""
        d = decisions["evt_007"]
        assert d["selected_lab"] is None
        assert d["eligible_labs"] == []

    def test_evt_008_priority_clamped_up(self, decisions):
        """stable-5.10 only matches collabora's stable* glob (not broonie's
        exact 'stable'). Priority 10 is below collabora's min 40, clamped up."""
        d = decisions["evt_008"]
        assert d["selected_lab"] == "lava-collabora"
        assert d["assigned_priority"] == 40
        assert d["priority_clamped"] is True
        assert d["eligible_labs"] == ["lava-collabora"]

    def test_evt_009_pengutronix_stable(self, decisions):
        """renesas-rzg2l only at cip(excluded) and pengutronix."""
        d = decisions["evt_009"]
        assert d["selected_lab"] == "lava-pengutronix"
        assert d["assigned_priority"] == 40
        assert d["priority_clamped"] is False

    def test_evt_010_chrome_internal_only(self, decisions):
        """chrome-platform: collabora has no chrome-* rule, pengutronix
        excludes chrome-*. Only internal matches."""
        d = decisions["evt_010"]
        assert d["selected_lab"] == "lava-internal"
        assert d["assigned_priority"] == 60
        assert d["eligible_labs"] == ["lava-internal"]

    def test_evt_011_riscv_internal(self, decisions):
        """qemu-riscv64 at riscv(excluded) and internal. Internal still
        has capacity at this point."""
        d = decisions["evt_011"]
        assert d["selected_lab"] == "lava-internal"
        assert d["assigned_priority"] == 35
        assert d["eligible_labs"] == ["lava-internal"]
        assert d["priority_clamped"] is False

    def test_evt_012_arm_soc_broonie(self, decisions):
        """arm-soc tree only matches broonie (not baylibre)."""
        d = decisions["evt_012"]
        assert d["selected_lab"] == "lava-broonie"
        assert d["assigned_priority"] == 30
        assert d["eligible_labs"] == ["lava-broonie"]

    def test_evt_013_capacity_driven_reroute(self, decisions):
        """Same query as evt_002 (next, rk3399) but collabora's reduced
        capacity headroom (1/4=0.25) lets baylibre win on cost advantage.
        Pengutronix is filtered out (0 capacity)."""
        d = decisions["evt_013"]
        assert d["selected_lab"] == "lava-baylibre"
        assert d["assigned_priority"] == 45
        assert d["priority_clamped"] is False
        assert "lava-pengutronix" not in d["eligible_labs"]

    def test_evt_013_eligible_labs(self, decisions):
        expected = ["lava-baylibre", "lava-collabora"]
        assert decisions["evt_013"]["eligible_labs"] == expected

    def test_evt_014_stable_glob_match(self, decisions):
        """stable-5.15 matches collabora's stable* glob but not baylibre's
        exact 'stable'. Collabora is the only eligible lab with capacity."""
        d = decisions["evt_014"]
        assert d["selected_lab"] == "lava-collabora"
        assert d["assigned_priority"] == 50
        assert "lava-baylibre" not in d["eligible_labs"]
        assert d["eligible_labs"] == ["lava-collabora"]

    def test_evt_015_capacity_blocked(self, decisions):
        """All eligible labs (broonie, collabora, internal, pengutronix)
        are at zero capacity. Event cannot be routed."""
        d = decisions["evt_015"]
        assert d["selected_lab"] is None
        assert d["eligible_labs"] == []
        assert d["assigned_priority"] is None
        assert d["lava_job"] is None


# ── Capacity Impact Analysis ──────────────────────────────────────────────


class TestCapacityImpact:
    def test_impact_structure(self, report):
        ci = report["capacity_impact"]
        assert "rerouted_events" in ci
        assert "blocked_events" in ci
        assert "total_rerouted" in ci
        assert "total_blocked" in ci

    def test_total_rerouted(self, report):
        assert report["capacity_impact"]["total_rerouted"] == 2

    def test_total_blocked(self, report):
        assert report["capacity_impact"]["total_blocked"] == 1

    def test_rerouted_count(self, report):
        assert len(report["capacity_impact"]["rerouted_events"]) == 2

    def test_blocked_count(self, report):
        assert len(report["capacity_impact"]["blocked_events"]) == 1

    def test_evt_003_rerouted(self, report):
        """With unlimited capacity, pengutronix wins evt_003 (higher score
        from full headroom + lower cost). Actual: collabora wins due to
        pengutronix's reduced headroom."""
        rerouted = report["capacity_impact"]["rerouted_events"]
        evt_003 = [r for r in rerouted if r["event_id"] == "evt_003"]
        assert len(evt_003) == 1
        assert evt_003[0]["actual_lab"] == "lava-collabora"
        assert evt_003[0]["unconstrained_lab"] == "lava-pengutronix"

    def test_evt_013_rerouted(self, report):
        """With unlimited capacity, collabora wins evt_013 (highest rk3399
        reliability). Actual: baylibre wins due to collabora's capacity
        dropping to 1/4 headroom."""
        rerouted = report["capacity_impact"]["rerouted_events"]
        evt_013 = [r for r in rerouted if r["event_id"] == "evt_013"]
        assert len(evt_013) == 1
        assert evt_013[0]["actual_lab"] == "lava-baylibre"
        assert evt_013[0]["unconstrained_lab"] == "lava-collabora"

    def test_evt_015_blocked(self, report):
        """With unlimited capacity, pengutronix wins (highest score among
        eligible labs for mainline/qemu-x86_64). Blocked because all 4
        eligible labs exhausted capacity."""
        blocked = report["capacity_impact"]["blocked_events"]
        evt_015 = [b for b in blocked if b["event_id"] == "evt_015"]
        assert len(evt_015) == 1
        assert evt_015[0]["unconstrained_lab"] == "lava-pengutronix"

    def test_evt_015_exhausted_labs(self, report):
        blocked = report["capacity_impact"]["blocked_events"]
        evt_015 = [b for b in blocked if b["event_id"] == "evt_015"][0]
        expected = [
            "lava-broonie",
            "lava-collabora",
            "lava-internal",
            "lava-pengutronix",
        ]
        assert evt_015["exhausted_labs"] == expected

    def test_rerouted_sorted_by_event_id(self, report):
        ids = [r["event_id"] for r in report["capacity_impact"]["rerouted_events"]]
        assert ids == sorted(ids)

    def test_blocked_sorted_by_event_id(self, report):
        ids = [b["event_id"] for b in report["capacity_impact"]["blocked_events"]]
        assert ids == sorted(ids)


# ── LAVA Job Generation ──────────────────────────────────────────────────


class TestLavaJobGeneration:
    def test_routed_events_have_jobs(self, decisions):
        routed = [
            "evt_001", "evt_002", "evt_003", "evt_004", "evt_008",
            "evt_009", "evt_010", "evt_011", "evt_012", "evt_013",
            "evt_014",
        ]
        for eid in routed:
            assert decisions[eid]["lava_job"] is not None, f"{eid} missing job"

    def test_unrouted_events_have_no_jobs(self, decisions):
        for eid in ["evt_005", "evt_006", "evt_007", "evt_015"]:
            assert decisions[eid]["lava_job"] is None, f"{eid} shouldn't have job"

    def test_job_required_fields(self, decisions):
        for eid, d in decisions.items():
            if d["lava_job"] is not None:
                job = d["lava_job"]
                for field in ["device_type", "job_name", "priority",
                              "timeouts", "boot_method", "notify"]:
                    assert field in job, f"{eid} missing field {field}"

    def test_job_name_format_evt_001(self, decisions):
        job = decisions["evt_001"]["lava_job"]
        assert job["job_name"] == "kernelci-mainline-master-qemu-arm64-a1b2c3d4e5f6"

    def test_job_name_format_evt_004(self, decisions):
        job = decisions["evt_004"]["lava_job"]
        assert job["job_name"] == "kernelci-android-common-android-mainline-db410c-abcdef123456"

    def test_job_name_format_evt_013(self, decisions):
        job = decisions["evt_013"]["lava_job"]
        assert job["job_name"] == "kernelci-next-next-20250602-rk3399-gru-kevin-a1a2a3a4a5a6"

    def test_boot_method_qemu(self, decisions):
        assert decisions["evt_001"]["lava_job"]["boot_method"] == "qemu"
        assert decisions["evt_011"]["lava_job"]["boot_method"] == "qemu"

    def test_boot_method_grub(self, decisions):
        assert decisions["evt_003"]["lava_job"]["boot_method"] == "grub"
        assert decisions["evt_010"]["lava_job"]["boot_method"] == "grub"

    def test_boot_method_fastboot(self, decisions):
        assert decisions["evt_004"]["lava_job"]["boot_method"] == "fastboot"

    def test_boot_method_uboot(self, decisions):
        assert decisions["evt_002"]["lava_job"]["boot_method"] == "u-boot"
        assert decisions["evt_008"]["lava_job"]["boot_method"] == "u-boot"
        assert decisions["evt_009"]["lava_job"]["boot_method"] == "u-boot"
        assert decisions["evt_012"]["lava_job"]["boot_method"] == "u-boot"
        assert decisions["evt_013"]["lava_job"]["boot_method"] == "u-boot"
        assert decisions["evt_014"]["lava_job"]["boot_method"] == "u-boot"

    def test_callback_url_matches_selected_lab(self, decisions):
        for eid, d in decisions.items():
            if d["lava_job"] is not None:
                lab = d["selected_lab"]
                expected_url = f"https://callback.kernelci.org/lava/{lab}"
                assert d["lava_job"]["notify"]["callback_url"] == expected_url

    def test_callback_token_pengutronix(self, decisions):
        job = decisions["evt_001"]["lava_job"]
        assert job["notify"]["token"] == "kernelci-callback-pengutronix"

    def test_callback_token_collabora(self, decisions):
        job = decisions["evt_002"]["lava_job"]
        assert job["notify"]["token"] == "kernelci-callback-collabora"

    def test_callback_token_baylibre(self, decisions):
        job = decisions["evt_004"]["lava_job"]
        assert job["notify"]["token"] == "kernelci-callback-baylibre"

    def test_callback_token_internal(self, decisions):
        job = decisions["evt_010"]["lava_job"]
        assert job["notify"]["token"] == "kernelci-callback-internal"

    def test_callback_token_broonie(self, decisions):
        job = decisions["evt_012"]["lava_job"]
        assert job["notify"]["token"] == "kernelci-callback-broonie"

    def test_callback_token_baylibre_evt_013(self, decisions):
        """evt_013 now routes to baylibre (capacity-driven), verify token."""
        job = decisions["evt_013"]["lava_job"]
        assert job["notify"]["token"] == "kernelci-callback-baylibre"

    def test_timeouts_structure(self, decisions):
        job = decisions["evt_001"]["lava_job"]
        assert job["timeouts"]["job"]["minutes"] == 30
        assert job["timeouts"]["action"]["minutes"] == 10
        assert job["timeouts"]["connection"]["minutes"] == 5

    def test_priority_matches_assigned(self, decisions):
        for eid, d in decisions.items():
            if d["lava_job"] is not None:
                assert d["lava_job"]["priority"] == d["assigned_priority"]

    def test_device_type_matches_event(self, decisions):
        expected_devices = {
            "evt_001": "qemu-arm64",
            "evt_002": "rk3399-gru-kevin",
            "evt_003": "x86-64-pc",
            "evt_004": "db410c",
            "evt_008": "bcm2711-rpi-4-b",
            "evt_012": "meson-g12b-a311d-khadas-vim3",
        }
        for eid, dev in expected_devices.items():
            assert decisions[eid]["lava_job"]["device_type"] == dev


# ── Lab Usage Summary ─────────────────────────────────────────────────────


class TestLabUsageSummary:
    def test_collabora_count(self, report):
        assert report["summary"]["labs_used"].get("lava-collabora") == 4

    def test_baylibre_count(self, report):
        assert report["summary"]["labs_used"].get("lava-baylibre") == 2

    def test_broonie_count(self, report):
        assert report["summary"]["labs_used"].get("lava-broonie") == 1

    def test_pengutronix_count(self, report):
        assert report["summary"]["labs_used"].get("lava-pengutronix") == 2

    def test_internal_count(self, report):
        assert report["summary"]["labs_used"].get("lava-internal") == 2

    def test_excluded_labs_not_used(self, report):
        used = report["summary"]["labs_used"]
        assert "lava-kontron" not in used
        assert "lava-cip" not in used
        assert "lava-riscv" not in used

    def test_total_routed_matches_sum(self, report):
        total = sum(report["summary"]["labs_used"].values())
        assert total == report["summary"]["routed"]
