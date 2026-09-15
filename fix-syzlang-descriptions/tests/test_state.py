
"""
Tests verifying that both the syzlang description file and the validation
tool have been correctly fixed for the vdma driver.
"""

import os
import re
import subprocess
import tempfile

import pytest

SYZLANG_FILE = "/app/sys/vdma.txt"
HEADER_FILE = "/app/include/vdma.h"
LINTER = "/app/tools/syzlang_lint.py"


def read_syzlang():
    with open(SYZLANG_FILE, "r") as f:
        return f.read()


def extract_struct_body(content, struct_name):
    """Extract the body of a struct definition (between { and })."""
    pattern = rf"(?:^|\n){struct_name}\s*\{{(.*?)\}}"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        return match.group(1)
    return ""


def get_struct_field_names(content, struct_name):
    """Get ordered list of field names from a syzlang struct."""
    body = extract_struct_body(content, struct_name)
    if not body:
        return []
    fields = []
    for line in body.strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            parts = line.split()
            if parts:
                fields.append(parts[0])
    return fields


# =============================================================
# Section 1: Syzlang description correctness
# =============================================================


class TestInclude:
    def test_includes_vdma_header(self):
        """Must include the vdma UAPI header, not a generic header."""
        content = read_syzlang()
        assert re.search(
            r"^include\s+<.*vdma\.h\s*>", content, re.MULTILINE
        ), "Must include the vdma.h UAPI header (e.g. include <uapi/linux/vdma.h>)"

    def test_does_not_include_generic_types(self):
        """Should not include generic linux/types.h as the primary include."""
        content = read_syzlang()
        # It's ok if types.h is also included, but vdma.h must be present
        has_vdma = re.search(r"^include\s+<.*vdma\.h", content, re.MULTILINE)
        assert has_vdma, "Must include vdma.h, not just linux/types.h"


class TestResources:
    def test_vdma_cookie_is_int64(self):
        """vdma_cookie_t is __u64, so resource must use int64."""
        content = read_syzlang()
        assert re.search(
            r"resource\s+vdma_cookie\s*\[\s*int64\s*\]", content
        ), "vdma_cookie resource must have int64 base type (__u64)"

    def test_vdma_channel_is_int32(self):
        """vdma_channel_t is __u32, so resource must use int32."""
        content = read_syzlang()
        assert re.search(
            r"resource\s+vdma_channel\s*\[\s*int32\s*\]", content
        ), "vdma_channel resource must have int32 base type (__u32)"

    def test_vdma_fence_is_int32(self):
        """vdma_fence_t is __u32, so resource must use int32."""
        content = read_syzlang()
        assert re.search(
            r"resource\s+vdma_fence\s*\[\s*int32\s*\]", content
        ), "vdma_fence resource must have int32 base type (__u32)"


class TestSyscalls:
    def test_openat_returns_fd_vdma(self):
        """openat$vdma must return fd_vdma, not generic fd."""
        content = read_syzlang()
        assert re.search(
            r"openat\$vdma\s*\([^)]*\)\s+fd_vdma\b", content
        ), "openat$vdma must return fd_vdma (not fd)"

    def test_alloc_uses_inout(self):
        """ALLOC is _IOWR with output channel field, must use ptr[inout]."""
        content = read_syzlang()
        assert re.search(
            r"ioctl\$VDMA_IOC_ALLOC\s*\([^)]*ptr\s*\[\s*inout", content
        ), "VDMA_IOC_ALLOC must use ptr[inout, ...] (channel is output)"

    def test_free_consumes_channel(self):
        """FREE ioctl must consume vdma_channel resource, not plain int32."""
        content = read_syzlang()
        assert re.search(
            r"ioctl\$VDMA_IOC_FREE\s*\([^)]*ptr\s*\[\s*in\s*,\s*vdma_channel\s*\]",
            content,
        ), "VDMA_IOC_FREE must use ptr[in, vdma_channel] (not int32)"

    def test_submit_uses_inout(self):
        """SUBMIT is _IOWR with output cookie, must use ptr[inout]."""
        content = read_syzlang()
        assert re.search(
            r"ioctl\$VDMA_IOC_SUBMIT\s*\([^)]*ptr\s*\[\s*inout", content
        ), "VDMA_IOC_SUBMIT must use ptr[inout, ...] (cookie is output)"

    def test_abort_consumes_channel(self):
        """ABORT ioctl must consume vdma_channel resource."""
        content = read_syzlang()
        assert re.search(
            r"ioctl\$VDMA_IOC_ABORT\s*\([^)]*ptr\s*\[\s*in\s*,\s*vdma_channel\s*\]",
            content,
        ), "VDMA_IOC_ABORT must use ptr[in, vdma_channel]"


