#!/usr/bin/env python3
"""
SVD-to-PAC code generator for TBMCU-001.

Parses a CMSIS-SVD XML file and generates a Rust Peripheral Access Crate (PAC)
with type-safe register access, supporting derived peripherals and register arrays.
"""

import xml.etree.ElementTree as ET
import os
import re
import sys
import copy


# ── Data model ────────────────────────────────────────────────────────────────

class Field:
    def __init__(self, name, description, bit_offset, bit_width, enum_values=None):
        self.name = name
        self.description = description
        self.bit_offset = bit_offset
        self.bit_width = bit_width
        self.enum_values = enum_values or []  # [(name, int_value), ...]

    @property
    def mask(self):
        return (1 << self.bit_width) - 1

    @property
    def rust_type(self):
        if self.bit_width <= 8:
            return "u8"
        elif self.bit_width <= 16:
            return "u16"
        else:
            return "u32"


class Register:
    def __init__(self, name, description, offset, size, access, reset_value, fields):
        self.name = name
        self.description = description
        self.offset = offset
        self.size = size
        self.access = access
        self.reset_value = reset_value
        self.fields = fields

    @property
    def is_readable(self):
        return self.access in ("read-write", "read-only")

    @property
    def is_writable(self):
        return self.access in ("read-write", "write-only")

    @property
    def is_rw(self):
        return self.access == "read-write"


class Peripheral:
    def __init__(self, name, description, base_address, registers):
        self.name = name
        self.description = description
        self.base_address = base_address
        self.registers = registers


# ── SVD parser ────────────────────────────────────────────────────────────────

def _parse_fields(parent_elem):
    """Parse field elements from a register or field container."""
    fields = []
    for f_elem in parent_elem.findall(".//field"):
        f_name = f_elem.find("name").text
        f_desc_el = f_elem.find("description")
        f_desc = f_desc_el.text if f_desc_el is not None else ""
        f_offset = int(f_elem.find("bitOffset").text, 0)
        f_width = int(f_elem.find("bitWidth").text, 0)

        evs = []
        for ev in f_elem.findall(".//enumeratedValue"):
            ev_name = ev.find("name").text
            ev_val = int(ev.find("value").text, 0)
            evs.append((ev_name, ev_val))

        fields.append(Field(f_name, f_desc, f_offset, f_width, evs))
    return fields


def _parse_register_elem(r_elem):
    """Parse a single register element, expanding dim arrays if present."""
    r_name_template = r_elem.find("name").text
    r_desc_el = r_elem.find("description")
    r_desc_template = r_desc_el.text if r_desc_el is not None else ""
    r_offset = int(r_elem.find("addressOffset").text, 0)
    r_size = int(r_elem.find("size").text, 0)
    r_access = r_elem.find("access").text
    r_reset = int(r_elem.find("resetValue").text, 0)

    fields_template = _parse_fields(r_elem)

    # Check for dim (register array)
    dim_el = r_elem.find("dim")
    if dim_el is not None:
        dim_count = int(dim_el.text)
        dim_incr = int(r_elem.find("dimIncrement").text, 0)
        dim_index_text = r_elem.find("dimIndex").text

        # Parse dimIndex: "1-4" range or "A,B,C,D" list
        if "-" in dim_index_text and "," not in dim_index_text:
            parts = dim_index_text.split("-")
            indices = [str(i) for i in range(int(parts[0]), int(parts[1]) + 1)]
        else:
            indices = [s.strip() for s in dim_index_text.split(",")]

        result = []
        for i, idx in enumerate(indices):
            expanded_name = r_name_template.replace("%s", idx)
            expanded_desc = r_desc_template.replace("%s", idx)
            expanded_offset = r_offset + i * dim_incr
            expanded_fields = [
                Field(
                    f.name.replace("%s", idx),
                    f.description.replace("%s", idx) if f.description else "",
                    f.bit_offset,
                    f.bit_width,
                    list(f.enum_values),
                )
                for f in fields_template
            ]
            result.append(
                Register(
                    expanded_name, expanded_desc, expanded_offset,
                    r_size, r_access, r_reset, expanded_fields,
                )
            )
        return result
    else:
        return [
            Register(
                r_name_template, r_desc_template, r_offset,
                r_size, r_access, r_reset, fields_template,
            )
        ]


