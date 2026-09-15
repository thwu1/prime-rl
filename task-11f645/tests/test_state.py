"""Tests for GGUF v3 forensic repair task.

Parses /app/output.gguf from scratch using a custom binary parser (no gguf
library dependency) and verifies structural correctness, metadata values,
tensor info, alignment, and tensor data accuracy against independently
generated reference data.
"""

import struct
import math
import os
import random
import pytest


# ---- Constants ----

GGUF_MAGIC = b'GGUF'
GGUF_VERSION = 3
ALIGNMENT = 64

GGML_TYPE_F32 = 0
GGML_TYPE_F16 = 1
GGML_TYPE_Q4_0 = 2

GGUF_TYPE_UINT8 = 0
GGUF_TYPE_INT8 = 1
GGUF_TYPE_UINT16 = 2
GGUF_TYPE_INT16 = 3
GGUF_TYPE_UINT32 = 4
GGUF_TYPE_INT32 = 5
GGUF_TYPE_FLOAT32 = 6
GGUF_TYPE_BOOL = 7
GGUF_TYPE_STRING = 8
GGUF_TYPE_ARRAY = 9
GGUF_TYPE_UINT64 = 10
GGUF_TYPE_INT64 = 11
GGUF_TYPE_FLOAT64 = 12

OUTPUT_PATH = '/app/output.gguf'
QK4_0 = 32


# ---- GGUF Binary Parser ----

class GGUFParser:
    """Minimal GGUF v3 binary parser for test validation."""

    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def read_bytes(self, n: int) -> bytes:
        result = self.data[self.offset:self.offset + n]
        assert len(result) == n, f"Unexpected EOF at offset {self.offset}"
        self.offset += n
        return result

    def read_uint32(self) -> int:
        return struct.unpack('<I', self.read_bytes(4))[0]

    def read_uint64(self) -> int:
        return struct.unpack('<Q', self.read_bytes(8))[0]

    def read_int32(self) -> int:
        return struct.unpack('<i', self.read_bytes(4))[0]

    def read_float32(self) -> float:
        return struct.unpack('<f', self.read_bytes(4))[0]

    def read_float64(self) -> float:
        return struct.unpack('<d', self.read_bytes(8))[0]

    def read_gguf_string(self) -> str:
        length = self.read_uint64()
        return self.read_bytes(length).decode('utf-8')

    def read_metadata_value(self, value_type: int):
        if value_type == GGUF_TYPE_UINT8:
            return struct.unpack('<B', self.read_bytes(1))[0]
        elif value_type == GGUF_TYPE_INT8:
            return struct.unpack('<b', self.read_bytes(1))[0]
        elif value_type == GGUF_TYPE_UINT16:
            return struct.unpack('<H', self.read_bytes(2))[0]
        elif value_type == GGUF_TYPE_INT16:
            return struct.unpack('<h', self.read_bytes(2))[0]
        elif value_type == GGUF_TYPE_UINT32:
            return self.read_uint32()
        elif value_type == GGUF_TYPE_INT32:
            return self.read_int32()
        elif value_type == GGUF_TYPE_FLOAT32:
            return self.read_float32()
        elif value_type == GGUF_TYPE_BOOL:
            return self.read_bytes(1)[0] != 0
        elif value_type == GGUF_TYPE_STRING:
            return self.read_gguf_string()
        elif value_type == GGUF_TYPE_ARRAY:
            arr_type = self.read_uint32()
            arr_len = self.read_uint64()
            return [self.read_metadata_value(arr_type) for _ in range(arr_len)]
        elif value_type == GGUF_TYPE_UINT64:
            return self.read_uint64()
        elif value_type == GGUF_TYPE_INT64:
            return struct.unpack('<q', self.read_bytes(8))[0]
        elif value_type == GGUF_TYPE_FLOAT64:
            return self.read_float64()
        else:
            raise ValueError(f"Unknown metadata value type: {value_type}")

    def read_metadata_kv(self):
        key = self.read_gguf_string()
        value_type = self.read_uint32()
        value = self.read_metadata_value(value_type)
        return key, value_type, value

    def read_tensor_info(self):
        name = self.read_gguf_string()
        n_dims = self.read_uint32()
        dims = [self.read_uint64() for _ in range(n_dims)]
        tensor_type = self.read_uint32()
        offset = self.read_uint64()
        return name, n_dims, dims, tensor_type, offset


