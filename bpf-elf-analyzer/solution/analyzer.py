#!/usr/bin/env python3
"""BPF ELF Object File Analyzer.

Parses compiled eBPF ELF object files to extract program metadata,
map definitions (via BTF), and instruction-level properties.
"""

import json
import os
import struct
import sys

from elftools.elf.elffile import ELFFile


# ── BPF instruction constants ──────────────────────────────────────

BPF_CALL_INSN = 0x85       # BPF_JMP | BPF_CALL
BPF_LD_IMM64 = 0x18        # 128-bit load (2 slots)
BPF_LDX_MEM_W = 0x61       # BPF_LDX | BPF_W | BPF_MEM
BPF_MOV64_REG = 0xBF       # BPF_ALU64 | BPF_MOV | BPF_X

# ── BPF helper ID → name mapping ──────────────────────────────────

BPF_HELPERS = {
    1: "bpf_map_lookup_elem",
    2: "bpf_map_update_elem",
    3: "bpf_map_delete_elem",
    4: "bpf_probe_read",
    5: "bpf_ktime_get_ns",
    6: "bpf_trace_printk",
    7: "bpf_get_prandom_u32",
    8: "bpf_get_smp_processor_id",
    9: "bpf_skb_store_bytes",
    10: "bpf_l3_csum_replace",
    11: "bpf_l4_csum_replace",
    12: "bpf_tail_call",
    13: "bpf_clone_redirect",
    14: "bpf_get_current_pid_tgid",
    15: "bpf_get_current_uid_gid",
    16: "bpf_get_current_comm",
    17: "bpf_get_cgroup_classid",
    18: "bpf_skb_vlan_push",
    19: "bpf_skb_vlan_pop",
    20: "bpf_skb_get_tunnel_key",
    21: "bpf_skb_set_tunnel_key",
    22: "bpf_perf_event_read",
    23: "bpf_redirect",
    24: "bpf_get_route_realm",
    25: "bpf_perf_event_output",
    26: "bpf_skb_load_bytes",
    27: "bpf_get_stackid",
    28: "bpf_csum_diff",
    29: "bpf_skb_get_tunnel_opt",
    30: "bpf_skb_set_tunnel_opt",
    45: "bpf_probe_read_str",
    112: "bpf_probe_read_user",
    113: "bpf_probe_read_kernel",
    114: "bpf_probe_read_user_str",
    115: "bpf_probe_read_kernel_str",
    177: "bpf_trace_vprintk",
}

# ── BPF map type ID → name mapping ────────────────────────────────

BPF_MAP_TYPES = {
    0: "BPF_MAP_TYPE_UNSPEC",
    1: "BPF_MAP_TYPE_HASH",
    2: "BPF_MAP_TYPE_ARRAY",
    3: "BPF_MAP_TYPE_PROG_ARRAY",
    4: "BPF_MAP_TYPE_PERF_EVENT_ARRAY",
    5: "BPF_MAP_TYPE_PERCPU_HASH",
    6: "BPF_MAP_TYPE_PERCPU_ARRAY",
    7: "BPF_MAP_TYPE_STACK_TRACE",
    8: "BPF_MAP_TYPE_CGROUP_ARRAY",
    9: "BPF_MAP_TYPE_LRU_HASH",
    10: "BPF_MAP_TYPE_LRU_PERCPU_HASH",
    11: "BPF_MAP_TYPE_LPM_TRIE",
    12: "BPF_MAP_TYPE_ARRAY_OF_MAPS",
    13: "BPF_MAP_TYPE_HASH_OF_MAPS",
    14: "BPF_MAP_TYPE_DEVMAP",
    15: "BPF_MAP_TYPE_SOCKMAP",
    16: "BPF_MAP_TYPE_CPUMAP",
    17: "BPF_MAP_TYPE_XSKMAP",
    18: "BPF_MAP_TYPE_SOCKHASH",
    19: "BPF_MAP_TYPE_CGROUP_STORAGE",
    20: "BPF_MAP_TYPE_REUSEPORT_SOCKARRAY",
    21: "BPF_MAP_TYPE_PERCPU_CGROUP_STORAGE",
    22: "BPF_MAP_TYPE_QUEUE",
    23: "BPF_MAP_TYPE_STACK",
    24: "BPF_MAP_TYPE_SK_STORAGE",
    25: "BPF_MAP_TYPE_DEVMAP_HASH",
    26: "BPF_MAP_TYPE_STRUCT_OPS",
    27: "BPF_MAP_TYPE_RINGBUF",
    28: "BPF_MAP_TYPE_INODE_STORAGE",
    29: "BPF_MAP_TYPE_TASK_STORAGE",
    30: "BPF_MAP_TYPE_BLOOM_FILTER",
}