def parse_svd(path):
    tree = ET.parse(path)
    root = tree.getroot()
    peripherals = []
    peripheral_map = {}  # name -> Peripheral for derivedFrom lookup

    for p_elem in root.findall(".//peripheral"):
        name = p_elem.find("name").text
        desc_el = p_elem.find("description")
        desc = desc_el.text if desc_el is not None else ""
        base = int(p_elem.find("baseAddress").text, 0)

        # Handle derivedFrom
        derived_from = p_elem.get("derivedFrom")

        if derived_from and derived_from in peripheral_map:
            parent = peripheral_map[derived_from]
            # Deep copy parent registers
            registers = []
            for r in parent.registers:
                registers.append(
                    Register(
                        r.name, r.description, r.offset, r.size,
                        r.access, r.reset_value,
                        [Field(f.name, f.description, f.bit_offset, f.bit_width,
                               list(f.enum_values)) for f in r.fields],
                    )
                )
        else:
            registers = []

        # Parse own registers
        own_reg_map = {}
        regs_elem = p_elem.find("registers")
        if regs_elem is not None:
            for r_elem in regs_elem.findall("register"):
                for r in _parse_register_elem(r_elem):
                    own_reg_map[r.name] = r

        if derived_from and derived_from in peripheral_map:
            # Merge: override existing, append new
            existing_names = [r.name for r in registers]
            for rname, r in own_reg_map.items():
                if rname in existing_names:
                    registers = [r if x.name == rname else x for x in registers]
                else:
                    registers.append(r)
        else:
            # Non-derived: just use own registers in order
            registers = list(own_reg_map.values())

        p = Peripheral(name, desc, base, registers)
        peripherals.append(p)
        peripheral_map[name] = p

    return peripherals


# ── Helpers ───────────────────────────────────────────────────────────────────

