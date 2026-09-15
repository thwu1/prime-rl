#!/usr/bin/env python3
"""Generate VK-GL-CTS conformance submission test data for audit task."""
import os
import json
import tarfile
import io

BASE = "/data"

# -- Test name generators --

def info_tests():
    return [f"dEQP-VK.info.{t}" for t in [
        "build", "device", "platform", "memory", "instance_extensions"]]

def api_tests():
    buf = [f"dEQP-VK.api.buffer.basic.{t}" for t in [
        "max_size", "max_size_sparse", "size_max_uint64", "create_none",
        "create_sparse_binding", "create_sparse_residency",
        "create_sparse_aliased", "create_protected"]]
    dev = [f"dEQP-VK.api.device_init.{t}" for t in [
        "create_instance_name_version", "create_instance_invalid_api_version",
        "create_instance_null_appinfo", "create_instance_unsupported_extensions",
        "create_instance_layer_name", "create_device_queue2",
        "create_device_unsupported_extensions",
        "create_device_unsupported_features",
        "create_device_queue_priorities", "create_multiple_devices",
        "enumerate_physical_devices", "device_properties", "device_features"]]
    return buf + dev

def compute_tests():
    basic = [f"dEQP-VK.compute.pipeline.basic.{t}" for t in [
        "empty_shader", "copy_ssbo_single_invocation",
        "copy_ssbo_multiple_invocations", "copy_ssbo_multiple_groups",
        "copy_ssbo_bounds", "copy_image_to_ssbo_small",
        "copy_image_to_ssbo_large", "copy_ssbo_to_image_small",
        "copy_ssbo_to_image_large", "image_atomic_op_local_size_1",
        "image_atomic_op_local_size_8", "image_barrier_single",
        "image_barrier_multiple", "shared_var_single_invocation",
        "shared_var_single_group", "shared_var_multiple_invocations",
        "shared_var_multiple_groups", "shared_atomic_op_single_invocation",
        "shared_atomic_op_single_group",
        "shared_atomic_op_multiple_invocations",
        "shared_atomic_op_multiple_groups", "ssbo_rw_single_invocation",
        "ssbo_rw_multiple_groups", "atomic_barrier_sum_small",
        "concurrent_compute"]]
    bvar = [f"dEQP-VK.compute.pipeline.builtin_var.{t}" for t in [
        "global_invocation_id", "global_invocation_id_component",
        "local_invocation_id", "local_invocation_id_component",
        "local_invocation_index", "num_work_groups",
        "num_work_groups_component", "work_group_id",
        "work_group_id_component", "work_group_size"]]
    return basic + bvar

def spirv_tests():
    prefix = "dEQP-VK.spirv_assembly.instruction"
    max3 = []
    for dtype in ["f16","f32","f64","i8","i16","i32","i64",
                   "u8","u16","u32","u64"]:
        for vec in ["scalar","vec2","vec3","vec4"]:
            max3.append(f"{prefix}.amd_trinary_minmax.max3.{dtype}.{vec}")
    storage = []
    for target in ["push_constant", "uniform"]:
        for dt in ["scalar_sint","scalar_uint","scalar_float",
                    "vector_sint","vector_uint","vector_float"]:
            for conv in ["16_to_32","16_to_64"]:
                storage.append(
                    f"{prefix}.compute.16bit_storage.{target}.{dt}_{conv}")
    for extra in ["matrix_float_16_to_32","matrix_float_16_to_64",
                   "struct_mixed_types_16_to_32","struct_mixed_types_16_to_64",
                   "array_stride_16_to_32","array_stride_16_to_64"]:
        storage.append(
            f"{prefix}.compute.16bit_storage.uniform.{extra}")
    return max3 + storage

