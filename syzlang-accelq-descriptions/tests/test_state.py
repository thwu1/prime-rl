"""
Validate evaluation.json correctness and semantic correctness of unified
syzlang descriptions for /dev/accelq.

Checks the comparative evaluation of two candidate description files,
then validates resource declarations, ioctl modeling, struct layout,
pointer modeling, length annotations, flag references, resource
production chains, and include directives in the final output.

"""

import json
import os
import re
import pytest

SYZLANG_PATH = "/app/accelq.txt"
EVAL_PATH = "/app/evaluation.json"

# Ground truth: which candidate is correct for each aspect
EVAL_GROUND_TRUTH = [
    ("include_path", "A"),
    ("buf_handle_base_type", "B"),
    ("create_ctx_ptr_direction", "A"),
    ("ctx_id_resource_production", "A"),
    ("queue_id_resource_production", "B"),
    ("submit_args_field_order", "B"),
    ("descs_ptr_type_modeling", "A"),
    ("nr_descs_length_annotation", "A"),
    ("descriptor_op_flag_reference", "B"),
    ("descriptor_handle_resource_types", "A"),
]


@pytest.fixture
def syzlang():
    """Load and strip comments from the syzlang file."""
    assert os.path.exists(SYZLANG_PATH), f"Output file {SYZLANG_PATH} not found"
    with open(SYZLANG_PATH) as f:
        content = f.read()
    lines = []
    for line in content.split("\n"):
        stripped = line
        in_quote = False
        for i, ch in enumerate(line):
            if ch == '"':
                in_quote = not in_quote
            elif ch == "#" and not in_quote:
                stripped = line[:i]
                break
        lines.append(stripped)
    return "\n".join(lines)


@pytest.fixture
def evaluation():
    """Load and parse the evaluation JSON file."""
    assert os.path.exists(EVAL_PATH), f"Evaluation file {EVAL_PATH} not found"
    with open(EVAL_PATH) as f:
        return json.load(f)


# ===== Evaluation correctness =====

class TestEvaluation:
    def test_evaluation_is_dict(self, evaluation):
        """evaluation.json must be a JSON object."""
        assert isinstance(evaluation, dict)

    @pytest.mark.parametrize("aspect,expected", EVAL_GROUND_TRUTH)
    def test_aspect_present(self, evaluation, aspect, expected):
        """Each required evaluation aspect must be present."""
        assert aspect in evaluation, f"Missing evaluation key: {aspect}"

    @pytest.mark.parametrize("aspect,expected", EVAL_GROUND_TRUTH)
    def test_correct_candidate(self, evaluation, aspect, expected):
        """Each aspect must identify the correct candidate."""
        assert aspect in evaluation, f"Missing evaluation key: {aspect}"
        actual = evaluation[aspect].get("correct", "").strip().upper()
        assert actual == expected, \
            f"Aspect {aspect}: expected candidate {expected}, got {actual}"

    @pytest.mark.parametrize("aspect,expected", EVAL_GROUND_TRUTH)
    def test_has_explanation(self, evaluation, aspect, expected):
        """Each aspect must include a non-trivial explanation."""
        assert aspect in evaluation, f"Missing evaluation key: {aspect}"
        expl = evaluation[aspect].get("explanation", "")
        assert isinstance(expl, str) and len(expl) > 10, \
            f"Aspect {aspect} needs a substantive explanation"


# ===== Resource declarations =====

