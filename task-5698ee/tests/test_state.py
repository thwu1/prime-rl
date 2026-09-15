
import json
import subprocess
import pytest

from Crypto.Hash import keccak as keccak_mod


def keccak256(data: bytes) -> bytes:
    h = keccak_mod.new(digest_bits=256)
    h.update(data)
    return h.digest()


# ============================================================
# Python reference implementation of EIP-712 typed data hashing
# ============================================================

def find_type_dependencies(primary_type, types, results=None):
    """Recursively collect all struct type dependencies."""
    if results is None:
        results = set()
    base = primary_type
    while base.endswith(']'):
        base = base[:base.rindex('[')]
    if base in results or base not in types:
        return results
    results.add(base)
    for field in types[base]:
        find_type_dependencies(field['type'], types, results)
    return results


def encode_type(primary_type, types):
    """Encode a struct type as its canonical string representation."""
    deps = find_type_dependencies(primary_type, types)
    deps.discard(primary_type)
    ordered = [primary_type] + sorted(deps)
    result = ''
    for type_name in ordered:
        fields = types[type_name]
        parts = ','.join(f"{f['type']} {f['name']}" for f in fields)
        result += f'{type_name}({parts})'
    return result


def type_hash(primary_type, types):
    """keccak256 of the canonical type string."""
    return keccak256(encode_type(primary_type, types).encode('utf-8'))