def sync_tests():
    fence = [f"dEQP-VK.synchronization.basic.fence.{t}" for t in [
        "one","multi","empty_submit","multi_waitall","multi_waitany"]]
    bsem = [f"dEQP-VK.synchronization.basic.binary_semaphore.{t}" for t in [
        "one_queue","multi_queue","chain"]]
    tsem = [f"dEQP-VK.synchronization.basic.timeline_semaphore.{t}" for t in [
        "one_queue","multi_queue","chain","wait_before_signal",
        "host_signal","host_wait"]]
    evt = [f"dEQP-VK.synchronization.basic.event.{t}" for t in [
        "host_set_device_wait","device_set_host_wait",
        "host_set_host_wait","device_set_device_wait",
        "single_submit_multi_event","multi_submit_multi_event",
        "multi_secondary_cmd_buf"]]
    return fence + bsem + tsem + evt

def memory_tests():
    alloc = [f"dEQP-VK.memory.allocation.basic.{t}" for t in [
        "size_256","size_1024","size_4096","size_131072","size_1048576"]]
    rand = [f"dEQP-VK.memory.allocation.random.{t}" for t in [
        "uniform_1_to_1048576","uniform_power_of_two","mixed_sizes"]]
    oom = [f"dEQP-VK.memory.allocation.oom.{t}" for t in [
        "device_oom","host_oom"]]
    mapb = [f"dEQP-VK.memory.mapping.basic.{t}" for t in [
        "full_map","sub_map","remap","coherent","flush_invalidate"]]
    mapr = [f"dEQP-VK.memory.mapping.random.{t}" for t in [
        "uniform_sizes","mixed_sizes"]]
    req = [f"dEQP-VK.memory.requirements.{t}" for t in [
        "buffer.regular","buffer.sparse","image.regular"]]
    return alloc + rand + oom + mapb + mapr + req

def ray_tracing_tests():
    """Extension-gated: requires VK_KHR_ray_tracing_pipeline."""
    return [f"dEQP-VK.ray_tracing.pipeline.{t}" for t in [
        "basic.triangles", "basic.aabbs", "closesthit.triangles",
        "closesthit.aabbs", "anyhit.triangles", "anyhit.aabbs",
        "miss.basic", "intersection.basic",
        "callable.basic", "recursive.depth_2"]]

def mesh_shader_tests():
    """Extension-gated: requires VK_EXT_mesh_shader."""
    return [f"dEQP-VK.mesh_shader.{t}" for t in [
        "basic.point_list", "basic.line_list", "basic.triangle_list",
        "basic.triangle_strip", "task_shader.basic",
        "task_shader.payload", "properties.max_draw_mesh_tasks",
        "properties.max_mesh_work_group_count"]]

# -- Mustpass categories (all included in mustpass files) --

CATEGORIES = {
    "info": info_tests(),
    "api": api_tests(),
    "compute": compute_tests(),
    "spirv-assembly": spirv_tests(),
    "synchronization": sync_tests(),
    "memory": memory_tests(),
    "ray-tracing": ray_tracing_tests(),
    "mesh-shader": mesh_shader_tests(),
}

ALL_MUSTPASS = []
for cat in ["info","api","compute","spirv-assembly","synchronization","memory",
            "ray-tracing","mesh-shader"]:
    ALL_MUSTPASS.extend(CATEGORIES[cat])

# Extension-gated tests: only mandatory if device supports the extension
EXTENSION_TEST_MAP = {
    "VK_KHR_ray_tracing_pipeline": ["dEQP-VK.ray_tracing.*"],
    "VK_EXT_mesh_shader": ["dEQP-VK.mesh_shader.*"],
}

DEVICE_EXTENSIONS = [
    "VK_KHR_16bit_storage",
    "VK_KHR_synchronization2",
    "VK_KHR_timeline_semaphore",
    "VK_KHR_buffer_device_address",
    "VK_AMD_shader_trinary_minmax",
    "VK_EXT_memory_budget",
    "VK_KHR_spirv_1_4",
    "VK_KHR_shader_float_controls",
]

# Tests in extension-gated categories (no results generated for these)
EXTENSION_GATED_TESTS = set(ray_tracing_tests() + mesh_shader_tests())