class TestStructFields:
    def test_sg_entry_field_order(self):
        """vdma_sg_entry field order must match header: addr, len, stride."""
        content = read_syzlang()
        fields = get_struct_field_names(content, "vdma_sg_entry")
        assert len(fields) >= 3, f"Expected >=3 fields, got {fields}"
        assert fields.index("addr") < fields.index("len"), \
            "addr must come before len in vdma_sg_entry"
        assert fields.index("len") < fields.index("stride"), \
            "len must come before stride in vdma_sg_entry"

    def test_alloc_req_channel_is_resource_output(self):
        """channel in vdma_alloc_req must be vdma_channel with (out)."""
        content = read_syzlang()
        body = extract_struct_body(content, "vdma_alloc_req")
        assert body, "vdma_alloc_req struct not found"
        assert re.search(
            r"channel\s+vdma_channel\b.*\(out\)", body
        ), "channel must be 'vdma_channel (out)' in vdma_alloc_req"

    def test_alloc_req_padding_const_zero(self):
        """padding in vdma_alloc_req must be const[0, int32]."""
        content = read_syzlang()
        body = extract_struct_body(content, "vdma_alloc_req")
        assert body, "vdma_alloc_req struct not found"
        assert re.search(
            r"padding\s+const\s*\[\s*0\s*,\s*int32\s*\]", body
        ), "padding must be const[0, int32] in vdma_alloc_req"

    def test_xfer_desc_flags_use_xfer_flags(self):
        """xfer_desc flags must reference vdma_xfer_flags, not vdma_cap_flags."""
        content = read_syzlang()
        body = extract_struct_body(content, "vdma_xfer_desc")
        assert body, "vdma_xfer_desc struct not found"
        flags_line = [
            l for l in body.split("\n")
            if l.strip().startswith("flags") and "flags[" in l
        ]
        assert flags_line, "flags field not found in vdma_xfer_desc"
        line = flags_line[0]
        assert "vdma_xfer_flags" in line, \
            "flags must use vdma_xfer_flags (not vdma_cap_flags)"
        assert "vdma_cap_flags" not in line, \
            "flags must NOT use vdma_cap_flags"

    def test_xfer_desc_sg_count_is_len(self):
        """sg_count in vdma_xfer_desc must use len[sg_list, int32]."""
        content = read_syzlang()
        body = extract_struct_body(content, "vdma_xfer_desc")
        assert body, "vdma_xfer_desc struct not found"
        assert re.search(
            r"sg_count\s+len\s*\[\s*sg_list\s*,\s*int32\s*\]", body
        ), "sg_count must be len[sg_list, int32]"

    def test_xfer_desc_cookie_is_resource_output(self):
        """cookie in vdma_xfer_desc must be vdma_cookie with (out)."""
        content = read_syzlang()
        body = extract_struct_body(content, "vdma_xfer_desc")
        assert body, "vdma_xfer_desc struct not found"
        assert re.search(
            r"cookie\s+vdma_cookie\b.*\(out\)", body
        ), "cookie must be 'vdma_cookie (out)' in vdma_xfer_desc"

    def test_xfer_desc_is_packed(self):
        """vdma_xfer_desc has __attribute__((packed)), needs [packed]."""
        content = read_syzlang()
        full = re.search(
            r"(vdma_xfer_desc\s*\{.*?\})(\s*\[.*?\])?",
            content, re.DOTALL
        )
        assert full, "vdma_xfer_desc not found"
        attrs = full.group(2) or ""
        assert "packed" in attrs, "vdma_xfer_desc must have [packed]"

    def test_chan_config_padding_const_zero(self):
        """padding in vdma_chan_config must be const[0, int32]."""
        content = read_syzlang()
        body = extract_struct_body(content, "vdma_chan_config")
        assert body, "vdma_chan_config struct not found"
        assert re.search(
            r"padding\s+const\s*\[\s*0\s*,\s*int32\s*\]", body
        ), "padding must be const[0, int32] in vdma_chan_config"

    def test_fence_req_field_order(self):
        """vdma_fence_req fields must match header: channel, fence_val, timeout_ms, status."""
        content = read_syzlang()
        fields = get_struct_field_names(content, "vdma_fence_req")
        assert len(fields) >= 4, f"Expected >=4 fields, got {fields}"
        assert "fence_val" in fields, "fence_val field missing"
        assert "timeout_ms" in fields, "timeout_ms field missing"
        fence_idx = fields.index("fence_val")
        timeout_idx = fields.index("timeout_ms")
        assert fence_idx < timeout_idx, \
            "fence_val must come before timeout_ms (matching C header order)"

    def test_batch_submit_cookies_type(self):
        """cookies in vdma_batch_submit must be array[vdma_cookie]."""
        content = read_syzlang()
        body = extract_struct_body(content, "vdma_batch_submit")
        assert body, "vdma_batch_submit struct not found"
        assert re.search(
            r"cookies\s+array\s*\[\s*vdma_cookie\s*\]", body
        ), "cookies must be array[vdma_cookie] in vdma_batch_submit"

    def test_batch_submit_is_packed(self):
        """vdma_batch_submit has __attribute__((packed)), needs [packed]."""
        content = read_syzlang()
        full = re.search(
            r"(vdma_batch_submit\s*\{.*?\})(\s*\[.*?\])?",
            content, re.DOTALL
        )
        assert full, "vdma_batch_submit not found"
        attrs = full.group(2) or ""
        assert "packed" in attrs, "vdma_batch_submit must have [packed]"