class TestResources:
    def test_fd_accelq(self, syzlang):
        """fd_accelq must be a subtype of fd."""
        assert re.search(r"resource\s+fd_accelq\s*\[\s*fd\s*\]", syzlang)

    def test_accelq_ctx(self, syzlang):
        """accelq_ctx must have int32 base type."""
        assert re.search(r"resource\s+accelq_ctx\s*\[\s*int32\s*\]", syzlang)

    def test_accelq_queue(self, syzlang):
        """accelq_queue must have int32 base type."""
        assert re.search(r"resource\s+accelq_queue\s*\[\s*int32\s*\]", syzlang)

    def test_accelq_job(self, syzlang):
        """accelq_job must have int32 base type."""
        assert re.search(r"resource\s+accelq_job\s*\[\s*int32\s*\]", syzlang)

    def test_buf_handle_base_type(self, syzlang):
        """Buffer handle resource base type must match __u64 width from header."""
        assert re.search(
            r"resource\s+accelq_\w*(?:buf|buffer|handle)\w*\s*\[\s*int64\s*\]",
            syzlang,
        ), "Buffer handle resource must have int64 base type (handle is __u64)"


# ===== ioctl declarations =====

IOCTL_CMDS = [
    "ACCELQ_CREATE_CTX",
    "ACCELQ_DESTROY_CTX",
    "ACCELQ_CREATE_QUEUE",
    "ACCELQ_DESTROY_QUEUE",
    "ACCELQ_SUBMIT",
    "ACCELQ_WAIT",
    "ACCELQ_GET_STATS",
    "ACCELQ_SET_PRIORITY",
    "ACCELQ_MAP_BUFFER",
    "ACCELQ_UNMAP_BUFFER",
]


class TestIoctlDeclarations:
    @pytest.mark.parametrize("cmd", IOCTL_CMDS)
    def test_ioctl_exists(self, syzlang, cmd):
        """Each ioctl command must be declared."""
        pattern = rf"ioctl\$\s*{re.escape(cmd)}\s*\("
        assert re.search(pattern, syzlang), f"ioctl${cmd} not declared"

    @pytest.mark.parametrize("cmd", IOCTL_CMDS)
    def test_ioctl_uses_fd_accelq(self, syzlang, cmd):
        """Each ioctl must use fd_accelq as the fd parameter."""
        pattern = rf"ioctl\$\s*{re.escape(cmd)}\s*\(\s*\w+\s+fd_accelq\b"
        assert re.search(pattern, syzlang), f"ioctl${cmd} doesn't use fd_accelq"


# ===== ioctl pointer directions must match _IOW/_IOWR macros =====

class TestIoctlPointerDirections:
    @pytest.mark.parametrize("cmd", [
        "ACCELQ_CREATE_CTX",
        "ACCELQ_CREATE_QUEUE",
        "ACCELQ_SUBMIT",
        "ACCELQ_WAIT",
        "ACCELQ_GET_STATS",
        "ACCELQ_MAP_BUFFER",
    ])
    def test_iowr_uses_inout(self, syzlang, cmd):
        """_IOWR ioctls must use ptr[inout, ...] to allow bidirectional data flow."""
        m = re.search(rf"ioctl\$\s*{re.escape(cmd)}\s*\([^)]+\)", syzlang)
        assert m, f"ioctl${cmd} not found"
        line = m.group(0)
        assert re.search(r"ptr\s*\[\s*inout\s*,", line), \
            f"ioctl${cmd} is _IOWR — must use ptr[inout, ...] for kernel to write back output fields"

    @pytest.mark.parametrize("cmd", [
        "ACCELQ_DESTROY_CTX",
        "ACCELQ_DESTROY_QUEUE",
        "ACCELQ_SET_PRIORITY",
        "ACCELQ_UNMAP_BUFFER",
    ])
    def test_iow_uses_in(self, syzlang, cmd):
        """_IOW ioctls must use ptr[in, ...]."""
        m = re.search(rf"ioctl\$\s*{re.escape(cmd)}\s*\([^)]+\)", syzlang)
        assert m, f"ioctl${cmd} not found"
        line = m.group(0)
        assert re.search(r"ptr\s*\[\s*in\s*,", line), \
            f"ioctl${cmd} is _IOW — must use ptr[in, ...]"


# ===== Device open =====

class TestDeviceOpen:
    def test_produces_fd_accelq(self, syzlang):
        """Some syscall must produce (return) fd_accelq."""
        assert re.search(r"\)\s+fd_accelq\b", syzlang), \
            "No syscall produces fd_accelq"