MISSING_TESTS = {
    "dEQP-VK.api.device_init.create_instance_layer_name",
    "dEQP-VK.compute.pipeline.basic.concurrent_compute",
    "dEQP-VK.spirv_assembly.instruction.compute.16bit_storage.uniform.array_stride_16_to_64",
    "dEQP-VK.synchronization.basic.event.multi_secondary_cmd_buf",
    "dEQP-VK.memory.allocation.oom.host_oom",
}

STATUS_MESSAGES = {
    "Pass": "Pass",
    "NotSupported": "Required feature or extension not supported",
    "QualityWarning": "Result within acceptable tolerance but near boundary",
    "CompatibilityWarning": "Implementation-defined behavior detected",
    "Fail": "Comparison failed",
    "InternalError": "Validation layer detected error during execution",
    "Crash": "Test process terminated unexpectedly",
    "ResourceError": "Out of memory during test execution",
}

STATUS_OVERRIDES = {
    # NotSupported (14)
    "dEQP-VK.api.buffer.basic.max_size_sparse": "NotSupported",
    "dEQP-VK.api.buffer.basic.create_sparse_binding": "NotSupported",
    "dEQP-VK.api.buffer.basic.create_sparse_residency": "NotSupported",
    "dEQP-VK.api.buffer.basic.create_sparse_aliased": "NotSupported",
    "dEQP-VK.spirv_assembly.instruction.amd_trinary_minmax.max3.i64.scalar": "NotSupported",
    "dEQP-VK.spirv_assembly.instruction.amd_trinary_minmax.max3.i64.vec2": "NotSupported",
    "dEQP-VK.spirv_assembly.instruction.amd_trinary_minmax.max3.i64.vec3": "NotSupported",
    "dEQP-VK.spirv_assembly.instruction.amd_trinary_minmax.max3.i64.vec4": "NotSupported",
    "dEQP-VK.spirv_assembly.instruction.amd_trinary_minmax.max3.u64.scalar": "NotSupported",
    "dEQP-VK.spirv_assembly.instruction.amd_trinary_minmax.max3.u64.vec2": "NotSupported",
    "dEQP-VK.spirv_assembly.instruction.amd_trinary_minmax.max3.u64.vec3": "NotSupported",
    "dEQP-VK.spirv_assembly.instruction.amd_trinary_minmax.max3.u64.vec4": "NotSupported",
    "dEQP-VK.synchronization.basic.timeline_semaphore.host_signal": "NotSupported",
    "dEQP-VK.memory.requirements.buffer.sparse": "NotSupported",
    # QualityWarning (4 from non-info tests)
    "dEQP-VK.compute.pipeline.basic.empty_shader": "QualityWarning",
    "dEQP-VK.api.device_init.create_instance_null_appinfo": "QualityWarning",
    "dEQP-VK.memory.mapping.basic.remap": "QualityWarning",
    "dEQP-VK.synchronization.basic.fence.empty_submit": "QualityWarning",
    # CompatibilityWarning (1)
    "dEQP-VK.api.device_init.device_features": "CompatibilityWarning",
    # Fail - waived by glob pattern, device 0x7340, waiver NOT expired (4)
    "dEQP-VK.spirv_assembly.instruction.amd_trinary_minmax.max3.f64.scalar": "Fail",
    "dEQP-VK.spirv_assembly.instruction.amd_trinary_minmax.max3.f64.vec2": "Fail",
    "dEQP-VK.spirv_assembly.instruction.amd_trinary_minmax.max3.f64.vec3": "Fail",
    "dEQP-VK.spirv_assembly.instruction.amd_trinary_minmax.max3.f64.vec4": "Fail",
    # Fail - waiver exists for device 0x7340 but EXPIRED (validUntil < CTS version) (1)
    "dEQP-VK.api.device_init.create_device_unsupported_features": "Fail",
    # Fail - waiver for WRONG device 0x9999 so not applicable (1)
    "dEQP-VK.compute.pipeline.basic.copy_ssbo_bounds": "Fail",
    # Fail - no waiver at all (2)
    "dEQP-VK.synchronization.basic.timeline_semaphore.wait_before_signal": "Fail",
    "dEQP-VK.memory.mapping.basic.flush_invalidate": "Fail",
    # InternalError (2)
    "dEQP-VK.compute.pipeline.basic.image_atomic_op_local_size_8": "InternalError",
    "dEQP-VK.memory.allocation.random.mixed_sizes": "InternalError",
    # Crash (1)
    "dEQP-VK.compute.pipeline.basic.copy_image_to_ssbo_large": "Crash",
    # ResourceError (1)
    "dEQP-VK.memory.allocation.oom.device_oom": "ResourceError",
}

