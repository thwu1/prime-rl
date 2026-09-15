"""
Tests for the EIP-712 TypedData hashing CLI tool.

Verifies the TypeScript implementation at /app/src/eip712.ts against
canonical test vectors and a Python reference implementation.
"""


import json
import subprocess

from Crypto.Hash import keccak as keccak_module


# ──────────────────────────────────────────────────────────────────────
# Python reference implementation (correct EIP-712)
# ──────────────────────────────────────────────────────────────────────

def keccak256(data: bytes) -> bytes:
    k = keccak_module.new(digest_bits=256)
    k.update(data)
    return k.digest()


def _find_deps(primary: str, types: dict, results: set = None) -> set:
    if results is None:
        results = set()
    base = primary.split("[")[0]
    if base in results or base not in types:
        return results
    results.add(base)
    for f in types[base]:
        _find_deps(f["type"], types, results)
    return results


def ref_encode_type(primary: str, types: dict) -> str:
    deps = _find_deps(primary, types)
    deps.discard(primary)
    order = [primary] + sorted(deps)
    return "".join(
        f"{t}({','.join(f['type'] + ' ' + f['name'] for f in types[t])})"
        for t in order
    )


def ref_encode_value(typ: str, val, types: dict) -> bytes:
    base = typ.split("[")[0]

    # Array types
    if typ.endswith("]"):
        elem = typ[: typ.rindex("[")]
        items = val if val is not None else []
        enc = b"".join(ref_encode_value(elem, item, types) for item in items)
        return keccak256(enc)

    # Struct types — handle null for recursive type termination
    if base in types:
        if val is None:
            return b'\x00' * 32
        return _ref_hash_struct(typ, val, types)

    # string
    if typ == "string":
        s = val if isinstance(val, str) else str(val) if val is not None else ""
        return keccak256(s.encode("utf-8"))

    # bytes (dynamic)
    if typ == "bytes":
        if isinstance(val, str) and val.startswith("0x"):
            data = bytes.fromhex(val[2:])
        elif isinstance(val, str):
            data = val.encode("utf-8")
        else:
            data = bytes(val)
        return keccak256(data)

    # address
    if typ == "address":
        addr = val.lower().replace("0x", "").zfill(40)
        return b"\x00" * 12 + bytes.fromhex(addr)

    # bool
    if typ == "bool":
        return (1 if val else 0).to_bytes(32, "big")

    # uintN
    if typ.startswith("uint"):
        return int(val).to_bytes(32, "big")

    # intN (signed)
    if typ.startswith("int"):
        v = int(val)
        if v < 0:
            v = (1 << 256) + v
        return v.to_bytes(32, "big")

    # bytesN (fixed)
    if typ.startswith("bytes"):
        size = int(typ[5:])
        if isinstance(val, str) and val.startswith("0x"):
            data = bytes.fromhex(val[2:])
        elif isinstance(val, bytes):
            data = val
        else:
            data = bytes()
        # right-pad to 32 bytes
        return (data[:size] + b"\x00" * 32)[:32]

    raise ValueError(f"Unknown type: {typ}")


def _ref_encode_data(primary: str, data: dict, types: dict) -> bytes:
    ts = ref_encode_type(primary, types)
    th = keccak256(ts.encode("utf-8"))
    result = th
    for f in types[primary]:
        result += ref_encode_value(f["type"], data.get(f["name"]), types)
    return result


def _ref_hash_struct(primary: str, data: dict, types: dict) -> bytes:
    return keccak256(_ref_encode_data(primary, data, types))


def ref_signing_hash(td: dict) -> str:
    dt = {"EIP712Domain": td["types"]["EIP712Domain"]}
    dh = _ref_hash_struct("EIP712Domain", td["domain"], dt)
    if td["primaryType"] == "EIP712Domain":
        return "0x" + keccak256(b"\x19\x01" + dh).hex()
    mh = _ref_hash_struct(td["primaryType"], td["message"], td["types"])
    return "0x" + keccak256(b"\x19\x01" + dh + mh).hex()


