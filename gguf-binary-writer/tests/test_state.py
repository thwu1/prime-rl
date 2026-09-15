
import struct
import os
import pytest
import math

GGUF_FILE = "/app/repaired.gguf"
ORIGINAL_FILE = "/app/model.gguf"

# Metadata value type IDs per GGUF spec
TYPE_UINT8   = 0
TYPE_INT8    = 1
TYPE_UINT16  = 2
TYPE_INT16   = 3
TYPE_UINT32  = 4
TYPE_INT32   = 5
TYPE_FLOAT32 = 6
TYPE_BOOL    = 7
TYPE_STRING  = 8
TYPE_ARRAY   = 9
TYPE_UINT64  = 10
TYPE_INT64   = 11
TYPE_FLOAT64 = 12

SCALAR_FORMATS = {
    TYPE_UINT8:   ('<B', 1),
    TYPE_INT8:    ('<b', 1),
    TYPE_UINT16:  ('<H', 2),
    TYPE_INT16:   ('<h', 2),
    TYPE_UINT32:  ('<I', 4),
    TYPE_INT32:   ('<i', 4),
    TYPE_FLOAT32: ('<f', 4),
    TYPE_BOOL:    ('<B', 1),
    TYPE_UINT64:  ('<Q', 8),
    TYPE_INT64:   ('<q', 8),
    TYPE_FLOAT64: ('<d', 8),
}

# Tensor type byte sizes (per element)
TENSOR_ELEM_SIZES = {
    0: 4,  # F32
    1: 2,  # F16
}


def align_offset(offset, alignment=32):
    remainder = offset % alignment
    if remainder == 0:
        return offset
    return offset + (alignment - remainder)


def read_gguf_string(data, offset):
    """Read a GGUF string: uint64 length + UTF-8 bytes. Returns (string, new_offset)."""
    length = struct.unpack_from('<Q', data, offset)[0]
    offset += 8
    string_val = data[offset:offset + length].decode('utf-8')
    offset += length
    return string_val, offset


def read_metadata_value(data, offset):
    """Read a metadata value. Returns (type_id, value, new_offset)."""
    type_id = struct.unpack_from('<I', data, offset)[0]
    offset += 4

    if type_id == TYPE_ARRAY:
        elem_type = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        count = struct.unpack_from('<Q', data, offset)[0]
        offset += 8
        elements = []
        for _ in range(count):
            if elem_type == TYPE_STRING:
                s, offset = read_gguf_string(data, offset)
                elements.append(s)
            else:
                fmt, size = SCALAR_FORMATS[elem_type]
                val = struct.unpack_from(fmt, data, offset)[0]
                offset += size
                elements.append(val)
        return type_id, (elem_type, elements), offset
    elif type_id == TYPE_STRING:
        val, offset = read_gguf_string(data, offset)
        return type_id, val, offset
    else:
        fmt, size = SCALAR_FORMATS[type_id]
        val = struct.unpack_from(fmt, data, offset)[0]
        offset += size
        return type_id, val, offset


