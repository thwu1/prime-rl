#!/usr/bin/env python3
"""Generate forensic evidence registry hive files.

Creates four hive files in /app/evidence/ with varying anti-forensic modifications:
- baseline.regf: Fragment stored as standard REG_SZ value (no concealment)
- suspect_alpha.regf: Fragment in valid value, but header major version spoofed to 0
- suspect_bravo.regf: Fragment hidden in cell slack space (padding after nk data)
- suspect_charlie.regf: Fragment in deleted (free) cell with residual vk data

"""
import struct
import os

HCELL_NIL = 0xFFFFFFFF
BASE_BLOCK_SIZE = 0x1000
HBIN_HDR_SIZE = 0x20
BIN_SIZE = 0x1000


def align8(n):
    return (n + 7) & ~7


def compute_checksum(header):
    """XOR of first 127 DWORDs. Special: 0->1, 0xFFFFFFFF->0xFFFFFFFE."""
    cs = 0
    for i in range(0, 508, 4):
        cs ^= struct.unpack_from('<I', header, i)[0]
    cs &= 0xFFFFFFFF
    if cs == 0xFFFFFFFF:
        cs = 0xFFFFFFFE
    if cs == 0:
        cs = 1
    return cs


def build_header(root_cell, hive_len, major=1, minor=5):
    h = bytearray(BASE_BLOCK_SIZE)
    struct.pack_into('<4s', h, 0x000, b'regf')
    struct.pack_into('<I', h, 0x004, 1)
    struct.pack_into('<I', h, 0x008, 1)
    struct.pack_into('<Q', h, 0x00C, 132000000000000000)
    struct.pack_into('<I', h, 0x014, major)
    struct.pack_into('<I', h, 0x018, minor)
    struct.pack_into('<I', h, 0x01C, 0)
    struct.pack_into('<I', h, 0x020, 1)
    struct.pack_into('<I', h, 0x024, root_cell)
    struct.pack_into('<I', h, 0x028, hive_len)
    struct.pack_into('<I', h, 0x02C, 1)
    cs = compute_checksum(h)
    struct.pack_into('<I', h, 0x1FC, cs)
    return bytes(h)


def encode_reg_sz(s):
    """Encode string as UTF-16LE with null terminator for REG_SZ."""
    return (s + '\0').encode('utf-16-le')


def make_nk(flags, parent, name, sk_count=0, sk_list=HCELL_NIL,
            val_count=0, val_list=HCELL_NIL, security=HCELL_NIL):
    name_b = name.encode('ascii')
    flags |= 0x0020
    d = bytearray(0x4C + len(name_b))
    struct.pack_into('<2s', d, 0x00, b'nk')
    struct.pack_into('<H', d, 0x02, flags)
    struct.pack_into('<Q', d, 0x04, 132000000000000000)
    struct.pack_into('<I', d, 0x10, parent)
    struct.pack_into('<I', d, 0x14, sk_count)
    struct.pack_into('<I', d, 0x18, 0)
    struct.pack_into('<I', d, 0x1C, sk_list)
    struct.pack_into('<I', d, 0x20, HCELL_NIL)
    struct.pack_into('<I', d, 0x24, val_count)
    struct.pack_into('<I', d, 0x28, val_list)
    struct.pack_into('<I', d, 0x2C, security)
    struct.pack_into('<I', d, 0x30, HCELL_NIL)
    struct.pack_into('<H', d, 0x48, len(name_b))
    struct.pack_into('<H', d, 0x4A, 0)
    d[0x4C:] = name_b
    return bytes(d)


def make_vk(name, dtype, data, data_offset=HCELL_NIL):
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
    struct.pack_into('<H', d, 0x10, 1)
    d[0x14:] = name_b
    return bytes(d)


def make_sk(flink, blink, ref_count=1):
    owner = bytes([1, 1, 0, 0, 0, 0, 0, 5, 18, 0, 0, 0])
    sd_hdr = bytearray(20)
    sd_hdr[0] = 1
    struct.pack_into('<H', sd_hdr, 2, 0x8004)
    struct.pack_into('<I', sd_hdr, 4, 20)
    struct.pack_into('<I', sd_hdr, 8, 32)
    sd = bytes(sd_hdr) + owner + owner
    d = bytearray(0x14 + len(sd))
    struct.pack_into('<2s', d, 0x00, b'sk')
    struct.pack_into('<I', d, 0x04, flink)
    struct.pack_into('<I', d, 0x08, blink)
    struct.pack_into('<I', d, 0x0C, ref_count)
    struct.pack_into('<I', d, 0x10, len(sd))
    d[0x14:] = sd
    return bytes(d)


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


