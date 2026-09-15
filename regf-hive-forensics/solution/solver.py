#!/usr/bin/env python3
"""Multi-tool forensic analyzer for registry hive evidence files.

Combines hivex command-line tools with manual binary analysis to extract
all data from hives, including anti-forensically concealed fragments.

Strategy:
  1. Try hivexml on each hive (standard tool analysis)
  2. Parse each hive binary manually (handles tool failures)
  3. Scan allocated cell slack space for hidden data
  4. Scan free cells for residual (deleted) data

"""
import json
import os
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET

EVIDENCE_DIR = "/app/evidence"
OUTPUT = "/app/findings.json"
HCELL_NIL = 0xFFFFFFFF
BASE_BLK = 0x1000
HBIN_HDR = 0x20


# ─── Phase 1: Tool-based analysis ──────────────────────────────────

def hivexml_extract(path):
    """Run hivexml and extract all value name->text pairs, or None on failure."""
    try:
        r = subprocess.run(["hivexml", path], capture_output=True, timeout=15)
        if r.returncode != 0:
            return None
        tree = ET.fromstring(r.stdout)
        vals = {}
        for v in tree.iter("value"):
            name = v.get("name", "")
            if name and v.text:
                vals[name] = v.text.strip()
        return vals
    except Exception:
        return None


# ─── Phase 2: Binary analysis helpers ──────────────────────────────

def read_hive(path):
    """Read hive file, return (header_bytes, hive_data_bytes, meta_dict)."""
    with open(path, "rb") as f:
        raw = f.read()
    hdr = raw[:BASE_BLK]
    hd = raw[BASE_BLK:]
    return hdr, hd, {
        "major": struct.unpack_from("<I", hdr, 0x14)[0],
        "minor": struct.unpack_from("<I", hdr, 0x18)[0],
        "root": struct.unpack_from("<I", hdr, 0x24)[0],
        "length": struct.unpack_from("<I", hdr, 0x28)[0],
    }


def get_cell_data(hd, ci, length):
    """Return (cell_body_bytes, abs_cell_size) or (None, 0) if invalid."""
    if ci == HCELL_NIL or ci + 4 > length or ci + 4 > len(hd):
        return None, 0
    sv = struct.unpack_from("<i", hd, ci)[0]
    absz = abs(sv)
    if absz < 8 or ci + absz > len(hd):
        return None, 0
    return hd[ci + 4:ci + absz], absz


def parse_nk_at(hd, off, length):
    """Parse nk cell at offset. Return info dict or None."""
    d, sz = get_cell_data(hd, off, length)
    if d is None or len(d) < 0x4C or d[:2] != b"nk":
        return None
    nl = struct.unpack_from("<H", d, 0x48)[0]
    fl = struct.unpack_from("<H", d, 0x02)[0]
    enc = "ascii" if fl & 0x20 else "utf-16-le"
    name = d[0x4C:0x4C + nl].decode(enc, errors="replace")
    return {
        "name": name,
        "cell_size": sz,
        "sk_count": struct.unpack_from("<I", d, 0x14)[0],
        "sk_list": struct.unpack_from("<I", d, 0x1C)[0],
        "val_count": struct.unpack_from("<I", d, 0x24)[0],
        "val_list": struct.unpack_from("<I", d, 0x28)[0],
        "data_end": 0x4C + nl,
    }


def decode_vk_data(d, hd, length):
    """Parse vk cell body bytes. Return (name, decoded_str) or (None, None)."""
    if len(d) < 0x14 or d[:2] != b"vk":
        return None, None
    nl = struct.unpack_from("<H", d, 0x02)[0]
    dl_raw = struct.unpack_from("<I", d, 0x04)[0]
    dtype = struct.unpack_from("<I", d, 0x0C)[0]
    vfl = struct.unpack_from("<H", d, 0x10)[0]
    enc = "ascii" if vfl & 1 else "utf-16-le"
    name = d[0x14:0x14 + nl].decode(enc, errors="replace")

    inline = bool(dl_raw & 0x80000000)
    alen = (dl_raw & 0x7FFFFFFF) if inline else dl_raw

    if inline:
        raw = d[0x08:0x08 + min(alen, 4)]
    else:
        dci = struct.unpack_from("<I", d, 0x08)[0]
        dd, _ = get_cell_data(hd, dci, length)
        raw = dd[:alen] if dd else b""

    if dtype == 1:  # REG_SZ
        try:
            return name, raw.decode("utf-16-le").rstrip("\x00")
        except Exception:
            return name, raw.decode("ascii", errors="replace").rstrip("\x00")
    elif dtype == 3:  # REG_BINARY
        try:
            return name, raw.decode("ascii")
        except Exception:
            return name, raw.hex()
    elif dtype == 4 and len(raw) >= 4:  # REG_DWORD
        return name, str(struct.unpack_from("<I", raw, 0)[0])
    return name, raw.hex()


def extract_values_binary(hd, nk, length):
    """Walk value list of an nk and return {name: decoded_data}."""
    vals = {}
    if nk["val_count"] == 0 or nk["val_list"] == HCELL_NIL:
        return vals
    vl, _ = get_cell_data(hd, nk["val_list"], length)
    if vl is None:
        return vals
    for i in range(nk["val_count"]):
        if 4 * i + 4 > len(vl):
            break
        vci = struct.unpack_from("<I", vl, 4 * i)[0]
        vd, _ = get_cell_data(hd, vci, length)
        if vd:
            n, v = decode_vk_data(vd, hd, length)
            if n:
                vals[n] = v
    return vals


