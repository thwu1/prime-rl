#!/usr/bin/env python3

"""
Generate a complete Rust PAC (Peripheral Access Crate) from the TB-MCU32 SVD file.

Produces:
  - src/lib.rs     — #![no_std], module declarations, singleton Peripherals::take()
  - src/gpio.rs    — Typestate GPIO with Pin<PORT, N, MODE>
  - src/<periph>.rs — Register blocks and volatile accessors for each non-GPIO peripheral
  - .cargo/config.toml — default build target
"""

import xml.etree.ElementTree as ET
import os

SVD_PATH = "/app/tb-mcu.svd"
SRC_DIR = "/app/src"
APP_DIR = "/app"


# ============================================================
# SVD parsing
# ============================================================

def parse_svd(path):
    tree = ET.parse(path)
    root = tree.getroot()

    peripherals = []
    periph_by_name = {}

    for p_elem in root.findall(".//peripheral"):
        name = p_elem.find("name").text
        base_addr = int(p_elem.find("baseAddress").text, 0)
        derived_from = p_elem.get("derivedFrom")

        desc_elem = p_elem.find("description")
        desc = desc_elem.text.strip() if desc_elem is not None else name

        group_elem = p_elem.find("groupName")
        if group_elem is not None:
            group = group_elem.text
        elif derived_from and derived_from in periph_by_name:
            group = periph_by_name[derived_from]["group"]
        else:
            group = name

        registers = []
        if derived_from and derived_from in periph_by_name:
            registers = list(periph_by_name[derived_from]["registers"])

        reg_elems = p_elem.findall(".//registers/register")
        if reg_elems:
            registers = []
            for r_elem in reg_elems:
                registers.append(_parse_register(r_elem))

        periph = {
            "name": name,
            "base_address": base_addr,
            "description": desc,
            "group": group,
            "registers": sorted(registers, key=lambda r: r["offset"]),
            "derived_from": derived_from,
        }
        peripherals.append(periph)
        periph_by_name[name] = periph

    return peripherals


def _parse_register(r_elem):
    name = r_elem.find("name").text
    offset = int(r_elem.find("addressOffset").text, 0)
    size = int(r_elem.find("size").text) if r_elem.find("size") is not None else 32
    access_elem = r_elem.find("access")
    access = access_elem.text if access_elem is not None else "read-write"
    fields = []
    for f_elem in r_elem.findall(".//field"):
        fa_elem = f_elem.find("access")
        fa = fa_elem.text if fa_elem is not None else access
        fields.append({
            "name": f_elem.find("name").text,
            "bit_offset": int(f_elem.find("bitOffset").text),
            "bit_width": int(f_elem.find("bitWidth").text),
            "access": fa,
        })
    return {
        "name": name,
        "offset": offset,
        "size": size,
        "access": access,
        "fields": sorted(fields, key=lambda f: f["bit_offset"]),
    }


# ============================================================
# Rust hex formatting helpers
# ============================================================

def rust_hex(addr):
    """Format address in Rust-idiomatic hex with underscores: 0x4800_0000"""
    h = f"{addr:08x}"
    return f"0x{h[:4]}_{h[4:]}"


def short_hex(val):
    """Format a small offset: 0x1C"""
    return f"0x{val:02X}"


# ============================================================
# Code generation: register block struct
# ============================================================

def gen_register_block(periph, block_name):
    lines = [
        f"/// Register block for {periph['description']}",
        "#[repr(C)]",
        f"pub struct {block_name} {{",
    ]
    current = 0
    ri = 0
    for reg in periph["registers"]:
        while current < reg["offset"]:
            lines.append(f"    _reserved{ri}: u32,")
            ri += 1
            current += 4
        acc = ""
        if reg["access"] == "read-only":
            acc = " /* read-only */"
        elif reg["access"] == "write-only":
            acc = " /* write-only */"
        lines.append(f"    pub {reg['name'].lower()}: u32,{acc}")
        current = reg["offset"] + reg["size"] // 8
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


# ============================================================
# Code generation: peripheral struct with volatile accessors
# ============================================================