def snake_case(name):
    """Convert CamelCase to snake_case."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower()


# ── Code generators ──────────────────────────────────────────────────────────

def generate_pac(peripherals, output_dir):
    src = os.path.join(output_dir, "src")
    os.makedirs(src, exist_ok=True)
    _gen_cargo_toml(output_dir)
    _gen_mmio(peripherals, src)
    _gen_lib(peripherals, src)
    for p in peripherals:
        _gen_peripheral(p, src)


def _gen_cargo_toml(output_dir):
    with open(os.path.join(output_dir, "Cargo.toml"), "w") as f:
        f.write(
            '[package]\nname = "tbmcu001-pac"\nversion = "0.1.0"\nedition = "2021"\n'
        )


def _gen_mmio(peripherals, src):
    reset_entries = []
    for p in peripherals:
        for r in p.registers:
            if r.reset_value != 0:
                reset_entries.append((p.base_address + r.offset, r.reset_value))

    lines = [
        "//! Mock memory-mapped I/O backend.",
        "",
        "use core::cell::UnsafeCell;",
        "",
        "const BASE_ADDR: u32 = 0x4000_0000;",
        "const MEM_WORDS: usize = 0x10000 / 4;",
        "",
        "struct MemBlock {",
        "    data: UnsafeCell<[u32; MEM_WORDS]>,",
        "}",
        "",
        "unsafe impl Sync for MemBlock {}",
        "",
        "static MEMORY: MemBlock = MemBlock {",
        "    data: UnsafeCell::new([0u32; MEM_WORDS]),",
        "};",
        "",
        "#[inline]",
        "fn idx(addr: u32) -> usize {",
        "    ((addr - BASE_ADDR) / 4) as usize",
        "}",
        "",
        "/// Read a 32-bit register value.",
        "pub fn read(addr: u32) -> u32 {",
        "    unsafe { (*MEMORY.data.get())[idx(addr)] }",
        "}",
        "",
        "/// Write a 32-bit register value.",
        "pub fn write(addr: u32, val: u32) {",
        "    unsafe { (*MEMORY.data.get())[idx(addr)] = val; }",
        "}",
        "",
        "/// Reset all memory to register reset values.",
        "pub fn init() {",
        "    unsafe {",
        "        let mem = &mut *MEMORY.data.get();",
        "        *mem = [0u32; MEM_WORDS];",
        "    }",
    ]
    for addr, val in reset_entries:
        lines.append(f"    write(0x{addr:08X}, 0x{val:08X});")
    lines.append("}")
    lines.append("")

    with open(os.path.join(src, "mmio.rs"), "w") as f:
        f.write("\n".join(lines))


def _gen_lib(peripherals, src):
    lines = [
        "#![no_std]",
        "#![allow(non_camel_case_types)]",
        "#![allow(non_snake_case)]",
        "",
        "pub mod mmio;",
    ]
    for p in peripherals:
        lines.append(f"pub mod {p.name.lower()};")

    lines += [
        "",
        "use core::sync::atomic::{AtomicBool, Ordering};",
        "",
        "static TAKEN: AtomicBool = AtomicBool::new(false);",
        "",
        "pub struct Peripherals {",
    ]
    for p in peripherals:
        lines.append(f"    pub {p.name}: {p.name.lower()}::{p.name},")
    lines += [
        "}",
        "",
        "impl Peripherals {",
        "    pub fn take() -> Option<Self> {",
        "        if TAKEN.compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire).is_ok() {",
        "            Some(unsafe { Self::steal() })",
        "        } else {",
        "            None",
        "        }",
        "    }",
        "",
        "    pub fn reset_singleton() {",
        "        TAKEN.store(false, Ordering::Release);",
        "    }",
        "",
        "    pub unsafe fn steal() -> Self {",
        "        Self {",
    ]
    for p in peripherals:
        lines.append(f"            {p.name}: {p.name.lower()}::{p.name}::new(),")
    lines += [
        "        }",
        "    }",
        "}",
        "",
    ]

    with open(os.path.join(src, "lib.rs"), "w") as f:
        f.write("\n".join(lines))


def _gen_peripheral(peripheral, src):
    p = peripheral
    lines = [f"//! {p.description}", ""]

    # Peripheral struct
    lines.append(f"pub struct {p.name} {{")
    for r in p.registers:
        lines.append(f"    pub {r.name.lower()}: {r.name},")
    lines += ["}", ""]

    lines.append(f"impl {p.name} {{")
    lines.append("    pub(crate) fn new() -> Self {")
    lines.append("        Self {")
    for r in p.registers:
        addr = p.base_address + r.offset
        lines.append(f"            {r.name.lower()}: {r.name} {{ addr: 0x{addr:08X} }},")
    lines += ["        }", "    }", "}", ""]

    # Each register
    for r in p.registers:
        lines += _gen_register(r)

    with open(os.path.join(src, f"{p.name.lower()}.rs"), "w") as f:
        f.write("\n".join(lines))


def _gen_register(reg):
    rmod = reg.name.lower()
    lines = []

    # Register struct
    lines += [
        f"pub struct {reg.name} {{",
        "    pub(crate) addr: u32,",
        "}",
        "",
        f"impl {reg.name} {{",
    ]

    if reg.is_readable:
        lines += [
            f"    pub fn read(&self) -> {rmod}::R {{",
            f"        {rmod}::R {{ bits: crate::mmio::read(self.addr) }}",
            "    }",
            "",
        ]

    if reg.is_writable:
        lines += [
            "    pub fn write<F>(&self, f: F)",
            "    where",
            f"        F: FnOnce(&mut {rmod}::W) -> &mut {rmod}::W,",
            "    {",
            f"        let mut w = {rmod}::W {{ bits: 0x{reg.reset_value:08X} }};",
            "        f(&mut w);",
            "        crate::mmio::write(self.addr, w.bits);",
            "    }",
            "",
        ]

    if reg.is_rw:
        lines += [
            "    pub fn modify<F>(&self, f: F)",
            "    where",
            f"        F: for<'w> FnOnce(&'w {rmod}::R, &'w mut {rmod}::W) -> &'w mut {rmod}::W,",
            "    {",
            "        let bits = crate::mmio::read(self.addr);",
            f"        let r = {rmod}::R {{ bits }};",
            f"        let mut w = {rmod}::W {{ bits }};",
            "        f(&r, &mut w);",
            "        crate::mmio::write(self.addr, w.bits);",
            "    }",
            "",
        ]

    if reg.is_writable:
        lines += [
            "    pub fn reset(&self) {",
            f"        crate::mmio::write(self.addr, 0x{reg.reset_value:08X});",
            "    }",
            "",
        ]

    lines += ["}", ""]

    # Field module
    lines.append(f"pub mod {rmod} {{")

    # R struct
    if reg.is_readable:
        lines += [
            "    pub struct R {",
            "        pub(crate) bits: u32,",
            "    }",
            "",
            "    impl R {",
            "        pub fn bits(&self) -> u32 { self.bits }",
            "",
        ]
        for field in reg.fields:
            fl = field.name.lower()
            reader = f"{field.name}_R"
            mask_hex = f"0x{field.mask:X}"
            lines += [
                f"        pub fn {fl}(&self) -> {reader} {{",
                f"            {reader} {{ bits: ((self.bits >> {field.bit_offset}) & {mask_hex}) as {field.rust_type} }}",
                "        }",
                "",
            ]
        lines += ["    }", ""]

        # Field readers
        for field in reg.fields:
            reader = f"{field.name}_R"
            lines += [
                f"    pub struct {reader} {{",
                f"        pub(crate) bits: {field.rust_type},",
                "    }",
                "",
                f"    impl {reader} {{",
                f"        pub fn bits(&self) -> {field.rust_type} {{ self.bits }}",
                "",
            ]
            for ev_name, ev_val in field.enum_values:
                is_fn = f"is_{snake_case(ev_name)}"
                lines += [
                    f"        pub fn {is_fn}(&self) -> bool {{ self.bits == {ev_val} }}",
                    "",
                ]
            lines += ["    }", ""]

    # W struct
    if reg.is_writable:
        lines += [
            "    pub struct W {",
            "        pub(crate) bits: u32,",
            "    }",
            "",
            "    impl W {",
            "        pub unsafe fn bits(&mut self, value: u32) -> &mut Self {",
            "            self.bits = value;",
            "            self",
            "        }",
            "",
        ]
        for field in reg.fields:
            fl = field.name.lower()
            writer = f"{field.name}_W"
            lines += [
                f"        pub fn {fl}(&mut self) -> {writer}<'_> {{",
                f"            {writer} {{ w: self }}",
                "        }",
                "",
            ]
        lines += ["    }", ""]

        # Field writers
        for field in reg.fields:
            writer = f"{field.name}_W"
            mask_hex = f"0x{field.mask:X}"
            lines += [
                f"    pub struct {writer}<'a> {{",
                "        pub(crate) w: &'a mut W,",
                "    }",
                "",
                f"    impl<'a> {writer}<'a> {{",
                f"        pub fn bits(self, value: {field.rust_type}) -> &'a mut W {{",
                f"            self.w.bits = (self.w.bits & !({mask_hex} << {field.bit_offset})) | (((value as u32) & {mask_hex}) << {field.bit_offset});",
                "            self.w",
                "        }",
                "",
            ]
            for ev_name, ev_val in field.enum_values:
                setter = snake_case(ev_name)
                lines += [
                    f"        pub fn {setter}(self) -> &'a mut W {{ self.bits({ev_val}) }}",
                    "",
                ]
            # set_bit/clear_bit for 1-bit fields without enums
            if field.bit_width == 1 and not field.enum_values:
                lines += [
                    "        pub fn set_bit(self) -> &'a mut W { self.bits(1) }",
                    "",
                    "        pub fn clear_bit(self) -> &'a mut W { self.bits(0) }",
                    "",
                ]
            lines += ["    }", ""]

    lines += ["}", ""]
    return lines


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    svd_path = "/app/device.svd"
    output_dir = "/app/generated-pac"

    if not os.path.isfile(svd_path):
        print(f"ERROR: SVD file not found at {svd_path}", file=sys.stderr)
        sys.exit(1)

    peripherals = parse_svd(svd_path)
    generate_pac(peripherals, output_dir)
    print(f"Generated PAC with {len(peripherals)} peripheral(s) at {output_dir}")


if __name__ == "__main__":
    main()
