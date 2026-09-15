#!/usr/bin/env python3
"""Construct a valid registry hive with payload hidden in sk cell slack.

Technique: Security descriptor (sk) cell slack space injection.
The payload ASCII bytes are appended after the declared security
descriptor data but within the oversized allocated sk cell boundary.
hivex reads only up to SecurityDescriptorLength, leaving the trailing
bytes invisible to all standard analysis tools.

"""
import struct

PAYLOAD = b"P0_h1v3_cr4ft"
NIL = 0xFFFFFFFF
BASE_BLK = 0x1000
HBIN_HDR = 0x20
BIN_SIZE = 0x1000


def align8(n):
    return (n + 7) & ~7


def compute_checksum(header):
    cs = 0
    for i in range(0, 508, 4):
        cs ^= struct.unpack_from('<I', header, i)[0]
    cs &= 0xFFFFFFFF
    if cs == 0xFFFFFFFF:
        cs = 0xFFFFFFFE
    if cs == 0:
        cs = 1
    return cs


def build_header(root_cell, hive_len):
    h = bytearray(BASE_BLK)
    struct.pack_into('<4s', h, 0x000, b'regf')
    struct.pack_into('<I', h, 0x004, 1)       # Sequence1
    struct.pack_into('<I', h, 0x008, 1)       # Sequence2
    struct.pack_into('<Q', h, 0x00C, 132000000000000000)  # Timestamp
    struct.pack_into('<I', h, 0x014, 1)       # Major (must be 1 for hivex)
    struct.pack_into('<I', h, 0x018, 5)       # Minor
    struct.pack_into('<I', h, 0x01C, 0)       # Type
    struct.pack_into('<I', h, 0x020, 1)       # Format
    struct.pack_into('<I', h, 0x024, root_cell)
    struct.pack_into('<I', h, 0x028, hive_len)
    struct.pack_into('<I', h, 0x02C, 1)       # Cluster
    cs = compute_checksum(h)
    struct.pack_into('<I', h, 0x1FC, cs)
    return bytes(h)


def encode_reg_sz(s):
    return (s + '\0').encode('utf-16-le')


def make_nk(flags, parent, name, sk_count=0, sk_list=NIL,
            val_count=0, val_list=NIL, security=NIL):
    name_b = name.encode('ascii')
    flags |= 0x0020  # KEY_COMP_NAME
    d = bytearray(0x4C + len(name_b))
    struct.pack_into('<2s', d, 0x00, b'nk')
    struct.pack_into('<H', d, 0x02, flags)
    struct.pack_into('<Q', d, 0x04, 132000000000000000)
    struct.pack_into('<I', d, 0x10, parent)
    struct.pack_into('<I', d, 0x14, sk_count)
    struct.pack_into('<I', d, 0x18, 0)
    struct.pack_into('<I', d, 0x1C, sk_list)
    struct.pack_into('<I', d, 0x20, NIL)
    struct.pack_into('<I', d, 0x24, val_count)
    struct.pack_into('<I', d, 0x28, val_list)
    struct.pack_into('<I', d, 0x2C, security)
    struct.pack_into('<I', d, 0x30, NIL)
    struct.pack_into('<H', d, 0x48, len(name_b))
    struct.pack_into('<H', d, 0x4A, 0)
    d[0x4C:] = name_b
    return bytes(d)


def make_vk(name, dtype, data, data_offset=NIL):
    name_b = name.encode('ascii')
    d = bytearray(0x14 + len(name_b))
    struct.pack_into('<2s', d, 0x00, b'vk')
    struct.pack_into('<H', d, 0x02, len(name_b))
    if len(data) <= 4:
        struct.pack_into('<I', d, 0x04, len(data) | 0x80000000)
        d[0x08:0x08 + len(data)] = data
    else:
        struct.pack_into('<I', d, 0x04, len(data))
        struct.pack_into('<I', d, 0x08, data_offset)
    struct.pack_into('<I', d, 0x0C, dtype)
    struct.pack_into('<H', d, 0x10, 1)  # VALUE_COMP_NAME
    d[0x14:] = name_b
    return bytes(d)


def make_sk_with_hidden_payload(flink, blink, payload, ref_count=1):
    """Build an sk cell with hidden payload after the security descriptor.

    The SecurityDescriptorLength field declares only the real SD size.
    hivex reads exactly that many bytes, so any data beyond is invisible
    to standard tools — but remains in the allocated cell's raw bytes.
    """
    owner_sid = bytes([1, 1, 0, 0, 0, 0, 0, 5, 18, 0, 0, 0])
    sd_hdr = bytearray(20)
    sd_hdr[0] = 1  # Revision
    struct.pack_into('<H', sd_hdr, 2, 0x8004)  # Control
    struct.pack_into('<I', sd_hdr, 4, 20)       # Owner offset
    struct.pack_into('<I', sd_hdr, 8, 32)       # Group offset
    sd = bytes(sd_hdr) + owner_sid + owner_sid   # 44 bytes total

    body = bytearray(0x14 + len(sd) + len(payload))
    struct.pack_into('<2s', body, 0x00, b'sk')
    struct.pack_into('<I', body, 0x04, flink)
    struct.pack_into('<I', body, 0x08, blink)
    struct.pack_into('<I', body, 0x0C, ref_count)
    struct.pack_into('<I', body, 0x10, len(sd))  # Only declares SD length
    body[0x14:0x14 + len(sd)] = sd
    body[0x14 + len(sd):] = payload              # Hidden after declared SD
    return bytes(body)