# ===== Flag sets =====

class TestFlags:
    def test_ctx_flags(self, syzlang):
        for f in ["ACCELQ_CTX_SHARED", "ACCELQ_CTX_EXCLUSIVE", "ACCELQ_CTX_LOW_LATENCY"]:
            assert f in syzlang, f"Missing flag: {f}"

    def test_queue_flags(self, syzlang):
        for f in ["ACCELQ_QUEUE_ORDERED", "ACCELQ_QUEUE_PREEMPT"]:
            assert f in syzlang, f"Missing flag: {f}"

    def test_submit_flags(self, syzlang):
        for f in ["ACCELQ_SUBMIT_FENCE", "ACCELQ_SUBMIT_SIGNAL", "ACCELQ_SUBMIT_NO_WAIT"]:
            assert f in syzlang, f"Missing flag: {f}"

    def test_wait_flags(self, syzlang):
        for f in ["ACCELQ_WAIT_TIMEOUT", "ACCELQ_WAIT_ANY"]:
            assert f in syzlang, f"Missing flag: {f}"

    def test_buf_flags(self, syzlang):
        for f in ["ACCELQ_BUF_READ", "ACCELQ_BUF_WRITE", "ACCELQ_BUF_COHERENT"]:
            assert f in syzlang, f"Missing flag: {f}"

    def test_op_types(self, syzlang):
        for f in ["ACCELQ_OP_COPY", "ACCELQ_OP_TRANSFORM", "ACCELQ_OP_REDUCE", "ACCELQ_OP_CUSTOM"]:
            assert f in syzlang, f"Missing op type: {f}"

    def test_prio_values(self, syzlang):
        for f in ["ACCELQ_PRIO_LOW", "ACCELQ_PRIO_NORMAL", "ACCELQ_PRIO_HIGH", "ACCELQ_PRIO_REALTIME"]:
            assert f in syzlang, f"Missing priority: {f}"


# ===== Resource producer/consumer chains =====

class TestResourceProduction:
    def test_ctx_produced_in_create(self, syzlang):
        """accelq_ctx must be produced (out) in the CREATE_CTX struct."""
        m_ioctl = re.search(
            r"ioctl\$\s*ACCELQ_CREATE_CTX\s*\([^,]+,[^,]+,\s*\w+\s+ptr\s*\[\s*\w+\s*,\s*(\w+)\s*\]",
            syzlang,
        )
        assert m_ioctl, "ACCELQ_CREATE_CTX ioctl not found"
        struct_name = m_ioctl.group(1)
        m_struct = re.search(
            rf"{re.escape(struct_name)}\s*\{{(.*?)\}}", syzlang, re.DOTALL
        )
        assert m_struct, f"Struct {struct_name} not found"
        body = m_struct.group(1)
        assert re.search(r"ctx_id\s+accelq_ctx\s+\(\s*out\s*\)", body), \
            "ctx_id must have (out) annotation in CREATE_CTX struct for resource production"

    def test_queue_produced(self, syzlang):
        """accelq_queue must appear with (out) annotation."""
        assert re.search(r"queue_id\s+accelq_queue\s+\(\s*out\s*\)", syzlang), \
            "accelq_queue never produced"

    def test_job_produced(self, syzlang):
        """accelq_job must appear with (out) annotation."""
        assert re.search(r"job_id\s+accelq_job\s+\(\s*out\s*\)", syzlang), \
            "accelq_job never produced"

    def test_buf_handle_produced(self, syzlang):
        """Buffer handle resource must appear with (out) annotation."""
        assert re.search(
            r"handle\s+accelq_\w*(?:buf|buffer|handle)\w*\s+\(\s*out\s*\)", syzlang
        ), "Buffer handle resource never produced"


# ===== Struct field ordering must match C layout =====