class BinBuilder:
    """Builds an hbin with automatic offset tracking."""

    def __init__(self, bin_size=BIN_SIZE):
        self.bin_size = bin_size
        self.offset = HBIN_HDR_SIZE
        self.cells = []

    def _make_cell(self, data, cell_size, allocated):
        cell = bytearray(cell_size)
        size_val = -cell_size if allocated else cell_size
        struct.pack_into('<i', cell, 0, size_val)
        cell[4:4 + len(data)] = data
        return cell

    def add_allocated(self, data, min_cell_size=None):
        off = self.offset
        sz = align8(4 + len(data))
        if min_cell_size and min_cell_size > sz:
            sz = align8(min_cell_size)
        self.cells.append(self._make_cell(data, sz, True))
        self.offset += sz
        return off

    def add_allocated_with_slack(self, data, total_cell_size, slack_data=b''):
        """Add allocated cell with explicit oversized cell, hiding data in slack."""
        off = self.offset
        sz = align8(total_cell_size)
        assert sz >= align8(4 + len(data)), "Cell too small for data"
        cell = bytearray(sz)
        struct.pack_into('<i', cell, 0, -sz)
        cell[4:4 + len(data)] = data
        if slack_data:
            slack_start = 4 + len(data)
            cell[slack_start:slack_start + len(slack_data)] = slack_data
        self.cells.append(cell)
        self.offset += sz
        return off

    def add_free(self, size=None, residual_data=b''):
        """Add free cell. If size=None, fills remaining bin space."""
        if size is None:
            size = self.bin_size - self.offset
        off = self.offset
        cell = bytearray(size)
        struct.pack_into('<i', cell, 0, size)
        if residual_data:
            cell[4:4 + len(residual_data)] = residual_data
        self.cells.append(cell)
        self.offset += size
        return off

    def build(self, file_offset=0):
        hbin = bytearray(self.bin_size)
        struct.pack_into('<4s', hbin, 0, b'hbin')
        struct.pack_into('<I', hbin, 4, file_offset)
        struct.pack_into('<I', hbin, 8, self.bin_size)
        struct.pack_into('<Q', hbin, 0x14, 132000000000000000)
        pos = HBIN_HDR_SIZE
        for cell in self.cells:
            hbin[pos:pos + len(cell)] = cell
            pos += len(cell)
        assert pos == self.bin_size, \
            f"Bin not full: 0x{pos:x} vs 0x{self.bin_size:x}"
        return bytes(hbin)


# ── Hive builders ───────────────────────────────────────────────────

def build_baseline():
    r"""Clean hive: \Base\Data with Fragment='Pr0j3ct_' as REG_SZ."""
    bb = BinBuilder()
    frag = encode_reg_sz("Pr0j3ct_")  # 18 bytes UTF-16LE

    # Pre-calculated cell offsets (sequential placement)
    root_off = 0x20                       # nk "Base": cell 0x58
    sk_off = root_off + 0x58              # 0x78, sk: cell 0x48
    lf_off = sk_off + 0x48                # 0xC0, lf(1): cell 0x10
    data_nk_off = lf_off + 0x10           # 0xD0, nk "Data": cell 0x58
    vl_off = data_nk_off + 0x58           # 0x128, val_list(1): cell 0x08
    vk_off = vl_off + 0x08                # 0x130, vk "Fragment": cell 0x20
    dc_off = vk_off + 0x20                # 0x150, data cell(18B): cell 0x18

    bb.add_allocated(make_nk(0x0004, root_off, "Base",
                             sk_count=1, sk_list=lf_off, security=sk_off))
    bb.add_allocated(make_sk(sk_off, sk_off, ref_count=2))
    bb.add_allocated(make_lf([(data_nk_off, b'Data')]))
    bb.add_allocated(make_nk(0x0000, root_off, "Data",
                             val_count=1, val_list=vl_off, security=sk_off))
    bb.add_allocated(make_value_list([vk_off]))
    bb.add_allocated(make_vk("Fragment", 1, frag, data_offset=dc_off))
    bb.add_allocated(frag)
    bb.add_free()

    return build_header(root_off, BIN_SIZE) + bb.build()