# ──────────────────────────────────────────────────────────────────────
# CLI runner
# ──────────────────────────────────────────────────────────────────────

def run_cli(typed_data: dict) -> dict:
    """Run the TypeScript CLI and return the parsed JSON output."""
    proc = subprocess.run(
        ["npx", "tsx", "src/cli.ts"],
        input=json.dumps(typed_data),
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"CLI exited with code {proc.returncode}:\n{proc.stderr[:1000]}"
    )
    out = proc.stdout.strip()
    assert out, "CLI produced no output"
    return json.loads(out)


# ──────────────────────────────────────────────────────────────────────
# Test data
# ──────────────────────────────────────────────────────────────────────

CANONICAL = {
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


# ──────────────────────────────────────────────────────────────────────
# Tests: Python reference sanity checks against known canonical values
# ──────────────────────────────────────────────────────────────────────


class TestPythonReference:
    def test_encode_type(self):
        et = ref_encode_type("Mail", CANONICAL["types"])
        assert et == (
            "Mail(Person from,Person to,string contents)"
            "Person(string name,address wallet)"
        )

    def test_type_hash(self):
        et = ref_encode_type("Mail", CANONICAL["types"])
        th = "0x" + keccak256(et.encode("utf-8")).hex()
        assert th == "0xa0cedeb2dc280ba39b857546d74f5549c3a1d7bdc2dd96bf881f76108e23dac2"

    def test_domain_separator(self):
        dt = {"EIP712Domain": CANONICAL["types"]["EIP712Domain"]}
        ds = "0x" + _ref_hash_struct("EIP712Domain", CANONICAL["domain"], dt).hex()
        assert ds == "0xf2cee375fa42b42143804025fc449deafd50cc031ca257e0b194a650a912090f"

    def test_message_struct_hash(self):
        mh = "0x" + _ref_hash_struct(
            "Mail", CANONICAL["message"], CANONICAL["types"]
        ).hex()
        assert mh == "0xc52c0ee5d84264471806290a3f2c4cecfc5490626bf912d01f240d7a274b371e"

    def test_signing_hash(self):
        sh = ref_signing_hash(CANONICAL)
        assert sh == "0xbe609aee343fb3c4b28e1df9e632fca64fcfaede20f02e86244efddf30957bd2"


# ──────────────────────────────────────────────────────────────────────
# Tests: TypeScript CLI against canonical test vectors
# ──────────────────────────────────────────────────────────────────────


class TestCLICanonical:
    def test_encode_type(self):
        r = run_cli(CANONICAL)
        assert r["encodeType"] == (
            "Mail(Person from,Person to,string contents)"
            "Person(string name,address wallet)"
        )

    def test_type_hash(self):
        r = run_cli(CANONICAL)
        assert (
            r["typeHash"]
            == "0xa0cedeb2dc280ba39b857546d74f5549c3a1d7bdc2dd96bf881f76108e23dac2"
        )

    def test_domain_separator(self):
        r = run_cli(CANONICAL)
        assert (
            r["domainSeparator"]
            == "0xf2cee375fa42b42143804025fc449deafd50cc031ca257e0b194a650a912090f"
        )

    def test_message_struct_hash(self):
        r = run_cli(CANONICAL)
        assert (
            r["messageStructHash"]
            == "0xc52c0ee5d84264471806290a3f2c4cecfc5490626bf912d01f240d7a274b371e"
        )

    def test_signing_hash(self):
        r = run_cli(CANONICAL)
        assert (
            r["signingHash"]
            == "0xbe609aee343fb3c4b28e1df9e632fca64fcfaede20f02e86244efddf30957bd2"
        )


# ──────────────────────────────────────────────────────────────────────
# Tests: edge cases verified against Python reference
# ──────────────────────────────────────────────────────────────────────


class TestCLIEdgeCases:
    def test_negative_int256(self):
        td = {
            "types": {
                "EIP712Domain": [{"name": "name", "type": "string"}],
                "Bid": [
                    {"name": "amount", "type": "int256"},
                    {"name": "bidder", "type": "address"},
                ],
            },
            "primaryType": "Bid",
            "domain": {"name": "Auction"},
            "message": {
                "amount": -1,
                "bidder": "0x0000000000000000000000000000000000000001",
            },
        }
        r = run_cli(td)
        expected = ref_signing_hash(td)
        assert r["signingHash"] == expected, (
            f"Negative int256 mismatch: got {r['signingHash']}, expected {expected}"
        )

    def test_bytes4_right_padding(self):
        td = {
            "types": {
                "EIP712Domain": [{"name": "name", "type": "string"}],
                "Selector": [
                    {"name": "sig", "type": "bytes4"},
                    {"name": "id", "type": "uint256"},
                ],
            },
            "primaryType": "Selector",
            "domain": {"name": "Contract"},
            "message": {"sig": "0xdeadbeef", "id": 42},
        }
        r = run_cli(td)
        expected = ref_signing_hash(td)
        assert r["signingHash"] == expected, (
            f"bytes4 mismatch: got {r['signingHash']}, expected {expected}"
        )

    def test_uint256_array(self):
        td = {
            "types": {
                "EIP712Domain": [{"name": "name", "type": "string"}],
                "Portfolio": [
                    {"name": "amounts", "type": "uint256[]"},
                    {"name": "owner", "type": "address"},
                ],
            },
            "primaryType": "Portfolio",
            "domain": {"name": "DeFi"},
            "message": {
                "amounts": [100, 200, 300],
                "owner": "0x0000000000000000000000000000000000000001",
            },
        }
        r = run_cli(td)
        assert r["signingHash"] is not None, "uint256[] array type must be supported"
        expected = ref_signing_hash(td)
        assert r["signingHash"] == expected, (
            f"uint256[] mismatch: got {r['signingHash']}, expected {expected}"
        )

    def test_struct_array_with_type_dependency(self):
        td = {
            "types": {
                "EIP712Domain": [{"name": "name", "type": "string"}],
                "Person": [
                    {"name": "name", "type": "string"},
                    {"name": "wallet", "type": "address"},
                ],
                "Group": [
                    {"name": "name", "type": "string"},
                    {"name": "members", "type": "Person[]"},
                ],
            },
            "primaryType": "Group",
            "domain": {"name": "DAO"},
            "message": {
                "name": "Founders",
                "members": [
                    {
                        "name": "Alice",
                        "wallet": "0x0000000000000000000000000000000000000001",
                    },
                    {
                        "name": "Bob",
                        "wallet": "0x0000000000000000000000000000000000000002",
                    },
                ],
            },
        }
        r = run_cli(td)
        # encodeType must include Person even though it appears via Person[]
        expected_et = (
            "Group(string name,Person[] members)"
            "Person(string name,address wallet)"
        )
        assert r["encodeType"] == expected_et, (
            f"encodeType with array dep mismatch: got {r['encodeType']}"
        )
        assert r["signingHash"] is not None, "Person[] array type must be supported"
        expected = ref_signing_hash(td)
        assert r["signingHash"] == expected, (
            f"struct array mismatch: got {r['signingHash']}, expected {expected}"
        )

    def test_diamond_type_dependencies(self):
        td = {
            "types": {
                "EIP712Domain": [{"name": "name", "type": "string"}],
                "Shared": [{"name": "value", "type": "uint256"}],
                "Left": [
                    {"name": "shared", "type": "Shared"},
                    {"name": "leftVal", "type": "string"},
                ],
                "Right": [
                    {"name": "shared", "type": "Shared"},
                    {"name": "rightVal", "type": "string"},
                ],
                "Root": [
                    {"name": "left", "type": "Left"},
                    {"name": "right", "type": "Right"},
                ],
            },
            "primaryType": "Root",
            "domain": {"name": "Diamond"},
            "message": {
                "left": {"shared": {"value": 1}, "leftVal": "L"},
                "right": {"shared": {"value": 2}, "rightVal": "R"},
            },
        }
        r = run_cli(td)
        expected_et = (
            "Root(Left left,Right right)"
            "Left(Shared shared,string leftVal)"
            "Right(Shared shared,string rightVal)"
            "Shared(uint256 value)"
        )
        assert r["encodeType"] == expected_et, (
            f"diamond encodeType mismatch: got {r['encodeType']}"
        )
        expected = ref_signing_hash(td)
        assert r["signingHash"] == expected

    def test_domain_only_primary_type(self):
        td = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                ]
            },
            "primaryType": "EIP712Domain",
            "domain": {"name": "TestDApp", "chainId": 1},
            "message": {},
        }
        r = run_cli(td)
        expected = ref_signing_hash(td)
        assert r["signingHash"] == expected

    def test_recursive_linked_list(self):
        """Recursive type with null terminator for self-referencing field."""
        td = {
            "types": {
                "EIP712Domain": [{"name": "name", "type": "string"}],
                "LinkedList": [
                    {"name": "value", "type": "uint256"},
                    {"name": "next", "type": "LinkedList"},
                ],
            },
            "primaryType": "LinkedList",
            "domain": {"name": "ListApp"},
            "message": {
                "value": 42,
                "next": {
                    "value": 99,
                    "next": None,
                },
            },
        }
        r = run_cli(td)
        # encodeType for a self-referencing type has no extra deps
        expected_et = "LinkedList(uint256 value,LinkedList next)"
        assert r["encodeType"] == expected_et, (
            f"recursive encodeType mismatch: got {r['encodeType']}"
        )
        assert r["signingHash"] is not None, (
            "Recursive type with null terminator must not crash"
        )
        expected = ref_signing_hash(td)
        assert r["signingHash"] == expected, (
            f"recursive linked list mismatch: got {r['signingHash']}, expected {expected}"
        )

    def test_recursive_tree_with_arrays(self):
        """Recursive type using array fields (TreeNode[]) for children."""
        td = {
            "types": {
                "EIP712Domain": [{"name": "name", "type": "string"}],
                "TreeNode": [
                    {"name": "label", "type": "string"},
                    {"name": "values", "type": "uint256[]"},
                    {"name": "children", "type": "TreeNode[]"},
                ],
            },
            "primaryType": "TreeNode",
            "domain": {"name": "Tree"},
            "message": {
                "label": "root",
                "values": [1, 2, 3],
                "children": [
                    {
                        "label": "left",
                        "values": [10],
                        "children": [],
                    },
                    {
                        "label": "right",
                        "values": [20, 30],
                        "children": [],
                    },
                ],
            },
        }
        r = run_cli(td)
        expected_et = "TreeNode(string label,uint256[] values,TreeNode[] children)"
        assert r["encodeType"] == expected_et, (
            f"recursive tree encodeType mismatch: got {r['encodeType']}"
        )
        assert r["signingHash"] is not None, (
            "Recursive tree type with array children must work"
        )
        expected = ref_signing_hash(td)
        assert r["signingHash"] == expected, (
            f"recursive tree mismatch: got {r['signingHash']}, expected {expected}"
        )

    def test_signed_int_array(self):
        """Array of signed integers, combining array encoding with two's complement."""
        td = {
            "types": {
                "EIP712Domain": [{"name": "name", "type": "string"}],
                "SignedData": [
                    {"name": "values", "type": "int256[]"},
                    {"name": "flag", "type": "bool"},
                ],
            },
            "primaryType": "SignedData",
            "domain": {"name": "SignedApp"},
            "message": {
                "values": [-1, 0, 1],
                "flag": True,
            },
        }
        r = run_cli(td)
        assert r["signingHash"] is not None, "int256[] must be supported"
        expected = ref_signing_hash(td)
        assert r["signingHash"] == expected, (
            f"int256[] mismatch: got {r['signingHash']}, expected {expected}"
        )
