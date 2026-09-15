
import json
import pytest


def load_report():
    with open("/app/report.json") as f:
        return json.load(f)


# ── Extracted Constants ──────────────────────────────────────────────────

class TestExtractedConstants:
    """Verify ioctl constants were extracted from C headers via GCC."""

    EXPECTED = {
        "HWACCEL_CREATE_CTX":     0xC0104801,
        "HWACCEL_DESTROY_CTX":    0x00004802,
        "HWACCEL_ALLOC_BUF":      0xC0204803,
        "HWACCEL_FREE_BUF":       0x40084804,
        "HWACCEL_MAP_BUF":        0xC0204805,
        "HWACCEL_CREATE_QUEUE":   0xC0084806,
        "HWACCEL_SUBMIT_JOB":     0x40304807,
        "HWACCEL_WAIT_JOB":       0xC0104808,
        "HWACCEL_CREATE_EVENT":   0xC0084809,
        "HWACCEL_CANCEL_JOB":     0x4010480A,
        "HWACCEL_GET_INFO":       0x8070480B,
        "HWACCEL_SET_POWER":      0x4008480C,
        "HWACCEL_DBG_READ_REG":   0xC0084810,
        "HWACCEL_DBG_WRITE_REG":  0x40084811,
        "HWACCEL_DBG_DUMP_STATE": 0x80404812,
        "HWACCEL_DBG_INJECT_ERR": 0x40084813,
    }

    def test_all_ioctl_commands_present(self):
        report = load_report()
        consts = report["extracted_constants"]
        for name in self.EXPECTED:
            assert name in consts, f"Missing extracted constant: {name}"

    def test_exactly_16_ioctl_commands(self):
        report = load_report()
        consts = report["extracted_constants"]
        ioctl_keys = [k for k in consts if k.startswith("HWACCEL_")]
        assert len(ioctl_keys) >= 16

    def test_create_ctx_value(self):
        report = load_report()
        assert report["extracted_constants"]["HWACCEL_CREATE_CTX"] == 0xC0104801

    def test_free_buf_value(self):
        report = load_report()
        assert report["extracted_constants"]["HWACCEL_FREE_BUF"] == 0x40084804

    def test_map_buf_value(self):
        report = load_report()
        assert report["extracted_constants"]["HWACCEL_MAP_BUF"] == 0xC0204805

    def test_submit_job_value(self):
        report = load_report()
        assert report["extracted_constants"]["HWACCEL_SUBMIT_JOB"] == 0x40304807

    def test_get_info_value(self):
        report = load_report()
        assert report["extracted_constants"]["HWACCEL_GET_INFO"] == 0x8070480B

    def test_cancel_job_value(self):
        report = load_report()
        assert report["extracted_constants"]["HWACCEL_CANCEL_JOB"] == 0x4010480A

    def test_set_power_value(self):
        report = load_report()
        assert report["extracted_constants"]["HWACCEL_SET_POWER"] == 0x4008480C

    def test_dbg_write_reg_value(self):
        report = load_report()
        assert report["extracted_constants"]["HWACCEL_DBG_WRITE_REG"] == 0x40084811

    def test_dbg_dump_state_value(self):
        report = load_report()
        assert report["extracted_constants"]["HWACCEL_DBG_DUMP_STATE"] == 0x80404812

    def test_all_values_correct(self):
        report = load_report()
        consts = report["extracted_constants"]
        for name, expected in self.EXPECTED.items():
            assert consts[name] == expected, \
                f"{name}: got {hex(consts[name])}, expected {hex(expected)}"


# ── Ioctl Mismatches ────────────────────────────────────────────────────