# Duplicate: this test appears twice in fraction 2 with different statuses
DUPLICATE_TEST = "dEQP-VK.spirv_assembly.instruction.compute.16bit_storage.uniform.scalar_uint_16_to_32"
DUPLICATE_FIRST_STATUS = "Pass"
DUPLICATE_SECOND_STATUS = "Fail"

FRACTION_MANDATORY = info_tests()

# Cross-fraction status conflict: info.platform gets QualityWarning in fraction 2
# (it gets Pass in fractions 1 and 3). Correct resolution: most-severe wins.
CROSS_FRACTION_OVERRIDES = {
    (2, "dEQP-VK.info.platform"): "QualityWarning",
}

CTS_RELEASE_NAME = "vulkan-cts-1.3.8.0"
CTS_RELEASE_ID = "0x01030800"

# -- QPA generation --

def qpa_entry(test_name, status):
    msg = STATUS_MESSAGES.get(status, status)
    return (
        f"#beginTestCaseResult {test_name}\n"
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<TestCaseResult Version="0.3.4" CasePath="{test_name}" '
        f'CaseType="SelfValidate">\n'
        f'    <Result StatusCode="{status}">{msg}</Result>\n'
        f'</TestCaseResult>\n'
        f"#endTestCaseResult\n\n"
    )

def qpa_header(fraction_idx, total_fractions, build_type="x86_64"):
    return (
        f"#sessionInfo releaseName {CTS_RELEASE_NAME}\n"
        f"#sessionInfo releaseId {CTS_RELEASE_ID}\n"
        f'#sessionInfo targetName "Linux {build_type}"\n'
        f"#sessionInfo fraction {fraction_idx},{total_fractions}\n\n"
    )

# -- File generation --

def generate_mustpass():
    os.makedirs(f"{BASE}/mustpass/vk-default", exist_ok=True)
    index_lines = []
    for cat_name, tests in CATEGORIES.items():
        fname = f"vk-default/{cat_name}.txt"
        index_lines.append(fname)
        fpath = f"{BASE}/mustpass/{fname}"
        with open(fpath, "w") as f:
            f.write("\n".join(tests) + "\n")
    with open(f"{BASE}/mustpass/vk-default.txt", "w") as f:
        f.write("\n".join(index_lines) + "\n")

