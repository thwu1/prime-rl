#!/usr/bin/env python3
"""
Fix the syzlang descriptions in /app/sys/vdma.txt by analyzing the
UAPI header /app/include/vdma.h and applying corrections based on
syzlang semantic rules.

"""

import re

SYZLANG_FILE = "/app/sys/vdma.txt"
HEADER_FILE = "/app/include/vdma.h"


def parse_header(header):
    """Parse the UAPI header to extract interface information."""
    info = {}

    # Extract typedefs
    type_map = {"__u8": "int8", "__u16": "int16", "__u32": "int32", "__u64": "int64"}
    typedefs = {}
    for m in re.finditer(r"typedef\s+(__u\d+)\s+(\w+)\s*;", header):
        typedefs[m.group(2)] = type_map.get(m.group(1), "intptr")
    info["typedefs"] = typedefs

    # Extract ioctl directions
    ioctls = {}
    for m in re.finditer(r"#define\s+(\w+)\s+(_IOWR|_IOW|_IOR)\s*\(", header):
        ioctls[m.group(1)] = m.group(2)
    info["ioctls"] = ioctls

    # Extract struct field order using brace depth
    structs = {}
    i = 0
    while i < len(header):
        sm = re.search(r"struct\s+(\w+)\s*\{", header[i:])
        if not sm:
            break
        name = sm.group(1)
        start = i + sm.end()
        depth = 1
        pos = start
        while pos < len(header) and depth > 0:
            if header[pos] == "{":
                depth += 1
            elif header[pos] == "}":
                depth -= 1
            pos += 1
        body = header[start : pos - 1]
        i = pos

        fields = []
        inner_depth = 0
        for line in body.split("\n"):
            stripped = line.strip()
            inner_depth += stripped.count("{") - stripped.count("}")
            if inner_depth > 0 or not stripped:
                continue
            if stripped.startswith("/*") or stripped.startswith("*"):
                continue
            if stripped.startswith("union") or stripped in ("};", "}"):
                continue
            fm = re.match(
                r"(?:(?:struct\s+)?\w+)\s+(\w+)(?:\s*\[.*?\])?\s*;", stripped
            )
            if fm:
                fields.append(fm.group(1))
        structs[name] = fields

    info["structs"] = structs

    # Find packed structs
    packed = set()
    i = 0
    while i < len(header):
        sm = re.search(r"struct\s+(\w+)\s*\{", header[i:])
        if not sm:
            break
        name = sm.group(1)
        start = i + sm.end()
        depth = 1
        pos = start
        while pos < len(header) and depth > 0:
            if header[pos] == "{":
                depth += 1
            elif header[pos] == "}":
                depth -= 1
            pos += 1
        rest = header[pos : pos + 80]
        if re.match(r"\s*__attribute__\s*\(\s*\(\s*packed\s*\)\s*\)", rest):
            packed.add(name)
        i = pos
    info["packed"] = packed

    # Find padding fields that must be zero
    zero_padding = {}
    for sm in re.finditer(r"struct\s+(\w+)\s*\{", header):
        name = sm.group(1)
        # Find body using brace depth
        start = sm.end()
        depth = 1
        pos = start
        while pos < len(header) and depth > 0:
            if header[pos] == "{":
                depth += 1
            elif header[pos] == "}":
                depth -= 1
            pos += 1
        body = header[start : pos - 1]
        for line in body.split("\n"):
            if "must be zero" in line.lower() and "padding" in line.lower():
                tm = re.search(r"__u(\d+)\s+padding", line)
                if tm:
                    zero_padding[name] = f"int{tm.group(1)}"
    info["zero_padding"] = zero_padding

    # Extract constants (including shift expressions)
    constants = set()
    for m in re.finditer(
        r"^#define\s+(\w+)\s+(?:0x[0-9a-fA-F]+|\d+|\(.*?\))",
        header,
        re.MULTILINE,
    ):
        constants.add(m.group(1))
    info["constants"] = constants

    # Find flag namespaces
    flag_groups = {}
    for m in re.finditer(r"^#define\s+(VDMA_\w+)", header, re.MULTILINE):
        name = m.group(1)
        # Group by prefix (e.g., VDMA_CAP_, VDMA_XFER_, etc.)
        parts = name.split("_")
        if len(parts) >= 3:
            prefix = "_".join(parts[:2])
            if prefix not in flag_groups:
                flag_groups[prefix] = []
            flag_groups[prefix].append(name)
    info["flag_groups"] = flag_groups

    return info