class TestIoctlMismatches:
    """Verify detection of syzlang vs C header ioctl value mismatches."""

    def test_exactly_three_mismatches(self):
        report = load_report()
        assert len(report["ioctl_mismatches"]) == 3

    def test_mismatches_sorted_by_syscall(self):
        report = load_report()
        names = [m["syscall"] for m in report["ioctl_mismatches"]]
        assert names == sorted(names)

    def test_free_buf_direction_mismatch(self):
        report = load_report()
        mm = {m["syscall"]: m for m in report["ioctl_mismatches"]}
        assert "ioctl$HWACCEL_FREE_BUF" in mm
        entry = mm["ioctl$HWACCEL_FREE_BUF"]
        assert entry["syzlang_value"] == 0xC0084804
        assert entry["expected_value"] == 0x40084804
        assert "direction" in entry["mismatch_fields"]
        assert "size" not in entry["mismatch_fields"]

    def test_map_buf_size_mismatch(self):
        report = load_report()
        mm = {m["syscall"]: m for m in report["ioctl_mismatches"]}
        assert "ioctl$HWACCEL_MAP_BUF" in mm
        entry = mm["ioctl$HWACCEL_MAP_BUF"]
        assert entry["syzlang_value"] == 0xC0104805
        assert entry["expected_value"] == 0xC0204805
        assert "size" in entry["mismatch_fields"]
        assert "direction" not in entry["mismatch_fields"]

    def test_get_info_size_mismatch(self):
        report = load_report()
        mm = {m["syscall"]: m for m in report["ioctl_mismatches"]}
        assert "ioctl$HWACCEL_GET_INFO" in mm
        entry = mm["ioctl$HWACCEL_GET_INFO"]
        assert entry["syzlang_value"] == 0x8040480B
        assert entry["expected_value"] == 0x8070480B
        assert "size" in entry["mismatch_fields"]
        assert "direction" not in entry["mismatch_fields"]

    def test_mismatch_fields_are_sorted(self):
        report = load_report()
        for m in report["ioctl_mismatches"]:
            assert m["mismatch_fields"] == sorted(m["mismatch_fields"])


# ── Struct Field Audit ─────────────────────────────────────────────────

class TestStructFieldAudit:
    """Verify detection of struct layout discrepancies between syzlang and C."""

    def test_only_buggy_structs_present(self):
        report = load_report()
        assert set(report["struct_field_audit"].keys()) == {
            "hwaccel_ctx_info", "hwaccel_state_dump"
        }

    def test_ctx_info_reserved_array_mismatch(self):
        report = load_report()
        audit = report["struct_field_audit"]["hwaccel_ctx_info"]
        assert len(audit) == 1
        entry = audit[0]
        assert entry["field"] == "reserved"
        assert entry["issue"] == "array_size_mismatch"
        assert entry["syzlang_value"] == 4
        assert entry["c_value"] == 2

    def test_state_dump_data_array_mismatch(self):
        report = load_report()
        audit = report["struct_field_audit"]["hwaccel_state_dump"]
        assert len(audit) == 1
        entry = audit[0]
        assert entry["field"] == "data"
        assert entry["issue"] == "array_size_mismatch"
        assert entry["syzlang_value"] == 4096
        assert entry["c_value"] == 48

    def test_no_false_positives_dev_info(self):
        """hwaccel_dev_info has arrays that match — should not appear."""
        report = load_report()
        assert "hwaccel_dev_info" not in report["struct_field_audit"]

    def test_no_reserved_field_noise(self):
        """__reserved fields omitted from syzlang should NOT be flagged."""
        report = load_report()
        for struct_name, discrepancies in report["struct_field_audit"].items():
            for d in discrepancies:
                assert not d["field"].startswith("__"), \
                    f"Padding field {d['field']} should not be flagged"

    def test_discrepancies_sorted_by_field(self):
        report = load_report()
        for struct_name, discrepancies in report["struct_field_audit"].items():
            fields = [d["field"] for d in discrepancies]
            assert fields == sorted(fields)


# ── Resource Identification ─────────────────────────────────────────────