def make_lf(entries):
    d = bytearray(4 + 8 * len(entries))
    struct.pack_into('<2s', d, 0, b'lf')
    struct.pack_into('<H', d, 2, len(entries))
    for i, (ci, hint) in enumerate(entries):
        struct.pack_into('<I', d, 4 + i * 8, ci)
        d[8 + i * 8:12 + i * 8] = hint[:4]
    return bytes(d)


def make_value_list(indexes):
    d = bytearray(4 * len(indexes))
    for i, ci in enumerate(indexes):
        struct.pack_into('<I', d, i * 4, ci)
    return bytes(d)


def make_cell(data, cell_size, allocated):
    """Build a raw cell: 4-byte signed size + data + padding."""
    cell = bytearray(cell_size)
    struct.pack_into('<i', cell, 0, -cell_size if allocated else cell_size)
    cell[4:4 + len(data)] = data
    return bytes(cell)


def build_crafted_hive():
    """Build a complete hive: root key Crafted -> subkey Public -> value Decoy.

    Payload P0_h1v3_cr4ft is hidden in sk cell slack space.

    Cell layout within single 4 KiB hbin:
      0x20: nk "Crafted"  (root, 0x58 bytes)
      0x78: sk             (oversized, 0x58 bytes, payload in slack)
      0xD0: lf             (subkey list, 0x10 bytes)
      0xE0: nk "Public"   (subkey, 0x58 bytes)
      0x138: value_list    (0x08 bytes)
      0x140: vk "Decoy"   (0x20 bytes)
      0x160: data cell     (REG_SZ "visible_data", 0x20 bytes)
      0x180: free cell     (remaining 0xE80 bytes)
    """
    root_off = HBIN_HDR  # 0x20

    # Phase 1: compute body sizes and cell sizes
    root_nk_body = make_nk(0x0004, root_off, "Crafted")
    root_csz = align8(4 + len(root_nk_body))           # 0x58

    sk_off = root_off + root_csz                        # 0x78
    sk_body = make_sk_with_hidden_payload(sk_off, sk_off, PAYLOAD, ref_count=2)
    sk_csz = align8(4 + len(sk_body))                   # 0x58

    lf_off = sk_off + sk_csz                            # 0xD0
    lf_csz = 0x10

    pub_off = lf_off + lf_csz                           # 0xE0
    pub_nk_body = make_nk(0x0000, root_off, "Public")
    pub_csz = align8(4 + len(pub_nk_body))              # 0x58

    vl_off = pub_off + pub_csz                          # 0x138
    vl_csz = 0x08

    vk_off = vl_off + vl_csz                            # 0x140
    decoy_data = encode_reg_sz("visible_data")          # 26 bytes
    vk_body = make_vk("Decoy", 1, decoy_data)
    vk_csz = align8(4 + len(vk_body))                   # 0x20

    dc_off = vk_off + vk_csz                            # 0x160
    dc_csz = align8(4 + len(decoy_data))                 # 0x20

    # Phase 2: rebuild bodies with final cross-references
    root_nk_body = make_nk(0x0004, root_off, "Crafted",
                           sk_count=1, sk_list=lf_off, security=sk_off)
    pub_nk_body = make_nk(0x0000, root_off, "Public",
                          val_count=1, val_list=vl_off, security=sk_off)
    lf_body = make_lf([(pub_off, b'Publ')])
    vl_body = make_value_list([vk_off])
    vk_body = make_vk("Decoy", 1, decoy_data, data_offset=dc_off)

    # Phase 3: assemble hbin
    hbin = bytearray(BIN_SIZE)
    struct.pack_into('<4s', hbin, 0, b'hbin')
    struct.pack_into('<I', hbin, 4, 0)          # FileOffset
    struct.pack_into('<I', hbin, 8, BIN_SIZE)   # Size
    struct.pack_into('<Q', hbin, 0x14, 132000000000000000)  # Timestamp

    cells = [
        (root_nk_body, root_csz),
        (sk_body, sk_csz),
        (lf_body, lf_csz),
        (pub_nk_body, pub_csz),
        (vl_body, vl_csz),
        (vk_body, vk_csz),
        (decoy_data, dc_csz),
    ]

    pos = HBIN_HDR
    for body, csz in cells:
        cell = make_cell(body, csz, allocated=True)
        hbin[pos:pos + csz] = cell
        pos += csz

    # Trailing free cell
    free_sz = BIN_SIZE - pos
    assert free_sz > 0, f"No space for free cell: pos=0x{pos:x}"
    struct.pack_into('<i', hbin, pos, free_sz)  # positive = free

    return build_header(root_off, BIN_SIZE) + bytes(hbin)


def main():
    hive = build_crafted_hive()
    with open("/app/crafted.regf", "wb") as f:
        f.write(hive)

    # Sanity: verify payload is in the hive data area
    assert PAYLOAD in hive[BASE_BLK:], "BUG: payload not in hive data"
    print(f"Crafted hive written: {len(hive)} bytes, payload verified")


if __name__ == '__main__':
    main()
