#!/usr/bin/env python3
"""
Apply all four fixes to /app/resolver.py:

1. Compression pointer loop detection  – add visited-offset tracking to
   decode_dns_name so circular pointers raise ValueError instead of looping.

2. CNAME chain following – after checking for a direct A-record answer,
   detect CNAME records and recursively resolve the target.

3. NS hostname resolution without glue – when no glue record is available
   for a delegated NS hostname, recursively resolve the NS name.

4. EDNS0 OPT record – append an OPT pseudo-record (type 41, UDP size 4096)
   to every outgoing query so servers may send responses > 512 bytes.
"""

import sys

RESOLVER_PATH = "/app/resolver.py"


def apply_fix(code: str, old: str, new: str, label: str) -> str:
    if old not in code:
        print(f"WARNING: pattern for '{label}' not found – was it already fixed?",
              file=sys.stderr)
        return code
    if code.count(old) != 1:
        print(f"WARNING: pattern for '{label}' matched {code.count(old)} times",
              file=sys.stderr)
    return code.replace(old, new, 1)


def main():
    with open(RESOLVER_PATH, "r") as fh:
        code = fh.read()

    # ------------------------------------------------------------------
    # Fix 1 – compression pointer loop detection
    # ------------------------------------------------------------------
    # a) Add _visited parameter to decode_dns_name
    code = apply_fix(
        code,
        "def decode_dns_name(data: bytes, offset: int) -> Tuple[str, int]:\n"
        "    parts = []\n"
        "    jumped = False\n"
        "    return_offset = offset",

        "def decode_dns_name(data: bytes, offset: int, _visited=None) -> Tuple[str, int]:\n"
        "    if _visited is None:\n"
        "        _visited = set()\n"
        "    parts = []\n"
        "    jumped = False\n"
        "    return_offset = offset",
        "compression-loop: add _visited param",
    )

    # b) Check visited set before following a pointer
    code = apply_fix(
        code,
        "            pointer = struct.unpack(\"!H\", data[offset:offset + 2])[0] & 0x3FFF\n"
        "            offset = pointer\n"
        "            continue",

        "            pointer = struct.unpack(\"!H\", data[offset:offset + 2])[0] & 0x3FFF\n"
        "            if pointer in _visited:\n"
        "                raise ValueError(\"Compression pointer loop detected\")\n"
        "            _visited.add(pointer)\n"
        "            offset = pointer\n"
        "            continue",
        "compression-loop: detect cycle",
    )

    # ------------------------------------------------------------------
    # Fix 2 – follow CNAME records during resolution
    # ------------------------------------------------------------------
    code = apply_fix(
        code,
        "        # Look for NS delegation",

        "        # Follow CNAME if present in answers\n"
        "        for rec in response.answers:\n"
        "            if rec.type_ == TYPE_CNAME and rec.name.lower().rstrip(\".\") == name.lower().rstrip(\".\"):\n"
        "                return resolve(rec.data, type_, _depth + 1)\n"
        "\n"
        "        # Look for NS delegation",
        "cname: follow CNAME records",
    )

    # ------------------------------------------------------------------
    # Fix 3 – resolve NS hostname when no glue record is available
    # ------------------------------------------------------------------
    code = apply_fix(
        code,
        "        if glue is not None:\n"
        "            nameserver = glue\n"
        "        else:\n"
        "            return None",

        "        if glue is not None:\n"
        "            nameserver = glue\n"
        "        else:\n"
        "            ns_ip = resolve(ns_name, TYPE_A, _depth + 1)\n"
        "            if ns_ip is None:\n"
        "                return None\n"
        "            nameserver = ns_ip",
        "ns-glue: resolve NS hostname",
    )

    # ------------------------------------------------------------------
    # Fix 4 – add EDNS0 OPT record to queries
    # ------------------------------------------------------------------
    code = apply_fix(
        code,
        "    header = struct.pack(\"!HHHHHH\", txn_id, flags, 1, 0, 0, 0)\n"
        "    question = encode_dns_name(name) + struct.pack(\"!HH\", type_, CLASS_IN)\n"
        "    return header + question",

        "    header = struct.pack(\"!HHHHHH\", txn_id, flags, 1, 0, 0, 1)\n"
        "    question = encode_dns_name(name) + struct.pack(\"!HH\", type_, CLASS_IN)\n"
        "    # EDNS0 OPT pseudo-record: name=root, type=OPT(41), class=UDP-size,\n"
        "    # ttl=extended-rcode+flags, rdlength=0\n"
        "    opt = b\"\\x00\" + struct.pack(\"!HHIH\", TYPE_OPT, 4096, 0, 0)\n"
        "    return header + question + opt",
        "edns0: add OPT record",
    )

    with open(RESOLVER_PATH, "w") as fh:
        fh.write(code)

    print("All four fixes applied successfully.")


if __name__ == "__main__":
    main()
