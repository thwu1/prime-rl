#!/usr/bin/env python3
"""Generate task environment: qcow2 memory image, device tree blob, system state, fault log."""
import struct
import json
import os
import subprocess

os.makedirs("/app", exist_ok=True)

# ---- Generate raw memory with page tables ----
MEM_SIZE = 256 * 1024  # 256 KiB
mem = bytearray(MEM_SIZE)


def w(offset, value):
    struct.pack_into('<Q', mem, offset, value)


# L2 root page table at offset 0x1000 (PA 0x80001000)
w(0x1000, 0x0000000020000801)

# L1 page table at offset 0x2000 (PA 0x80002000)
w(0x2000, 0x0000000020001001)
w(0x2008, 0x00000000200804CF)   # Fault 3: misaligned superpage
w(0x2010, 0x0000000020001401)
w(0x2018, 0x0000000020001801)
w(0x2020, 0x0000000020001C01)
w(0x2028, 0x0000000020002001)

# L0 page table #0 at offset 0x4000 (PA 0x80004000)
w(0x4000, 0x0000000020004042)   # Fault 1: V=0 (bit 0 clear, bit 1 set => R=1 but V=0)
w(0x4008, 0x00000000200044C5)   # Fault 2: R=0,W=1 reserved encoding
w(0x4010, 0x00000000200028C7)   # Valid
w(0x4018, 0x000000002000644B)   # Valid

# L0 page table #1 at offset 0x5000 (PA 0x80005000)
w(0x5000, 0x0000000020004843)   # Fault 4: store but W=0
w(0x5008, 0x0000000020004C03)   # Fault 5: non-leaf at level 0
w(0x5010, 0x0000000020005047)   # Fault 6: store but W=0, D=0
w(0x5018, 0x00000000200054CF)   # Valid

# L0 page table #2 at offset 0x6000 (PA 0x80006000)
w(0x6000, 0x0000000020005453)   # Fault 7: U-page accessed by S-mode without SUM
w(0x6008, 0x0000000020003443)   # Valid

# L0 page table #3 at offset 0x7000 (PA 0x80007000)
w(0x7000, 0x0000000020005801)   # Fault 8: pointer (non-leaf) at L0
w(0x7008, 0x00000000200038C7)   # Valid

# L0 page table #4 at offset 0x8000 (PA 0x80008000)
w(0x8000, 0x80000000200410C3)   # Fault 9: invalid NAPOT encoding
w(0x8008, 0x0000000020005C43)   # Fault 10: fetch but X=0
w(0x8010, 0x0000000020003CCF)   # Valid

# Scatter recognizable data at mapped page regions
for off in [0x10000, 0x11000, 0x12000, 0x13000,
            0x14000, 0x15000, 0x16000, 0x17000]:
    if off + 16 <= MEM_SIZE:
        struct.pack_into('<QQ', mem, off,
                         0xDEADBEEFCAFEBABE, 0x0123456789ABCDEF)

# Write raw memory to temp file, then convert to qcow2
raw_path = "/tmp/memory.raw"
with open(raw_path, "wb") as f:
    f.write(mem)

subprocess.run(
    ["qemu-img", "convert", "-f", "raw", "-O", "qcow2",
     raw_path, "/app/memory.qcow2"],
    check=True
)
os.unlink(raw_path)