# ── Section name → program type mapping ───────────────────────────

PROG_SECTION_PREFIXES = [
    "xdp",
    "kprobe/",
    "kretprobe/",
    "ksyscall/",
    "kretsyscall/",
    "tracepoint/",
    "tp/",
    "tp_btf/",
    "raw_tp/",
    "raw_tracepoint/",
    "fentry/",
    "fexit/",
    "freplace/",
    "lsm/",
    "iter/",
    "cgroup/",
    "cgroup_skb/",
    "sk_skb/",
    "sk_msg",
    "sk_reuseport/",
    "socket",
    "struct_ops/",
    "tc",
    "classifier",
    "action",
]


def is_prog_section(name):
    """Check if an ELF section name corresponds to a BPF program."""
    # Exact-match section names
    if name in ("xdp", "tc", "classifier", "action", "sk_msg"):
        return True
    # Prefix-match section names (must have trailing content after the prefix)
    slash_prefixes = [
        "xdp/", "kprobe/", "kretprobe/", "ksyscall/", "kretsyscall/",
        "tracepoint/", "tp/", "tp_btf/", "raw_tp/", "raw_tracepoint/",
        "fentry/", "fexit/", "freplace/", "lsm/", "iter/",
        "cgroup/", "cgroup_skb/", "sk_skb/", "sk_reuseport/",
        "struct_ops/", "tc/", "tcx/",
    ]
    for pfx in slash_prefixes:
        if name.startswith(pfx):
            return True
    # "socket" prefix matches socket_filter, sockops, etc.
    if name.startswith("socket"):
        return True
    return False


def section_to_prog_type(name):
    """Derive BPF program type from section name."""
    if name == "xdp" or name.startswith("xdp/"):
        return "xdp"
    if name.startswith("kprobe/"):
        return "kprobe"
    if name.startswith("kretprobe/"):
        return "kretprobe"
    if name.startswith("ksyscall/"):
        return "kprobe"
    if name.startswith("kretsyscall/"):
        return "kretprobe"
    if name.startswith("tracepoint/") or name.startswith("tp/"):
        return "tracepoint"
    if name.startswith("tp_btf/"):
        return "tp_btf"
    if name.startswith("raw_tp/") or name.startswith("raw_tracepoint/"):
        return "raw_tracepoint"
    if name.startswith("fentry/"):
        return "fentry"
    if name.startswith("fexit/"):
        return "fexit"
    if name.startswith("freplace/"):
        return "freplace"
    if name.startswith("lsm/"):
        return "lsm"
    if name.startswith("iter/"):
        return "iter"
    if name.startswith("cgroup_skb/") or name.startswith("cgroup/"):
        return "cgroup"
    if name == "tc" or name.startswith("tc/") or name == "classifier" or name == "action":
        return "tc"
    if name.startswith("sk_skb/"):
        return "sk_skb"
    if name.startswith("sk_msg"):
        return "sk_msg"
    if name.startswith("socket"):
        return "socket_filter"
    if name.startswith("struct_ops/"):
        return "struct_ops"
    return "unknown"


# ── BPF instruction decoder ──────────────────────────────────────