def parse_gguf(filepath):
    """Parse a GGUF file and return all parsed structures."""
    with open(filepath, 'rb') as f:
        data = f.read()

    offset = 0

    # Header
    magic = struct.unpack_from('<I', data, offset)[0]; offset += 4
    version = struct.unpack_from('<I', data, offset)[0]; offset += 4
    tensor_count = struct.unpack_from('<Q', data, offset)[0]; offset += 8
    metadata_kv_count = struct.unpack_from('<Q', data, offset)[0]; offset += 8

    # Metadata KV pairs
    metadata = {}
    for _ in range(metadata_kv_count):
        key, offset = read_gguf_string(data, offset)
        type_id, value, offset = read_metadata_value(data, offset)
        metadata[key] = (type_id, value)

    # Tensor info entries
    tensor_infos = []
    for _ in range(tensor_count):
        name, offset = read_gguf_string(data, offset)
        n_dims = struct.unpack_from('<I', data, offset)[0]; offset += 4
        dims = []
        for _ in range(n_dims):
            dim = struct.unpack_from('<Q', data, offset)[0]; offset += 8
            dims.append(dim)
        tensor_type = struct.unpack_from('<I', data, offset)[0]; offset += 4
        tensor_offset = struct.unpack_from('<Q', data, offset)[0]; offset += 8
        tensor_infos.append({
            'name': name,
            'n_dims': n_dims,
            'dimensions': dims,
            'type': tensor_type,
            'offset': tensor_offset,
        })

    # Compute tensor data start (aligned)
    alignment = 32
    if 'general.alignment' in metadata:
        _, alignment_val = metadata['general.alignment']
        alignment = alignment_val
    tensor_data_start = align_offset(offset, alignment)

    return {
        'raw': data,
        'magic': magic,
        'version': version,
        'tensor_count': tensor_count,
        'metadata_kv_count': metadata_kv_count,
        'metadata': metadata,
        'tensor_infos': tensor_infos,
        'tensor_data_start': tensor_data_start,
        'alignment': alignment,
    }


# ---- Module-level parse ----
_parsed = None

def get_parsed():
    global _parsed
    if _parsed is None:
        _parsed = parse_gguf(GGUF_FILE)
    return _parsed


# ========== TESTS ==========

class TestAntiCheat:
    """Verify the solver actually repaired the file rather than just copying."""

    def test_original_file_exists(self):
        assert os.path.exists(ORIGINAL_FILE), \
            "Original corrupted file /app/model.gguf must be preserved"

    def test_repaired_file_exists(self):
        assert os.path.exists(GGUF_FILE), \
            f"Repaired file {GGUF_FILE} does not exist"

    def test_repaired_differs_from_original(self):
        with open(ORIGINAL_FILE, 'rb') as f:
            original = f.read()
        with open(GGUF_FILE, 'rb') as f:
            repaired = f.read()
        assert original != repaired, \
            "Repaired file must differ from the corrupted original"


class TestFileExists:
    def test_output_file_exists(self):
        assert os.path.exists(GGUF_FILE), f"Output file {GGUF_FILE} does not exist"

    def test_output_file_not_empty(self):
        size = os.path.getsize(GGUF_FILE)
        assert size > 0, "Output file is empty"

    def test_output_file_minimum_size(self):
        size = os.path.getsize(GGUF_FILE)
        assert size > 1000, f"Output file too small ({size} bytes), likely incomplete"


class TestHeader:
    def test_magic_bytes(self):
        p = get_parsed()
        assert p['magic'] == 0x46554747, \
            f"Magic should be 0x46554747 ('GGUF'), got 0x{p['magic']:08X}"

    def test_version(self):
        p = get_parsed()
        assert p['version'] == 3, f"Version should be 3, got {p['version']}"

    def test_tensor_count(self):
        p = get_parsed()
        assert p['tensor_count'] == 6, \
            f"Tensor count should be 6, got {p['tensor_count']}"

    def test_metadata_kv_count(self):
        p = get_parsed()
        assert p['metadata_kv_count'] == 20, \
            f"Metadata KV count should be 20, got {p['metadata_kv_count']}"


class TestMetadataStringFields:
    """Verify all string-type metadata fields."""

    def test_general_architecture(self):
        p = get_parsed()
        assert 'general.architecture' in p['metadata']
        type_id, value = p['metadata']['general.architecture']
        assert type_id == TYPE_STRING, f"Expected STRING type (8), got {type_id}"
        assert value == 'llama', f"Expected 'llama', got '{value}'"

    def test_general_name(self):
        p = get_parsed()
        assert 'general.name' in p['metadata']
        type_id, value = p['metadata']['general.name']
        assert type_id == TYPE_STRING
        assert value == 'TestModel-Bench'

    def test_tokenizer_model(self):
        p = get_parsed()
        assert 'tokenizer.ggml.model' in p['metadata']
        type_id, value = p['metadata']['tokenizer.ggml.model']
        assert type_id == TYPE_STRING
        assert value == 'llama'