def gen_peripheral_struct(periph, block_name):
    name = periph["name"]
    base = rust_hex(periph["base_address"])

    lines = [
        f"pub struct {name} {{",
        "    _private: (),",
        "}",
        "",
        f"impl {name} {{",
        f"    pub const BASE: usize = {base};",
        "",
        f"    pub(crate) fn new() -> Self {{",
        f"        {name} {{ _private: () }}",
        "    }",
        "",
        f"    /// Access the register block.",
        f"    pub fn register_block(&self) -> &{block_name} {{",
        f"        unsafe {{ &*(Self::BASE as *const {block_name}) }}",
        "    }",
        "",
    ]

    for reg in periph["registers"]:
        rn = reg["name"].lower()
        off = short_hex(reg["offset"])

        if reg["access"] in ("read-write", "read-only"):
            lines += [
                f"    /// Read {reg['name']} register (offset {off}).",
                f"    pub fn {rn}_read(&self) -> u32 {{",
                f"        unsafe {{ core::ptr::read_volatile((Self::BASE + {off}) as *const u32) }}",
                "    }",
                "",
            ]
        if reg["access"] in ("read-write", "write-only"):
            lines += [
                f"    /// Write {reg['name']} register (offset {off}).",
                f"    pub fn {rn}_write(&self, val: u32) {{",
                f"        unsafe {{ core::ptr::write_volatile((Self::BASE + {off}) as *mut u32, val) }}",
                "    }",
                "",
            ]
        if reg["access"] == "read-write":
            lines += [
                f"    /// Read-modify-write {reg['name']}.",
                f"    pub fn {rn}_modify<F: FnOnce(u32) -> u32>(&self, f: F) {{",
                f"        let v = self.{rn}_read();",
                f"        self.{rn}_write(f(v));",
                "    }",
                "",
            ]

    lines.append("}")
    lines.append("")
    return "\n".join(lines)


# ============================================================
# Code generation: GPIO typestate module
# ============================================================