def decode_bpf_insns(data):
    """Decode raw bytes into a list of BPF instructions."""
    insns = []
    off = 0
    while off + 8 <= len(data):
        opcode, regs, offset, imm = struct.unpack_from("<BBhi", data, off)
        dst = regs & 0x0F
        src = (regs >> 4) & 0x0F
        insn = {
            "opcode": opcode,
            "dst": dst,
            "src": src,
            "off": offset,
            "imm": imm,
            "is_wide": False,
        }
        off += 8

        # 128-bit wide load uses two slots
        if opcode == BPF_LD_IMM64 and off + 8 <= len(data):
            _, _, _, imm2 = struct.unpack_from("<BBhi", data, off)
            insn["imm_hi"] = imm2
            insn["is_wide"] = True
            off += 8

        insns.append(insn)
    return insns


def extract_helpers(insns):
    """Return sorted list of BPF helper names called by the program."""
    helpers = set()
    for insn in insns:
        # Helper call: opcode == 0x85, src_reg == 0 (not BPF-to-BPF call)
        if insn["opcode"] == BPF_CALL_INSN and insn["src"] == 0:
            hid = insn["imm"]
            name = BPF_HELPERS.get(hid, f"bpf_helper_{hid}")
            helpers.add(name)
    return sorted(helpers)


def detect_packet_access(insns, prog_type):
    """Detect if a program accesses packet data through context."""
    if prog_type not in ("xdp", "tc"):
        return False

    if prog_type == "xdp":
        data_off, end_off = 0, 4
    else:
        data_off, end_off = 76, 80

    # Track which registers hold the context pointer (R1 initially)
    ctx_regs = {1}
    found_data = False
    found_end = False

    for insn in insns:
        # MOV64_REG: copy register
        if insn["opcode"] == BPF_MOV64_REG and insn["src"] in ctx_regs:
            ctx_regs.add(insn["dst"])

        # LDX_MEM_W: 32-bit load from memory
        if insn["opcode"] == BPF_LDX_MEM_W and insn["src"] in ctx_regs:
            if insn["off"] == data_off:
                found_data = True
            if insn["off"] == end_off:
                found_end = True

    return found_data and found_end


# ── BTF parser ────────────────────────────────────────────────────

BTF_MAGIC = 0xEB9F

BTF_KIND_INT = 1
BTF_KIND_PTR = 2
BTF_KIND_ARRAY = 3
BTF_KIND_STRUCT = 4
BTF_KIND_UNION = 5
BTF_KIND_ENUM = 6
BTF_KIND_FWD = 7
BTF_KIND_TYPEDEF = 8
BTF_KIND_VOLATILE = 9
BTF_KIND_CONST = 10
BTF_KIND_RESTRICT = 11
BTF_KIND_FUNC = 12
BTF_KIND_FUNC_PROTO = 13
BTF_KIND_VAR = 14
BTF_KIND_DATASEC = 15
BTF_KIND_FLOAT = 16
BTF_KIND_DECL_TAG = 17
BTF_KIND_TYPE_TAG = 18
BTF_KIND_ENUM64 = 19

# Kinds that are transparent modifiers (skip during resolution)
_MODIFIER_KINDS = {BTF_KIND_CONST, BTF_KIND_VOLATILE, BTF_KIND_RESTRICT, BTF_KIND_TYPEDEF, BTF_KIND_TYPE_TAG}


class BTFType:
    __slots__ = ("name_off", "kind", "vlen", "kflag", "size_or_type", "name", "extra")

    def __init__(self, name_off, kind, vlen, kflag, size_or_type):
        self.name_off = name_off
        self.kind = kind
        self.vlen = vlen
        self.kflag = kflag
        self.size_or_type = size_or_type
        self.name = ""
        self.extra = None