# ---- Generate device tree blob ----
dts_content = """/dts-v1/;

/ {
\t#address-cells = <2>;
\t#size-cells = <2>;
\tcompatible = "riscv-custom-soc";
\tmodel = "RV64 Debug Platform rev3";

\tchosen {
\t\tbootargs = "earlycon=sbi loglevel=7";
\t};

\tcpus {
\t\t#address-cells = <1>;
\t\t#size-cells = <0>;
\t\ttimebase-frequency = <10000000>;

\t\tcpu@0 {
\t\t\tdevice_type = "cpu";
\t\t\treg = <0>;
\t\t\tcompatible = "riscv";
\t\t\triscv,isa = "rv64imafdc";
\t\t\tmmu-type = "riscv,sv39";
\t\t\tstatus = "okay";
\t\t};
\t};

\tmemory@80000000 {
\t\tdevice_type = "memory";
\t\treg = <0x00000000 0x80000000 0x00000000 0x00040000>;
\t};

\treserved-memory {
\t\t#address-cells = <2>;
\t\t#size-cells = <2>;
\t\tranges;

\t\topensbi@80000000 {
\t\t\treg = <0x00000000 0x80000000 0x00000000 0x00000400>;
\t\t\tno-map;
\t\t};
\t};

\tsoc {
\t\t#address-cells = <2>;
\t\t#size-cells = <2>;
\t\tcompatible = "simple-bus";
\t\tranges;

\t\tclint@2000000 {
\t\t\tcompatible = "riscv,clint0";
\t\t\treg = <0x00000000 0x02000000 0x00000000 0x00010000>;
\t\t};

\t\tplic@c000000 {
\t\t\tcompatible = "riscv,plic0";
\t\t\treg = <0x00000000 0x0c000000 0x00000000 0x04000000>;
\t\t\tinterrupt-controller;
\t\t\t#interrupt-cells = <1>;
\t\t\triscv,ndev = <96>;
\t\t};

\t\tserial@10000000 {
\t\t\tcompatible = "ns16550a";
\t\t\treg = <0x00000000 0x10000000 0x00000000 0x00001000>;
\t\t\tclock-frequency = <3686400>;
\t\t};
\t};
};
"""

dts_path = "/tmp/platform.dts"
with open(dts_path, "w") as f:
    f.write(dts_content)

subprocess.run(
    ["dtc", "-I", "dts", "-O", "dtb", "-q",
     "-o", "/app/platform.dtb", dts_path],
    check=True
)
os.unlink(dts_path)

# ---- System configuration ----
# Physical memory layout is intentionally NOT here; it must be
# extracted from the device tree blob at /app/platform.dtb.
system = {
    "satp": "0x8000000000080001",
    "mstatus": "0x0000000000000000",
    "menvcfg": "0x0000000000000000",
    "extensions": {
        "Svade": True,
        "Svadu": False,
        "Svnapot": True,
        "Svpbmt": False
    },
    "xlen": 64,
    "platform_dtb": "/app/platform.dtb"
}

with open("/app/system.json", "w") as f:
    json.dump(system, f, indent=2)

# ---- Fault trace ----
faults = [
    {"id": 1, "va": "0x0000000000000abc", "access": "load", "privilege": "S",
     "observed_fault": "load_page_fault"},
    {"id": 2, "va": "0x0000000000001234", "access": "load", "privilege": "S",
     "observed_fault": "load_page_fault"},
    {"id": 3, "va": "0x0000000000200abc", "access": "load", "privilege": "S",
     "observed_fault": "load_page_fault"},
    {"id": 4, "va": "0x0000000000400500", "access": "store", "privilege": "S",
     "observed_fault": "store_page_fault"},
    {"id": 5, "va": "0x0000000000401000", "access": "load", "privilege": "S",
     "observed_fault": "load_page_fault"},
    {"id": 6, "va": "0x0000000000402100", "access": "store", "privilege": "S",
     "observed_fault": "store_page_fault"},
    {"id": 7, "va": "0x0000000000600000", "access": "load", "privilege": "S",
     "observed_fault": "load_page_fault"},
    {"id": 8, "va": "0x0000000000800abc", "access": "load", "privilege": "S",
     "observed_fault": "load_page_fault"},
    {"id": 9, "va": "0x0000000000a00abc", "access": "load", "privilege": "S",
     "observed_fault": "load_page_fault"},
    {"id": 10, "va": "0x0000000000a01000", "access": "fetch", "privilege": "S",
     "observed_fault": "fetch_page_fault"},
]

with open("/app/faults.json", "w") as f:
    json.dump(faults, f, indent=2)