class TestStructLayout:
    def test_submit_args_field_order(self, syzlang):
        """accelq_submit_args fields must match C struct member order."""
        m = re.search(r"accelq_submit_args\s*\{(.*?)\}", syzlang, re.DOTALL)
        assert m, "accelq_submit_args struct not found"
        body = m.group(1)
        fields = re.findall(r"^\s*(\w+)\s", body, re.MULTILINE)
        # C header order: ctx_id, queue_id, nr_descs, flags, descs_ptr, job_id, reserved
        expected_order = ["ctx_id", "queue_id", "nr_descs", "flags", "descs_ptr", "job_id", "reserved"]
        for i in range(len(expected_order) - 1):
            f1, f2 = expected_order[i], expected_order[i + 1]
            if f1 in fields and f2 in fields:
                assert fields.index(f1) < fields.index(f2), \
                    f"Field {f1} must come before {f2} (matching C struct layout)"


# ===== Descriptor / submit pointer modeling =====

class TestPointerModeling:
    def test_descs_ptr_is_pointer(self, syzlang):
        """descs_ptr must use ptr or ptr64 (not raw int64)."""
        assert re.search(r"descs_ptr\s+ptr(?:64)?\s*\[", syzlang), \
            "descs_ptr should be modeled as ptr/ptr64, not int64"

    def test_nr_descs_is_len(self, syzlang):
        """nr_descs must be len[descs_ptr, ...]."""
        assert re.search(r"nr_descs\s+len\s*\[\s*descs_ptr", syzlang), \
            "nr_descs should be len[descs_ptr, ...]"


# ===== Descriptor struct semantics =====

class TestDescriptorStruct:
    def test_descriptor_struct_exists(self, syzlang):
        """accelq_descriptor struct must exist."""
        assert re.search(r"accelq_descriptor\s*\{", syzlang), \
            "accelq_descriptor struct not found"

    def test_descriptor_op_uses_correct_flags(self, syzlang):
        """Descriptor op field must reference operation type constants, not submit flags."""
        m = re.search(r"accelq_descriptor\s*\{(.*?)\}", syzlang, re.DOTALL)
        assert m, "accelq_descriptor struct not found"
        body = m.group(1)
        op_lines = [l for l in body.split("\n") if re.match(r"\s*op\s", l)]
        assert op_lines, "No 'op' field found in accelq_descriptor"
        op_line = op_lines[0]
        assert "accelq_op_types" in op_line, \
            "Descriptor op field must use accelq_op_types flag set"
        assert "accelq_submit_flags" not in op_line, \
            "Descriptor op field must NOT use accelq_submit_flags"

    def test_descriptor_handle_fields_use_resource(self, syzlang):
        """src_handle and dst_handle must use a resource type (not raw int64)."""
        m = re.search(r"accelq_descriptor\s*\{(.*?)\}", syzlang, re.DOTALL)
        assert m, "accelq_descriptor struct not found"
        body = m.group(1)
        assert re.search(r"src_handle\s+accelq_\w+", body), \
            "src_handle in descriptor should use a buffer handle resource type"
        assert re.search(r"dst_handle\s+accelq_\w+", body), \
            "dst_handle in descriptor should use a buffer handle resource type"

    def test_descriptor_params_array(self, syzlang):
        """Descriptor params must be array[int8, 32]."""
        assert re.search(r"params\s+array\s*\[\s*int8\s*,\s*32\s*\]", syzlang), \
            "params should be array[int8, 32]"


# ===== Reserved fields =====

class TestReservedFields:
    def test_reserved_is_const_zero(self, syzlang):
        """At least one reserved field must be const[0, ...]."""
        assert re.search(r"reserved\s+const\s*\[\s*0", syzlang), \
            "Reserved fields should be const[0, ...]"


# ===== Include directives =====

class TestIncludes:
    def test_includes_accelq_header(self, syzlang):
        """Must include the accelq header at the correct path."""
        assert re.search(r"include\s*<accelq\.h>", syzlang), \
            "Must include accelq.h (not a subdirectory path)"