class TestResourceIdentification:
    """Verify all resources are found with correct metadata."""

    def test_all_resources_present(self):
        report = load_report()
        expected = {
            "fd_hwaccel", "fd_hwaccel_ctx", "fd_hwaccel_queue",
            "fd_hwaccel_event", "hwaccel_buf_handle", "hwaccel_job_id",
            "fd_hwaccel_debug",
        }
        assert set(report["resources"].keys()) == expected

    def test_resource_parent_fd_hwaccel(self):
        report = load_report()
        assert report["resources"]["fd_hwaccel"]["parent"] == "fd"

    def test_resource_parent_fd_hwaccel_ctx(self):
        report = load_report()
        assert report["resources"]["fd_hwaccel_ctx"]["parent"] == "fd"

    def test_resource_parent_fd_hwaccel_queue(self):
        report = load_report()
        assert report["resources"]["fd_hwaccel_queue"]["parent"] == "fd"

    def test_resource_parent_fd_hwaccel_event(self):
        report = load_report()
        assert report["resources"]["fd_hwaccel_event"]["parent"] == "fd"

    def test_resource_parent_hwaccel_buf_handle(self):
        report = load_report()
        assert report["resources"]["hwaccel_buf_handle"]["parent"] == "int32"

    def test_resource_parent_hwaccel_job_id(self):
        report = load_report()
        assert report["resources"]["hwaccel_job_id"]["parent"] == "int64"

    def test_resource_parent_fd_hwaccel_debug(self):
        report = load_report()
        assert report["resources"]["fd_hwaccel_debug"]["parent"] == "fd_hwaccel"

    def test_special_values_buf_handle(self):
        report = load_report()
        sv = report["resources"]["hwaccel_buf_handle"]["special_values"]
        assert 0xFFFFFFFF in sv or 4294967295 in sv

    def test_special_values_job_id(self):
        report = load_report()
        assert 0 in report["resources"]["hwaccel_job_id"]["special_values"]

    def test_no_special_values_fd_hwaccel(self):
        report = load_report()
        assert report["resources"]["fd_hwaccel"]["special_values"] == []


# ── Resource Producers ──────────────────────────────────────────────────

class TestResourceProducers:
    """Verify producer detection including through struct fields."""

    def test_fd_hwaccel_producer(self):
        report = load_report()
        producers = sorted(report["resources"]["fd_hwaccel"]["producers"])
        assert producers == ["syz_open_dev$hwaccel"]

    def test_fd_hwaccel_ctx_producer(self):
        report = load_report()
        producers = sorted(report["resources"]["fd_hwaccel_ctx"]["producers"])
        assert producers == ["ioctl$HWACCEL_CREATE_CTX"]

    def test_fd_hwaccel_queue_producer(self):
        report = load_report()
        producers = sorted(report["resources"]["fd_hwaccel_queue"]["producers"])
        assert producers == ["ioctl$HWACCEL_CREATE_QUEUE"]

    def test_fd_hwaccel_event_producer(self):
        report = load_report()
        producers = sorted(report["resources"]["fd_hwaccel_event"]["producers"])
        assert producers == ["ioctl$HWACCEL_CREATE_EVENT"]

    def test_buf_handle_producer_through_struct(self):
        """hwaccel_buf_handle is produced via (out) field in ptr[inout, hwaccel_buf_alloc]."""
        report = load_report()
        producers = sorted(report["resources"]["hwaccel_buf_handle"]["producers"])
        assert producers == ["ioctl$HWACCEL_ALLOC_BUF"]

    def test_job_id_no_producer(self):
        """hwaccel_job_id has no producer — this is a deliberate defect."""
        report = load_report()
        assert report["resources"]["hwaccel_job_id"]["producers"] == []

    def test_fd_hwaccel_debug_producer(self):
        report = load_report()
        producers = sorted(report["resources"]["fd_hwaccel_debug"]["producers"])
        assert producers == ["syz_open_dev$hwaccel_debug"]


# ── Resource Consumers ──────────────────────────────────────────────────