def _to_int(value):
    """Parse a value to int, handling hex strings."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        v = value.strip()
        if v.startswith('0x') or v.startswith('0X'):
            return int(v, 16)
        return int(v)
    return int(value)


def encode_value(field_type, value, types):
    """Encode a single field value to 32 bytes per EIP-712."""
    if field_type in types:
        if value is None:
            return b'\x00' * 32
        return hash_struct(field_type, value, types)

    if field_type.endswith(']'):
        inner = field_type[:field_type.rindex('[')]
        parts = b''.join(encode_value(inner, item, types) for item in value)
        return keccak256(parts)

    if field_type == 'string':
        s = '' if value is None else str(value)
        return keccak256(s.encode('utf-8'))

    if field_type == 'bytes':
        if isinstance(value, str):
            if value.startswith('0x') or value.startswith('0X'):
                data = bytes.fromhex(value[2:])
            else:
                data = value.encode('utf-8')
        elif isinstance(value, (bytes, bytearray)):
            data = bytes(value)
        else:
            data = bytes(value)
        return keccak256(data)

    if field_type == 'bool':
        return (1 if value else 0).to_bytes(32, 'big')

    if field_type == 'address':
        if isinstance(value, str):
            h = value[2:] if value.startswith('0x') else value
        else:
            h = hex(value)[2:]
        h = h.lower().zfill(40)
        return b'\x00' * 12 + bytes.fromhex(h)

    if field_type.startswith('uint'):
        n = _to_int(value)
        return n.to_bytes(32, 'big', signed=False)

    if field_type.startswith('int'):
        n = _to_int(value)
        if n < 0:
            n = (1 << 256) + n
        return n.to_bytes(32, 'big', signed=False)

    if field_type.startswith('bytes'):
        size = int(field_type[5:])
        result_buf = bytearray(32)
        if isinstance(value, str) and value.startswith('0x'):
            raw = bytes.fromhex(value[2:])
        elif isinstance(value, int):
            raw = value.to_bytes(size, 'big')
        elif isinstance(value, str):
            raw = value.encode('utf-8')
        else:
            raw = bytes(value)
        for i in range(min(len(raw), size)):
            result_buf[i] = raw[i]
        return bytes(result_buf)

    raise ValueError(f'Unsupported EIP-712 type: {field_type}')


def encode_data(primary_type, data, types):
    """Encode all struct fields, prefixed by typeHash."""
    parts = [type_hash(primary_type, types)]
    for field in types[primary_type]:
        val = data.get(field['name'])
        parts.append(encode_value(field['type'], val, types))
    return b''.join(parts)


def hash_struct(primary_type, data, types):
    """keccak256(encodeData(...))"""
    return keccak256(encode_data(primary_type, data, types))


def compute_sign_hash(typed_data):
    """Compute the final EIP-712 signing hash."""
    types = typed_data['types']
    primary_type = typed_data['primaryType']
    domain_sep = hash_struct('EIP712Domain', typed_data['domain'], types)
    msg_hash = hash_struct(primary_type, typed_data['message'], types)
    return '0x' + keccak256(b'\x19\x01' + domain_sep + msg_hash).hex()


def compute_expected_json(typed_data):
    """Compute the expected --json output using the Python reference."""
    types = typed_data['types']
    primary = typed_data['primaryType']
    domain_sep = hash_struct('EIP712Domain', typed_data['domain'], types)
    msg_hash = hash_struct(primary, typed_data['message'], types)
    sign_hash = keccak256(b'\x19\x01' + domain_sep + msg_hash)

    deps = find_type_dependencies(primary, types)
    deps.discard(primary)
    deps.discard('EIP712Domain')

    ref_types = {}
    for dep in sorted(deps):
        ref_types[dep] = {
            'typeHash': '0x' + type_hash(dep, types).hex(),
            'encodeType': encode_type(dep, types),
        }

    return {
        'signingHash': '0x' + sign_hash.hex(),
        'domainSeparator': '0x' + domain_sep.hex(),
        'messageHash': '0x' + msg_hash.hex(),
        'primaryType': primary,
        'encodeType': encode_type(primary, types),
        'typeHash': '0x' + type_hash(primary, types).hex(),
        'referencedTypes': ref_types,
    }


# ============================================================
# Test helpers
# ============================================================

def run_ts(typed_data, extra_args=None):
    """Run the TypeScript EIP-712 implementation and return stdout."""
    cmd = ['npx', 'tsx', 'eip712.ts']
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(
        cmd,
        input=json.dumps(typed_data),
        capture_output=True,
        text=True,
        cwd='/app',
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f'TypeScript execution failed (exit {result.returncode}):\n'
            f'stdout: {result.stdout}\nstderr: {result.stderr}'
        )
    return result.stdout.strip()


def run_ts_raw(typed_data, extra_args=None):
    """Run the TypeScript EIP-712 implementation and return CompletedProcess."""
    cmd = ['npx', 'tsx', 'eip712.ts']
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(
        cmd,
        input=json.dumps(typed_data),
        capture_output=True,
        text=True,
        cwd='/app',
        timeout=30,
    )


# ============================================================
# Test data
# ============================================================

CANONICAL_MAIL = {
    "types": {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
            {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"},
            {"name": "verifyingContract", "type": "address"},
        ],
        "Person": [
            {"name": "name", "type": "string"},
            {"name": "wallet", "type": "address"},
        ],
        "Mail": [
            {"name": "from", "type": "Person"},
            {"name": "to", "type": "Person"},
            {"name": "contents", "type": "string"},
        ],
    },
    "primaryType": "Mail",
    "domain": {
        "name": "Ether Mail",
        "version": "1",
        "chainId": 1,
        "verifyingContract": "0xCcCCccccCCCCcCCCCCCcCcCccCcCCCcCcccccccC",
    },
    "message": {
        "from": {
            "name": "Cow",
            "wallet": "0xCD2a3d9F938E13CD947Ec05AbC7FE734Df8DD826",
        },
        "to": {
            "name": "Bob",
            "wallet": "0xbBbBBBBbbBBBbbbBbbBbbbbBBbBbbbbBbBbbBBbB",
        },
        "contents": "Hello, Bob!",
    },
}

TYPE_ORDERING_DATA = {
    "types": {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
            {"name": "chainId", "type": "uint256"},
        ],
        "Recipient": [
            {"name": "wallet", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "Transfer": [
            {"name": "recipient", "type": "Recipient"},
            {"name": "nonce", "type": "uint256"},
        ],
    },
    "primaryType": "Transfer",
    "domain": {"name": "Token", "chainId": 1},
    "message": {
        "recipient": {
            "wallet": "0xbBbBBBBbbBBBbbbBbbBbbbbBBbBbbbbBbBbbBBbB",
            "amount": "1000",
        },
        "nonce": "42",
    },
}

ARRAY_DEPS_DATA = {
    "types": {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
        ],
        "Item": [
            {"name": "id", "type": "uint256"},
            {"name": "price", "type": "uint256"},
        ],
        "Order": [
            {"name": "items", "type": "Item[]"},
            {"name": "buyer", "type": "address"},
        ],
    },
    "primaryType": "Order",
    "domain": {"name": "Market"},
    "message": {
        "items": [
            {"id": "1", "price": "100"},
            {"id": "2", "price": "200"},
        ],
        "buyer": "0xCD2a3d9F938E13CD947Ec05AbC7FE734Df8DD826",
    },
}

SIGNED_INT_DATA = {
    "types": {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
        ],
        "SignedData": [
            {"name": "value", "type": "int256"},
            {"name": "flag", "type": "bool"},
        ],
    },
    "primaryType": "SignedData",
    "domain": {"name": "Test"},
    "message": {
        "value": "-1",
        "flag": True,
    },
}

DYNAMIC_BYTES_DATA = {
    "types": {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
        ],
        "Payload": [
            {"name": "data", "type": "bytes"},
            {"name": "nonce", "type": "uint256"},
        ],
    },
    "primaryType": "Payload",
    "domain": {"name": "Test"},
    "message": {
        "data": "0xdeadbeef01020304",
        "nonce": "1",
    },
}

COMPLEX_NESTED_DATA = {
    "types": {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
        ],
        "Coord": [
            {"name": "x", "type": "int256"},
            {"name": "y", "type": "int256"},
        ],
        "Vertex": [
            {"name": "pos", "type": "Coord"},
            {"name": "label", "type": "string"},
        ],
        "Edge": [
            {"name": "src", "type": "Vertex"},
            {"name": "dst", "type": "Vertex"},
            {"name": "weight", "type": "uint256"},
        ],
        "Graph": [
            {"name": "edges", "type": "Edge[]"},
            {"name": "metadata", "type": "bytes"},
            {"name": "version", "type": "int32"},
        ],
    },
    "primaryType": "Graph",
    "domain": {"name": "GraphDB"},
    "message": {
        "edges": [
            {
                "src": {"pos": {"x": "-10", "y": "20"}, "label": "A"},
                "dst": {"pos": {"x": "30", "y": "-40"}, "label": "B"},
                "weight": "100",
            }
        ],
        "metadata": "0xabcdef",
        "version": "-1",
    },
}

MULTI_ARRAY_SWAP_DATA = {
    "types": {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
        ],
        "Asset": [
            {"name": "token", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "Swap": [
            {"name": "give", "type": "Asset[]"},
            {"name": "receive", "type": "Asset[]"},
            {"name": "deadline", "type": "uint256"},
        ],
    },
    "primaryType": "Swap",
    "domain": {"name": "DEX"},
    "message": {
        "give": [
            {"token": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "amount": "1000000"},
            {"token": "0xdAC17F958D2ee523a2206206994597C13D831ec7", "amount": "2000000"},
        ],
        "receive": [
            {"token": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "amount": "500000000000000000"},
        ],
        "deadline": "1700000000",
    },
}

BYTES32_PERMIT_DATA = {
    "types": {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
        ],
        "Permit": [
            {"name": "txHash", "type": "bytes32"},
            {"name": "deadline", "type": "uint256"},
            {"name": "allowed", "type": "bool"},
        ],
    },
    "primaryType": "Permit",
    "domain": {"name": "Bridge"},
    "message": {
        "txHash": "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        "deadline": "115792089237316195423570985008687907853269984665640564039457584007913129639935",
        "allowed": True,
    },
}


# ============================================================
# Tests: verify the Python reference against canonical values
# ============================================================

class TestReference:
    """Validate the Python reference implementation against known EIP-712 vectors."""

    def test_encode_type_mail(self):
        et = encode_type('Mail', CANONICAL_MAIL['types'])
        assert et == (
            'Mail(Person from,Person to,string contents)'
            'Person(string name,address wallet)'
        )

    def test_type_hash_mail(self):
        th = type_hash('Mail', CANONICAL_MAIL['types'])
        assert th.hex() == 'a0cedeb2dc280ba39b857546d74f5549c3a1d7bdc2dd96bf881f76108e23dac2'

    def test_struct_hash_message(self):
        sh = hash_struct('Mail', CANONICAL_MAIL['message'], CANONICAL_MAIL['types'])
        assert sh.hex() == 'c52c0ee5d84264471806290a3f2c4cecfc5490626bf912d01f240d7a274b371e'

    def test_struct_hash_domain(self):
        sh = hash_struct(
            'EIP712Domain', CANONICAL_MAIL['domain'], CANONICAL_MAIL['types']
        )
        assert sh.hex() == 'f2cee375fa42b42143804025fc449deafd50cc031ca257e0b194a650a912090f'

    def test_sign_hash(self):
        result = compute_sign_hash(CANONICAL_MAIL)
        assert result == '0xbe609aee343fb3c4b28e1df9e632fca64fcfaede20f02e86244efddf30957bd2'


# ============================================================
# Tests: basic signing hash mode
# ============================================================

class TestBasicMode:
    """Compare the TypeScript EIP-712 implementation output against the reference."""

    def test_canonical_mail(self):
        expected = compute_sign_hash(CANONICAL_MAIL)
        actual = run_ts(CANONICAL_MAIL)
        assert actual == expected, (
            f'Canonical mail mismatch.\n  Expected: {expected}\n  Got:      {actual}'
        )

    def test_type_ordering(self):
        expected = compute_sign_hash(TYPE_ORDERING_DATA)
        actual = run_ts(TYPE_ORDERING_DATA)
        assert actual == expected, (
            f'Type ordering mismatch.\n  Expected: {expected}\n  Got:      {actual}'
        )

    def test_array_dependencies(self):
        expected = compute_sign_hash(ARRAY_DEPS_DATA)
        actual = run_ts(ARRAY_DEPS_DATA)
        assert actual == expected, (
            f'Array dependency mismatch.\n  Expected: {expected}\n  Got:      {actual}'
        )

    def test_signed_integers(self):
        expected = compute_sign_hash(SIGNED_INT_DATA)
        actual = run_ts(SIGNED_INT_DATA)
        assert actual == expected, (
            f'Signed integer mismatch.\n  Expected: {expected}\n  Got:      {actual}'
        )

    def test_dynamic_bytes(self):
        expected = compute_sign_hash(DYNAMIC_BYTES_DATA)
        actual = run_ts(DYNAMIC_BYTES_DATA)
        assert actual == expected, (
            f'Dynamic bytes mismatch.\n  Expected: {expected}\n  Got:      {actual}'
        )

    def test_complex_nested(self):
        expected = compute_sign_hash(COMPLEX_NESTED_DATA)
        actual = run_ts(COMPLEX_NESTED_DATA)
        assert actual == expected, (
            f'Complex nested mismatch.\n  Expected: {expected}\n  Got:      {actual}'
        )

    def test_multi_array_swap(self):
        expected = compute_sign_hash(MULTI_ARRAY_SWAP_DATA)
        actual = run_ts(MULTI_ARRAY_SWAP_DATA)
        assert actual == expected, (
            f'Multi-array swap mismatch.\n  Expected: {expected}\n  Got:      {actual}'
        )

    def test_bytes32_permit(self):
        expected = compute_sign_hash(BYTES32_PERMIT_DATA)
        actual = run_ts(BYTES32_PERMIT_DATA)
        assert actual == expected, (
            f'Bytes32 permit mismatch.\n  Expected: {expected}\n  Got:      {actual}'
        )


# ============================================================
# Tests: --json output mode
# ============================================================

class TestJsonMode:
    """Verify --json mode outputs correct structured data with intermediate hashes."""

    def test_json_canonical_mail(self):
        expected = compute_expected_json(CANONICAL_MAIL)
        output = json.loads(run_ts(CANONICAL_MAIL, ['--json']))
        assert output == expected, (
            f'JSON output mismatch for canonical mail.\n'
            f'  Expected: {json.dumps(expected, indent=2)}\n'
            f'  Got:      {json.dumps(output, indent=2)}'
        )

    def test_json_complex_nested(self):
        expected = compute_expected_json(COMPLEX_NESTED_DATA)
        output = json.loads(run_ts(COMPLEX_NESTED_DATA, ['--json']))
        assert set(output['referencedTypes'].keys()) == {'Coord', 'Edge', 'Vertex'}, (
            f'Expected referenced types Coord, Edge, Vertex; got {list(output["referencedTypes"].keys())}'
        )
        assert output == expected

    def test_json_no_referenced_types(self):
        expected = compute_expected_json(SIGNED_INT_DATA)
        output = json.loads(run_ts(SIGNED_INT_DATA, ['--json']))
        assert output['referencedTypes'] == {}, (
            f'Expected empty referencedTypes; got {output["referencedTypes"]}'
        )
        assert output == expected

    def test_json_multi_array_swap(self):
        expected = compute_expected_json(MULTI_ARRAY_SWAP_DATA)
        output = json.loads(run_ts(MULTI_ARRAY_SWAP_DATA, ['--json']))
        assert 'Asset' in output['referencedTypes'], (
            'Expected Asset in referencedTypes'
        )
        assert output == expected


# ============================================================
# Tests: --verify mode
# ============================================================

class TestVerifyMode:
    """Verify --verify mode matches exit codes and output."""

    def test_verify_match(self):
        expected = compute_sign_hash(CANONICAL_MAIL)
        result = run_ts_raw(CANONICAL_MAIL, ['--verify', expected])
        assert result.returncode == 0, (
            f'Expected exit 0 for matching hash, got {result.returncode}\n'
            f'stderr: {result.stderr}'
        )
        assert result.stdout.strip() == expected

    def test_verify_mismatch(self):
        wrong = '0x' + '00' * 32
        result = run_ts_raw(CANONICAL_MAIL, ['--verify', wrong])
        assert result.returncode == 1, (
            f'Expected exit 1 for mismatching hash, got {result.returncode}\n'
            f'stderr: {result.stderr}'
        )
        expected = compute_sign_hash(CANONICAL_MAIL)
        assert result.stdout.strip() == expected

    def test_verify_case_insensitive(self):
        expected = compute_sign_hash(CANONICAL_MAIL)
        upper = expected[:2] + expected[2:].upper()
        result = run_ts_raw(CANONICAL_MAIL, ['--verify', upper])
        assert result.returncode == 0, (
            f'Expected exit 0 for case-insensitive match, got {result.returncode}\n'
            f'stderr: {result.stderr}'
        )