def generate_qpa_files():
    os.makedirs(f"{BASE}/results", exist_ok=True)

    # Build non-info test list with results (excluding missing and extension-gated)
    non_info_with_results = [t for t in ALL_MUSTPASS
                             if t not in MISSING_TESTS
                             and t not in EXTENSION_GATED_TESTS
                             and not t.startswith("dEQP-VK.info.")]

    # Split into 3 fractions: 55, 58, 53
    fractions = [
        non_info_with_results[0:55],
        non_info_with_results[55:113],
        non_info_with_results[113:],
    ]

    for frac_idx, frac_tests in enumerate(fractions, 1):
        content = qpa_header(frac_idx, 3)
        # Write fraction-mandatory (info) tests with possible cross-fraction overrides
        for t in FRACTION_MANDATORY:
            status = CROSS_FRACTION_OVERRIDES.get((frac_idx, t), "Pass")
            content += qpa_entry(t, status)

        if frac_idx == 2:
            # Insert duplicate early: Pass for DUPLICATE_TEST
            for t in frac_tests[:16]:
                status = STATUS_OVERRIDES.get(t, "Pass")
                content += qpa_entry(t, status)
            content += qpa_entry(DUPLICATE_TEST, DUPLICATE_FIRST_STATUS)
            for t in frac_tests[16:]:
                if t == DUPLICATE_TEST:
                    status = DUPLICATE_SECOND_STATUS
                else:
                    status = STATUS_OVERRIDES.get(t, "Pass")
                content += qpa_entry(t, status)
        else:
            for t in frac_tests:
                status = STATUS_OVERRIDES.get(t, "Pass")
                content += qpa_entry(t, status)

        fname = f"TestResults-x86_64-{frac_idx}-of-3.qpa"

        if frac_idx == 3:
            # Store third fraction inside a tar.gz archive with nested path
            content_bytes = content.encode("utf-8")
            tar_path = f"{BASE}/results/batch-run-fraction-3.tar.gz"
            with tarfile.open(tar_path, "w:gz") as tar:
                info = tarfile.TarInfo(name=f"run-2024-03-15/{fname}")
                info.size = len(content_bytes)
                tar.addfile(info, io.BytesIO(content_bytes))
        else:
            with open(f"{BASE}/results/{fname}", "w") as f:
                f.write(content)

    # Run metadata (not a QPA file — tests must not confuse this with results)
    run_config = {
        "run_id": "conformance-run-2024-03-15",
        "total_fractions": 3,
        "target": "x86_64",
        "deqp_target": "default",
        "start_time": "2024-03-15T08:00:00Z",
        "end_time": "2024-03-15T14:23:17Z",
        "notes": "Fraction 3 archived for storage efficiency"
    }
    with open(f"{BASE}/results/run-config.json", "w") as f:
        json.dump(run_config, f, indent=2)

def generate_waivers():
    os.makedirs(f"{BASE}/waivers", exist_ok=True)
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<waiver_list>
    <waiver vendorName="TestVendor" vendorId="0x1234" url="https://gitlab.khronos.org/Tracker/vk-gl-cts/issues/4201" validUntil="vulkan-cts-1.4.0.0">
        <description>AMD FP64 trinary minmax operations produce incorrect results on this device family due to hardware different rounding mode</description>
        <device_list>
            <d>0x7340</d>
            <d>0x7341</d>
        </device_list>
        <t>dEQP-VK.spirv_assembly.instruction.amd_trinary_minmax.max3.f64.*</t>
    </waiver>
    <waiver vendorName="TestVendor" vendorId="0x1234" url="https://gitlab.khronos.org/Tracker/vk-gl-cts/issues/4315" validUntil="vulkan-cts-1.3.7.0">
        <description>Device feature query returns inconsistent results when querying unsupported features on this specific hardware revision</description>
        <device_list>
            <d>0x7340</d>
        </device_list>
        <t>dEQP-VK.api.device_init.create_device_unsupported_features</t>
    </waiver>
    <waiver vendorName="OtherVendor" vendorId="0x5678" url="https://gitlab.khronos.org/Tracker/vk-gl-cts/issues/4502">
        <description>SSBO bounds checking produces false negatives on different hardware family due to non-standard memory alignment</description>
        <device_list>
            <d>0x9999</d>
            <d>0x9998</d>
        </device_list>
        <t>dEQP-VK.compute.pipeline.basic.copy_ssbo_bounds</t>
    </waiver>
</waiver_list>
'''
    with open(f"{BASE}/waivers/waivers.xml", "w") as f:
        f.write(xml)

    xsd = '''<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="waiver_list">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="waiver" maxOccurs="unbounded">
          <xs:complexType>
            <xs:sequence>
              <xs:element name="description" type="xs:string"/>
              <xs:element name="device_list">
                <xs:complexType>
                  <xs:sequence>
                    <xs:element name="d" type="xs:string" maxOccurs="unbounded"/>
                  </xs:sequence>
                </xs:complexType>
              </xs:element>
              <xs:element name="t" type="xs:string"/>
            </xs:sequence>
            <xs:attribute name="vendorName" type="xs:string" use="required"/>
            <xs:attribute name="vendorId" type="xs:string" use="required"/>
            <xs:attribute name="url" type="xs:string"/>
            <xs:attribute name="validUntil" type="xs:string"/>
          </xs:complexType>
        </xs:element>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