class TestResourceConsumers:
    """Verify consumer detection including through nested pointers in structs."""

    def test_fd_hwaccel_consumers(self):
        report = load_report()
        consumers = sorted(report["resources"]["fd_hwaccel"]["consumers"])
        assert consumers == [
            "ioctl$HWACCEL_CREATE_CTX",
            "ioctl$HWACCEL_CREATE_EVENT",
            "ioctl$HWACCEL_CREATE_QUEUE",
            "ioctl$HWACCEL_GET_INFO",
            "ioctl$HWACCEL_SET_POWER",
        ]

    def test_fd_hwaccel_ctx_consumers(self):
        report = load_report()
        consumers = sorted(report["resources"]["fd_hwaccel_ctx"]["consumers"])
        assert consumers == [
            "ioctl$HWACCEL_ALLOC_BUF",
            "ioctl$HWACCEL_DESTROY_CTX",
            "ioctl$HWACCEL_FREE_BUF",
            "ioctl$HWACCEL_MAP_BUF",
        ]

    def test_fd_hwaccel_queue_consumers(self):
        report = load_report()
        consumers = sorted(report["resources"]["fd_hwaccel_queue"]["consumers"])
        assert consumers == [
            "ioctl$HWACCEL_CANCEL_JOB",
            "ioctl$HWACCEL_SUBMIT_JOB",
            "ioctl$HWACCEL_WAIT_JOB",
        ]

    def test_fd_hwaccel_event_no_consumer(self):
        """fd_hwaccel_event is produced but never consumed — deliberate defect."""
        report = load_report()
        assert report["resources"]["fd_hwaccel_event"]["consumers"] == []

    def test_buf_handle_consumers_through_structs(self):
        """hwaccel_buf_handle consumed via struct fields, including nested ptr[in, array[...]]."""
        report = load_report()
        consumers = sorted(report["resources"]["hwaccel_buf_handle"]["consumers"])
        assert "ioctl$HWACCEL_FREE_BUF" in consumers
        assert "ioctl$HWACCEL_MAP_BUF" in consumers
        assert "ioctl$HWACCEL_SUBMIT_JOB" in consumers
        assert len(consumers) == 3

    def test_job_id_consumer(self):
        report = load_report()
        consumers = sorted(report["resources"]["hwaccel_job_id"]["consumers"])
        assert consumers == ["ioctl$HWACCEL_CANCEL_JOB"]

    def test_fd_hwaccel_debug_consumers(self):
        report = load_report()
        consumers = sorted(report["resources"]["fd_hwaccel_debug"]["consumers"])
        assert consumers == [
            "ioctl$HWACCEL_DBG_DUMP_STATE",
            "ioctl$HWACCEL_DBG_INJECT_ERR",
            "ioctl$HWACCEL_DBG_READ_REG",
            "ioctl$HWACCEL_DBG_WRITE_REG",
        ]


# ── Orphan Resources ───────────────────────────────────────────────────

class TestOrphanResources:
    """Resources missing either a producer or a consumer."""

    def test_orphan_list(self):
        report = load_report()
        orphans = sorted(report["orphan_resources"])
        assert orphans == ["fd_hwaccel_event", "hwaccel_job_id"]


# ── Dead Consumers ─────────────────────────────────────────────────────

class TestDeadConsumers:
    """Syscalls consuming resources that can never be produced."""

    def test_dead_consumers(self):
        report = load_report()
        dead = sorted(report["dead_consumers"])
        assert dead == ["ioctl$HWACCEL_CANCEL_JOB"]


# ── Undefined Refs ─────────────────────────────────────────────────────

class TestUndefinedRefs:
    """Flag sets referenced but never defined."""

    def test_undefined_flag_names(self):
        report = load_report()
        undef_names = sorted([r["name"] for r in report["undefined_refs"]])
        assert undef_names == ["hwaccel_cap_flags", "hwaccel_wait_flags"]

    def test_undefined_flag_categories(self):
        report = load_report()
        for ref in report["undefined_refs"]:
            assert ref["category"] == "flags"

    def test_undefined_flag_contexts(self):
        report = load_report()
        ctx_map = {r["name"]: r["referenced_by"] for r in report["undefined_refs"]}
        assert ctx_map["hwaccel_cap_flags"] == "hwaccel_ctx_info"
        assert ctx_map["hwaccel_wait_flags"] == "hwaccel_job_wait"