def gen_gpio_module(gpio_peripherals):
    """Generate the full gpio.rs with typestate Pin<PORT, N, MODE>."""

    code = '''\
use core::marker::PhantomData;

// ----------------------------------------------------------------
// Mode type-state markers
// ----------------------------------------------------------------

/// Pin is in reset (unconfigured) state.
pub struct Reset;

/// Input mode, parameterised by pull configuration.
pub struct Input<PULL>(PhantomData<PULL>);
/// Output mode, parameterised by output type.
pub struct Output<OTYPE>(PhantomData<OTYPE>);
/// Alternate-function mode (AF0–AF7).
pub struct Alternate<const AF: u8>;
/// Analog mode.
pub struct Analog;

// Input sub-modes
pub struct Floating;
pub struct PullUp;
pub struct PullDown;

// Output sub-modes
pub struct PushPull;
pub struct OpenDrain;

// ----------------------------------------------------------------
// Register block (shared by all GPIO ports)
// ----------------------------------------------------------------

/// GPIO register block (matches SVD layout for GPIOA/B/C).
#[repr(C)]
pub struct GpioRegisterBlock {
    pub moder: u32,      // 0x00
    pub otyper: u32,     // 0x04
    pub ospeedr: u32,    // 0x08
    pub pupdr: u32,      // 0x0C
    pub idr: u32,        // 0x10 read-only
    pub odr: u32,        // 0x14
    pub bsrr: u32,       // 0x18 write-only
    _reserved0: u32,     // 0x1C
    pub afrl: u32,       // 0x20
    pub afrh: u32,       // 0x24
}

// ----------------------------------------------------------------
// Port base-address lookup
// ----------------------------------------------------------------

const fn gpio_base(port: char) -> usize {
    match port {
        \'A\' => 0x4800_0000,
        \'B\' => 0x4800_0400,
        \'C\' => 0x4800_0800,
        _ => panic!("invalid GPIO port"),
    }
}

// ----------------------------------------------------------------
// Generic Pin
// ----------------------------------------------------------------

/// A GPIO pin whose port, number, and electrical mode are tracked at the
/// type level.  Mode transitions *consume* the old pin and return a new
/// one, so invalid operations are compile-time errors.
pub struct Pin<const PORT: char, const N: u8, MODE> {
    _mode: PhantomData<MODE>,
}

impl<const PORT: char, const N: u8, MODE> Pin<PORT, N, MODE> {
    pub(crate) fn new() -> Self {
        Pin { _mode: PhantomData }
    }
}

// ----------------------------------------------------------------
// Transitions from Reset
// ----------------------------------------------------------------

impl<const PORT: char, const N: u8> Pin<PORT, N, Reset> {
    /// Configure as floating input (MODER=00, PUPDR=00).
    pub fn into_floating_input(self) -> Pin<PORT, N, Input<Floating>> {
        let base = gpio_base(PORT);
        unsafe {
            let moder = base as *mut u32;
            let v = core::ptr::read_volatile(moder);
            core::ptr::write_volatile(moder, v & !(0b11 << (N as u32 * 2)));
            let pupdr = (base + 0x0C) as *mut u32;
            let v = core::ptr::read_volatile(pupdr);
            core::ptr::write_volatile(pupdr, v & !(0b11 << (N as u32 * 2)));
        }
        Pin::new()
    }

    /// Configure as pull-up input (MODER=00, PUPDR=01).
    pub fn into_pull_up_input(self) -> Pin<PORT, N, Input<PullUp>> {
        let base = gpio_base(PORT);
        unsafe {
            let moder = base as *mut u32;
            let v = core::ptr::read_volatile(moder);
            core::ptr::write_volatile(moder, v & !(0b11 << (N as u32 * 2)));
            let pupdr = (base + 0x0C) as *mut u32;
            let v = core::ptr::read_volatile(pupdr);
            let v = (v & !(0b11 << (N as u32 * 2))) | (0b01 << (N as u32 * 2));
            core::ptr::write_volatile(pupdr, v);
        }
        Pin::new()
    }

    /// Configure as pull-down input (MODER=00, PUPDR=10).
    pub fn into_pull_down_input(self) -> Pin<PORT, N, Input<PullDown>> {
        let base = gpio_base(PORT);
        unsafe {
            let moder = base as *mut u32;
            let v = core::ptr::read_volatile(moder);
            core::ptr::write_volatile(moder, v & !(0b11 << (N as u32 * 2)));
            let pupdr = (base + 0x0C) as *mut u32;
            let v = core::ptr::read_volatile(pupdr);
            let v = (v & !(0b11 << (N as u32 * 2))) | (0b10 << (N as u32 * 2));
            core::ptr::write_volatile(pupdr, v);
        }
        Pin::new()
    }

    /// Configure as push-pull output (MODER=01, OTYPER=0).
    pub fn into_push_pull_output(self) -> Pin<PORT, N, Output<PushPull>> {
        let base = gpio_base(PORT);
        unsafe {
            let moder = base as *mut u32;
            let v = core::ptr::read_volatile(moder);
            let v = (v & !(0b11 << (N as u32 * 2))) | (0b01 << (N as u32 * 2));
            core::ptr::write_volatile(moder, v);
            let otyper = (base + 0x04) as *mut u32;
            let v = core::ptr::read_volatile(otyper);
            core::ptr::write_volatile(otyper, v & !(1u32 << N));
        }
        Pin::new()
    }

    /// Configure as open-drain output (MODER=01, OTYPER=1).
    pub fn into_open_drain_output(self) -> Pin<PORT, N, Output<OpenDrain>> {
        let base = gpio_base(PORT);
        unsafe {
            let moder = base as *mut u32;
            let v = core::ptr::read_volatile(moder);
            let v = (v & !(0b11 << (N as u32 * 2))) | (0b01 << (N as u32 * 2));
            core::ptr::write_volatile(moder, v);
            let otyper = (base + 0x04) as *mut u32;
            let v = core::ptr::read_volatile(otyper);
            core::ptr::write_volatile(otyper, v | (1u32 << N));
        }
        Pin::new()
    }

    /// Configure as alternate function (MODER=10, AFR[L/H] set).
    pub fn into_alternate<const AF: u8>(self) -> Pin<PORT, N, Alternate<AF>> {
        let base = gpio_base(PORT);
        unsafe {
            let moder = base as *mut u32;
            let v = core::ptr::read_volatile(moder);
            let v = (v & !(0b11 << (N as u32 * 2))) | (0b10 << (N as u32 * 2));
            core::ptr::write_volatile(moder, v);
            if N < 8 {
                let afrl = (base + 0x20) as *mut u32;
                let v = core::ptr::read_volatile(afrl);
                let v = (v & !(0b1111 << (N as u32 * 4))) | ((AF as u32) << (N as u32 * 4));
                core::ptr::write_volatile(afrl, v);
            } else {
                let afrh = (base + 0x24) as *mut u32;
                let off = (N - 8) as u32;
                let v = core::ptr::read_volatile(afrh);
                let v = (v & !(0b1111 << (off * 4))) | ((AF as u32) << (off * 4));
                core::ptr::write_volatile(afrh, v);
            }
        }
        Pin::new()
    }

    /// Configure as analog (MODER=11).
    pub fn into_analog(self) -> Pin<PORT, N, Analog> {
        let base = gpio_base(PORT);
        unsafe {
            let moder = base as *mut u32;
            let v = core::ptr::read_volatile(moder);
            let v = v | (0b11 << (N as u32 * 2));
            core::ptr::write_volatile(moder, v);
        }
        Pin::new()
    }
}

// ----------------------------------------------------------------
// Output operations (only available when MODE = Output<_>)
// ----------------------------------------------------------------

impl<const PORT: char, const N: u8, OTYPE> Pin<PORT, N, Output<OTYPE>> {
    /// Drive pin high via BSRR set bits (bits 0–15).
    pub fn set_high(&mut self) {
        let base = gpio_base(PORT);
        unsafe {
            let bsrr = (base + 0x18) as *mut u32;
            core::ptr::write_volatile(bsrr, 1u32 << N);
        }
    }

    /// Drive pin low via BSRR reset bits (bits 16–31).
    pub fn set_low(&mut self) {
        let base = gpio_base(PORT);
        unsafe {
            let bsrr = (base + 0x18) as *mut u32;
            core::ptr::write_volatile(bsrr, 1u32 << (N as u32 + 16));
        }
    }

    /// Read back the output level from ODR.
    pub fn is_set_high(&self) -> bool {
        let base = gpio_base(PORT);
        unsafe {
            let odr = (base + 0x14) as *const u32;
            core::ptr::read_volatile(odr) & (1u32 << N) != 0
        }
    }

    pub fn is_set_low(&self) -> bool {
        !self.is_set_high()
    }

    /// Return to reset state.
    pub fn into_reset(self) -> Pin<PORT, N, Reset> {
        Pin::new()
    }
}

// ----------------------------------------------------------------
// Input operations (only available when MODE = Input<_>)
// ----------------------------------------------------------------

impl<const PORT: char, const N: u8, PULL> Pin<PORT, N, Input<PULL>> {
    /// Read the pin level from IDR.
    pub fn is_high(&self) -> bool {
        let base = gpio_base(PORT);
        unsafe {
            let idr = (base + 0x10) as *const u32;
            core::ptr::read_volatile(idr) & (1u32 << N) != 0
        }
    }

    pub fn is_low(&self) -> bool {
        !self.is_high()
    }

    /// Return to reset state.
    pub fn into_reset(self) -> Pin<PORT, N, Reset> {
        Pin::new()
    }
}

// ----------------------------------------------------------------
// Alternate-function operations
// ----------------------------------------------------------------

impl<const PORT: char, const N: u8, const AF: u8> Pin<PORT, N, Alternate<AF>> {
    /// Return to reset state.
    pub fn into_reset(self) -> Pin<PORT, N, Reset> {
        Pin::new()
    }
}

'''

    # Generate per-port structs + pin collections
    for periph in gpio_peripherals:
        port_name = periph["name"]        # e.g. GPIOA
        letter = port_name[-1]            # e.g. A
        base = rust_hex(periph["base_address"])

        code += f"// ---- {port_name} ----\n\n"

        code += f"pub struct {port_name} {{\n    _private: (),\n}}\n\n"

        code += f"impl {port_name} {{\n"
        code += f"    pub const BASE: usize = {base};\n\n"
        code += f"    pub(crate) fn new() -> Self {{ {port_name} {{ _private: () }} }}\n\n"
        code += f"    /// Split into individual typed pins.\n"
        code += f"    pub fn split(self) -> {port_name}Pins {{\n"
        code += f"        {port_name}Pins {{\n"
        for i in range(16):
            code += f"            p{letter.lower()}{i}: Pin::new(),\n"
        code += f"        }}\n"
        code += f"    }}\n\n"
        code += f"    pub fn register_block(&self) -> &GpioRegisterBlock {{\n"
        code += f"        unsafe {{ &*(Self::BASE as *const GpioRegisterBlock) }}\n"
        code += f"    }}\n"
        code += f"}}\n\n"

        code += f"pub struct {port_name}Pins {{\n"
        for i in range(16):
            code += f"    pub p{letter.lower()}{i}: Pin<'{letter}', {i}, Reset>,\n"
        code += f"}}\n\n"

    return code