class TestMetadataUint32Fields:
    """Verify all uint32-type metadata fields."""

    def test_quantization_version(self):
        p = get_parsed()
        assert 'general.quantization_version' in p['metadata']
        type_id, value = p['metadata']['general.quantization_version']
        assert type_id == TYPE_UINT32, f"Expected UINT32 type (4), got {type_id}"
        assert value == 2

    def test_alignment(self):
        p = get_parsed()
        assert 'general.alignment' in p['metadata']
        type_id, value = p['metadata']['general.alignment']
        assert type_id == TYPE_UINT32
        assert value == 32

    def test_file_type(self):
        p = get_parsed()
        assert 'general.file_type' in p['metadata']
        type_id, value = p['metadata']['general.file_type']
        assert type_id == TYPE_UINT32
        assert value == 1  # MOSTLY_F16

    def test_bos_token_id(self):
        p = get_parsed()
        assert 'tokenizer.ggml.bos_token_id' in p['metadata']
        type_id, value = p['metadata']['tokenizer.ggml.bos_token_id']
        assert type_id == TYPE_UINT32
        assert value == 2

    def test_eos_token_id(self):
        p = get_parsed()
        assert 'tokenizer.ggml.eos_token_id' in p['metadata']
        type_id, value = p['metadata']['tokenizer.ggml.eos_token_id']
        assert type_id == TYPE_UINT32
        assert value == 1


class TestMetadataUint64Fields:
    """Verify all uint64-type metadata fields."""

    def test_context_length(self):
        p = get_parsed()
        assert 'llama.context_length' in p['metadata']
        type_id, value = p['metadata']['llama.context_length']
        assert type_id == TYPE_UINT64, f"Expected UINT64 type (10), got {type_id}"
        assert value == 4096

    def test_embedding_length(self):
        p = get_parsed()
        type_id, value = p['metadata']['llama.embedding_length']
        assert type_id == TYPE_UINT64
        assert value == 256

    def test_block_count(self):
        p = get_parsed()
        type_id, value = p['metadata']['llama.block_count']
        assert type_id == TYPE_UINT64
        assert value == 4

    def test_feed_forward_length(self):
        p = get_parsed()
        type_id, value = p['metadata']['llama.feed_forward_length']
        assert type_id == TYPE_UINT64
        assert value == 512

    def test_head_count(self):
        p = get_parsed()
        type_id, value = p['metadata']['llama.attention.head_count']
        assert type_id == TYPE_UINT64
        assert value == 8

    def test_head_count_kv(self):
        p = get_parsed()
        type_id, value = p['metadata']['llama.attention.head_count_kv']
        assert type_id == TYPE_UINT64
        assert value == 4

    def test_rope_dimension_count(self):
        p = get_parsed()
        type_id, value = p['metadata']['llama.rope.dimension_count']
        assert type_id == TYPE_UINT64
        assert value == 32


class TestMetadataFloat32Fields:
    """Verify all float32-type metadata fields."""

    def test_layer_norm_rms_epsilon(self):
        p = get_parsed()
        assert 'llama.attention.layer_norm_rms_epsilon' in p['metadata']
        type_id, value = p['metadata']['llama.attention.layer_norm_rms_epsilon']
        assert type_id == TYPE_FLOAT32, f"Expected FLOAT32 type (6), got {type_id}"
        assert abs(value - 1e-5) < 1e-8, f"Expected 1e-5, got {value}"

    def test_rope_freq_base(self):
        p = get_parsed()
        assert 'llama.rope.freq_base' in p['metadata']
        type_id, value = p['metadata']['llama.rope.freq_base']
        assert type_id == TYPE_FLOAT32
        assert abs(value - 10000.0) < 0.1, f"Expected 10000.0, got {value}"