# ── Invalid Len Refs ───────────────────────────────────────────────────

class TestInvalidLenRefs:
    """len[] references to nonexistent sibling fields."""

    def test_invalid_len_count(self):
        report = load_report()
        assert len(report["invalid_len_refs"]) == 2

    def test_invalid_len_buf_map(self):
        report = load_report()
        entries = {(r["struct"], r["field"]): r["references"]
                   for r in report["invalid_len_refs"]}
        assert ("hwaccel_buf_map", "length") in entries
        assert entries[("hwaccel_buf_map", "length")] == "data"

    def test_invalid_len_state_dump(self):
        report = load_report()
        entries = {(r["struct"], r["field"]): r["references"]
                   for r in report["invalid_len_refs"]}
        assert ("hwaccel_state_dump", "num_entries") in entries
        assert entries[("hwaccel_state_dump", "num_entries")] == "entries"


# ── Unused Flags ───────────────────────────────────────────────────────

class TestUnusedFlags:
    """Flag sets defined but never referenced."""

    def test_unused_flags(self):
        report = load_report()
        unused = sorted(report["unused_flags"])
        assert unused == ["hwaccel_debug_levels"]


# ── Resource Dependency Order ──────────────────────────────────────────

class TestResourceDependencyOrder:
    """Topologically sorted resource creation order."""

    def test_excludes_no_producer_resources(self):
        report = load_report()
        order = report["resource_dependency_order"]
        assert "hwaccel_job_id" not in order

    def test_includes_all_produced_resources(self):
        report = load_report()
        order = report["resource_dependency_order"]
        expected = {
            "fd_hwaccel", "fd_hwaccel_ctx", "fd_hwaccel_queue",
            "fd_hwaccel_event", "hwaccel_buf_handle", "fd_hwaccel_debug",
        }
        assert set(order) == expected

    def test_fd_hwaccel_before_dependents(self):
        report = load_report()
        order = report["resource_dependency_order"]
        idx_hwaccel = order.index("fd_hwaccel")
        for dep in ["fd_hwaccel_ctx", "fd_hwaccel_queue", "fd_hwaccel_event"]:
            assert order.index(dep) > idx_hwaccel, \
                f"{dep} should come after fd_hwaccel"

    def test_fd_hwaccel_ctx_before_buf_handle(self):
        report = load_report()
        order = report["resource_dependency_order"]
        assert order.index("fd_hwaccel_ctx") < order.index("hwaccel_buf_handle")

    def test_buf_handle_is_last(self):
        """hwaccel_buf_handle depends on fd_hwaccel_ctx which depends on fd_hwaccel."""
        report = load_report()
        order = report["resource_dependency_order"]
        assert order.index("hwaccel_buf_handle") == len(order) - 1

    def test_exact_order_with_alphabetical_tiebreak(self):
        report = load_report()
        order = report["resource_dependency_order"]
        expected = [
            "fd_hwaccel",
            "fd_hwaccel_ctx",
            "fd_hwaccel_debug",
            "fd_hwaccel_event",
            "fd_hwaccel_queue",
            "hwaccel_buf_handle",
        ]
        assert order == expected


# ── Minimum Call Depth ─────────────────────────────────────────────────