class BTF:
    """Minimal BTF parser — enough to extract BPF map definitions."""

    def __init__(self, raw):
        self.raw = raw
        self.types = [None]  # 1-indexed
        self.str_data = b""
        self._parse()

    # -- internal helpers --

    def _get_str(self, off):
        end = self.str_data.index(b"\0", off)
        return self.str_data[off:end].decode("utf-8", errors="replace")

    def _parse(self):
        magic, ver, flags, hdr_len = struct.unpack_from("<HBBI", self.raw, 0)
        if magic != BTF_MAGIC:
            raise ValueError(f"Bad BTF magic {hex(magic)}")
        t_off, t_len, s_off, s_len = struct.unpack_from("<IIII", self.raw, 8)
        base = hdr_len
        self.type_raw = self.raw[base + t_off: base + t_off + t_len]
        self.str_data = self.raw[base + s_off: base + s_off + s_len]
        self._parse_types()

    def _parse_types(self):
        d = self.type_raw
        pos = 0
        while pos + 12 <= len(d):
            noff, info, sot = struct.unpack_from("<III", d, pos)
            kind = (info >> 24) & 0x1F
            vlen = info & 0xFFFF
            kflag = (info >> 31) & 1
            t = BTFType(noff, kind, vlen, kflag, sot)
            t.name = self._get_str(noff) if noff else ""
            pos += 12

            if kind == BTF_KIND_INT:
                t.extra = struct.unpack_from("<I", d, pos)[0]
                pos += 4
            elif kind == BTF_KIND_ARRAY:
                atype, itype, nelem = struct.unpack_from("<III", d, pos)
                t.extra = {"type": atype, "index_type": itype, "nelems": nelem}
                pos += 12
            elif kind in (BTF_KIND_STRUCT, BTF_KIND_UNION):
                members = []
                for _ in range(vlen):
                    mn, mt, mo = struct.unpack_from("<III", d, pos)
                    members.append({"name_off": mn, "name": self._get_str(mn) if mn else "", "type": mt, "offset": mo})
                    pos += 12
                t.extra = members
            elif kind == BTF_KIND_ENUM:
                pos += vlen * 8
            elif kind == BTF_KIND_FUNC_PROTO:
                pos += vlen * 8
            elif kind == BTF_KIND_VAR:
                t.extra = {"linkage": struct.unpack_from("<I", d, pos)[0]}
                pos += 4
            elif kind == BTF_KIND_DATASEC:
                entries = []
                for _ in range(vlen):
                    dt, do_, ds = struct.unpack_from("<III", d, pos)
                    entries.append({"type": dt, "offset": do_, "size": ds})
                    pos += 12
                t.extra = entries
            elif kind == BTF_KIND_DECL_TAG:
                pos += 4
            elif kind == BTF_KIND_ENUM64:
                pos += vlen * 12
            # PTR, FWD, TYPEDEF, VOLATILE, CONST, RESTRICT, FUNC, FLOAT, TYPE_TAG
            # have no extra data

            self.types.append(t)

    # -- public API --

    def resolve(self, tid):
        """Follow modifier types to reach the underlying concrete type."""
        seen = set()
        while 0 < tid < len(self.types) and tid not in seen:
            seen.add(tid)
            t = self.types[tid]
            if t is None:
                return None
            if t.kind in _MODIFIER_KINDS:
                tid = t.size_or_type
            else:
                return t
        return None

    def type_size(self, tid):
        """Compute the byte-size of a type."""
        t = self.resolve(tid)
        if t is None:
            return 0
        if t.kind == BTF_KIND_INT:
            return t.size_or_type  # size field
        if t.kind == BTF_KIND_PTR:
            return 8
        if t.kind in (BTF_KIND_STRUCT, BTF_KIND_UNION):
            return t.size_or_type  # size field
        if t.kind == BTF_KIND_ENUM:
            return t.size_or_type
        if t.kind == BTF_KIND_FLOAT:
            return t.size_or_type
        if t.kind == BTF_KIND_ARRAY:
            elem_sz = self.type_size(t.extra["type"])
            return elem_sz * t.extra["nelems"]
        if t.kind == BTF_KIND_ENUM64:
            return t.size_or_type
        return 0

    def _uint_value(self, member_tid):
        """Extract the integer value encoded by __uint() convention: PTR→ARRAY, nelems = value."""
        t = self.resolve(member_tid)
        if t is None or t.kind != BTF_KIND_PTR:
            return None
        arr = self.resolve(t.size_or_type)
        if arr is None or arr.kind != BTF_KIND_ARRAY:
            return None
        return arr.extra["nelems"]

    def _type_size_via_ptr(self, member_tid):
        """Extract the size encoded by __type() convention: PTR→actual_type, sizeof gives size."""
        t = self.resolve(member_tid)
        if t is None or t.kind != BTF_KIND_PTR:
            return None
        return self.type_size(t.size_or_type)

    def extract_maps(self):
        """Extract user-defined BPF map definitions from BTF."""
        maps = []
        for t in self.types:
            if t is None or t.kind != BTF_KIND_DATASEC:
                continue
            if t.name != ".maps":
                continue
            for entry in t.extra:
                var_tid = entry["type"]
                if var_tid >= len(self.types):
                    continue
                var = self.types[var_tid]
                if var is None or var.kind != BTF_KIND_VAR:
                    continue
                st = self.resolve(var.size_or_type)
                if st is None or st.kind != BTF_KIND_STRUCT:
                    continue

                minfo = {"name": var.name}
                for member in st.extra:
                    mname = member["name"]
                    mtid = member["type"]

                    if mname in ("type", "max_entries", "key_size", "value_size",
                                 "map_flags", "pinning", "numa_node"):
                        val = self._uint_value(mtid)
                        if val is not None:
                            minfo[mname] = val

                    elif mname in ("key", "value"):
                        sz = self._type_size_via_ptr(mtid)
                        if sz is not None:
                            minfo[mname + "_size"] = sz

                # Normalise map_type to string
                raw_type = minfo.pop("type", None)
                if raw_type is not None:
                    minfo["map_type"] = BPF_MAP_TYPES.get(raw_type, f"BPF_MAP_TYPE_{raw_type}")

                maps.append(minfo)
        return maps