class TestMetadataArrayFields:
    """Verify all array-type metadata fields."""

    def test_tokenizer_tokens_type(self):
        p = get_parsed()
        assert 'tokenizer.ggml.tokens' in p['metadata']
        type_id, value = p['metadata']['tokenizer.ggml.tokens']
        assert type_id == TYPE_ARRAY, f"Expected ARRAY type (9), got {type_id}"

    def test_tokenizer_tokens_element_type(self):
        p = get_parsed()
        type_id, (elem_type, elements) = p['metadata']['tokenizer.ggml.tokens']
        assert elem_type == TYPE_STRING, \
            f"Expected STRING element type (8), got {elem_type}"

    def test_tokenizer_tokens_values(self):
        p = get_parsed()
        type_id, (elem_type, elements) = p['metadata']['tokenizer.ggml.tokens']
        expected = ['<pad>', '<eos>', '<bos>', 'hello', 'world']
        assert elements == expected, f"Expected {expected}, got {elements}"

    def test_tokenizer_scores_type(self):
        p = get_parsed()
        assert 'tokenizer.ggml.scores' in p['metadata']
        type_id, value = p['metadata']['tokenizer.ggml.scores']
        assert type_id == TYPE_ARRAY

    def test_tokenizer_scores_element_type(self):
        p = get_parsed()
        type_id, (elem_type, elements) = p['metadata']['tokenizer.ggml.scores']
        assert elem_type == TYPE_FLOAT32, \
            f"Expected FLOAT32 element type (6), got {elem_type}"

    def test_tokenizer_scores_values(self):
        p = get_parsed()
        type_id, (elem_type, elements) = p['metadata']['tokenizer.ggml.scores']
        expected = [0.0, 0.0, 0.0, -1.0, -2.0]
        assert len(elements) == len(expected), \
            f"Expected {len(expected)} scores, got {len(elements)}"
        for i, (actual, exp) in enumerate(zip(elements, expected)):
            assert abs(actual - exp) < 1e-6, \
                f"Score[{i}]: expected {exp}, got {actual}"

    def test_tokenizer_token_type_type(self):
        p = get_parsed()
        assert 'tokenizer.ggml.token_type' in p['metadata']
        type_id, value = p['metadata']['tokenizer.ggml.token_type']
        assert type_id == TYPE_ARRAY

    def test_tokenizer_token_type_element_type(self):
        p = get_parsed()
        type_id, (elem_type, elements) = p['metadata']['tokenizer.ggml.token_type']
        assert elem_type == TYPE_INT32, \
            f"Expected INT32 element type (5), got {elem_type}"

    def test_tokenizer_token_type_values(self):
        p = get_parsed()
        type_id, (elem_type, elements) = p['metadata']['tokenizer.ggml.token_type']
        expected = [3, 3, 3, 1, 1]
        assert elements == expected, f"Expected {expected}, got {elements}"


class TestTensorInfo:
    """Verify tensor info entries (names, types, dimensions)."""

    def _find_tensor(self, name):
        p = get_parsed()
        for t in p['tensor_infos']:
            if t['name'] == name:
                return t
        pytest.fail(f"Tensor '{name}' not found in tensor info entries")

    def test_tensor_count(self):
        p = get_parsed()
        assert len(p['tensor_infos']) == 6

    def test_token_embd_weight(self):
        t = self._find_tensor('token_embd.weight')
        assert t['type'] == 0, f"Expected F32 (0), got {t['type']}"
        assert t['dimensions'] == [256, 5], f"Expected [256, 5], got {t['dimensions']}"
        assert t['n_dims'] == 2

    def test_attn_norm_weight(self):
        t = self._find_tensor('blk.0.attn_norm.weight')
        assert t['type'] == 0, f"Expected F32 (0), got {t['type']}"
        assert t['dimensions'] == [256], f"Expected [256], got {t['dimensions']}"
        assert t['n_dims'] == 1

    def test_attn_q_weight(self):
        t = self._find_tensor('blk.0.attn_q.weight')
        assert t['type'] == 1, f"Expected F16 (1), got {t['type']}"
        assert t['dimensions'] == [256, 256], \
            f"Expected [256, 256], got {t['dimensions']}"
        assert t['n_dims'] == 2

    def test_attn_k_weight(self):
        t = self._find_tensor('blk.0.attn_k.weight')
        assert t['type'] == 1, f"Expected F16 (1), got {t['type']}"
        assert t['dimensions'] == [128, 256], \
            f"Expected [128, 256], got {t['dimensions']}"
        assert t['n_dims'] == 2

    def test_ffn_up_weight(self):
        t = self._find_tensor('blk.0.ffn_up.weight')
        assert t['type'] == 1, f"Expected F16 (1), got {t['type']}"
        assert t['dimensions'] == [512, 256], \
            f"Expected [512, 256], got {t['dimensions']}"
        assert t['n_dims'] == 2

    def test_output_norm_weight(self):
        t = self._find_tensor('output_norm.weight')
        assert t['type'] == 0, f"Expected F32 (0), got {t['type']}"
        assert t['dimensions'] == [256], f"Expected [256], got {t['dimensions']}"
        assert t['n_dims'] == 1