# ============================================================
# Code generation: lib.rs
# ============================================================

def gen_lib_rs(peripherals):
    gpio_names = [p["name"] for p in peripherals if p["group"] == "GPIO"]
    non_gpio = [p for p in peripherals if p["group"] != "GPIO"]
    modules = sorted(set(["gpio"] + [p["name"].lower() for p in non_gpio]))

    lines = ["#![no_std]", ""]
    for m in modules:
        lines.append(f"pub mod {m};")
    lines += [
        "",
        "use core::sync::atomic::{AtomicBool, Ordering};",
        "",
        "/// Singleton container for all MCU peripherals.",
        "pub struct Peripherals {",
    ]
    for p in peripherals:
        if p["group"] == "GPIO":
            lines.append(f"    pub {p['name'].lower()}: gpio::{p['name']},")
        else:
            lines.append(
                f"    pub {p['name'].lower()}: {p['name'].lower()}::{p['name']},"
            )
    lines += [
        "}",
        "",
        "static PERIPHERALS_TAKEN: AtomicBool = AtomicBool::new(false);",
        "",
        "impl Peripherals {",
        "    /// Take the peripherals singleton.  Returns `None` if already taken.",
        "    pub fn take() -> Option<Self> {",
        "        if PERIPHERALS_TAKEN",
        "            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)",
        "            .is_ok()",
        "        {",
        "            Some(unsafe { Self::steal() })",
        "        } else {",
        "            None",
        "        }",
        "    }",
        "",
        "    /// Unsafely obtain peripherals without the singleton check.",
        "    pub unsafe fn steal() -> Self {",
        "        Peripherals {",
    ]
    for p in peripherals:
        if p["group"] == "GPIO":
            lines.append(f"            {p['name'].lower()}: gpio::{p['name']}::new(),")
        else:
            lines.append(
                f"            {p['name'].lower()}: {p['name'].lower()}::{p['name']}::new(),"
            )
    lines += [
        "        }",
        "    }",
        "}",
        "",
    ]
    return "\n".join(lines)