class TestEventModeling:
    def test_event_is_packed(self):
        """vdma_event has __attribute__((packed)), needs [packed]."""
        content = read_syzlang()
        full = re.search(
            r"(vdma_event\s*\{.*?\})(\s*\[.*?\])?",
            content, re.DOTALL
        )
        assert full, "vdma_event struct not found"
        attrs = full.group(2) or ""
        assert "packed" in attrs, "vdma_event must have [packed]"

    def test_event_sub_structs_exist(self):
        """Event sub-type structs must be defined for proper union modeling."""
        content = read_syzlang()
        assert re.search(
            r"^vdma_event_xfer_done\s*\{", content, re.MULTILINE
        ), "vdma_event_xfer_done struct not found"
        assert re.search(
            r"^vdma_event_error\s*\{", content, re.MULTILINE
        ), "vdma_event_error struct not found"
        assert re.search(
            r"^vdma_event_threshold\s*\{", content, re.MULTILINE
        ), "vdma_event_threshold struct not found"

    def test_event_models_union(self):
        """vdma_event must model the anonymous union, not use a bare field."""
        content = read_syzlang()
        body = extract_struct_body(content, "vdma_event")
        assert body, "vdma_event struct not found"
        lines = [
            l.strip() for l in body.strip().split("\n")
            if l.strip() and not l.strip().startswith("#")
        ]
        field_names = [l.split()[0] for l in lines if l.split()]
        # The event struct should NOT just have a bare 'cookie int64'
        # as a catch-all for the union — it should reference a union type
        # Check that the struct references some payload/union type
        field_types = [
            l.split()[1] if len(l.split()) > 1 else ""
            for l in lines if l.split()
        ]
        has_union_ref = any(
            "event" in t and ("payload" in t or "union" in t or "done" in t)
            for t in field_types
        )
        # Also accept if a syzlang union [...] referencing event types exists
        has_syzlang_union = bool(re.search(
            r"\w+\s*\[\s*\n(?:.*\n)*?\s*\]",
            content
        ))
        assert has_union_ref or has_syzlang_union, \
            "vdma_event must model the union (define event sub-structs and a union type)"