# ---- Reference data generation ----

def gen_reference_data():
    """Generate the same tensor data used by the task setup (seed 12345)."""
    rng = random.Random(12345)

    def gen_f32(n):
        return [rng.gauss(0, 1) for _ in range(n)]

    token_embd = gen_f32(512)    # [32, 16]
    attn_norm = gen_f32(16)       # [16]
    ffn_down = gen_f32(1024)      # [64, 16]
    output = gen_f32(512)         # [32, 16]

    return token_embd, attn_norm, ffn_down, output


def dequantize_q4_0_block(block_bytes: bytes):
    """Dequantize a single Q4_0 block (18 bytes) to 32 float32 values."""
    d = struct.unpack('<e', block_bytes[0:2])[0]
    qs = block_bytes[2:18]
    result = [0.0] * 32
    for j in range(16):
        xi0 = qs[j] & 0x0F
        xi1 = (qs[j] >> 4) & 0x0F
        result[j] = (xi0 - 8) * d
        result[j + 16] = (xi1 - 8) * d
    return result


def dequantize_q4_0(data: bytes, n_elements: int):
    """Dequantize Q4_0 data to list of float32 values."""
    n_blocks = n_elements // 32
    result = []
    for i in range(n_blocks):
        block = data[i * 18:(i + 1) * 18]
        result.extend(dequantize_q4_0_block(block))
    return result


# ---- Shared parser ----

def parse_full():
    """Parse the output GGUF file, returning structured data."""
    with open(OUTPUT_PATH, 'rb') as f:
        data = f.read()
    parser = GGUFParser(data)

    magic = parser.read_bytes(4)
    version = parser.read_uint32()
    tensor_count = parser.read_uint64()
    kv_count = parser.read_uint64()

    metadata = {}
    metadata_order = []
    for _ in range(kv_count):
        key, vtype, value = parser.read_metadata_kv()
        metadata[key] = (vtype, value)
        metadata_order.append(key)

    tensors = []
    for _ in range(tensor_count):
        tensors.append(parser.read_tensor_info())

    header_end = parser.offset
    padding_size = (ALIGNMENT - (header_end % ALIGNMENT)) % ALIGNMENT
    tensor_data_start = header_end + padding_size

    return {
        'data': data,
        'magic': magic,
        'version': version,
        'tensor_count': tensor_count,
        'kv_count': kv_count,
        'metadata': metadata,
        'metadata_order': metadata_order,
        'tensors': tensors,
        'header_end': header_end,
        'padding_size': padding_size,
        'tensor_data_start': tensor_data_start,
    }


# ---- Tests ----

class TestFileExists:
    def test_output_file_exists(self):
        assert os.path.exists(OUTPUT_PATH), \
            f"{OUTPUT_PATH} not found. Did you produce the repaired GGUF file?"

    def test_output_file_nonzero(self):
        size = os.path.getsize(OUTPUT_PATH)
        assert size > 100, f"Output file is suspiciously small: {size} bytes"


class TestHeader:
    def test_magic(self):
        parsed = parse_full()
        assert parsed['magic'] == GGUF_MAGIC, \
            f"Wrong magic: got {parsed['magic']!r}, expected {GGUF_MAGIC!r}"

    def test_version_is_3(self):
        """Header version must be 3, not 2."""
        parsed = parse_full()
        assert parsed['version'] == 3, \
            f"Version should be 3, got {parsed['version']}"

    def test_tensor_count(self):
        parsed = parse_full()
        assert parsed['tensor_count'] == 4, \
            f"Wrong tensor count: got {parsed['tensor_count']}, expected 4"

    def test_metadata_kv_count_is_14(self):
        """Header kv_count must be 14, not 12."""
        parsed = parse_full()
        assert parsed['kv_count'] == 14, \
            f"Wrong KV count: got {parsed['kv_count']}, expected 14"