class TestAlignment:
    """Verify 32-byte alignment constraints."""

    def test_all_tensor_offsets_aligned(self):
        p = get_parsed()
        alignment = p['alignment']
        for t in p['tensor_infos']:
            assert t['offset'] % alignment == 0, \
                f"Tensor '{t['name']}' offset {t['offset']} not aligned to {alignment}"

    def test_tensor_data_start_aligned(self):
        p = get_parsed()
        alignment = p['alignment']
        assert p['tensor_data_start'] % alignment == 0, \
            f"Tensor data start {p['tensor_data_start']} not aligned to {alignment}"

    def test_first_tensor_offset_is_zero(self):
        p = get_parsed()
        assert len(p['tensor_infos']) > 0
        assert p['tensor_infos'][0]['offset'] == 0, \
            f"First tensor offset should be 0, got {p['tensor_infos'][0]['offset']}"

    def test_tensor_offsets_increasing(self):
        p = get_parsed()
        offsets = [t['offset'] for t in p['tensor_infos']]
        for i in range(1, len(offsets)):
            assert offsets[i] > offsets[i - 1], \
                f"Tensor offsets not strictly increasing: {offsets}"

    def test_tensor_offsets_non_overlapping(self):
        """Verify tensors don't overlap in the data section."""
        p = get_parsed()
        for i in range(len(p['tensor_infos']) - 1):
            t_curr = p['tensor_infos'][i]
            t_next = p['tensor_infos'][i + 1]
            n_elements = 1
            for d in t_curr['dimensions']:
                n_elements *= d
            elem_size = TENSOR_ELEM_SIZES[t_curr['type']]
            data_size = n_elements * elem_size
            assert t_curr['offset'] + data_size <= t_next['offset'], \
                f"Tensor '{t_curr['name']}' (offset={t_curr['offset']}, size={data_size}) " \
                f"overlaps with '{t_next['name']}' (offset={t_next['offset']})"