# ============================================================
# Code generation: non-GPIO peripheral module
# ============================================================

def gen_peripheral_module(periph):
    block_name = f"{periph['name']}RegisterBlock"
    parts = [
        gen_register_block(periph, block_name),
        gen_peripheral_struct(periph, block_name),
    ]
    return "\n".join(parts)


# ============================================================
# Main
# ============================================================

def main():
    peripherals = parse_svd(SVD_PATH)

    gpio_periphs = [p for p in peripherals if p["group"] == "GPIO"]
    non_gpio_periphs = [p for p in peripherals if p["group"] != "GPIO"]

    os.makedirs(SRC_DIR, exist_ok=True)

    # lib.rs
    with open(os.path.join(SRC_DIR, "lib.rs"), "w") as f:
        f.write(gen_lib_rs(peripherals))

    # gpio.rs
    with open(os.path.join(SRC_DIR, "gpio.rs"), "w") as f:
        f.write(gen_gpio_module(gpio_periphs))

    # individual peripheral modules
    for p in non_gpio_periphs:
        mod_name = p["name"].lower()
        with open(os.path.join(SRC_DIR, f"{mod_name}.rs"), "w") as f:
            f.write(gen_peripheral_module(p))

    # .cargo/config.toml
    cargo_dir = os.path.join(APP_DIR, ".cargo")
    os.makedirs(cargo_dir, exist_ok=True)
    with open(os.path.join(cargo_dir, "config.toml"), "w") as f:
        f.write('[build]\ntarget = "thumbv7m-none-eabi"\n')

    print("PAC generated successfully.")


if __name__ == "__main__":
    main()