# ── Main analysis routine ─────────────────────────────────────────

def analyze(path):
    with open(path, "rb") as f:
        elf = ELFFile(f)

        report = {
            "filename": os.path.basename(path),
            "license": "",
            "programs": [],
            "maps": [],
        }

        # --- license ---
        lic = elf.get_section_by_name("license")
        if lic is not None:
            report["license"] = lic.data().rstrip(b"\x00").decode("utf-8", errors="replace")

        # --- symbol table: map section index → function names ---
        symtab = elf.get_section_by_name(".symtab")
        sec_funcs = {}  # sec_idx → [func_name, ...]
        if symtab:
            for sym in symtab.iter_symbols():
                if sym.entry["st_info"]["type"] == "STT_FUNC":
                    sidx = sym.entry["st_shndx"]
                    if isinstance(sidx, int):
                        sec_funcs.setdefault(sidx, []).append(sym.name)

        # --- programs ---
        for idx, sec in enumerate(elf.iter_sections()):
            sname = sec.name
            if not is_prog_section(sname):
                continue
            if sec["sh_type"] != "SHT_PROGBITS":
                continue
            raw = sec.data()
            if len(raw) == 0:
                continue

            insns = decode_bpf_insns(raw)
            ptype = section_to_prog_type(sname)
            helpers = extract_helpers(insns)
            pkt = detect_packet_access(insns, ptype)

            names = sec_funcs.get(idx, [sname])
            fname = names[0] if names else sname

            report["programs"].append({
                "name": fname,
                "section": sname,
                "prog_type": ptype,
                "num_instructions": len(insns),
                "helpers_called": helpers,
                "has_packet_access": pkt,
            })

        # --- maps via BTF ---
        btf_sec = elf.get_section_by_name(".BTF")
        if btf_sec is not None:
            try:
                btf = BTF(btf_sec.data())
                report["maps"] = btf.extract_maps()
            except Exception as exc:
                print(f"  BTF parse warning for {path}: {exc}", file=sys.stderr)

    return report


def main():
    samples = "/app/samples"
    outdir = "/app/reports"
    os.makedirs(outdir, exist_ok=True)

    for fname in sorted(os.listdir(samples)):
        if not fname.endswith(".o"):
            continue
        fpath = os.path.join(samples, fname)
        rep = analyze(fpath)
        out = os.path.join(outdir, fname.replace(".o", ".json"))
        with open(out, "w") as fp:
            json.dump(rep, fp, indent=2)
        print(f"  {fname} -> {os.path.basename(out)}  "
              f"({len(rep['programs'])} prog(s), {len(rep['maps'])} map(s))")


if __name__ == "__main__":
    main()