class TestMinimumCallDepth:
    """Minimum prerequisite syscall count for each syscall via resource deps."""

    EXPECTED = {
        "syz_open_dev$hwaccel": 0,
        "syz_open_dev$hwaccel_debug": 0,
        "ioctl$HWACCEL_CREATE_CTX": 1,
        "ioctl$HWACCEL_DESTROY_CTX": 2,
        "ioctl$HWACCEL_ALLOC_BUF": 2,
        "ioctl$HWACCEL_FREE_BUF": 3,
        "ioctl$HWACCEL_MAP_BUF": 3,
        "ioctl$HWACCEL_CREATE_QUEUE": 1,
        "ioctl$HWACCEL_SUBMIT_JOB": 4,
        "ioctl$HWACCEL_WAIT_JOB": 2,
        "ioctl$HWACCEL_CREATE_EVENT": 1,
        "ioctl$HWACCEL_CANCEL_JOB": -1,
        "ioctl$HWACCEL_GET_INFO": 1,
        "ioctl$HWACCEL_SET_POWER": 1,
        "ioctl$HWACCEL_DBG_READ_REG": 1,
        "ioctl$HWACCEL_DBG_WRITE_REG": 1,
        "ioctl$HWACCEL_DBG_DUMP_STATE": 1,
        "ioctl$HWACCEL_DBG_INJECT_ERR": 1,
    }

    def test_all_syscalls_present(self):
        report = load_report()
        depth = report["minimum_call_depth"]
        for name in self.EXPECTED:
            assert name in depth, f"Missing syscall in minimum_call_depth: {name}"

    def test_depth_zero_no_resource_inputs(self):
        """Syscalls that open devices need no preceding calls."""
        report = load_report()
        depth = report["minimum_call_depth"]
        assert depth["syz_open_dev$hwaccel"] == 0
        assert depth["syz_open_dev$hwaccel_debug"] == 0

    def test_depth_one_direct_device_fd(self):
        """Ioctls needing only a device fd require 1 predecessor."""
        report = load_report()
        depth = report["minimum_call_depth"]
        for name in ["ioctl$HWACCEL_CREATE_CTX", "ioctl$HWACCEL_CREATE_QUEUE",
                      "ioctl$HWACCEL_CREATE_EVENT", "ioctl$HWACCEL_GET_INFO",
                      "ioctl$HWACCEL_SET_POWER"]:
            assert depth[name] == 1, f"{name}: expected 1, got {depth[name]}"

    def test_depth_two_context_dependent(self):
        """Ioctls needing a context fd require 2 predecessors."""
        report = load_report()
        depth = report["minimum_call_depth"]
        assert depth["ioctl$HWACCEL_DESTROY_CTX"] == 2
        assert depth["ioctl$HWACCEL_ALLOC_BUF"] == 2

    def test_depth_three_buffer_dependent(self):
        """Ioctls needing context + buffer handle require 3 predecessors."""
        report = load_report()
        depth = report["minimum_call_depth"]
        assert depth["ioctl$HWACCEL_FREE_BUF"] == 3
        assert depth["ioctl$HWACCEL_MAP_BUF"] == 3

    def test_depth_four_cross_chain_union(self):
        """SUBMIT_JOB needs queue (chain A) + buf_handle (chain B).
        Chain A: open_dev -> create_queue (2 syscalls)
        Chain B: open_dev -> create_ctx -> alloc_buf (3 syscalls)
        Union: open_dev + create_queue + create_ctx + alloc_buf = 4 distinct."""
        report = load_report()
        depth = report["minimum_call_depth"]
        assert depth["ioctl$HWACCEL_SUBMIT_JOB"] == 4

    def test_unreachable_no_producer(self):
        """CANCEL_JOB needs hwaccel_job_id which has no producer."""
        report = load_report()
        depth = report["minimum_call_depth"]
        assert depth["ioctl$HWACCEL_CANCEL_JOB"] == -1

    def test_debug_ioctls_depth_one(self):
        """Debug ioctls need only the debug device fd."""
        report = load_report()
        depth = report["minimum_call_depth"]
        for name in ["ioctl$HWACCEL_DBG_READ_REG", "ioctl$HWACCEL_DBG_WRITE_REG",
                      "ioctl$HWACCEL_DBG_DUMP_STATE", "ioctl$HWACCEL_DBG_INJECT_ERR"]:
            assert depth[name] == 1

    def test_all_depths_correct(self):
        report = load_report()
        depth = report["minimum_call_depth"]
        for name, expected in self.EXPECTED.items():
            assert depth[name] == expected, \
                f"{name}: got {depth[name]}, expected {expected}"