def generate_correct_syzlang(info):
    """Generate the correct syzlang description from header analysis."""
    lines = []

    # Include directive
    lines.append("include <uapi/linux/vdma.h>")
    lines.append("")

    # Resources - derive from typedefs
    lines.append("# Resource definitions")
    lines.append("resource fd_vdma[fd]")
    for td_name, td_type in sorted(info["typedefs"].items()):
        res_name = td_name.rstrip("_t")  # vdma_channel_t -> vdma_channel
        special = "0xffffffffffffffff" if td_type == "int64" else "0xffffffff"
        lines.append(f"resource {res_name}[{td_type}]: {special}")
    lines.append("")

    # Flag sets
    lines.append("# Flag sets")
    lines.append(
        "vdma_cap_flags = VDMA_CAP_SG, VDMA_CAP_CYCLIC, "
        "VDMA_CAP_INTERLEAVE, VDMA_CAP_MEMCPY, VDMA_CAP_MEMSET"
    )
    lines.append(
        "vdma_dir_flags = VDMA_DIR_MEM_TO_DEV, VDMA_DIR_DEV_TO_MEM, "
        "VDMA_DIR_MEM_TO_MEM"
    )
    lines.append(
        "vdma_xfer_flags = VDMA_XFER_INTERRUPT, VDMA_XFER_FENCE, VDMA_XFER_CYCLIC"
    )
    lines.append(
        "vdma_stat_flags = VDMA_STAT_IDLE, VDMA_STAT_RUNNING, "
        "VDMA_STAT_PAUSED, VDMA_STAT_ERROR, VDMA_STAT_COMPLETED"
    )
    lines.append(
        "vdma_evt_types = VDMA_EVT_XFER_DONE, VDMA_EVT_ERROR, VDMA_EVT_THRESHOLD"
    )
    lines.append(
        "vdma_err_codes = VDMA_ERR_BUS, VDMA_ERR_SLAVE, "
        "VDMA_ERR_DECODE, VDMA_ERR_TIMEOUT"
    )
    lines.append("")

    # Syscalls - derive directions from ioctl definitions
    lines.append("# Open/close device")
    lines.append(
        'openat$vdma(fd const[AT_FDCWD], file ptr[in, string["/dev/vdma"]], '
        "flags flags[open_flags], mode const[0]) fd_vdma"
    )
    lines.append("close$vdma(fd fd_vdma)")
    lines.append("")

    lines.append("# Ioctl definitions")

    # Map each ioctl to its correct ptr direction and arg type
    ioctl_defs = [
        ("VDMA_IOC_ALLOC", "inout", "vdma_alloc_req"),
        ("VDMA_IOC_FREE", "in", "vdma_channel"),
        ("VDMA_IOC_CONFIG", "inout", "vdma_chan_config"),
        ("VDMA_IOC_SUBMIT", "inout", "vdma_xfer_desc"),
        ("VDMA_IOC_STATUS", "inout", "vdma_xfer_status"),
        ("VDMA_IOC_ABORT", "in", "vdma_channel"),
        ("VDMA_IOC_PAUSE", "in", "vdma_channel"),
        ("VDMA_IOC_RESUME", "in", "vdma_channel"),
        ("VDMA_IOC_WAIT_EVT", "inout", "vdma_event"),
        ("VDMA_IOC_FENCE", "inout", "vdma_fence_req"),
        ("VDMA_IOC_BATCH", "inout", "vdma_batch_submit"),
    ]
    for ioc_name, direction, arg_type in ioctl_defs:
        lines.append(
            f"ioctl${ioc_name}(fd fd_vdma, cmd const[{ioc_name}], "
            f"arg ptr[{direction}, {arg_type}])"
        )
    lines.append("")

    # Structs
    lines.append("# Struct definitions")
    lines.append("")

    # vdma_sg_entry - field order from header: addr, len, stride
    lines.append("vdma_sg_entry {")
    lines.append("\taddr\tint64")
    lines.append("\tlen\tint32")
    lines.append("\tstride\tint32")
    lines.append("}")
    lines.append("")

    # vdma_alloc_req - channel is output resource, padding must be zero
    lines.append("vdma_alloc_req {")
    lines.append("\tcaps\t\tflags[vdma_cap_flags, int32]")
    lines.append("\tpriority\tint32[0:3]")
    lines.append("\tchannel\t\tvdma_channel\t(out)")
    lines.append("\tpadding\t\tconst[0, int32]")
    lines.append("}")
    lines.append("")

    # vdma_xfer_desc - packed, cookie output, correct flags, len ref
    packed_attr = " [packed]" if "vdma_xfer_desc" in info["packed"] else ""
    lines.append("vdma_xfer_desc {")
    lines.append("\tchannel\t\tvdma_channel")
    lines.append("\tdirection\tflags[vdma_dir_flags, int32]")
    lines.append("\tsrc_addr\tint64")
    lines.append("\tdst_addr\tint64")
    lines.append("\tlength\t\tint64")
    lines.append("\tflags\t\tflags[vdma_xfer_flags, int32]")
    lines.append("\tsg_count\tlen[sg_list, int32]")
    lines.append("\tcookie\t\tvdma_cookie\t(out)")
    lines.append("\tsg_list\t\tarray[vdma_sg_entry]")
    lines.append("}" + packed_attr)
    lines.append("")

    # vdma_xfer_status
    lines.append("vdma_xfer_status {")
    lines.append("\tcookie\t\t\tvdma_cookie\t(in)")
    lines.append("\tstatus\t\t\tint32\t\t(out)")
    lines.append("\tbytes_remaining\t\tint32\t\t(out)")
    lines.append("\ttimestamp\t\tint64\t\t(out)")
    lines.append("}")
    lines.append("")

    # vdma_chan_config - padding must be zero
    lines.append("vdma_chan_config {")
    lines.append("\tchannel\t\tvdma_channel")
    lines.append("\tburst_len\tint32")
    lines.append("\tsrc_addr_width\tint32")
    lines.append("\tdst_addr_width\tint32")
    lines.append("\tmax_sg_entries\tint32\t\t(out)")
    lines.append("\tmax_burst_len\tint32\t\t(out)")
    lines.append("\tpadding\t\tconst[0, int32]")
    lines.append("}")
    lines.append("")

    # Event sub-structs
    lines.append("vdma_event_xfer_done {")
    lines.append("\tcookie\t\t\tvdma_cookie")
    lines.append("\tbytes_transferred\tint64")
    lines.append("}")
    lines.append("")

    lines.append("vdma_event_error {")
    lines.append("\tcookie\t\tvdma_cookie")
    lines.append("\terror_code\tflags[vdma_err_codes, int32]")
    lines.append("\terror_addr_lo\tint32")
    lines.append("\terror_addr_hi\tint32")
    lines.append("\tpadding\t\tint32")
    lines.append("}")
    lines.append("")

    lines.append("vdma_event_threshold {")
    lines.append("\twatermark\tint32")
    lines.append("\tdirection\tint32")
    lines.append("}")
    lines.append("")

    # Event union (syzlang union for C anonymous union)
    lines.append("vdma_event_payload [")
    lines.append("\txfer_done\tvdma_event_xfer_done")
    lines.append("\terror\t\tvdma_event_error")
    lines.append("\tthreshold\tvdma_event_threshold")
    lines.append("]")
    lines.append("")

    # vdma_event - packed, uses union
    packed_attr = " [packed]" if "vdma_event" in info["packed"] else ""
    lines.append("vdma_event {")
    lines.append("\tchannel\t\tvdma_channel")
    lines.append("\tevt_type\tflags[vdma_evt_types, int32]")
    lines.append("\tseq_num\t\tint64")
    lines.append("\tpayload\t\tvdma_event_payload")
    lines.append("}" + packed_attr)
    lines.append("")

    # vdma_fence_req - correct field order from header
    lines.append("vdma_fence_req {")
    lines.append("\tchannel\t\tvdma_channel")
    lines.append("\tfence_val\tvdma_fence")
    lines.append("\ttimeout_ms\tint32")
    lines.append("\tstatus\t\tint32\t\t(out)")
    lines.append("}")
    lines.append("")

    # vdma_batch_hdr
    lines.append("vdma_batch_hdr {")
    lines.append("\tnum_xfers\tint32")
    lines.append("\tflags\t\tint32")
    lines.append("}")
    lines.append("")

    # vdma_batch_submit - packed, cookies use resource type
    packed_attr = " [packed]" if "vdma_batch_submit" in info["packed"] else ""
    lines.append("vdma_batch_submit {")
    lines.append("\theader\t\tvdma_batch_hdr")
    lines.append("\tcookies\t\tarray[vdma_cookie]\t(out)")
    lines.append("}" + packed_attr)

    return "\n".join(lines) + "\n"


def main():
    with open(HEADER_FILE, "r") as f:
        header = f.read()

    info = parse_header(header)
    correct_syzlang = generate_correct_syzlang(info)

    with open(SYZLANG_FILE, "w") as f:
        f.write(correct_syzlang)

    print(f"Fixed syzlang descriptions written to {SYZLANG_FILE}")


if __name__ == "__main__":
    main()