class TestMetadata:
    EXPECTED_KV = [
        ("general.architecture", GGUF_TYPE_STRING, "llama"),
        ("general.name", GGUF_TYPE_STRING, "TinyTestModel"),
        ("general.alignment", GGUF_TYPE_UINT32, 64),
        ("general.quantization_version", GGUF_TYPE_UINT32, 2),
        ("general.file_type", GGUF_TYPE_UINT32, 2),
        ("llama.context_length", GGUF_TYPE_UINT64, 512),
        ("llama.embedding_length", GGUF_TYPE_UINT64, 16),
        ("llama.block_count", GGUF_TYPE_UINT64, 1),
        ("llama.feed_forward_length", GGUF_TYPE_UINT64, 32),
        ("llama.attention.head_count", GGUF_TYPE_UINT64, 2),
        ("llama.attention.layer_norm_rms_epsilon", GGUF_TYPE_FLOAT32, 1e-5),
        ("llama.rope.dimension_count", GGUF_TYPE_UINT64, 8),
        ("general.tags", GGUF_TYPE_ARRAY, ["test", "tiny", "benchmark"]),
        ("general.quantized_by", GGUF_TYPE_STRING, "local"),
    ]

    def test_all_keys_present(self):
        parsed = parse_full()
        for exp_key, _, _ in self.EXPECTED_KV:
            assert exp_key in parsed['metadata'], f"Missing metadata key: {exp_key}"

    def test_no_extra_keys(self):
        parsed = parse_full()
        expected_keys = {k for k, _, _ in self.EXPECTED_KV}
        actual_keys = set(parsed['metadata'].keys())
        extra = actual_keys - expected_keys
        assert not extra, f"Unexpected extra metadata keys: {extra}"

    def test_metadata_types(self):
        parsed = parse_full()
        for exp_key, exp_type, _ in self.EXPECTED_KV:
            vtype, _ = parsed['metadata'][exp_key]
            assert vtype == exp_type, \
                f"Wrong type for '{exp_key}': got {vtype}, expected {exp_type}"

    def test_context_length_type_is_uint64(self):
        """llama.context_length must have type UINT64 (10), not UINT32 (4)."""
        parsed = parse_full()
        vtype, value = parsed['metadata']['llama.context_length']
        assert vtype == GGUF_TYPE_UINT64, \
            f"llama.context_length type should be UINT64 (10), got {vtype}"
        assert value == 512

    def test_metadata_string_values(self):
        parsed = parse_full()
        string_kvs = [(k, v) for k, t, v in self.EXPECTED_KV if t == GGUF_TYPE_STRING]
        for key, expected in string_kvs:
            _, actual = parsed['metadata'][key]
            assert actual == expected, \
                f"Wrong value for '{key}': got {actual!r}, expected {expected!r}"

    def test_metadata_uint32_values(self):
        parsed = parse_full()
        uint32_kvs = [(k, v) for k, t, v in self.EXPECTED_KV if t == GGUF_TYPE_UINT32]
        for key, expected in uint32_kvs:
            _, actual = parsed['metadata'][key]
            assert actual == expected, \
                f"Wrong value for '{key}': got {actual}, expected {expected}"

    def test_metadata_uint64_values(self):
        parsed = parse_full()
        uint64_kvs = [(k, v) for k, t, v in self.EXPECTED_KV if t == GGUF_TYPE_UINT64]
        for key, expected in uint64_kvs:
            _, actual = parsed['metadata'][key]
            assert actual == expected, \
                f"Wrong value for '{key}': got {actual}, expected {expected}"

    def test_metadata_float32_values(self):
        parsed = parse_full()
        float_kvs = [(k, v) for k, t, v in self.EXPECTED_KV if t == GGUF_TYPE_FLOAT32]
        for key, expected in float_kvs:
            _, actual = parsed['metadata'][key]
            assert abs(actual - expected) < 1e-9, \
                f"Wrong value for '{key}': got {actual}, expected {expected}"

    def test_metadata_array_value(self):
        parsed = parse_full()
        _, actual = parsed['metadata']['general.tags']
        expected = ["test", "tiny", "benchmark"]
        assert actual == expected, \
            f"Wrong value for 'general.tags': got {actual!r}, expected {expected!r}"