# =============================================================
# Section 2: Linter correctness
# =============================================================


class TestLinter:
    def test_linter_passes_on_correct_descriptions(self):
        """Fixed linter must report 0 errors on the fixed descriptions."""
        result = subprocess.run(
            ["python3", LINTER, HEADER_FILE, SYZLANG_FILE],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, \
            f"Linter reported errors:\n{result.stdout}\n{result.stderr}"
        assert "0 errors" in result.stdout.lower() or "passed" in result.stdout.lower(), \
            f"Unexpected linter output:\n{result.stdout}"

    def test_linter_catches_wrong_resource_type(self):
        """Linter must still detect real bugs (wrong resource base type)."""
        bad_syzlang = (
            "include <uapi/linux/vdma.h>\n"
            "resource fd_vdma[fd]\n"
            "resource vdma_cookie[int32]: 0xffffffff\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write(bad_syzlang)
            tmp = f.name
        try:
            result = subprocess.run(
                ["python3", LINTER, HEADER_FILE, tmp],
                capture_output=True, text=True,
            )
            assert result.returncode != 0, \
                "Linter should catch wrong resource base type"
            assert "vdma_cookie" in result.stdout, \
                "Error should mention vdma_cookie"
        finally:
            os.unlink(tmp)

    def test_linter_handles_shift_constants(self):
        """Linter must correctly extract constants using (1 << N) syntax."""
        test_syzlang = (
            "include <uapi/linux/vdma.h>\n"
            "resource fd_vdma[fd]\n"
            "vdma_cap_flags = VDMA_CAP_SG, VDMA_CAP_CYCLIC\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write(test_syzlang)
            tmp = f.name
        try:
            result = subprocess.run(
                ["python3", LINTER, HEADER_FILE, tmp],
                capture_output=True, text=True,
            )
            # Must NOT report VDMA_CAP_SG or VDMA_CAP_CYCLIC as unknown
            assert "unknown constant 'VDMA_CAP_SG'" not in result.stdout, \
                "Linter must handle (1 << N) constants"
            assert "unknown constant 'VDMA_CAP_CYCLIC'" not in result.stdout, \
                "Linter must handle (1 << N) constants"
        finally:
            os.unlink(tmp)

    def test_linter_correct_iowr_classification(self):
        """Linter must not confuse _IOWR with _IOW."""
        test_syzlang = (
            "include <uapi/linux/vdma.h>\n"
            "resource fd_vdma[fd]\n"
            "resource vdma_channel[int32]: 0xffffffff\n"
            "vdma_alloc_req {\n"
            "\tcaps\tint32\n"
            "\tpriority\tint32\n"
            "\tchannel\tint32\n"
            "\tpadding\tint32\n"
            "}\n"
            "ioctl$VDMA_IOC_ALLOC(fd fd_vdma, cmd const[VDMA_IOC_ALLOC], "
            "arg ptr[inout, vdma_alloc_req])\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write(test_syzlang)
            tmp = f.name
        try:
            result = subprocess.run(
                ["python3", LINTER, HEADER_FILE, tmp],
                capture_output=True, text=True,
            )
            # ALLOC is _IOWR, so ptr[inout] is correct — no direction error
            direction_err = [
                l for l in result.stdout.split("\n")
                if "VDMA_IOC_ALLOC" in l and "ptr[in]" in l
            ]
            assert not direction_err, \
                "Linter should not flag ptr[inout] for _IOWR ioctl ALLOC"
        finally:
            os.unlink(tmp)