class TestTensorData:
    """Verify actual tensor data values in the binary file."""

    def _read_tensor_data(self, tensor_index, count=10):
        """Read the first `count` elements from a tensor."""
        p = get_parsed()
        t = p['tensor_infos'][tensor_index]
        data_start = p['tensor_data_start'] + t['offset']
        elem_size = TENSOR_ELEM_SIZES[t['type']]

        n_elements = 1
        for d in t['dimensions']:
            n_elements *= d
        actual_count = min(count, n_elements)

        values = []
        if t['type'] == 0:  # F32
            for i in range(actual_count):
                val = struct.unpack_from('<f', p['raw'], data_start + i * 4)[0]
                values.append(val)
        elif t['type'] == 1:  # F16
            for i in range(actual_count):
                val = struct.unpack_from('<e', p['raw'], data_start + i * 2)[0]
                values.append(val)
        return values

    def test_token_embd_data(self):
        """token_embd.weight (F32, fill_value=0.01)"""
        values = self._read_tensor_data(0, count=20)
        for i, v in enumerate(values):
            assert abs(v - 0.01) < 1e-6, \
                f"token_embd.weight[{i}]: expected ~0.01, got {v}"

    def test_attn_norm_data(self):
        """blk.0.attn_norm.weight (F32, fill_value=1.0)"""
        values = self._read_tensor_data(1, count=20)
        for i, v in enumerate(values):
            assert abs(v - 1.0) < 1e-6, \
                f"blk.0.attn_norm.weight[{i}]: expected ~1.0, got {v}"

    def test_attn_q_data_f16(self):
        """blk.0.attn_q.weight (F16, fill_value=0.02) — extended check covers
        previously-corrupted region."""
        values = self._read_tensor_data(2, count=200)
        for i, v in enumerate(values):
            assert not math.isnan(v) and not math.isinf(v), \
                f"blk.0.attn_q.weight[{i}]: NaN/Inf detected"
            assert abs(v - 0.02) < 1e-3, \
                f"blk.0.attn_q.weight[{i}]: expected ~0.02, got {v}"

    def test_attn_k_data_f16(self):
        """blk.0.attn_k.weight (F16, fill_value=0.03)"""
        values = self._read_tensor_data(3, count=20)
        for i, v in enumerate(values):
            assert abs(v - 0.03) < 1e-3, \
                f"blk.0.attn_k.weight[{i}]: expected ~0.03, got {v}"

    def test_ffn_up_data_f16(self):
        """blk.0.ffn_up.weight (F16, fill_value=0.04)"""
        values = self._read_tensor_data(4, count=20)
        for i, v in enumerate(values):
            assert abs(v - 0.04) < 1e-3, \
                f"blk.0.ffn_up.weight[{i}]: expected ~0.04, got {v}"

    def test_output_norm_data(self):
        """output_norm.weight (F32, fill_value=1.0)"""
        values = self._read_tensor_data(5, count=20)
        for i, v in enumerate(values):
            assert abs(v - 1.0) < 1e-6, \
                f"output_norm.weight[{i}]: expected ~1.0, got {v}"

    def test_tensor_data_region_in_bounds(self):
        """Verify all tensor data fits within the file."""
        p = get_parsed()
        file_size = len(p['raw'])
        for t in p['tensor_infos']:
            n_elements = 1
            for d in t['dimensions']:
                n_elements *= d
            data_size = n_elements * TENSOR_ELEM_SIZES[t['type']]
            end_offset = p['tensor_data_start'] + t['offset'] + data_size
            assert end_offset <= file_size, \
                f"Tensor '{t['name']}' data extends beyond file " \
                f"(end={end_offset}, file_size={file_size})"


class TestMetadataCompleteness:
    """Verify all 20 required metadata keys are present."""

    EXPECTED_KEYS = [
        'general.architecture',
        'general.name',
        'general.quantization_version',
        'general.alignment',
        'general.file_type',
        'llama.context_length',
        'llama.embedding_length',
        'llama.block_count',
        'llama.feed_forward_length',
        'llama.attention.head_count',
        'llama.attention.head_count_kv',
        'llama.attention.layer_norm_rms_epsilon',
        'llama.rope.dimension_count',
        'llama.rope.freq_base',
        'tokenizer.ggml.model',
        'tokenizer.ggml.tokens',
        'tokenizer.ggml.scores',
        'tokenizer.ggml.token_type',
        'tokenizer.ggml.bos_token_id',
        'tokenizer.ggml.eos_token_id',
    ]

    def test_all_keys_present(self):
        p = get_parsed()
        for key in self.EXPECTED_KEYS:
            assert key in p['metadata'], f"Missing metadata key: '{key}'"

    def test_no_extra_keys(self):
        p = get_parsed()
        actual_keys = set(p['metadata'].keys())
        expected_keys = set(self.EXPECTED_KEYS)
        extra = actual_keys - expected_keys
        assert len(extra) == 0, f"Unexpected extra metadata keys: {extra}"


class TestPaddingBytes:
    """Verify padding between header/tensor_info and tensor data is correct."""

    def test_padding_alignment(self):
        p = get_parsed()
        tds = p['tensor_data_start']
        alignment = p['alignment']
        assert tds % alignment == 0