'''
    with open(f"{BASE}/waivers/waivers.xsd", "w") as f:
        f.write(xsd)

def generate_device_info():
    device_info = {
        "vendorName": "TestVendor",
        "vendorId": "0x1234",
        "deviceId": "0x7340",
        "deviceName": "TestGPU RX 7900 XTX",
        "driverVersion": "23.3.1",
        "apiVersion": "1.3.280",
        "spirvVersion": "1.6"
    }
    with open(f"{BASE}/device-info.json", "w") as f:
        json.dump(device_info, f, indent=2)

def generate_device_extensions():
    data = {"supported_extensions": DEVICE_EXTENSIONS}
    with open(f"{BASE}/device-extensions.json", "w") as f:
        json.dump(data, f, indent=2)

def generate_extension_test_map():
    with open(f"{BASE}/extension-test-map.json", "w") as f:
        json.dump(EXTENSION_TEST_MAP, f, indent=2)

def generate_statement():
    os.makedirs(f"{BASE}/submission", exist_ok=True)
    # Intentionally missing OS field
    content = (
        "CONFORM_VERSION:         vulkan-cts-1.3.8.0\n"
        "PRODUCT:                 TestGPU RX 7900 XTX\n"
        "CPU:                     x86_64\n"
    )
    with open(f"{BASE}/submission/STATEMENT-TestVendor", "w") as f:
        f.write(content)

def generate_fraction_mandatory():
    with open(f"{BASE}/fraction-mandatory.txt", "w") as f:
        f.write("\n".join(FRACTION_MANDATORY) + "\n")

def generate_report_schema():
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "VK-GL-CTS Conformance Audit Report",
        "description": "Schema for conformance submission audit reports. All array fields must contain sorted values.",
        "type": "object",
        "required": [
            "raw_mustpass_total", "applicable_mustpass_total",
            "tests_with_results", "tests_missing_count",
            "tests_missing", "raw_status_counts", "waived_tests_count",
            "waived_tests", "expired_waivers_count", "expired_waivers",
            "effective_status_counts",
            "conformance_violations_count", "conformance_violations",
            "duplicate_results_count", "duplicate_results",
            "cross_fraction_conflicts_count", "cross_fraction_conflicts",
            "fraction_count",
            "fraction_mandatory_complete", "statement_valid",
            "statement_errors", "overall_conformant"
        ],
        "properties": {
            "raw_mustpass_total": {
                "type": "integer",
                "description": "Total number of tests across all mustpass category files"
            },
            "applicable_mustpass_total": {
                "type": "integer",
                "description": "Number of mustpass tests after excluding extension-gated groups for extensions the device does not support"
            },
            "tests_with_results": {
                "type": "integer",
                "description": "Number of unique tests with results across all fractions"
            },
            "tests_missing_count": {
                "type": "integer",
                "description": "Number of applicable mustpass tests with no result in any fraction"
            },
            "tests_missing": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Sorted list of applicable mustpass test paths with no result"
            },
            "raw_status_counts": {
                "type": "object",
                "additionalProperties": {"type": "integer"},
                "description": "Count of each status code after all duplicate/conflict resolution but before waiver application"
            },
            "waived_tests_count": {
                "type": "integer",
                "description": "Number of tests whose Fail status was converted to Waiver by a valid non-expired waiver"
            },
            "waived_tests": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Sorted list of test paths that were waived"
            },
            "expired_waivers_count": {
                "type": "integer",
                "description": "Number of device-matching waiver entries that were not applied because their validUntil version predates the submission CTS version"
            },
            "expired_waivers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Sorted list of test patterns from expired waiver entries"
            },
            "effective_status_counts": {
                "type": "object",
                "additionalProperties": {"type": "integer"},
                "description": "Count of each status code after waiver application"
            },
            "conformance_violations_count": {
                "type": "integer",
                "description": "Number of tests with non-allowed effective status"
            },
            "conformance_violations": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Sorted list of test paths with non-allowed effective status"
            },
            "duplicate_results_count": {
                "type": "integer",
                "description": "Number of tests appearing more than once within a single fraction"
            },
            "duplicate_results": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Sorted list of test paths that appear as intra-fraction duplicates"
            },
            "cross_fraction_conflicts_count": {
                "type": "integer",
                "description": "Number of tests with differing statuses across fractions after intra-fraction resolution"
            },
            "cross_fraction_conflicts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Sorted list of test paths with cross-fraction status conflicts"
            },
            "fraction_count": {
                "type": "integer",
                "description": "Total number of result fractions processed"
            },
            "fraction_mandatory_complete": {
                "type": "boolean",
                "description": "Whether all fraction-mandatory tests appear in every fraction"
            },
            "statement_valid": {
                "type": "boolean",
                "description": "Whether the conformance statement contains all required fields"
            },
            "statement_errors": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of validation errors found in the conformance statement"
            },
            "overall_conformant": {
                "type": "boolean",
                "description": "True iff no violations, no missing tests, valid statement, and mandatory complete"
            }
        }
    }
    with open(f"{BASE}/report-schema.json", "w") as f:
        json.dump(schema, f, indent=2)

def generate_conformance_doc():
    os.makedirs(f"{BASE}/docs", exist_ok=True)
    doc = r'''# VK-GL-CTS Conformance Submission Requirements

