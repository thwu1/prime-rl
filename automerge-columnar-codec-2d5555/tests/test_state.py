
"""
Tests for the Automerge binary format columnar codec.
Verifies encoding/decoding against specification examples and round-trip consistency.
"""

import subprocess
import tempfile
import os
import json
import pytest


def run_ts(code: str) -> subprocess.CompletedProcess:
    """Run TypeScript code using tsx and return the completed process."""
    fd, path = tempfile.mkstemp(suffix='.ts', dir='/tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(code)
        result = subprocess.run(
            ['npx', 'tsx', path],
            capture_output=True, text=True, cwd='/app', timeout=30
        )
        return result
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


@pytest.fixture(scope='session', autouse=True)
def install_deps():
    """Ensure npm dependencies are installed."""
    subprocess.run(
        ['npm', 'install', '--silent'],
        cwd='/app', capture_output=True, timeout=120
    )


# ========== uLEB128 Tests ==========

class TestULEB128:
    def test_encode_zero(self):
        r = run_ts("""
import { encodeULEB128 } from '/app/src/codec.ts';
console.log(JSON.stringify(Array.from(encodeULEB128(0n))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0x00]

    def test_encode_127(self):
        r = run_ts("""
import { encodeULEB128 } from '/app/src/codec.ts';
console.log(JSON.stringify(Array.from(encodeULEB128(127n))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0x7F]

    def test_encode_128(self):
        r = run_ts("""
import { encodeULEB128 } from '/app/src/codec.ts';
console.log(JSON.stringify(Array.from(encodeULEB128(128n))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0x80, 0x01]

    def test_encode_300(self):
        r = run_ts("""
import { encodeULEB128 } from '/app/src/codec.ts';
console.log(JSON.stringify(Array.from(encodeULEB128(300n))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0xAC, 0x02]

    def test_decode_roundtrip(self):
        r = run_ts("""
import { encodeULEB128, decodeULEB128 } from '/app/src/codec.ts';
const values = [0n, 1n, 127n, 128n, 255n, 300n, 16383n, 16384n];
const results = values.map(v => {
    const encoded = encodeULEB128(v);
    const [decoded] = decodeULEB128(encoded);
    return Number(decoded);
});
console.log(JSON.stringify(results));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0, 1, 127, 128, 255, 300, 16383, 16384]

    def test_overlong_rejection(self):
        """Overlong encoding 0x80 0x00 for value 0 must be rejected."""
        r = run_ts("""
import { decodeULEB128 } from '/app/src/codec.ts';
try {
    decodeULEB128(new Uint8Array([0x80, 0x00]));
    console.log('ACCEPTED');
} catch (e) {
    console.log('REJECTED');
}
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert r.stdout.strip() == 'REJECTED'


# ========== Signed LEB128 Tests ==========

class TestLEB128:
    def test_encode_zero(self):
        r = run_ts("""
import { encodeLEB128 } from '/app/src/codec.ts';
console.log(JSON.stringify(Array.from(encodeLEB128(0n))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0x00]

    def test_encode_positive_63(self):
        r = run_ts("""
import { encodeLEB128 } from '/app/src/codec.ts';
console.log(JSON.stringify(Array.from(encodeLEB128(63n))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0x3F]

    def test_encode_positive_64(self):
        r = run_ts("""
import { encodeLEB128 } from '/app/src/codec.ts';
console.log(JSON.stringify(Array.from(encodeLEB128(64n))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0xC0, 0x00]

    def test_encode_negative_1(self):
        r = run_ts("""
import { encodeLEB128 } from '/app/src/codec.ts';
console.log(JSON.stringify(Array.from(encodeLEB128(-1n))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0x7F]

    def test_encode_negative_3(self):
        r = run_ts("""
import { encodeLEB128 } from '/app/src/codec.ts';
console.log(JSON.stringify(Array.from(encodeLEB128(-3n))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0x7D]

    def test_encode_negative_64(self):
        r = run_ts("""
import { encodeLEB128 } from '/app/src/codec.ts';
console.log(JSON.stringify(Array.from(encodeLEB128(-64n))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0x40]

    def test_encode_negative_65(self):
        r = run_ts("""
import { encodeLEB128 } from '/app/src/codec.ts';
console.log(JSON.stringify(Array.from(encodeLEB128(-65n))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0xBF, 0x7F]

    def test_decode_roundtrip(self):
        r = run_ts("""
import { encodeLEB128, decodeLEB128 } from '/app/src/codec.ts';
const values = [0n, 1n, -1n, 63n, 64n, -64n, -65n, 127n, -128n, 8191n, -8192n];
const results = values.map(v => {
    const encoded = encodeLEB128(v);
    const [decoded] = decodeLEB128(encoded);
    return Number(decoded);
});
console.log(JSON.stringify(results));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0, 1, -1, 63, 64, -64, -65, 127, -128, 8191, -8192]


# ========== RLE Tests ==========

class TestRLE:
    def test_encode_spec_example(self):
        """Spec: [0,0,0,null,null,1,2,3] -> 0x03 0x00 0x00 0x02 0x7d 0x01 0x02 0x03"""
        r = run_ts("""
import { rleEncode, encodeULEB128 } from '/app/src/codec.ts';
const values: (bigint | null)[] = [0n, 0n, 0n, null, null, 1n, 2n, 3n];
const encoded = rleEncode(values, encodeULEB128);
console.log(JSON.stringify(Array.from(encoded)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0x03, 0x00, 0x00, 0x02, 0x7D, 0x01, 0x02, 0x03]

    def test_decode_spec_example(self):
        r = run_ts("""
import { rleDecode, decodeULEB128 } from '/app/src/codec.ts';
const data = new Uint8Array([0x03, 0x00, 0x00, 0x02, 0x7D, 0x01, 0x02, 0x03]);
const values = rleDecode(data, decodeULEB128);
console.log(JSON.stringify(values.map(v => v === null ? null : Number(v))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0, 0, 0, None, None, 1, 2, 3]

    def test_group_column_spec_example(self):
        """Spec: [0,1,2,2,2] -> 0x7e 0x00 0x01 0x03 0x02"""
        r = run_ts("""
import { rleEncode, encodeULEB128 } from '/app/src/codec.ts';
const values: (bigint | null)[] = [0n, 1n, 2n, 2n, 2n];
const encoded = rleEncode(values, encodeULEB128);
console.log(JSON.stringify(Array.from(encoded)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0x7E, 0x00, 0x01, 0x03, 0x02]

    def test_roundtrip(self):
        r = run_ts("""
import { rleEncode, rleDecode, encodeULEB128, decodeULEB128 } from '/app/src/codec.ts';
const values: (bigint | null)[] = [5n, 5n, 5n, null, 1n, 2n, 3n, 3n, null, null, 0n];
const encoded = rleEncode(values, encodeULEB128);
const decoded = rleDecode(encoded, decodeULEB128);
console.log(JSON.stringify(decoded.map(v => v === null ? null : Number(v))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [5, 5, 5, None, 1, 2, 3, 3, None, None, 0]

    def test_empty_input(self):
        r = run_ts("""
import { rleEncode, rleDecode, encodeULEB128, decodeULEB128 } from '/app/src/codec.ts';
const encoded = rleEncode([], encodeULEB128);
const decoded = rleDecode(encoded, decodeULEB128);
console.log(JSON.stringify({ enc: Array.from(encoded), dec: decoded }));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        result = json.loads(r.stdout.strip())
        assert result['enc'] == []
        assert result['dec'] == []

    def test_all_nulls(self):
        r = run_ts("""
import { rleEncode, rleDecode, encodeULEB128, decodeULEB128 } from '/app/src/codec.ts';
const values: (bigint | null)[] = [null, null, null, null];
const encoded = rleEncode(values, encodeULEB128);
const decoded = rleDecode(encoded, decodeULEB128);
console.log(JSON.stringify(decoded));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [None, None, None, None]

    def test_literal_run_decode(self):
        """Verify that rleDecode correctly handles negative-length literal runs."""
        r = run_ts("""
import { rleDecode, decodeULEB128 } from '/app/src/codec.ts';
// Manually construct: literal run of 3 values (7, 8, 9)
// LEB(-3) = 0x7D, uLEB(7) = 0x07, uLEB(8) = 0x08, uLEB(9) = 0x09
const data = new Uint8Array([0x7D, 0x07, 0x08, 0x09]);
const values = rleDecode(data, decodeULEB128);
console.log(JSON.stringify(values.map(v => v === null ? null : Number(v))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [7, 8, 9]


# ========== Delta Column Tests ==========

class TestDeltaColumn:
    def test_decode_spec_example(self):
        """Spec: bytes -> [3,4,5,6,9,7,8]"""
        r = run_ts("""
import { deltaDecode } from '/app/src/codec.ts';
const data = new Uint8Array([0x7f, 0x03, 0x03, 0x01, 0x7d, 0x03, 0x7e, 0x01]);
const values = deltaDecode(data);
console.log(JSON.stringify(values.map(v => Number(v))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [3, 4, 5, 6, 9, 7, 8]

    def test_encode_spec_example(self):
        """Spec: [3,4,5,6,9,7,8] -> specific bytes"""
        r = run_ts("""
import { deltaEncode } from '/app/src/codec.ts';
const values = [3n, 4n, 5n, 6n, 9n, 7n, 8n];
const encoded = deltaEncode(values);
console.log(JSON.stringify(Array.from(encoded)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0x7F, 0x03, 0x03, 0x01, 0x7D, 0x03, 0x7E, 0x01]

    def test_roundtrip(self):
        r = run_ts("""
import { deltaEncode, deltaDecode } from '/app/src/codec.ts';
const values = [1n, 5n, 10n, 100n, 50n, 51n, 52n];
const encoded = deltaEncode(values);
const decoded = deltaDecode(encoded);
console.log(JSON.stringify(decoded.map(v => Number(v))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [1, 5, 10, 100, 50, 51, 52]

    def test_single_value(self):
        r = run_ts("""
import { deltaEncode, deltaDecode } from '/app/src/codec.ts';
const values = [42n];
const encoded = deltaEncode(values);
const decoded = deltaDecode(encoded);
console.log(JSON.stringify(decoded.map(v => Number(v))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [42]

    def test_starts_from_zero(self):
        """The first delta must be the first value itself (starting from 0)."""
        r = run_ts("""
import { deltaEncode, decodeLEB128, rleDecode } from '/app/src/codec.ts';
const values = [7n];
const encoded = deltaEncode(values);
const deltas = rleDecode(encoded, decodeLEB128);
console.log(JSON.stringify(deltas.map(v => v === null ? null : Number(v))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [7]

    def test_decreasing_sequence(self):
        """Delta column must correctly handle decreasing values (negative deltas)."""
        r = run_ts("""
import { deltaEncode, deltaDecode } from '/app/src/codec.ts';
const values = [100n, 90n, 80n, 70n];
const encoded = deltaEncode(values);
const decoded = deltaDecode(encoded);
console.log(JSON.stringify(decoded.map(v => Number(v))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [100, 90, 80, 70]

    def test_empty_input(self):
        r = run_ts("""
import { deltaEncode, deltaDecode } from '/app/src/codec.ts';
const encoded = deltaEncode([]);
const decoded = deltaDecode(encoded);
console.log(JSON.stringify({ enc: Array.from(encoded), dec: decoded.map(v => Number(v)) }));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        result = json.loads(r.stdout.strip())
        assert result['enc'] == []
        assert result['dec'] == []


# ========== Boolean Column Tests ==========

class TestBooleanColumn:
    def test_encode_spec_example(self):
        """Spec: [true,true,false,false,false] -> [0x00, 0x02, 0x03]"""
        r = run_ts("""
import { booleanEncode } from '/app/src/codec.ts';
const values = [true, true, false, false, false];
const encoded = booleanEncode(values);
console.log(JSON.stringify(Array.from(encoded)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0x00, 0x02, 0x03]

    def test_decode_spec_example(self):
        """Spec: [0x00, 0x02, 0x03] -> [true,true,false,false,false]"""
        r = run_ts("""
import { booleanDecode } from '/app/src/codec.ts';
const data = new Uint8Array([0x00, 0x02, 0x03]);
const values = booleanDecode(data);
console.log(JSON.stringify(values));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [True, True, False, False, False]

    def test_roundtrip(self):
        r = run_ts("""
import { booleanEncode, booleanDecode } from '/app/src/codec.ts';
const values = [false, false, true, false, true, true, true];
const encoded = booleanEncode(values);
const decoded = booleanDecode(encoded);
console.log(JSON.stringify(decoded));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [False, False, True, False, True, True, True]

    def test_all_false(self):
        r = run_ts("""
import { booleanEncode, booleanDecode } from '/app/src/codec.ts';
const values = [false, false, false];
const encoded = booleanEncode(values);
const decoded = booleanDecode(encoded);
console.log(JSON.stringify({ encoded: Array.from(encoded), decoded }));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        result = json.loads(r.stdout.strip())
        assert result['encoded'] == [0x03]
        assert result['decoded'] == [False, False, False]

    def test_all_true(self):
        r = run_ts("""
import { booleanEncode, booleanDecode } from '/app/src/codec.ts';
const values = [true, true, true];
const encoded = booleanEncode(values);
const decoded = booleanDecode(encoded);
console.log(JSON.stringify({ encoded: Array.from(encoded), decoded }));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        result = json.loads(r.stdout.strip())
        assert result['encoded'] == [0x00, 0x03]
        assert result['decoded'] == [True, True, True]

    def test_single_false(self):
        """Encoding [false] must produce [0x01] (one false run), not [0x00, 0x01]."""
        r = run_ts("""
import { booleanEncode } from '/app/src/codec.ts';
const encoded = booleanEncode([false]);
console.log(JSON.stringify(Array.from(encoded)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0x01]


# ========== Column Specification Tests ==========

class TestColumnSpec:
    def test_decode_actor_column(self):
        """actor column: spec=1, ID=0, type=1"""
        r = run_ts("""
import { decodeColumnSpec } from '/app/src/codec.ts';
console.log(JSON.stringify(decodeColumnSpec(1)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == {"id": 0, "type": 1, "deflate": False}

    def test_decode_maxop_column(self):
        """maxOp column: spec=19, ID=1, type=3"""
        r = run_ts("""
import { decodeColumnSpec } from '/app/src/codec.ts';
console.log(JSON.stringify(decodeColumnSpec(19)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == {"id": 1, "type": 3, "deflate": False}

    def test_decode_message_column(self):
        """message column: spec=53, ID=3, type=5"""
        r = run_ts("""
import { decodeColumnSpec } from '/app/src/codec.ts';
console.log(JSON.stringify(decodeColumnSpec(53)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == {"id": 3, "type": 5, "deflate": False}

    def test_decode_deps_group_column(self):
        """deps group column: spec=64, ID=4, type=0"""
        r = run_ts("""
import { decodeColumnSpec } from '/app/src/codec.ts';
console.log(JSON.stringify(decodeColumnSpec(64)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == {"id": 4, "type": 0, "deflate": False}

    def test_decode_extra_metadata_column(self):
        """extra metadata column: spec=86, ID=5, type=6"""
        r = run_ts("""
import { decodeColumnSpec } from '/app/src/codec.ts';
console.log(JSON.stringify(decodeColumnSpec(86)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == {"id": 5, "type": 6, "deflate": False}

    def test_decode_with_deflate(self):
        """Column spec with deflate bit set: spec=94 = (5 << 4) | 0x08 | 6 = 94"""
        r = run_ts("""
import { decodeColumnSpec } from '/app/src/codec.ts';
console.log(JSON.stringify(decodeColumnSpec(94)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == {"id": 5, "type": 6, "deflate": True}

    def test_encode_decode_roundtrip(self):
        r = run_ts("""
import { encodeColumnSpec, decodeColumnSpec } from '/app/src/codec.ts';
const specs = [
    { id: 0, type: 1, deflate: false },
    { id: 1, type: 3, deflate: false },
    { id: 4, type: 0, deflate: false },
    { id: 5, type: 6, deflate: true },
    { id: 3, type: 5, deflate: false },
];
const results = specs.map(s => {
    const encoded = encodeColumnSpec(s.id, s.type, s.deflate);
    return decodeColumnSpec(encoded);
});
console.log(JSON.stringify(results));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        results = json.loads(r.stdout.strip())
        assert results[0] == {"id": 0, "type": 1, "deflate": False}
        assert results[1] == {"id": 1, "type": 3, "deflate": False}
        assert results[2] == {"id": 4, "type": 0, "deflate": False}
        assert results[3] == {"id": 5, "type": 6, "deflate": True}
        assert results[4] == {"id": 3, "type": 5, "deflate": False}

    def test_encode_known_specs(self):
        """Verify that encoding produces the spec-defined specification values."""
        r = run_ts("""
import { encodeColumnSpec } from '/app/src/codec.ts';
const results = [
    encodeColumnSpec(0, 1, false),  // actor -> 1
    encodeColumnSpec(0, 3, false),  // seq -> 3
    encodeColumnSpec(1, 3, false),  // maxOp -> 19
    encodeColumnSpec(2, 3, false),  // time -> 35
    encodeColumnSpec(3, 5, false),  // message -> 53
    encodeColumnSpec(4, 0, false),  // deps group -> 64
    encodeColumnSpec(4, 3, false),  // deps index -> 67
    encodeColumnSpec(5, 6, false),  // extra meta -> 86
    encodeColumnSpec(5, 7, false),  // extra data -> 87
];
console.log(JSON.stringify(results));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [1, 3, 19, 35, 53, 64, 67, 86, 87]


# ========== Value Metadata Tests ==========

class TestValueMetadata:
    def test_encode_utf8_string(self):
        """UTF-8 string of length 5: type=6, length=5 -> (5 << 4) | 6 = 86"""
        r = run_ts("""
import { encodeValueMetadata } from '/app/src/codec.ts';
console.log(Number(encodeValueMetadata(6, 5)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert int(r.stdout.strip()) == 86

    def test_decode_utf8_string(self):
        """Decode 86 -> type=6, length=5"""
        r = run_ts("""
import { decodeValueMetadata } from '/app/src/codec.ts';
console.log(JSON.stringify(decodeValueMetadata(86n)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == {"type": 6, "length": 5}

    def test_encode_counter(self):
        """Counter of length 2: type=8, length=2 -> (2 << 4) | 8 = 40"""
        r = run_ts("""
import { encodeValueMetadata } from '/app/src/codec.ts';
console.log(Number(encodeValueMetadata(8, 2)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert int(r.stdout.strip()) == 40

    def test_decode_counter(self):
        """Decode 40 -> type=8, length=2"""
        r = run_ts("""
import { decodeValueMetadata } from '/app/src/codec.ts';
console.log(JSON.stringify(decodeValueMetadata(40n)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == {"type": 8, "length": 2}

    def test_encode_null(self):
        """Null: type=0, length=0 -> 0"""
        r = run_ts("""
import { encodeValueMetadata } from '/app/src/codec.ts';
console.log(Number(encodeValueMetadata(0, 0)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert int(r.stdout.strip()) == 0

    def test_encode_true(self):
        """True: type=2, length=0 -> (0 << 4) | 2 = 2"""
        r = run_ts("""
import { encodeValueMetadata } from '/app/src/codec.ts';
console.log(Number(encodeValueMetadata(2, 0)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert int(r.stdout.strip()) == 2

    def test_encode_float64(self):
        """Float64: type=5, length=8 -> (8 << 4) | 5 = 133"""
        r = run_ts("""
import { encodeValueMetadata } from '/app/src/codec.ts';
console.log(Number(encodeValueMetadata(5, 8)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert int(r.stdout.strip()) == 133

    def test_roundtrip(self):
        r = run_ts("""
import { encodeValueMetadata, decodeValueMetadata } from '/app/src/codec.ts';
const cases = [
    { type: 0, length: 0 },
    { type: 2, length: 0 },
    { type: 3, length: 3 },
    { type: 5, length: 8 },
    { type: 6, length: 12 },
    { type: 8, length: 1 },
    { type: 9, length: 5 },
];
const results = cases.map(c => {
    const encoded = encodeValueMetadata(c.type, c.length);
    return decodeValueMetadata(encoded);
});
console.log(JSON.stringify(results));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        results = json.loads(r.stdout.strip())
        expected = [
            {"type": 0, "length": 0},
            {"type": 2, "length": 0},
            {"type": 3, "length": 3},
            {"type": 5, "length": 8},
            {"type": 6, "length": 12},
            {"type": 8, "length": 1},
            {"type": 9, "length": 5},
        ]
        assert results == expected


# ========== Chunk Tests ==========

class TestChunk:
    def test_empty_document_bytes(self):
        """Empty document must match the 14 bytes from the spec."""
        r = run_ts("""
import { createEmptyDocument } from '/app/src/codec.ts';
const doc = createEmptyDocument();
console.log(JSON.stringify(Array.from(doc)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        expected = [0x85, 0x6F, 0x4A, 0x83, 0xB8, 0x1A, 0x95, 0x44,
                    0x00, 0x04, 0x00, 0x00, 0x00, 0x00]
        assert json.loads(r.stdout.strip()) == expected

    def test_checksum_computation(self):
        """Checksum for empty document chunk content."""
        r = run_ts("""
import { computeChecksum, encodeULEB128 } from '/app/src/codec.ts';
const chunkType = 0x00;
const contents = new Uint8Array([0x00, 0x00, 0x00, 0x00]);
const lengthBytes = encodeULEB128(BigInt(contents.length));
const checksum = computeChecksum(chunkType, lengthBytes, contents);
console.log(JSON.stringify(Array.from(checksum)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0xB8, 0x1A, 0x95, 0x44]

    def test_parse_valid_empty_document(self):
        """Parsing the spec's empty document must report valid=true."""
        r = run_ts("""
import { parseChunkHeader } from '/app/src/codec.ts';
const data = new Uint8Array([
    0x85, 0x6f, 0x4a, 0x83,
    0xb8, 0x1a, 0x95, 0x44,
    0x00, 0x04,
    0x00, 0x00, 0x00, 0x00
]);
const header = parseChunkHeader(data);
console.log(JSON.stringify({
    chunkType: header.chunkType,
    chunkLength: Number(header.chunkLength),
    valid: header.valid
}));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        result = json.loads(r.stdout.strip())
        assert result == {"chunkType": 0, "chunkLength": 4, "valid": True}

    def test_construct_parse_roundtrip(self):
        """Constructing a chunk and parsing it back must produce valid=true."""
        r = run_ts("""
import { constructChunk, parseChunkHeader } from '/app/src/codec.ts';
const contents = new Uint8Array([0x01, 0x02, 0x03, 0x04, 0x05]);
const chunk = constructChunk(0x01, contents);
const header = parseChunkHeader(chunk);
console.log(JSON.stringify({
    chunkType: header.chunkType,
    chunkLength: Number(header.chunkLength),
    valid: header.valid
}));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        result = json.loads(r.stdout.strip())
        assert result["chunkType"] == 1
        assert result["chunkLength"] == 5
        assert result["valid"] is True

    def test_magic_bytes(self):
        """MAGIC_BYTES must be [0x85, 0x6f, 0x4a, 0x83]."""
        r = run_ts("""
import { MAGIC_BYTES } from '/app/src/codec.ts';
console.log(JSON.stringify(Array.from(MAGIC_BYTES)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0x85, 0x6F, 0x4A, 0x83]

    def test_parse_corrupted_checksum(self):
        """Parsing data with a wrong checksum must report valid=false."""
        r = run_ts("""
import { parseChunkHeader } from '/app/src/codec.ts';
const data = new Uint8Array([
    0x85, 0x6f, 0x4a, 0x83,
    0xFF, 0xFF, 0xFF, 0xFF,
    0x00, 0x04,
    0x00, 0x00, 0x00, 0x00
]);
const header = parseChunkHeader(data);
console.log(JSON.stringify({ valid: header.valid }));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        result = json.loads(r.stdout.strip())
        assert result["valid"] is False

    def test_construct_larger_chunk(self):
        """Construct and parse a chunk with contents > 127 bytes (multi-byte uLEB length)."""
        r = run_ts("""
import { constructChunk, parseChunkHeader } from '/app/src/codec.ts';
const contents = new Uint8Array(200);
for (let i = 0; i < 200; i++) contents[i] = i & 0xFF;
const chunk = constructChunk(0x02, contents);
const header = parseChunkHeader(chunk);
console.log(JSON.stringify({
    chunkType: header.chunkType,
    chunkLength: Number(header.chunkLength),
    valid: header.valid,
    totalSize: chunk.length
}));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        result = json.loads(r.stdout.strip())
        assert result["chunkType"] == 2
        assert result["chunkLength"] == 200
        assert result["valid"] is True
        # Header: 4 magic + 4 checksum + 1 type + 2 length (200 needs 2 uLEB bytes) = 11
        assert result["totalSize"] == 211


# ========== String Column Tests ==========

class TestStringColumn:
    def test_encode_spec_example(self):
        """Spec: ["a","",null,"boo","boo"] -> specific bytes"""
        r = run_ts("""
import { stringEncode } from '/app/src/codec.ts';
const values: (string | null)[] = ["a", "", null, "boo", "boo"];
const encoded = stringEncode(values);
console.log(JSON.stringify(Array.from(encoded)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        expected = [0x7E, 0x01, 0x61, 0x00, 0x00, 0x01, 0x02, 0x03, 0x62, 0x6F, 0x6F]
        assert json.loads(r.stdout.strip()) == expected

    def test_all_same(self):
        """Compressed run of identical strings."""
        r = run_ts("""
import { stringEncode } from '/app/src/codec.ts';
const values: (string | null)[] = ["hi", "hi", "hi"];
const encoded = stringEncode(values);
console.log(JSON.stringify(Array.from(encoded)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0x03, 0x02, 0x68, 0x69]

    def test_decode_spec_example(self):
        """Decode the spec example bytes back to strings."""
        r = run_ts("""
import { stringDecode } from '/app/src/codec.ts';
const data = new Uint8Array([0x7E, 0x01, 0x61, 0x00, 0x00, 0x01, 0x02, 0x03, 0x62, 0x6F, 0x6F]);
const values = stringDecode(data);
console.log(JSON.stringify(values));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == ["a", "", None, "boo", "boo"]

    def test_roundtrip(self):
        r = run_ts("""
import { stringEncode, stringDecode } from '/app/src/codec.ts';
const values: (string | null)[] = ["hello", null, null, "world", "world", "", "x"];
const encoded = stringEncode(values);
const decoded = stringDecode(encoded);
console.log(JSON.stringify(decoded));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == ["hello", None, None, "world", "world", "", "x"]

    def test_utf8_multibyte(self):
        """Multi-byte UTF-8 characters must round-trip correctly."""
        r = run_ts("""
import { stringEncode, stringDecode } from '/app/src/codec.ts';
const values: (string | null)[] = ["\\u00e9", "\\u00e9", null, "\\u{1f600}"];
const encoded = stringEncode(values);
const decoded = stringDecode(encoded);
console.log(JSON.stringify(decoded));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == ["\u00e9", "\u00e9", None, "\U0001f600"]

    def test_all_nulls(self):
        r = run_ts("""
import { stringEncode, stringDecode } from '/app/src/codec.ts';
const values: (string | null)[] = [null, null, null];
const encoded = stringEncode(values);
const decoded = stringDecode(encoded);
console.log(JSON.stringify(decoded));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [None, None, None]

    def test_empty_input(self):
        r = run_ts("""
import { stringEncode, stringDecode } from '/app/src/codec.ts';
const encoded = stringEncode([]);
const decoded = stringDecode(encoded);
console.log(JSON.stringify({ enc: Array.from(encoded), dec: decoded }));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        result = json.loads(r.stdout.strip())
        assert result['enc'] == []
        assert result['dec'] == []


# ========== Integration Tests ==========

class TestIntegration:
    def test_delta_encode_first_delta_value(self):
        """
        Verify that the first delta in the encoded output is the value itself
        (since the sequence starts from zero).
        """
        r = run_ts("""
import { deltaEncode, rleDecode, decodeLEB128 } from '/app/src/codec.ts';
const encoded = deltaEncode([10n, 20n, 30n]);
const deltas = rleDecode(encoded, decodeLEB128);
console.log(JSON.stringify(deltas.map(v => v === null ? null : Number(v))));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [10, 10, 10]

    def test_boolean_initial_false_encoding(self):
        """
        Verify that encoding [false] produces [0x01] (one false value),
        not [0x00, 0x01] (zero trues, then one false).
        """
        r = run_ts("""
import { booleanEncode } from '/app/src/codec.ts';
const encoded = booleanEncode([false]);
console.log(JSON.stringify(Array.from(encoded)));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        assert json.loads(r.stdout.strip()) == [0x01]

    def test_column_spec_consistency(self):
        """
        All nine standard change column specs must decode to the correct
        ID and type as defined in the specification.
        """
        r = run_ts("""
import { decodeColumnSpec } from '/app/src/codec.ts';
const specTable = [
    { spec: 1,  expectedId: 0, expectedType: 1 },
    { spec: 3,  expectedId: 0, expectedType: 3 },
    { spec: 19, expectedId: 1, expectedType: 3 },
    { spec: 35, expectedId: 2, expectedType: 3 },
    { spec: 53, expectedId: 3, expectedType: 5 },
    { spec: 64, expectedId: 4, expectedType: 0 },
    { spec: 67, expectedId: 4, expectedType: 3 },
    { spec: 86, expectedId: 5, expectedType: 6 },
    { spec: 87, expectedId: 5, expectedType: 7 },
];
const results = specTable.map(({ spec, expectedId, expectedType }) => {
    const decoded = decodeColumnSpec(spec);
    return {
        spec,
        idOk: decoded.id === expectedId,
        typeOk: decoded.type === expectedType,
        decoded
    };
});
const allOk = results.every(r => r.idOk && r.typeOk);
console.log(JSON.stringify({ allOk, results }));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        result = json.loads(r.stdout.strip())
        assert result["allOk"] is True, f"Column spec failures: {result['results']}"

    def test_full_codec_roundtrip(self):
        """
        End-to-end: create an empty document, parse it, verify
        the chunk is valid and has the correct structure.
        """
        r = run_ts("""
import { createEmptyDocument, parseChunkHeader } from '/app/src/codec.ts';
const doc = createEmptyDocument();
const header = parseChunkHeader(doc);
const contents = doc.slice(header.headerSize, header.headerSize + Number(header.chunkLength));
console.log(JSON.stringify({
    valid: header.valid,
    chunkType: header.chunkType,
    chunkLength: Number(header.chunkLength),
    contents: Array.from(contents)
}));
""")
        assert r.returncode == 0, f"TS error: {r.stderr}"
        result = json.loads(r.stdout.strip())
        assert result["valid"] is True
        assert result["chunkType"] == 0
        assert result["chunkLength"] == 4
        assert result["contents"] == [0, 0, 0, 0]