def walk_subkeys(hd, nk, length):
    """Return list of subkey cell offsets from nk's subkey list."""
    offsets = []
    if nk["sk_count"] == 0 or nk["sk_list"] == HCELL_NIL:
        return offsets
    d, _ = get_cell_data(hd, nk["sk_list"], length)
    if d is None or len(d) < 4:
        return offsets
    sig, cnt = d[:2], struct.unpack_from("<H", d, 2)[0]
    if sig in (b"lf", b"lh"):
        for i in range(cnt):
            o = 4 + i * 8
            if o + 4 > len(d):
                break
            offsets.append(struct.unpack_from("<I", d, o)[0])
    elif sig == b"li":
        for i in range(cnt):
            o = 4 + i * 4
            if o + 4 > len(d):
                break
            offsets.append(struct.unpack_from("<I", d, o)[0])
    return offsets


# ─── Phase 3: Slack space scan ──────────────────────────────────────

def scan_slack(hd, length):
    """Find printable ASCII hidden in allocated nk cell slack space."""
    results = []
    off = HBIN_HDR
    while off + 4 < min(length, len(hd)):
        sv = struct.unpack_from("<i", hd, off)[0]
        if sv == 0:
            break
        absz = abs(sv)
        if absz < 8:
            break
        if sv < 0:  # allocated cell
            d = hd[off + 4:off + absz]
            if len(d) >= 0x4C and d[:2] == b"nk":
                nl = struct.unpack_from("<H", d, 0x48)[0]
                data_end = 0x4C + nl
                slack = d[data_end:]
                non_null = bytes(b for b in slack if b != 0)
                if len(non_null) >= 3:
                    try:
                        t = non_null.decode("ascii")
                        if all(c.isprintable() for c in t):
                            results.append(t)
                    except Exception:
                        pass
        off += absz
    return results


# ─── Phase 4: Free cell (deleted data) scan ─────────────────────────

def scan_free_vk(hd, length):
    """Find vk signatures in free cells and extract residual value data."""
    results = []
    off = HBIN_HDR
    while off + 4 < min(length, len(hd)):
        sv = struct.unpack_from("<i", hd, off)[0]
        if sv == 0:
            break
        absz = abs(sv)
        if absz < 8:
            break
        if sv > 0:  # free cell
            d = hd[off + 4:off + absz]
            if len(d) >= 0x14 and d[:2] == b"vk":
                n, v = decode_vk_data(d, hd, length)
                if n and v:
                    results.append((n, v))
        off += absz
    return results


# ─── Main analysis pipeline ────────────────────────────────────────

def analyze(fname, fpath):
    """Full multi-tool analysis of one hive file. Returns (fragment, technique)."""
    frag = None
    tech = None

    # Phase 1: Standard tool attempt
    xml_vals = hivexml_extract(fpath)

    # Phase 2: Binary header + structure analysis
    _, hd, meta = read_hive(fpath)
    L = meta["length"]

    # Detect version spoofing
    if meta["major"] != 1:
        tech = f"version spoofing (major={meta['major']})"

    # Extract values from hivexml output if available
    if xml_vals and "Fragment" in xml_vals:
        frag = xml_vals["Fragment"]
        if tech is None:
            tech = "plaintext"

    # Walk key tree manually (handles version-spoofed hives where tools fail)
    if frag is None:
        root = parse_nk_at(hd, meta["root"], L)
        if root:
            root_vals = extract_values_binary(hd, root, L)
            if "Fragment" in root_vals:
                frag = root_vals["Fragment"]
                if tech is None:
                    tech = "plaintext"
            for sk_off in walk_subkeys(hd, root, L):
                sk = parse_nk_at(hd, sk_off, L)
                if sk:
                    sv = extract_values_binary(hd, sk, L)
                    if "Fragment" in sv and frag is None:
                        frag = sv["Fragment"]
                        if tech is None:
                            tech = "plaintext"

    # Phase 3: Slack space analysis
    slack = scan_slack(hd, L)
    if slack and frag is None:
        frag = slack[0]
        tech = "cell slack space concealment"

    # Phase 4: Deleted cell recovery
    free_vks = scan_free_vk(hd, L)
    for n, v in free_vks:
        if n == "Fragment" and frag is None:
            frag = v
            tech = "deleted cell residual data recovery"

    return frag, tech


def main():
    frags = {}
    techs = {}
    for fname in sorted(os.listdir(EVIDENCE_DIR)):
        if not fname.endswith(".regf"):
            continue
        fp = os.path.join(EVIDENCE_DIR, fname)
        f, t = analyze(fname, fp)
        if f:
            frags[fname] = f
        if t:
            techs[fname] = t

    combined = "".join(frags[k] for k in sorted(frags))

    out = {
        "fragments": frags,
        "techniques": techs,
        "combined_flag": combined,
        "crafted_technique": (
            "Security descriptor (sk) cell slack space injection: "
            "the payload is appended after the declared security descriptor "
            "data but within the oversized allocated sk cell boundary. "
            "hivex reads only up to the SecurityDescriptorLength field value, "
            "leaving trailing bytes invisible to all standard analysis tools "
            "while the cell remains validly allocated."
        ),
    }
    with open(OUTPUT, "w") as fp:
        json.dump(out, fp, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