## 1. Scope

This document defines the evaluation criteria for Vulkan Conformance Test Suite
(VK-GL-CTS) submissions under the Khronos Adopters Program. An audit report
must assess every dimension described below.

## 2. Test Result Format

Results are stored in Quality Program Archive (`.qpa`) files. The format mixes
plain-text directives with embedded XML. Session metadata appears as
`#sessionInfo key value` lines at the top of each file. The `releaseName`
session key contains the CTS release version used for the run (e.g.,
`vulkan-cts-1.3.8.0`). Individual test results are delimited by marker lines:

    #beginTestCaseResult <test_case_path>
    ... XML content with <Result StatusCode="..."> ...
    #endTestCaseResult

Result files may be stored as plain `.qpa`, gzip-compressed (`.qpa.gz`), or
within tar archives (`.tar.gz`) with arbitrary internal directory structures.
All formats must be discovered and processed.

## 3. Status Code Taxonomy

### 3.1 Allowed (non-blocking) statuses

| Code                  | Meaning                                          |
|-----------------------|--------------------------------------------------|
| `Pass`                | Test completed successfully                      |
| `NotSupported`        | Tested feature/extension not available on device  |
| `QualityWarning`      | Result within tolerance but near boundary         |
| `CompatibilityWarning`| Implementation-defined behavior detected          |
| `Waiver`              | Failure reclassified via an approved waiver        |

### 3.2 Non-conformant (blocking) statuses

| Code             | Meaning                                         |
|------------------|--------------------------------------------------|
| `Fail`           | Test produced incorrect results                  |
| `InternalError`  | Validation layer or driver internal error         |
| `Crash`          | Test process terminated unexpectedly             |
| `ResourceError`  | Resource exhaustion prevented test completion     |

### 3.3 Severity ordering

Status codes are ordered by severity from least to most severe:

    Pass < NotSupported < QualityWarning < CompatibilityWarning
         < Fail < InternalError < Crash < ResourceError

This ordering is used for cross-fraction conflict resolution (Section 5.2).

## 4. Mustpass Coverage

### 4.1 Structure

The file `vk-default.txt` is an index referencing per-category test list files
(one test path per line). The complete mustpass set is the union of all tests
across all referenced category files.

### 4.2 Extension-gated test groups