def build_alpha():
    r"""Version-spoofed hive (major=0): \Alpha with Fragment='Z3r0_'."""
    bb = BinBuilder()
    frag = encode_reg_sz("Z3r0_")  # 12 bytes UTF-16LE

    root_off = 0x20                       # nk "Alpha": cell 0x58
    sk_off = root_off + 0x58              # 0x78, sk: cell 0x48
    vl_off = sk_off + 0x48                # 0xC0, val_list(1): cell 0x08
    vk_off = vl_off + 0x08                # 0xC8, vk "Fragment": cell 0x20
    dc_off = vk_off + 0x20                # 0xE8, data cell(12B): cell 0x10

    bb.add_allocated(make_nk(0x0004, root_off, "Alpha",
                             val_count=1, val_list=vl_off, security=sk_off))
    bb.add_allocated(make_sk(sk_off, sk_off, ref_count=1))
    bb.add_allocated(make_value_list([vk_off]))
    bb.add_allocated(make_vk("Fragment", 1, frag, data_offset=dc_off))
    bb.add_allocated(frag)
    bb.add_free()

    return build_header(root_off, BIN_SIZE, major=0, minor=5) + bb.build()


def build_bravo():
    r"""Slack-space hive: \Bravo\Public with Status=42; 'R3gf_' hidden in root slack."""
    bb = BinBuilder()

    root_off = 0x20                       # nk "Bravo": oversized cell 0xA0
    sk_off = root_off + 0xA0              # 0xC0, sk: cell 0x48
    lf_off = sk_off + 0x48                # 0x108, lf(1): cell 0x10
    pub_nk_off = lf_off + 0x10            # 0x118, nk "Public": cell 0x58
    vl_off = pub_nk_off + 0x58            # 0x170, val_list(1): cell 0x08
    vk_off = vl_off + 0x08                # 0x178, vk "Status": cell 0x20

    root_nk = make_nk(0x0004, root_off, "Bravo",
                      sk_count=1, sk_list=lf_off, security=sk_off)
    bb.add_allocated_with_slack(root_nk, total_cell_size=0xA0, slack_data=b"R3gf_")
    bb.add_allocated(make_sk(sk_off, sk_off, ref_count=2))
    bb.add_allocated(make_lf([(pub_nk_off, b'Publ')]))
    bb.add_allocated(make_nk(0x0000, root_off, "Public",
                             val_count=1, val_list=vl_off, security=sk_off))
    bb.add_allocated(make_value_list([vk_off]))
    bb.add_allocated(make_vk("Status", 4, struct.pack('<I', 42)))
    bb.add_free()

    return build_header(root_off, BIN_SIZE) + bb.build()


def build_charlie():
    r"""Deleted-cells hive: \Charlie (empty), deleted Fragment='FrE3' in free cells."""
    bb = BinBuilder()

    root_off = 0x20                        # nk "Charlie": cell 0x58
    sk_off = root_off + 0x58               # 0x78, sk: cell 0x48
    free_nk_off = sk_off + 0x48            # 0xC0, FREE residual nk "Deleted"
    free_vl_off = free_nk_off + 0x58       # 0x118, FREE residual value list
    free_vk_off = free_vl_off + 0x08       # 0x120, FREE residual vk "Fragment"

    # Active cells
    bb.add_allocated(make_nk(0x0004, root_off, "Charlie", security=sk_off))
    bb.add_allocated(make_sk(sk_off, sk_off, ref_count=1))

    # Deleted cells (free with residual data from former key tree)
    deleted_nk = make_nk(0x0000, root_off, "Deleted",
                         val_count=1, val_list=free_vl_off, security=sk_off)
    bb.add_free(size=0x58, residual_data=deleted_nk)

    deleted_vl = make_value_list([free_vk_off])
    bb.add_free(size=0x08, residual_data=deleted_vl)

    deleted_vk = make_vk("Fragment", 3, b"FrE3")  # REG_BINARY, inline
    bb.add_free(size=0x20, residual_data=deleted_vk)

    bb.add_free()  # trailing free space

    return build_header(root_off, BIN_SIZE) + bb.build()


def main():
    os.makedirs('/app/evidence', exist_ok=True)

    hives = {
        'baseline.regf': build_baseline(),
        'suspect_alpha.regf': build_alpha(),
        'suspect_bravo.regf': build_bravo(),
        'suspect_charlie.regf': build_charlie(),
    }

    for name, data in hives.items():
        path = f'/app/evidence/{name}'
        with open(path, 'wb') as f:
            f.write(data)
        size = os.path.getsize(path)
        print(f'{name}: {size} bytes')
        assert size == 0x2000, f'{name}: unexpected size {size:#x}'

    print("Generated evidence hives in /app/evidence/")


if __name__ == '__main__':
    main()