class TestTensorInfo:
    EXPECTED_TENSORS = [
        ("token_embd.weight", 2, [32, 16], GGML_TYPE_F32),
        ("blk.0.attn_norm.weight", 1, [16], GGML_TYPE_F16),
        ("blk.0.ffn_down.weight", 2, [64, 16], GGML_TYPE_Q4_0),
        ("output.weight", 2, [32, 16], GGML_TYPE_F32),
    ]

    def test_tensor_count(self):
        parsed = parse_full()
        assert len(parsed['tensors']) == 4

    def test_tensor_names(self):
        parsed = parse_full()
        for i, (exp_name, _, _, _) in enumerate(self.EXPECTED_TENSORS):
            name = parsed['tensors'][i][0]
            assert name == exp_name, \
                f"Tensor {i}: got name {name!r}, expected {exp_name!r}"

    def test_tensor_dimensions(self):
        parsed = parse_full()
        for i, (_, exp_ndims, exp_dims, _) in enumerate(self.EXPECTED_TENSORS):
            _, n_dims, dims, _, _ = parsed['tensors'][i]
            assert n_dims == exp_ndims, \
                f"Tensor {i}: got {n_dims} dims, expected {exp_ndims}"
            assert dims == exp_dims, \
                f"Tensor {i}: got dims {dims}, expected {exp_dims}"

    def test_tensor_types(self):
        parsed = parse_full()
        for i, (name, _, _, exp_type) in enumerate(self.EXPECTED_TENSORS):
            _, _, _, ttype, _ = parsed['tensors'][i]
            assert ttype == exp_type, \
                f"Tensor '{name}': got type {ttype}, expected {exp_type}"

    def test_ffn_down_is_q4_0(self):
        """blk.0.ffn_down.weight type must be Q4_0 (2), not Q2_K (10)."""
        parsed = parse_full()
        name, _, _, ttype, _ = parsed['tensors'][2]
        assert name == "blk.0.ffn_down.weight"
        assert ttype == GGML_TYPE_Q4_0, \
            f"ffn_down type should be Q4_0 (2), got {ttype}"

    def test_tensor_offsets_aligned(self):
        parsed = parse_full()
        for name, _, _, _, offset in parsed['tensors']:
            assert offset % ALIGNMENT == 0, \
                f"Tensor '{name}' offset {offset} not aligned to {ALIGNMENT}"

    def test_tensor_offsets_non_overlapping(self):
        """Verify tensor data regions don't overlap."""
        parsed = parse_full()
        regions = []
        for name, _, dims, ttype, offset in parsed['tensors']:
            n_elements = 1
            for d in dims:
                n_elements *= d
            if ttype == GGML_TYPE_F32:
                size = n_elements * 4
            elif ttype == GGML_TYPE_F16:
                size = n_elements * 2
            elif ttype == GGML_TYPE_Q4_0:
                size = (n_elements // 32) * 18
            else:
                raise ValueError(f"Unknown type {ttype}")
            regions.append((name, offset, offset + size))
        regions.sort(key=lambda x: x[1])
        for i in range(len(regions) - 1):
            name_a, _, end_a = regions[i]
            name_b, start_b, _ = regions[i + 1]
            assert end_a <= start_b, \
                f"'{name_a}' (ends {end_a}) overlaps '{name_b}' (starts {start_b})"


class TestAlignmentPadding:
    def test_padding_is_zeros(self):
        """Padding bytes between header/tensor_info and tensor data must be 0x00."""
        parsed = parse_full()
        data = parsed['data']
        header_end = parsed['header_end']
        padding_size = parsed['padding_size']
        if padding_size > 0:
            padding = data[header_end:header_end + padding_size]
            non_zero = [i for i, b in enumerate(padding) if b != 0]
            assert len(non_zero) == 0, \
                f"{len(non_zero)} non-zero padding bytes (must all be 0x00)"

    def test_tensor_data_start_aligned(self):
        parsed = parse_full()
        assert parsed['tensor_data_start'] % ALIGNMENT == 0, \
            f"Tensor data start {parsed['tensor_data_start']} not aligned"


class TestTensorDataF32:
    def test_token_embd_weight(self):
        """Verify token_embd.weight F32 data matches reference exactly."""
        ref_data = gen_reference_data()
        ref = ref_data[0]
        parsed = parse_full()
        data = parsed['data']
        tds = parsed['tensor_data_start']

        name, _, dims, ttype, offset = parsed['tensors'][0]
        assert name == "token_embd.weight"
        assert ttype == GGML_TYPE_F32

        n_elements = 1
        for d in dims:
            n_elements *= d
        assert n_elements == len(ref)

        start = tds + offset
        for i in range(n_elements):
            got = struct.unpack('<f', data[start + i * 4:start + (i + 1) * 4])[0]
            assert abs(got - ref[i]) < 1e-6, \
                f"token_embd.weight[{i}]: got {got}, expected {ref[i]}"

    def test_output_weight(self):
        """Verify output.weight F32 data matches reference exactly."""
        ref_data = gen_reference_data()
        ref = ref_data[3]
        parsed = parse_full()
        data = parsed['data']
        tds = parsed['tensor_data_start']

        name, _, dims, ttype, offset = parsed['tensors'][3]
        assert name == "output.weight"
        assert ttype == GGML_TYPE_F32

        n_elements = 1
        for d in dims:
            n_elements *= d
        assert n_elements == len(ref)

        start = tds + offset
        for i in range(n_elements):
            got = struct.unpack('<f', data[start + i * 4:start + (i + 1) * 4])[0]
            assert abs(got - ref[i]) < 1e-6, \
                f"output.weight[{i}]: got {got}, expected {ref[i]}"


class TestTensorDataF16:
    def test_attn_norm_weight(self):
        """Verify blk.0.attn_norm.weight F16 data dequantizes close to reference."""
        ref_data = gen_reference_data()
        ref = ref_data[1]
        parsed = parse_full()
        data = parsed['data']
        tds = parsed['tensor_data_start']

        name, _, dims, ttype, offset = parsed['tensors'][1]
        assert name == "blk.0.attn_norm.weight"
        assert ttype == GGML_TYPE_F16

        n_elements = 1
        for d in dims:
            n_elements *= d
        assert n_elements == len(ref)

        start = tds + offset
        max_error = 0.0
        for i in range(n_elements):
            fp16_val = struct.unpack('<e', data[start + i * 2:start + (i + 1) * 2])[0]
            error = abs(fp16_val - ref[i])
            max_error = max(max_error, error)

        assert max_error < 0.01, \
            f"F16 max absolute error too large: {max_error:.6f} (threshold: 0.01)"


class TestTensorDataQ40:
    def test_ffn_down_weight_rmse(self):
        """Verify blk.0.ffn_down.weight Q4_0 dequantizes within RMSE tolerance."""
        ref_data = gen_reference_data()
        ref = ref_data[2]
        parsed = parse_full()
        data = parsed['data']
        tds = parsed['tensor_data_start']

        name, _, dims, ttype, offset = parsed['tensors'][2]
        assert name == "blk.0.ffn_down.weight"
        assert ttype == GGML_TYPE_Q4_0

        n_elements = 1
        for d in dims:
            n_elements *= d
        assert n_elements == len(ref)

        n_blocks = n_elements // 32
        start = tds + offset
        tensor_bytes = data[start:start + n_blocks * 18]
        dequantized = dequantize_q4_0(tensor_bytes, n_elements)

        sum_sq = 0.0
        for i in range(n_elements):
            diff = dequantized[i] - ref[i]
            sum_sq += diff * diff
        rmse = math.sqrt(sum_sq) / n_elements

        assert rmse < 0.01, \
            f"Q4_0 RMSE too large: {rmse:.6f} (threshold: 0.01)"

    def test_ffn_down_weight_block_structure(self):
        """Verify Q4_0 blocks have valid structure."""
        parsed = parse_full()
        data = parsed['data']
        tds = parsed['tensor_data_start']

        name, _, dims, ttype, offset = parsed['tensors'][2]
        assert name == "blk.0.ffn_down.weight"

        n_elements = 1
        for d in dims:
            n_elements *= d
        n_blocks = n_elements // 32

        start = tds + offset
        total_q4_size = n_blocks * 18
        tensor_bytes = data[start:start + total_q4_size]
        assert len(tensor_bytes) == total_q4_size, \
            f"Q4_0 data size mismatch: got {len(tensor_bytes)}, expected {total_q4_size}"

        for b in range(n_blocks):
            block = tensor_bytes[b * 18:(b + 1) * 18]
            qs = block[2:18]
            for j in range(16):
                lo = qs[j] & 0x0F
                hi = (qs[j] >> 4) & 0x0F
                assert 0 <= lo <= 15
                assert 0 <= hi <= 15