The mustpass includes test groups for optional Vulkan extensions. Tests for
extensions not declared in the device's supported extension list are excluded
from mandatory coverage calculations. The mapping from extension names to test
path glob patterns is defined in `extension-test-map.json`. For each entry in
the map, if the corresponding extension is absent from the device's supported
extension list (`device-extensions.json`), all mustpass tests matching the
associated patterns are excluded from the applicable mustpass set.

The **raw mustpass total** is the count of all tests in the category files.
The **applicable mustpass total** excludes extension-gated tests for
unsupported extensions. Missing-test analysis uses the applicable set.

## 5. Fractioned Execution

### 5.1 Intra-fraction duplicates

If a test appears multiple times within a single fraction, the final recorded
result supersedes all earlier occurrences. These must be reported.

### 5.2 Cross-fraction conflicts

The same test may appear in multiple fractions. When statuses agree, this is
normal cross-fraction overlap. When statuses differ after intra-fraction
resolution, the result with the highest severity (per Section 3.3) is used as
the authoritative status. Such conflicts must be reported.

### 5.3 Fraction-mandatory tests

Certain tests are designated as fraction-mandatory and must appear in the
result set of every fraction for the submission to be complete.

## 6. Waivers

### 6.1 Format

Waiver definitions are in an XML file whose structure conforms to the provided
XSD schema. Each `<waiver>` element contains a `<device_list>` of device IDs
and a `<t>` element with a test path pattern supporting glob-style wildcards
(`*` matches any sequence of characters).

### 6.2 Device scoping

A waiver applies only if the submission's device ID (from `device-info.json`)
appears in the waiver's `<device_list>`. Waivers targeting other devices must
be excluded regardless of test pattern match.

### 6.3 Version validity

Waivers may carry a `validUntil` attribute specifying the last CTS release
version for which the waiver is approved. Compare using dotted-integer version
semantics (e.g., `1.3.7.0 < 1.3.8.0`). If a waiver's `validUntil` version is
strictly less than the submission's CTS release version (from `releaseName`
session info), the waiver has expired and must not be applied. Expired
device-matching waivers must be reported separately.

### 6.4 Application

Only tests with `Fail` status whose path matches a valid (non-expired,
device-matching) waiver pattern have their effective status changed to `Waiver`.

## 7. Conformance Statement

Each submission includes a `STATEMENT-<Adopter>` file under the submission
directory. The following fields are mandatory:

- `CONFORM_VERSION`
- `PRODUCT`
- `CPU`
- `OS`

All four fields must be present for the statement to be valid. Fields appear as
`KEY: value` lines.

## 8. Conformance Determination

A submission achieves conformance if and only if:

1. Every test in the applicable mustpass set has a result in at least one fraction
2. No test has a non-allowed effective status (zero conformance violations)
3. All fraction-mandatory tests appear in every fraction's result set
4. The conformance statement is valid
'''
    with open(f"{BASE}/docs/conformance-requirements.md", "w") as f:
        f.write(doc)

# -- Main --

if __name__ == "__main__":
    os.makedirs(BASE, exist_ok=True)
    generate_mustpass()
    generate_qpa_files()
    generate_waivers()
    generate_device_info()
    generate_device_extensions()
    generate_extension_test_map()
    generate_statement()
    generate_fraction_mandatory()
    generate_report_schema()
    generate_conformance_doc()
    print(f"Generated {len(ALL_MUSTPASS)} total mustpass tests")
    print(f"Extension-gated tests: {len(EXTENSION_GATED_TESTS)}")
    print(f"Missing tests: {len(MISSING_TESTS)}")
    print(f"Tests with results: {len(ALL_MUSTPASS) - len(MISSING_TESTS) - len(EXTENSION_GATED_TESTS)}")
    print("Data generation complete.")
    # Verify critical files
    for needed in ["device-extensions.json", "device-info.json",
                    "extension-test-map.json", "fraction-mandatory.txt",
                    "report-schema.json"]:
        path = os.path.join(BASE, needed)
        assert os.path.isfile(path), f"MISSING: {path}"
    print("All critical files verified.")
